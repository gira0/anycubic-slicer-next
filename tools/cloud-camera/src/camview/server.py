"""Local helper: receives a Shengwang session from the patched slicer UI and
serves the viewer page that joins it in a WebRTC-capable browser.

Security: bound to 127.0.0.1, every request needs the per-run random token,
the Host header is checked (DNS rebinding), and sessions expire after SESSION_TTL
seconds. Session contents (temporary credentials) are never logged.
"""
from __future__ import annotations

import hmac
import json
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SESSION_TTL = 120          # seconds a session stays available to the viewer
VIEWER_ALIVE = 5           # viewer is "open" if it polled within this many seconds
MAX_BODY = 64 * 1024
REQUIRED = ("appid", "channel")


def find_browser_command() -> list[str] | None:
    """Command prefix for a Chromium-family browser, or None."""
    import os
    override = os.environ.get("CAMVIEW_BROWSER")
    if override:
        return override.split()
    if shutil.which("flatpak"):
        r = subprocess.run(["flatpak", "info", "org.chromium.Chromium"], capture_output=True)
        if r.returncode == 0:
            return ["flatpak", "run", "org.chromium.Chromium"]
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "brave-browser"):
        if shutil.which(name):
            return [name]
    return None


class State:
    def __init__(self, token: str, get_sdk):
        self.token = token
        self.get_sdk = get_sdk  # callable returning the verified SDK path
        self.lock = threading.Lock()
        self.seq = 0
        self.session: dict | None = None
        self.session_time = 0.0
        self.last_poll = 0.0
        self.port = 0

    def set_session(self, session: dict) -> bool:
        """Store a session; return True if a viewer window must be opened."""
        with self.lock:
            self.seq += 1
            self.session = session
            self.session_time = time.monotonic()
            return time.monotonic() - self.last_poll > VIEWER_ALIVE

    def poll(self, since: int) -> dict:
        with self.lock:
            self.last_poll = time.monotonic()
            if self.session and time.monotonic() - self.session_time > SESSION_TTL:
                self.session = None
            return {"seq": self.seq, "session": self.session if self.seq != since else None}


def launch_viewer(state: State) -> None:
    url = f"http://127.0.0.1:{state.port}/viewer?t={state.token}"
    cmd = find_browser_command()
    if cmd is None:
        print(f"camview: no Chromium-family browser found; open this URL in one: {url}")
        return
    print("camview: opening the viewer window")
    subprocess.Popen(
        cmd + [f"--app={url}", "--window-size=1024,636", "--autoplay-policy=no-user-gesture-required"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def make_handler(state: State):
    class Handler(BaseHTTPRequestHandler):
        server_version = "camview"

        def log_message(self, *args):  # never log requests (URLs carry the token)
            pass

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Camview-Token")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

        def _send(self, code, body=b"", ctype="text/plain; charset=utf-8"):
            self.send_response(code)
            self._cors()
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in (f"127.0.0.1:{state.port}", f"localhost:{state.port}")

        def _token_ok(self, supplied: str | None) -> bool:
            return bool(supplied) and hmac.compare_digest(supplied, state.token)

        def do_OPTIONS(self):
            if not self._host_ok():
                return self._send(403)
            self._send(204)

        def do_GET(self):
            if not self._host_ok():
                return self._send(403)
            url = urlparse(self.path)
            q = parse_qs(url.query)
            if not self._token_ok(q.get("t", [None])[0]):
                return self._send(403)
            if url.path == "/viewer":
                html = (Path(__file__).parent / "viewer" / "viewer.html").read_bytes()
                return self._send(200, html, "text/html; charset=utf-8")
            if url.path == "/agora.js":
                try:
                    sdk_bytes = state.get_sdk().read_bytes()
                except Exception:
                    return self._send(502)
                return self._send(200, sdk_bytes, "text/javascript; charset=utf-8")
            if url.path == "/session":
                try:
                    since = int(q.get("since", ["0"])[0])
                except ValueError:
                    since = 0
                return self._send(200, json.dumps(state.poll(since)).encode(), "application/json")
            self._send(404)

        def do_POST(self):
            if not self._host_ok():
                return self._send(403)
            if urlparse(self.path).path != "/session":
                return self._send(404)
            if not self._token_ok(self.headers.get("X-Camview-Token")):
                return self._send(403)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    raise ValueError
                body = json.loads(self.rfile.read(length))
                sw = body["shengwang"]
                if not all(sw.get(k) for k in REQUIRED):
                    raise ValueError
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                return self._send(400)
            session = {"printer": body.get("printer") or {}, "shengwang": sw}
            if state.set_session(session):
                launch_viewer(state)
            print(f"camview: session received for printer {session['printer'].get('id')}")
            self._send(204)

    return Handler


def start_server(token: str, get_sdk) -> tuple[ThreadingHTTPServer, State]:
    state = State(token, get_sdk)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    state.port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, state
