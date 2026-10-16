"""Local helper: receives a Shengwang session from the patched slicer UI and
serves the viewer page that joins it in a WebRTC-capable browser.

Security: bound to 127.0.0.1, every request needs the per-run random token,
the Host header is checked (DNS rebinding), and sessions expire after SESSION_TTL
seconds. Session contents (temporary credentials) are never logged. The viewer
is opened with a one-time ticket instead of the token, because the browser's
command line is readable by other local users; the page gets the token in its
response body.
"""
import hmac
import json
import secrets
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SESSION_TTL = 120          # seconds a session stays available to the viewer
VIEWER_ALIVE = 5           # viewer is "open" if it polled within this many seconds
VIEWER_LAUNCH_GRACE = 30   # seconds a just-launched viewer gets to start polling
TOKEN_PLACEHOLDER = "__CAMVIEW_TOKEN__"
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
    def __init__(self, token: str, sdk_path: Path):
        self.token = token
        self.sdk_path = sdk_path
        self.lock = threading.Lock()
        self.seq = 0
        self.session: dict | None = None
        self.last_poll = 0.0
        self.launched_at: float | None = None
        self.ticket: str | None = None
        self.port = 0
        self._expiry: threading.Timer | None = None

    def _expire(self, seq: int) -> None:
        with self.lock:
            if self.seq == seq:  # not replaced by a newer session meanwhile
                self.session = None

    def set_session(self, session: dict) -> bool:
        """Store a session; return True if a viewer window must be opened.

        The session (temporary credentials) is dropped SESSION_TTL seconds later
        whether or not a viewer ever polls for it.
        """
        with self.lock:
            self.seq += 1
            self.session = session
            if self._expiry:
                self._expiry.cancel()
            self._expiry = threading.Timer(SESSION_TTL, self._expire, args=(self.seq,))
            self._expiry.daemon = True
            self._expiry.start()
            now = time.monotonic()
            if now - self.last_poll <= VIEWER_ALIVE:
                return False
            # A browser can take longer than VIEWER_ALIVE to start, and the viewer
            # stops polling while it joins. Without this, a second session in
            # that window opens a second viewer, and both join with the same uid
            # (UID_CONFLICT). The grace runs its full length, even after the
            # first poll.
            if self.launched_at is not None and now - self.launched_at <= VIEWER_LAUNCH_GRACE:
                return False
            self.launched_at = now
            return True

    def new_ticket(self) -> str:
        with self.lock:
            self.ticket = secrets.token_urlsafe(24)
            return self.ticket

    def redeem_ticket(self, supplied: str | None) -> bool:
        """Accept the current viewer ticket once."""
        with self.lock:
            ok = bool(supplied) and self.ticket is not None and hmac.compare_digest(supplied, self.ticket)
            if ok:
                self.ticket = None
            return ok

    def poll(self, since: int) -> dict:
        with self.lock:
            self.last_poll = time.monotonic()
            return {"seq": self.seq, "session": self.session if self.seq != since else None}


def launch_viewer(state: State) -> None:
    url = f"http://127.0.0.1:{state.port}/viewer?ticket={state.new_ticket()}"
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
            if url.path == "/viewer":
                if not state.redeem_ticket(q.get("ticket", [None])[0]):
                    return self._send(403)
                html = resources.files("camview").joinpath("viewer/viewer.html").read_text(encoding="utf-8")
                html = html.replace(TOKEN_PLACEHOLDER, state.token)
                return self._send(200, html.encode(), "text/html; charset=utf-8")
            if not self._token_ok(q.get("t", [None])[0]):
                return self._send(403)
            if url.path == "/agora.js":
                return self._send(200, state.sdk_path.read_bytes(), "text/javascript; charset=utf-8")
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
                if not isinstance(body, dict):
                    raise ValueError
                sw = body.get("shengwang")
                if not isinstance(sw, dict) or not all(sw.get(k) for k in REQUIRED):
                    raise ValueError
                printer = body.get("printer")
                if not isinstance(printer, dict):
                    printer = {}
            except (ValueError, json.JSONDecodeError):
                return self._send(400)
            session = {"printer": printer, "shengwang": sw}
            if state.set_session(session):
                launch_viewer(state)
            print(f"camview: session received for printer {printer.get('id')}")
            self._send(204)

    return Handler


def start_server(token: str, sdk_path: Path) -> tuple[ThreadingHTTPServer, State]:
    state = State(token, sdk_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    state.port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, state
