"""Fetch and cache the Agora Web SDK (the version the slicer bundles)."""
import hashlib
import os
import urllib.request
from pathlib import Path

VERSION = "4.24.4"
URL = f"https://cdn.jsdelivr.net/npm/agora-rtc-sdk-ng@{VERSION}/AgoraRTC_N-production.js"
SHA256 = "95b6f11857017444b89d6cd1dbb68d7b8cc0e8855ace7c2c88500190428b118d"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "camview"


def ensure_sdk() -> Path:
    """Return the path of the verified SDK, downloading it on first use."""
    path = cache_dir() / f"AgoraRTC_N-{VERSION}.js"
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == SHA256:
        return path
    print(f"Downloading Agora Web SDK {VERSION} ...")
    with urllib.request.urlopen(URL, timeout=60) as resp:
        data = resp.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256:
        raise RuntimeError(f"Agora SDK checksum mismatch: got {digest}, expected {SHA256}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path
