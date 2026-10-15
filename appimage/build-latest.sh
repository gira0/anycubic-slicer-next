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

# Capture the index before parsing it: awk exits at the first match, and with
# pipefail a curl killed by SIGPIPE would abort the build.
packages=$(fetch_upstream "$packages_url")
deb_filename=$(awk '
    /^Package: anycubicslicernext$/ { in_package=1; next }
    in_package && /^Filename:/ { print $2; exit }
    in_package && /^$/ { in_package=0 }
' <<< "$packages")
if [[ -z "$deb_filename" ]]; then
    echo "Could not find anycubicslicernext in the APT index" >&2
    exit 1
fi

fetch_upstream -o "$deb_path" "$apt_base_url/$deb_filename"
app_version=$(dpkg-deb -f "$deb_path" Version)
if [[ -z "$app_version" ]]; then
    echo "Could not determine the application version from $deb_path" >&2
    exit 1
fi

mkdir -p "$work_dir/extracted"
cd "$work_dir/extracted"
ar x "$deb_path"
tar -xf data.tar.*
cp -a usr/. "$app_dir/"

cp "$script_dir/AppRun" "$app_dir/AppRun"
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
if [[ -f "$icon_file" ]]; then
    cp "$icon_file" "$app_dir/AnycubicSlicer.png"
fi

# appimagetool embeds this in the runtime's .upd_info section, which is where
# AppImageUpdate reads it. A key in the .desktop file is not used.
update_information='gh-releases-zsync|gira0|anycubic-slicer-next|latest|AnycubicSlicer-x86_64.AppImage.zsync'

if [[ ! -x "$appimage_tool" ]]; then
    curl -fsSL -o "$appimage_tool" \
        https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$appimage_tool"
fi

versioned_appimage="$work_dir/AnycubicSlicer-${app_version}-x86_64.AppImage"
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
        printf 'versioned_appimage=%s\n' "$versioned_appimage"
        printf 'latest_appimage=%s\n' "$latest_appimage"
        printf 'zsync=%s\n' "$latest_appimage.zsync"
    } >> "$GITHUB_OUTPUT"
fi

printf '%s\n' "$app_version"