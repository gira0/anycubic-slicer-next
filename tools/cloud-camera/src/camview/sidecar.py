"""Sidecar mode, started by the AppImage's AppRun.

Prepares (and caches) the patched Workbench web UI from the installed
libWorkbench.so, starts the helper server, writes the Workbench URL for the
slicer to a ready file, then keeps running until the slicer process exits.
If anything is unsupported (no browser, patch no longer matches, ...) it exits
without writing a URL and the slicer starts stock.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import signal
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import patch, sdk, server

KEEP_CACHED_UIS = 2        # newest cached UIs that are never pruned
HEARTBEAT = 30             # seconds between "still in use" touches of the UI directory
ACTIVE_WINDOW = 180        # a UI touched this recently belongs to a running sidecar


def _log(msg: str) -> None:
    print(f"camview: {msg}", file=sys.stderr, flush=True)


def prepared_webui(lib: Path) -> Path:
    """Return the cached patched web UI for this libWorkbench.so, creating it if needed."""
    digest = hashlib.sha256(lib.read_bytes()).hexdigest()[:16]
    webui_dir = sdk.cache_dir() / "webui"
    target = webui_dir / f"{digest}-v{patch.PATCH_VERSION}"
    if (target / "index.html").is_file():
        _touch(target)
        return target
    webui_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".new-", dir=webui_dir))
    try:
        patch.extract_webui(lib, tmp)
        patch.patch_webui(tmp)
        try:
            os.rename(tmp, target)
        except OSError:
            # Fine only if another instance won the race with a complete copy;
            # any other failure must not publish a URL to a missing index.html.
            if not (target / "index.html").is_file():
                raise
            shutil.rmtree(tmp, ignore_errors=True)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    _touch(target)
    prune(webui_dir)
    return target


def _touch(path: Path) -> None:
    try:
        os.utime(path)
    except OSError:
        pass


def prune(webui_dir: Path, now: float | None = None) -> None:
    """Remove cached UIs of old slicer versions.

    Keeps the newest KEEP_CACHED_UIS and any directory touched within ACTIVE_WINDOW:
    running sidecars refresh their directory every HEARTBEAT seconds, and the slicer
    keeps loading assets from it, so an in-use UI must never be deleted.
    """
    now = time.time() if now is None else now
    dirs = sorted((d for d in webui_dir.iterdir() if d.is_dir() and not d.name.startswith(".")),
                  key=lambda d: d.stat().st_mtime, reverse=True)
    for d in dirs[KEEP_CACHED_UIS:]:
        if now - d.stat().st_mtime > ACTIVE_WINDOW:
            shutil.rmtree(d, ignore_errors=True)


def _parent_alive(parent_pid: int) -> bool:
    """True while we are still a child of the process that started us.

    AppRun starts the sidecar as a background child and later exec()s the slicer, so
    the parent keeps the same PID. Comparing getppid() is robust against PID reuse
    (when the parent dies we are re-parented and getppid() changes).
    """
    return os.getppid() == parent_pid


def run_sidecar(lib: Path, parent_pid: int, ready_file: Path) -> int:
    if server.find_browser_command() is None:
        _log("no supported browser (Chromium family or Firefox) found; cloud camera support disabled "
             "(set CAMVIEW_BROWSER to enable)")
        return 3
    try:
        webui = prepared_webui(lib)
    except Exception as e:  # patch mismatch, unreadable library, ...
        _log(f"cloud camera support disabled: {e}")
        return 4

    token = secrets.token_urlsafe(24)
    httpd, state = server.start_server(token, sdk.ensure_sdk)
    threading.Thread(target=lambda: _prefetch_sdk(), daemon=True).start()

    url = f"{(webui / 'index.html').as_uri()}?cv={state.port}.{token}"
    tmp = ready_file.with_name(ready_file.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(url + "\n")
    os.replace(tmp, ready_file)

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    last_beat = time.monotonic()
    while not stop.is_set() and _parent_alive(parent_pid):
        time.sleep(1)
        if time.monotonic() - last_beat >= HEARTBEAT:
            _touch(webui)  # tell other sidecars' pruning that this UI is in use
            last_beat = time.monotonic()
    httpd.shutdown()
    return 0


def _prefetch_sdk() -> None:
    try:
        sdk.ensure_sdk()
    except Exception as e:
        _log(f"could not prefetch the Agora SDK ({e}); will retry when the viewer opens")
