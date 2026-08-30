#!/usr/bin/env bash
set -euo pipefail

apt_base_url="${APT_BASE_URL:-https://cdn-universe-slicer.anycubic.com/prod}"
work_dir="${RUNNER_TEMP:-/tmp}/anycubic-slicer-version-check"
deb_path="$work_dir/anycubicslicernext.deb"

rm -rf "$work_dir"
mkdir -p "$work_dir"

deb_filename=$(curl -fsSL "$apt_base_url/dists/noble/main/binary-amd64/Packages" | awk '
    /^Package: anycubicslicernext$/ { in_package=1; next }
    in_package && /^Filename:/ { print $2; exit }
    in_package && /^$/ { in_package=0 }
')
if [[ -z "$deb_filename" ]]; then
    echo "Could not find anycubicslicernext in the APT index" >&2
    exit 1
fi

curl -fsSL -o "$deb_path" "$apt_base_url/$deb_filename"
mkdir -p "$work_dir/extracted"
cd "$work_dir/extracted"
ar x "$deb_path"
tar -xf data.tar.*

app_version=$(strings usr/bin/AnycubicSlicerNext | grep -oE 'AnycubicSlicerNext/[0-9]+(\.[0-9]+)+' | head -n1 | cut -d/ -f2)
if [[ -z "$app_version" ]]; then
    echo "Could not determine the application version" >&2
    exit 1
fi

printf 'app_version=%s\n' "$app_version"
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    printf 'app_version=%s\n' "$app_version" >> "$GITHUB_OUTPUT"
fi