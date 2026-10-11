#!/usr/bin/env bash
set -euo pipefail

apt_base_url="${APT_BASE_URL:-https://cdn-universe-slicer.anycubic.com/prod}"
packages_url="$apt_base_url/dists/noble/main/binary-amd64/Packages"
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
work_dir="${RUNNER_TEMP:-/tmp}/anycubic-slicer-build"
deb_path="$work_dir/anycubicslicernext.deb"
app_dir="$work_dir/AnycubicSlicer.AppDir"
appimage_tool="$work_dir/appimagetool"

rm -rf "$work_dir"
mkdir -p "$work_dir" "$app_dir"

deb_filename=$(curl -fsSL "$packages_url" | awk '
    /^Package: anycubicslicernext$/ { in_package=1; next }
    in_package && /^Filename:/ { print $2; exit }
    in_package && /^$/ { in_package=0 }
')
if [[ -z "$deb_filename" ]]; then
    echo "Could not find anycubicslicernext in the APT index" >&2
    exit 1
fi

curl -fsSL -o "$deb_path" "$apt_base_url/$deb_filename"
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

# Cloud camera helper (tools/cloud-camera). The web UI patch itself is applied on the
# user's machine at launch; here we only check that it still applies to this version.
mkdir -p "$app_dir/share/camview"
cp -a "$script_dir/../tools/cloud-camera/src/camview" "$app_dir/share/camview/"
# Do not let the check below write bytecode into the bundle that gets packaged.
if ! PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$app_dir/share/camview" python3 -s -m camview prepare \
        --lib "$app_dir/lib/libWorkbench.so" "$work_dir/camview-check"; then
    echo "::warning::cloud camera patch no longer applies to $app_version; the AppImage falls back to stock behaviour"
fi
rm -rf "$work_dir/camview-check"
find "$app_dir/share/camview" -name __pycache__ -prune -exec rm -rf {} +

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

update_information='X-AppImage-UpdateInformation=gh-releases-zsync|gira0|anycubic-slicer-next|latest|AnycubicSlicer-x86_64.AppImage.zsync'
if grep -q '^X-AppImage-UpdateInformation=' "$desktop_file"; then
    sed -i "s|^X-AppImage-UpdateInformation=.*|$update_information|" "$desktop_file"
else
    printf '\n%s\n' "$update_information" >> "$desktop_file"
fi

if [[ ! -x "$appimage_tool" ]]; then
    curl -fsSL -o "$appimage_tool" \
        https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$appimage_tool"
fi

versioned_appimage="$work_dir/AnycubicSlicer-${app_version}-x86_64.AppImage"
latest_appimage="$work_dir/AnycubicSlicer-x86_64.AppImage"
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 "$appimage_tool" "$app_dir" "$versioned_appimage"
cp "$versioned_appimage" "$latest_appimage"
zsyncmake "$latest_appimage" -o "$latest_appimage.zsync"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    {
        printf 'app_version=%s\n' "$app_version"
        printf 'versioned_appimage=%s\n' "$versioned_appimage"
        printf 'latest_appimage=%s\n' "$latest_appimage"
        printf 'zsync=%s\n' "$latest_appimage.zsync"
    } >> "$GITHUB_OUTPUT"
fi

printf '%s\n' "$app_version"