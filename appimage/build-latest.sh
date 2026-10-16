#!/usr/bin/env bash
set -euo pipefail

apt_base_url="${APT_BASE_URL:-https://cdn-universe-slicer.anycubic.com/prod}"
packages_url="$apt_base_url/dists/noble/main/binary-amd64/Packages"
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=appimage/fetch-upstream.sh
source "$script_dir/fetch-upstream.sh"
# "original" is the unmodified AppImage. "camview" additionally ships the
# tools/cloud-camera helper and is published as its own release stream.
variant="${VARIANT:-original}"
case "$variant" in
    original) name_suffix='' ;;
    camview) name_suffix='-camview' ;;
    *)
        echo "Unknown VARIANT '$variant'; expected 'original' or 'camview'" >&2
        exit 1
        ;;
esac
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
app_version=$(dpkg-deb -f "$deb_path" Version)
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

mkdir -p "$work_dir/extracted"
cd "$work_dir/extracted"
ar x "$deb_path"
tar -xf data.tar.*
cp -a usr/. "$app_dir/"

if [[ "$variant" == camview ]]; then
    # AppRun.camview forwards everything except the "camview" subcommand to the
    # unchanged AppRun, which stays next to it under another name.
    cp "$script_dir/AppRun" "$app_dir/AppRun.slicer"
    cp "$script_dir/AppRun.camview" "$app_dir/AppRun"
    chmod +x "$app_dir/AppRun.slicer"
    # The tool is pure standard library Python; the host provides python3.
    mkdir -p "$app_dir/camview"
    cp -a "$script_dir/../tools/cloud-camera/src/camview" "$app_dir/camview/camview"
    find "$app_dir/camview" -name __pycache__ -type d -prune -exec rm -rf {} +
else
    cp "$script_dir/AppRun" "$app_dir/AppRun"
fi
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
if [[ "$variant" == camview ]]; then
    # An exact tag would pin the AppImage to the release it came from. The
    # camview releases are published as pre-releases, and "latest-pre" follows
    # only those, so this build never updates to the original stream (whose
    # releases are regular ones) and the original never sees camview.
    update_tag=latest-pre
else
    update_tag=latest
fi
update_information="gh-releases-zsync|gira0|anycubic-slicer-next|$update_tag|AnycubicSlicer${name_suffix}-x86_64.AppImage.zsync"

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

versioned_appimage="$work_dir/AnycubicSlicer-${app_version}${name_suffix}-x86_64.AppImage"
latest_appimage="$work_dir/AnycubicSlicer${name_suffix}-x86_64.AppImage"
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