#!/usr/bin/env bash
set -euo pipefail

apt_base_url="${APT_BASE_URL:-https://cdn-universe-slicer.anycubic.com/prod}"
packages_url="$apt_base_url/dists/noble/main/binary-amd64/Packages"
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=appimage/fetch-upstream.sh
source "$script_dir/fetch-upstream.sh"
work_dir="${RUNNER_TEMP:-/tmp}/anycubic-slicer-build"
deb_path="$work_dir/anycubicslicernext.deb"
app_dir="$work_dir/AnycubicSlicer.AppDir"
appimage_tool="$work_dir/appimagetool"

rm -rf "$work_dir"
mkdir -p "$work_dir" "$app_dir"

packages=$(fetch_upstream "$packages_url")
deb_filename=$(package_field Filename <<< "$packages")
deb_sha256=$(package_field SHA256 <<< "$packages")
if [[ -z "$deb_filename" || -z "$deb_sha256" ]]; then
    echo "Could not find the anycubicslicernext Filename and SHA256 in the APT index" >&2
    exit 1
fi

fetch_upstream -o "$deb_path" "$apt_base_url/$deb_filename"
if ! sha256sum --check --quiet <<< "$deb_sha256  $deb_path"; then
    echo "Downloaded package does not match the SHA256 in the APT index" >&2
    exit 1
fi
app_version=$(strip_epoch "$(dpkg-deb -f "$deb_path" Version)")
if [[ -z "$app_version" ]]; then
    echo "Could not determine the application version from $deb_path" >&2
    exit 1
fi
validate_version "$app_version"
# The workflow passes the version the check job verified. Building a different
# one would publish a release whose completeness was never checked.
if [[ -n "${EXPECTED_APP_VERSION:-}" && "$app_version" != "$EXPECTED_APP_VERSION" ]]; then
    echo "Upstream changed from $EXPECTED_APP_VERSION to $app_version since the check; the next run picks it up" >&2
    exit 1
fi
# Upstream version plus packaging revision, for example 2.0.06-1.
release_version="$app_version-$(package_revision "$script_dir")"

mkdir -p "$work_dir/extracted"
cd "$work_dir/extracted"
ar x "$deb_path"
tar -xf data.tar.*
cp -a usr/. "$app_dir/"

cp "$script_dir/AppRun" "$app_dir/AppRun"
# The camview cloud camera helper (tools/cloud-camera). AppRun starts it next to
# the slicer. It is pure standard library Python; the host provides python3.
mkdir -p "$app_dir/camview"
cp -a "$script_dir/../tools/cloud-camera/src/camview" "$app_dir/camview/camview"
# camview patches the Workbench web UI on the user's machine. Check here whether
# the patch still applies to this upstream version. If it does not, the AppImage
# is still good: the helper notices the same thing at start and the slicer runs
# without the cloud camera. So this warns and lets the release notes say so,
# instead of holding back a new slicer version.
camview_patch=ok
camview_status=0
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$app_dir/camview" python3 -P -s -c \
    'import sys; from camview.cli import main; sys.argv[0] = "camview"; main()' \
    prepare --lib "$app_dir/lib/libWorkbench.so" "$work_dir/camview-check" >/dev/null || camview_status=$?
# 3 is camview's exit status for a patch that does not apply (EXIT_PATCH_FAILED
# in cli.py). Anything else failed before or after the patch step, which means
# the build itself is broken.
if (( camview_status == 3 )); then
    camview_patch=failed
    echo "::warning title=camview patch::The camview web UI patch does not apply to $app_version, so this AppImage runs without the cloud camera; fix tools/cloud-camera/src/camview/patch.py and bump appimage/PACKAGE_REVISION" >&2
elif (( camview_status != 0 )); then
    echo "::error title=camview check::'camview prepare' failed with status $camview_status before it could check the web UI patch (python3 3.11 or newer missing, import error, or no lib/libWorkbench.so in the package?); see the log above" >&2
    exit 1
fi
rm -rf "$work_dir/camview-check"
find "$app_dir/camview" -name __pycache__ -type d -prune -exec rm -rf {} +
chmod +x "$app_dir/AppRun"
cp -a "$app_dir/share/AnycubicSlicerNext/resources" "$app_dir/resources"

source_desktop_file="$app_dir/share/applications/AnycubicSlicer.desktop"
if [[ ! -f "$source_desktop_file" ]]; then
    echo "Expected desktop file was not found: $source_desktop_file" >&2
    exit 1
fi

desktop_file="$app_dir/AnycubicSlicer.desktop"
cp "$source_desktop_file" "$desktop_file"
sed -i 's|^Icon=.*|Icon=AnycubicSlicer|' "$desktop_file"

icon_file="$app_dir/share/AnycubicSlicerNext/resources/images/AnycubicSlicer.png"
if [[ ! -f "$icon_file" ]]; then
    echo "Expected icon file was not found: $icon_file" >&2
    exit 1
fi
cp "$icon_file" "$app_dir/AnycubicSlicer.png"
# Ship .DirIcon as a regular file. appimagetool otherwise creates a symlink, and
# integrators such as Gear Lever extract only .DirIcon, get a dangling link and
# install no icon, so the taskbar shows none.
cp "$icon_file" "$app_dir/.DirIcon"

# appimagetool embeds this in the runtime's .upd_info section, which is where
# AppImageUpdate reads it. A key in the .desktop file is not used.
update_information="gh-releases-zsync|gira0|anycubic-slicer-next|latest|AnycubicSlicer-x86_64.AppImage.zsync"

# AppImageKit is archived, so this continuous build no longer changes. The
# checksum makes sure the tool that packages the release is the one we tested.
appimage_tool_sha256=b90f4a8b18967545fda78a445b27680a1642f1ef9488ced28b65398f2be7add2
curl -fsSL -o "$appimage_tool" \
    https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
if ! sha256sum --check --quiet <<< "$appimage_tool_sha256  $appimage_tool"; then
    echo "appimagetool does not match the pinned SHA256" >&2
    exit 1
fi
chmod +x "$appimage_tool"

versioned_appimage="$work_dir/AnycubicSlicer-${release_version}-x86_64.AppImage"
latest_appimage="$work_dir/AnycubicSlicer-x86_64.AppImage"
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 "$appimage_tool" \
    -u "$update_information" "$app_dir" "$versioned_appimage"
cp "$versioned_appimage" "$latest_appimage"
# A relative URL resolves next to the .zsync file on the release page. Without
# -u, zsyncmake records this runner's local path.
zsyncmake -u "$(basename -- "$latest_appimage")" -o "$latest_appimage.zsync" "$latest_appimage"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    {
        printf 'app_version=%s\n' "$app_version"
        printf 'release_version=%s\n' "$release_version"
        printf 'versioned_appimage=%s\n' "$versioned_appimage"
        printf 'latest_appimage=%s\n' "$latest_appimage"
        printf 'zsync=%s\n' "$latest_appimage.zsync"
        printf 'camview_patch=%s\n' "$camview_patch"
    } >> "$GITHUB_OUTPUT"
fi

printf '%s\n' "$release_version"