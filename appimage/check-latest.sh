#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=appimage/fetch-upstream.sh
source "$script_dir/fetch-upstream.sh"

apt_base_url="${APT_BASE_URL:-https://cdn-universe-slicer.anycubic.com/prod}"

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

# The Packages stanza carries the same Version as the .deb control file, so the
# check does not need to download the package.
app_version=$(strip_epoch "$(package_field Version <<< "$packages")")
if [[ -z "$app_version" ]]; then
    echo "Could not find the anycubicslicernext version in the APT index" >&2
    exit 1
fi
validate_version "$app_version"
release_version="$app_version-$(package_revision "$script_dir")"

printf 'app_version=%s\nrelease_version=%s\n' "$app_version" "$release_version"
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    printf 'app_version=%s\nrelease_version=%s\n' "$app_version" "$release_version" >> "$GITHUB_OUTPUT"
fi
