# Anycubic Slicer Next

[![GitHub release](https://img.shields.io/github/release/gira0/anycubic-slicer-next.svg)](https://github.com/gira0/anycubic-slicer-next/releases)

Linux Flatpak and AppImage packages for Anycubic Slicer Next.

Download at the [releases](https://github.com/gira0/anycubic-slicer-next/releases) page.

## AppImage

Download `AnycubicSlicer-x86_64.AppImage` from the latest GitHub release, make it
executable, and run it:

```bash
chmod +x AnycubicSlicer-x86_64.AppImage
./AnycubicSlicer-x86_64.AppImage
```

The AppImage includes AppImageUpdate metadata. The updater uses the stable
`AnycubicSlicer-x86_64.AppImage` release asset and its matching
`AnycubicSlicer-x86_64.AppImage.zsync` file to download future updates.

The AppImage requires glibc 2.38+ and GLib 2.76+. Use the Flatpak on older Linux
distributions.

### Cloud printer cameras

Anycubic disables the camera view for cloud-connected printers on Linux. The
AppImage works around that: press play on a cloud printer's camera and the video
opens in a separate browser window. This needs `python3` 3.11 or newer and a
Chromium-family browser or Firefox on the host. If something is missing, the
slicer simply starts without it. Details and limits are in
[tools/cloud-camera/README.md](tools/cloud-camera/README.md).

It is on by default. To turn it off, set `CAMVIEW=0` in the environment or pass
`--no-camview` as the first argument:

```bash
CAMVIEW=0 ./AnycubicSlicer-x86_64.AppImage
./AnycubicSlicer-x86_64.AppImage --no-camview
```

Until 2.0.0.6-2 this was a separate download (`AnycubicSlicer-camview-x86_64.AppImage`,
published as pre-releases). That stream has ended; switch to the regular
AppImage and drop the `camview run` arguments from your launcher.

## Automated Updates

The GitHub Actions workflow in `.github/workflows/appimage.yml` runs daily at
03:17 UTC, on pushes to `main` that touch `appimage/`, `tools/cloud-camera/` or
the workflow itself, and manually with `workflow_dispatch`.

Releases are tagged `<package version>-<packaging revision>`, for example
`2.0.0.6-1`. The revision lives in `appimage/PACKAGE_REVISION`. To ship a
packaging fix for an upstream version that is already released, bump it; a push
without a bump finds the releases complete and builds nothing.

Each run:

1. Reads the current package version from Anycubic's APT repository, drops a
	Debian epoch such as `1:`, and appends the packaging revision.
2. Checks whether the matching GitHub release contains the versioned AppImage,
	stable AppImage, and `.zsync` asset.
3. Skips the expensive AppImage build when the release is complete.
4. Downloads the package, verifies it against the checksum in the APT index,
	then builds and publishes a new release, or repairs missing assets on an
	existing release.

The build and version detection scripts are in `appimage/`. The latest known
application version is determined from the live APT package rather than being
hardcoded in this repository.

## Flatpak

The Flatpak build instructions are in [flatpak/HOWTO.md](flatpak/HOWTO.md).

## Building

The AppImage build instructions, including dependencies and troubleshooting, are
in [appimage/HOWTO.md](appimage/HOWTO.md).

Packages are published in the [GitHub releases](https://github.com/gira0/anycubic-slicer-next/releases) section.

If this helps you please star the repo or support me on Ko-fi.
