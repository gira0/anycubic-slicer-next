# Repository Agent Guidance

## Project Scope

This repository packages Anycubic Slicer Next for Linux as an AppImage and a
Flatpak. Keep packaging changes focused and preserve the existing runtime
workarounds unless a tested replacement is available.

## AppImage Automation

- The daily workflow is `.github/workflows/appimage.yml`.
- `appimage/check-latest.sh` reads Anycubic's APT metadata and extracts the real
  application version from the binary. The Debian package version is different.
- `appimage/build-latest.sh` builds the AppImage, injects AppImageUpdate metadata,
  and creates the matching `.zsync` file.
- The workflow must check release completeness before doing the expensive build.
- Required release assets are the versioned AppImage, stable
  `AnycubicSlicer-x86_64.AppImage`, and
  `AnycubicSlicer-x86_64.AppImage.zsync`.

## Validation

Run these checks after changing shell scripts or the workflow:

```bash
bash -n appimage/check-latest.sh
bash -n appimage/build-latest.sh
bash -n appimage/AppRun
git diff --check
```

Use an Ubuntu 24.04 environment for packaging validation. `appimagetool` is an
AppImage and requires FUSE compatibility support (`libfuse2t64`) or an equivalent
extract-and-run setup.

## Release Safety

Do not commit generated AppImages, extracted Debian contents, or temporary build
directories. Do not create a release for an application version that already has
all required assets.

## Documentation

- `docs/cloud-video-investigation.md`: why cloud-connected video monitoring does
  not work on Linux (no WebRTC in the system WebKitGTK), what was tried
  (patching `libWorkbench.so` crashes the app via an integrity check;
  `ACNEXT_WORKBENCH_ENV_VAR` works as a Workbench URL override), and how to
  revisit it. Read it before attempting any video-related change, and do not
  modify `libWorkbench.so`. Keep `*.apk` files out of git.
- `tools/cloud-camera/`: `camview`, a `uv` prototype that shows cloud printer
  cameras on Linux through a patched Workbench copy and a Chromium viewer window
  (see its README). Run it with `uv run camview run --appimage PATH`.
  The AppImage bundles it (`share/camview`) and `AppRun` starts it as a sidecar. Keep it
  stdlib-only and Python 3.9 compatible, bump `PATCH_VERSION` in `patch.py` when the
  web UI patch changes, and never ship patched copies of Anycubic's web assets.
