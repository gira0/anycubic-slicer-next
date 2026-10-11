"""Fetch and cache the Agora Web SDK (the version the slicer bundles)."""
from __future__ import annotations

import hashlib
import os
import tempfile
import threading
import urllib.request
from pathlib import Path

VERSION = "4.24.4"
URL = f"https://cdn.jsdelivr.net/npm/agora-rtc-sdk-ng@{VERSION}/AgoraRTC_N-production.js"
SHA256 = "95b6f11857017444b89d6cd1dbb68d7b8cc0e8855ace7c2c88500190428b118d"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "camview"


_download_lock = threading.Lock()


def _valid(path: Path) -> bool:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() == SHA256
    except OSError:
        return False


def ensure_sdk() -> Path:
    """Return the path of the verified SDK, downloading it on first use.

    Safe to call from several threads and processes: downloads are serialized in
    this process and published with an atomic rename, so readers never see a
    partially written file.
    """
    path = cache_dir() / f"AgoraRTC_N-{VERSION}.js"
    with _download_lock:
        if _valid(path):
            return path
        print(f"Downloading Agora Web SDK {VERSION} ...")
        with urllib.request.urlopen(URL, timeout=60) as resp:
            data = resp.read()
        digest = hashlib.sha256(data).hexdigest()
        if digest != SHA256:
            raise RuntimeError(f"Agora SDK checksum mismatch: got {digest}, expected {SHA256}")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".sdk-", suffix=".part")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return path
