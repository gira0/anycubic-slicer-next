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

KEEP_CACHED_UIS = 2


def _log(msg: str) -> None:
    print(f"camview: {msg}", file=sys.stderr, flush=True)


def prepared_webui(lib: Path) -> Path:
    """Return the cached patched web UI for this libWorkbench.so, creating it if needed."""
    digest = hashlib.sha256(lib.read_bytes()).hexdigest()[:16]
    webui_dir = sdk.cache_dir() / "webui"
    target = webui_dir / f"{digest}-v{patch.PATCH_VERSION}"
    if (target / "index.html").is_file():
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
    # Prune older UIs (other slicer versions).
    old = sorted((d for d in webui_dir.iterdir() if d.is_dir() and not d.name.startswith(".")),
                 key=lambda d: d.stat().st_mtime, reverse=True)
    for d in old[KEEP_CACHED_UIS:]:
        shutil.rmtree(d, ignore_errors=True)
    return target


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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
    tmp.write_text(url + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, ready_file)

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    while not stop.is_set() and _alive(parent_pid):
        time.sleep(1)
    httpd.shutdown()
    return 0


def _prefetch_sdk() -> None:
    try:
        sdk.ensure_sdk()
    except Exception as e:
        _log(f"could not prefetch the Agora SDK ({e}); will retry when the viewer opens")
