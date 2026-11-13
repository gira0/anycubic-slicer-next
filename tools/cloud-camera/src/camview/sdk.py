"""Fetch and cache the Agora Web SDK (the version the slicer bundles)."""
import hashlib
import os
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "4.24.4"
URL = f"https://cdn.jsdelivr.net/npm/agora-rtc-sdk-ng@{VERSION}/AgoraRTC_N-production.js"
SHA256 = "95b6f11857017444b89d6cd1dbb68d7b8cc0e8855ace7c2c88500190428b118d"
STALE_PART_AGE = 3600  # seconds after which a leftover .sdk-*.part file is removed


class SdkError(RuntimeError):
    pass


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "camview"


def _valid(path: Path) -> bool:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() == SHA256
    except OSError:
        return False


def _remove_stale_parts(directory: Path) -> None:
    """Remove temporary files left behind by a download that was killed."""
    for part in directory.glob(".sdk-*.part"):
        try:
            # Old enough that no running download can still be writing it.
            if time.time() - part.stat().st_mtime > STALE_PART_AGE:
                part.unlink()
        except OSError:
            pass


def ensure_sdk() -> Path:
    """Return the path of the verified SDK, downloading it on first use.

    The download is written to a temporary file and published with an atomic
    rename, so no camview process ever reads a partially written file.
    """
    path = cache_dir() / f"AgoraRTC_N-{VERSION}.js"
    if _valid(path):
        return path
    try:
        print(f"Downloading Agora Web SDK {VERSION} ...", flush=True)
    except (OSError, ValueError):  # nobody listening; the download still matters
        pass
    try:
        with urllib.request.urlopen(URL, timeout=60) as resp:
            data = resp.read()
    except (urllib.error.URLError, OSError) as e:
        raise SdkError(f"could not download the Agora Web SDK from {URL}: {e}") from e
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256:
        raise SdkError(f"Agora SDK checksum mismatch: got {digest}, expected {SHA256}")
    # A unique name opened with "x" instead of mkstemp, so the cached file gets
    # the usual umask-based permissions rather than 0600.
    tmp = path.parent / f".sdk-{os.getpid()}-{secrets.token_hex(4)}.part"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _remove_stale_parts(path.parent)
        try:
            with open(tmp, "xb") as f:
                f.write(data)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as e:
        raise SdkError(f"could not store the Agora Web SDK in {path.parent}: {e}") from e
    return path
