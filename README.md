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

## Automated Updates

The GitHub Actions workflow in `.github/workflows/appimage.yml` runs daily at
03:17 UTC and can also be started manually with `workflow_dispatch`.

Each run:

1. Reads the current package filename from Anycubic's APT repository.
2. Extracts the real application version from the Debian binary. The Debian
	package version and application version are different.
3. Checks whether the matching GitHub release contains the versioned AppImage,
	stable AppImage, and `.zsync` asset.
4. Skips the expensive AppImage build when the release is complete.
5. Builds and publishes a new release, or repairs missing assets on an existing
	release.

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
