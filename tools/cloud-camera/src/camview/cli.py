"""camview command line: run the slicer with a patched Workbench and a camera viewer."""
from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import patch, sdk, server, sidecar


def _find_lib(args, workdir: Path) -> Path:
    if args.lib:
        return Path(args.lib)
    appimage = Path(args.appimage or os.environ.get("CAMVIEW_APPIMAGE", "")).expanduser()
    if not appimage.is_file():
        sys.exit("camview: pass --appimage PATH (or --lib PATH to libWorkbench.so), or set CAMVIEW_APPIMAGE")
    extract = workdir / "appimage"
    extract.mkdir()
    r = subprocess.run([str(appimage.resolve()), "--appimage-extract", "lib/libWorkbench.so"],
                       cwd=extract, capture_output=True)
    lib = extract / "squashfs-root" / "lib" / "libWorkbench.so"
    if r.returncode != 0 or not lib.is_file():
        sys.exit("camview: could not extract lib/libWorkbench.so from the AppImage")
    return lib


def _prepare(args, workdir: Path) -> Path:
    lib = _find_lib(args, workdir)
    root = workdir / "webui"
    root.mkdir()
    patch.extract_webui(lib, root)
    patch.patch_webui(root)
    return root


def cmd_prepare(args) -> int:
    """Extract and patch the web UI into a directory (for inspection)."""
    out = Path(args.out)
    with tempfile.TemporaryDirectory(prefix="camview-") as tmp:
        root = _prepare(args, Path(tmp))
        shutil.copytree(root, out, dirs_exist_ok=True)
    print(f"Patched web UI written to {out}")
    return 0


def cmd_run(args) -> int:
    appimage = Path(args.appimage or os.environ.get("CAMVIEW_APPIMAGE", "")).expanduser()
    if not appimage.is_file():
        sys.exit("camview: pass --appimage PATH or set CAMVIEW_APPIMAGE")
    sdk_path = sdk.ensure_sdk()
    token = secrets.token_urlsafe(24)
    httpd, state = server.start_server(token, lambda: sdk_path)
    with tempfile.TemporaryDirectory(prefix="camview-") as tmp:
        try:
            root = _prepare(args, Path(tmp))
        except patch.PatchError as e:
            sys.exit(f"camview: {e}")
        env = dict(os.environ, ACNEXT_WORKBENCH_ENV_VAR=f"{(root / 'index.html').as_uri()}?cv={state.port}.{token}")
        if server.find_browser_command() is None:
            print("camview: warning: no Chromium-family browser found; set CAMVIEW_BROWSER")
        print("camview: starting the slicer with the patched Workbench")
        try:
            return subprocess.call([str(appimage.resolve()), *args.slicer_args], env=env)
        finally:
            httpd.shutdown()


def cmd_sidecar(args) -> int:
    """Used by the AppImage's AppRun; see sidecar.py."""
    return sidecar.run_sidecar(Path(args.lib), args.parent_pid, Path(args.ready_file))


def main() -> None:
    p = argparse.ArgumentParser(prog="camview", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn, help_ in (("run", cmd_run, "run the slicer with cloud camera support"),
                            ("prepare", cmd_prepare, "extract and patch the web UI into a directory")):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--appimage", help="path to the Anycubic Slicer AppImage (or CAMVIEW_APPIMAGE)")
        if name == "prepare":
            sp.add_argument("--lib", help="path to libWorkbench.so instead of an AppImage")
            sp.add_argument("out", help="output directory")
        else:
            sp.set_defaults(lib=None)
            sp.add_argument("slicer_args", nargs="*", help="arguments passed to the slicer")
        sp.set_defaults(fn=fn)
    sc = sub.add_parser("sidecar", help="AppImage mode: prepare the UI, serve the helper, write the URL")
    sc.add_argument("--lib", required=True, help="path to libWorkbench.so")
    sc.add_argument("--parent-pid", type=int, required=True, help="exit when this process exits")
    sc.add_argument("--ready-file", required=True, help="file the Workbench URL is written to")
    sc.set_defaults(fn=cmd_sidecar)
    args = p.parse_args()
    sys.exit(args.fn(args))
