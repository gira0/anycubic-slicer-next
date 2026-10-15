#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=appimage/fetch-upstream.sh
source "$script_dir/fetch-upstream.sh"

apt_base_url="${APT_BASE_URL:-https://cdn-universe-slicer.anycubic.com/prod}"
work_dir="${RUNNER_TEMP:-/tmp}/anycubic-slicer-version-check"
deb_path="$work_dir/anycubicslicernext.deb"

rm -rf "$work_dir"
mkdir -p "$work_dir"

# An expired or otherwise invalid upstream certificate is Anycubic's problem and
# can last for days. Report it as a warning and skip this run without failing,
# so the daily schedule does not send a failure notice every day.
UPSTREAM_TLS_ANNOTATION=warning
fetch_status=0
packages=$(fetch_upstream "$apt_base_url/dists/noble/main/binary-amd64/Packages") || fetch_status=$?
if (( fetch_status == 60 )); then
    echo "Skipping version check until the upstream certificate is fixed." >&2
    exit 0
fi
(( fetch_status == 0 )) || exit "$fetch_status"

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

printf 'app_version=%s\n' "$app_version"
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    printf 'app_version=%s\n' "$app_version" >> "$GITHUB_OUTPUT"
fi