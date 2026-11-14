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
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import NamedTuple
from urllib.parse import parse_qs, urlparse

from . import sdk

SESSION_TTL = 120          # seconds a session stays available to the viewer
VIEWER_ALIVE = 5           # viewer is "open" if it polled within this many seconds
VIEWER_LAUNCH_GRACE = 30   # seconds a just-launched viewer gets to start polling
VIEWER_CLOSE_WAIT = 2      # seconds an open viewer gets to fetch the "closed" notice
BROWSER_EXIT_WAIT = 5      # seconds in which a failing browser command is reported
TOKEN_PLACEHOLDER = "__CAMVIEW_TOKEN__"
MAX_BODY = 64 * 1024
REQUIRED = ("appid", "channel")


CHROMIUM, GECKO = "chromium", "gecko"
# (family, Flatpak app id, binary names), in order of preference. Firefox works
# too but has no app-style window.
BROWSERS = (
    (CHROMIUM, "org.chromium.Chromium",
     ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "brave-browser")),
    (GECKO, "org.mozilla.firefox", ("firefox",)),
)
# Words in an executable name or Flatpak app id that mean a Firefox-based browser
# (firefox-esr, librewolf, zen-browser, app.zen_browser.zen, waterfox, floorp, ...).
GECKO_WORDS = frozenset(("firefox", "librewolf", "zen", "waterfox", "floorp", "icecat"))


def log(msg: str) -> None:
    """Print a status line; never fail because nobody is listening.

    Started from a desktop launcher, the helper may have a closed stdout, and a
    failing print must not break the request that wanted to report something.
    """
    try:
        print(f"camview: {msg}", flush=True)
    except (OSError, ValueError):
        pass


class Browser(NamedTuple):
    cmd: list[str]   # command prefix; the viewer arguments are appended
    family: str      # CHROMIUM or GECKO


def browser_family(cmd: list[str]) -> str:
    """Family of a browser command, from its executable name or Flatpak app id.

    Only that name counts, not the whole command: /opt/firefox-tools/chromium is
    Chromium, and "flatpak run io.gitlab.librewolf-community" is Gecko.
    """
    name = os.path.basename(cmd[0])
    if name == "flatpak" and "run" in cmd:
        app = [part for part in cmd[cmd.index("run") + 1:] if not part.startswith("-")]
        name = app[0] if app else name
    return GECKO if GECKO_WORDS & set(re.split(r"[^a-z0-9]+", name.lower())) else CHROMIUM


def find_browser() -> Browser | None:
    """A browser to show the viewer in (Chromium family preferred, then Firefox), or None.

    Runs "flatpak info", so call it once and keep the result.
    """
    override = os.environ.get("CAMVIEW_BROWSER", "").split()
    if override:
        return Browser(override, browser_family(override))
    flatpak = shutil.which("flatpak")
    for family, app_id, names in BROWSERS:
        if flatpak and subprocess.run(["flatpak", "info", app_id], capture_output=True).returncode == 0:
            return Browser(["flatpak", "run", app_id], family)
        for name in names:
            if shutil.which(name):
                return Browser([name], family)
    return None


def viewer_args(browser: Browser, url: str) -> list[str]:
    """Command line that opens url in a viewer window of the given browser.

    Chromium gets a small app-style window. Gecko has no equivalent, so there it
    is an ordinary browser window of the default size.
    """
    if browser.family == GECKO:
        return browser.cmd + ["--new-window", url]
    return browser.cmd + [f"--app={url}", "--window-size=1024,636", "--autoplay-policy=no-user-gesture-required"]


class State:
    def __init__(self, token: str, sdk_path: Path | None, browser: Browser | None = None):
        self.token = token
        self.sdk_path = sdk_path   # None: fetched when the first viewer asks for it
        self._sdk_lock = threading.Lock()
        self.browser = browser
        self.closed = False
        self.close_seen = threading.Event()
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

    def sdk_file(self) -> Path:
        """The verified Agora SDK, downloaded on first use (raises sdk.SdkError)."""
        with self._sdk_lock:  # two viewers must not download it twice
            if self.sdk_path is None:
                self.sdk_path = sdk.ensure_sdk()
            return self.sdk_path

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
            return {"seq": self.seq, "session": self.session if self.seq != since else None,
                    "closed": self.closed}

    def close(self) -> None:
        """Mark the helper as shutting down and give an open viewer time to see it.

        The viewer treats only this notice as "the slicer was closed"; a failed
        poll can also be a suspend or a network change.
        """
        with self.lock:
            self.closed = True
            self.session = None
            viewer_open = time.monotonic() - self.last_poll <= VIEWER_ALIVE
        if viewer_open:
            self.close_seen.wait(VIEWER_CLOSE_WAIT)


def _report_browser_exit(proc: subprocess.Popen, url: str) -> None:
    """Say so if the browser command fails right away (its output is not shown).

    A browser that hands the URL to an already running instance also exits at
    once, but with status 0.
    """
    try:
        status = proc.wait(BROWSER_EXIT_WAIT)
    except subprocess.TimeoutExpired:
        return
    if status != 0:
        log(f"the browser command exited with status {status}; if no viewer window "
            f"appeared, check CAMVIEW_BROWSER or open this URL in a browser: {url}")


def launch_viewer(state: State) -> None:
    url = f"http://127.0.0.1:{state.port}/viewer?ticket={state.new_ticket()}"
    if state.browser is None:
        log(f"no supported browser found; open this URL in one: {url}")
        return
    log("opening the viewer window")
    try:
        proc = subprocess.Popen(viewer_args(state.browser, url),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        log(f"could not start the browser ({e}); open this URL in one: {url}")
        return
    threading.Thread(target=_report_browser_exit, args=(proc, url), daemon=True).start()


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
                try:
                    body = state.sdk_file().read_bytes()
                except (sdk.SdkError, OSError) as e:
                    log(str(e))
                    return self._send(502)
                return self._send(200, body, "text/javascript; charset=utf-8")
            if url.path == "/session":
                try:
                    since = int(q.get("since", ["0"])[0])
                except ValueError:
                    since = 0
                reply = state.poll(since)
                self._send(200, json.dumps(reply).encode(), "application/json")
                if reply["closed"]:
                    state.close_seen.set()
                return
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
            log(f"session received for printer {printer.get('id')}")
            self._send(204)

    return Handler


def start_server(token: str, sdk_path: Path | None, browser: Browser | None = None) -> tuple[ThreadingHTTPServer, State]:
    state = State(token, sdk_path, browser)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    state.port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, state
