# Repository Agent Guidance

## Project Scope

This repository packages Anycubic Slicer Next for Linux as an AppImage and a
Flatpak. Keep packaging changes focused and preserve the existing runtime
workarounds unless a tested replacement is available.

## AppImage Automation

- The workflow is `.github/workflows/appimage.yml`. It runs daily, on pushes to
  `main` that touch `appimage/`, `tools/cloud-camera/` or the workflow, and on
  manual dispatch. One job checks, builds and publishes.
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

## Cloud Camera (camview)

- There is one AppImage and one release stream. It ships
  `tools/cloud-camera/src/camview` in the AppDir, and `appimage/AppRun` starts it
  as a helper next to the slicer (`camview sidecar`). Cloud camera support is on
  by default; `CAMVIEW=0` in the environment or `--no-camview` as the first
  argument turns it off. `AppRun camview ...` still runs the tool itself.
- The helper must never keep the slicer from starting. `AppRun` waits for it at
  most ten seconds, and anything missing or failing (host `python3` 3.11+, a
  browser, a web UI the patch no longer fits) starts the slicer exactly as
  before. Keep that property in any change to `AppRun` or `sidecar.py`, and keep
  the helper start above the `LD_LIBRARY_PATH` export so `python3` and the
  browser never load bundled libraries.
- The helper downloads nothing at start. The Agora Web SDK is fetched when a
  viewer first asks for it.
- The build runs `camview prepare` against the new `libWorkbench.so`. A patch
  that no longer applies is a warning, not a failure: the release is published
  and its notes say that cloud camera viewing does not work yet. Fix `patch.py`
  and bump the revision. Any other failure of that check fails the build.
- Until `2.0.0.6-2` there was a separate camview stream (pre-releases tagged
  `<version>-<revision>-camview`, update string `latest-pre`). It is no longer
  built. Releases of the one stream must stay regular releases, because the
  update string follows `latest`. An even earlier sidecar design is kept as the
  tag `archive/appimage-cloud-camera`.

## Validation

Run these checks after changing shell scripts or the workflow:

```bash
bash -n appimage/check-latest.sh
bash -n appimage/build-latest.sh
bash -n appimage/fetch-upstream.sh
bash -n appimage/AppRun
git diff --check
```

Use an Ubuntu 24.04 environment for packaging validation. `appimagetool` is an
AppImage and requires FUSE compatibility support (`libfuse2t64`) or an equivalent
extract-and-run setup.

## Release Safety

Do not commit generated AppImages, extracted Debian contents, or temporary build
directories. Do not create a release for a release tag (version plus packaging
revision) that already has all required assets.

## Documentation

- `docs/cloud-video-investigation.md`: why cloud-connected video monitoring does
  not work on Linux (no WebRTC in the system WebKitGTK), what was tried
  (patching `libWorkbench.so` crashes the app via an integrity check;
  `ACNEXT_WORKBENCH_ENV_VAR` works as a Workbench URL override), and how to
  revisit it. Read it before attempting any video-related change, and do not
  modify `libWorkbench.so`. Keep `*.apk` files out of git.
- `tools/cloud-camera/`: `camview`, a `uv` prototype that shows cloud printer
  cameras on Linux through a patched Workbench copy and a browser viewer window
  (see its README). The AppImage starts it by default; to run the working tree
  against an AppImage, use `uv run camview run --appimage PATH`.
