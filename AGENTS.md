# Repository Agent Guidance

## Project Scope

This repository packages Anycubic Slicer Next for Linux as an AppImage and a
Flatpak. Keep packaging changes focused and preserve the existing runtime
workarounds unless a tested replacement is available.

## AppImage Automation

- The workflow is `.github/workflows/appimage.yml`. It runs daily, on pushes to
  `main` that touch `appimage/`, `tools/cloud-camera/` or the workflow, and on
  manual dispatch. One matrix job per variant checks, builds and publishes.
- `appimage/check-latest.sh` reads the Debian package `Version` from Anycubic's
  APT metadata and strips the epoch (`1:2.0.0.6` -> `2.0.0.6`). Current binaries
  no longer embed the application version, so do not go back to `strings`.
- Release tags are `<version>-<revision>` (from `2.0.0.6-1` on). The revision is
  `appimage/PACKAGE_REVISION`, a positive integer. Bump it in any change that
  should ship new AppImages for an already released upstream version; it may go
  back to `1` when the upstream version changes.
- `appimage/build-latest.sh` builds the AppImage, injects AppImageUpdate metadata,
  and creates the matching `.zsync` file.
- The workflow must check release completeness before doing the expensive build.
- Required release assets are the versioned
  `AnycubicSlicer-<version>-<revision>-x86_64.AppImage`, stable
  `AnycubicSlicer-x86_64.AppImage`, and
  `AnycubicSlicer-x86_64.AppImage.zsync`.

## Camview Variant

- The schedule and pushes build both variants; a manual run picks `both`,
  `original` or `camview`. The camview variant publishes a separate release
  tagged `<version>-<revision>-camview`, created with `--latest=false --prerelease`,
  with assets `AnycubicSlicer-<version>-<revision>-camview-x86_64.AppImage`,
  `AnycubicSlicer-camview-x86_64.AppImage` and its `.zsync`.
- `appimage/build-latest.sh` reads `VARIANT` (default `original`). The original
  variant's output must stay identical. The camview variant ships
  `tools/cloud-camera/src/camview` in the AppDir, and `appimage/AppRun.camview`
  becomes its `AppRun`: `AppRun camview ...` runs the tool with the host
  `python3`, anything else goes to the unchanged `AppRun`, kept as `AppRun.slicer`.
- The camview update string follows `latest-pre` (AppImageUpdate maps any other
  value to one exact tag, which would pin the AppImage to its own release), so
  camview releases must stay pre-releases and original releases must not be.

## Validation

Run these checks after changing shell scripts or the workflow:

```bash
bash -n appimage/check-latest.sh
bash -n appimage/build-latest.sh
bash -n appimage/fetch-upstream.sh
bash -n appimage/AppRun
bash -n appimage/AppRun.camview
git diff --check
```

Use an Ubuntu 24.04 environment for packaging validation. `appimagetool` is an
AppImage and requires FUSE compatibility support (`libfuse2t64`) or an equivalent
extract-and-run setup.

## Release Safety

Do not commit generated AppImages, extracted Debian contents, or temporary build
directories. Do not create a release for a release tag (version plus packaging revision,
plus `-camview` for that stream) that already has all required assets.

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
