"""Sidecar mode: the helper as started by the AppImage's AppRun.

AppRun starts this in the background before it execs the slicer. The sidecar
patches a copy of the Workbench web UI, starts the helper server and writes the
Workbench URL to a ready file; AppRun exports that URL to the slicer. It then
runs until the slicer exits.

Whatever goes wrong here (no browser, a patch that no longer applies, an
unwritable cache) ends the sidecar without a ready file, and AppRun starts the
slicer as usual. The camera must never keep the slicer from starting.
"""
import os
import secrets
import shutil
import signal
import threading
from pathlib import Path

from . import patch, sdk, server

EXIT_PATCH_FAILED = 3   # same meaning as in cli.py
EXIT_NO_BROWSER = 4
RUN_PREFIX = "run-"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:  # exists, but belongs to someone else
        return True
    return True


def _remove_stale_runs(base: Path) -> None:
    """Remove web UI copies whose sidecar was killed before it could clean up."""
    for run in base.glob(RUN_PREFIX + "*"):
        try:
            pid = int(run.name.split("-")[1])
        except (IndexError, ValueError):
            continue
        if not _pid_alive(pid):
            shutil.rmtree(run, ignore_errors=True)


def _run_dir() -> Path:
    """A private directory for this run's web UI copy.

    It lives in the cache directory, not in /tmp: the copy is about 70 MB and
    /tmp is often kept in memory.
    """
    base = sdk.cache_dir() / "webui"
    base.mkdir(parents=True, exist_ok=True)
    _remove_stale_runs(base)
    run = base / f"{RUN_PREFIX}{os.getpid()}-{secrets.token_hex(4)}"
    run.mkdir(mode=0o700)
    return run


def run_sidecar(lib: Path, parent_pid: int, ready_file: Path) -> int:
    if os.getppid() != parent_pid:
        server.log("the cloud camera is off: the helper was not started by the slicer's launcher")
        return 1
    browser = server.find_browser()
    if browser is None:
        server.log("no supported browser (Chromium family or Firefox) found, so the cloud camera "
                   "is off; set CAMVIEW_BROWSER to a browser command to enable it")
        return EXIT_NO_BROWSER

    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *_: stop.set())

    token = secrets.token_urlsafe(24)
    # No SDK yet: it is downloaded when a viewer first asks for it, so a start
    # without a cloud camera never touches the network.
    httpd, state = server.start_server(token, None, browser)
    root: Path | None = None
    try:
        try:
            root = _run_dir()
            patch.extract_webui(lib, root)
            patch.patch_webui(root, f"http://127.0.0.1:{state.port}", token)
        except patch.PatchError as e:
            server.log(f"the cloud camera is off: {e}")
            return EXIT_PATCH_FAILED
        except OSError as e:
            server.log(f"the cloud camera is off: {e}")
            return 1

        # Written under another name first, so AppRun never reads half a URL.
        tmp = ready_file.with_name(ready_file.name + ".tmp")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write((root / "index.html").as_uri() + "\n")
            os.replace(tmp, ready_file)
        except OSError as e:
            server.log(f"the cloud camera is off: {e}")
            return 1

        # AppRun execs the slicer, which keeps AppRun's PID. When that process
        # dies we get a new parent, so this also survives PID reuse.
        while not stop.wait(1) and os.getppid() == parent_pid:
            pass
        state.close()  # lets an open viewer know that the slicer is gone
        httpd.shutdown()
        return 0
    finally:
        # The failure paths skip httpd.shutdown(): it waits up to half a second,
        # AppRun is waiting for us, and the server thread ends with the process.
        if root is not None:
            shutil.rmtree(root, ignore_errors=True)
