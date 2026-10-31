# Helpers for Anycubic's APT repository, sourced by check-latest.sh and
# build-latest.sh. TLS verification stays on. When the server certificate fails
# verification, report what the server presented so the failure is clearly an
# upstream problem rather than a broken build. Set UPSTREAM_TLS_ANNOTATION to
# "warning" to report it as a warning instead of an error.

fetch_upstream() {
    local url="${*: -1}"
    local status=0
    curl -fsSL "$@" || status=$?
    if (( status == 60 )); then
        report_certificate_problem "$url"
    fi
    return "$status"
}

report_certificate_problem() {
    local url="$1"
    local host="${url#*://}"
    host="${host%%/*}"

    local details
    details=$(openssl s_client -connect "$host:443" -servername "$host" </dev/null 2>/dev/null \
        | openssl x509 -noout -subject -issuer -enddate 2>/dev/null) || true

    local level="${UPSTREAM_TLS_ANNOTATION:-error}"
    local message="$host presented a certificate that failed verification (curl exit 60). This is a problem on Anycubic's server, not in this repository; builds resume once they fix it."
    if [[ -n "$details" ]]; then
        message="$message Certificate: $(tr '\n' ';' <<< "$details")"
    fi

    if [[ -n "${GITHUB_ACTIONS:-}" ]]; then
        printf '::%s title=Upstream certificate problem::%s\n' "$level" "$message" >&2
    else
        printf '%s\n' "$message" >&2
    fi
}

# Print one field of the anycubicslicernext stanza from a Packages index on stdin.
package_field() {
    awk -v field="$1:" '
        /^Package: anycubicslicernext$/ { in_package=1; next }
        in_package && $1 == field { print $2; exit }
        in_package && /^$/ { in_package=0 }
    '
}

# Print a Debian version without its epoch ("1:2.0.0.6" -> "2.0.0.6"). Anycubic
# added epoch 1 when it renumbered 2.0.06 as 2.0.0.6; the epoch only orders
# packages for apt, and ":" is not allowed in a Git tag.
strip_epoch() {
    if [[ "$1" =~ ^[0-9]+:(.*)$ ]]; then
        printf '%s\n' "${BASH_REMATCH[1]}"
    else
        printf '%s\n' "$1"
    fi
}

# The version becomes a release tag, a file name and a workflow output, so
# reject anything that is not a plain version string or not a valid Git tag
# (Git refuses "~", "..", and a trailing "." or ".lock").
validate_version() {
    if [[ ! "$1" =~ ^[0-9][0-9A-Za-z.+-]*$ || "$1" == *..* || "$1" == *. || "$1" == *.lock ]]; then
        echo "Refusing unexpected upstream version string: $1" >&2
        exit 1
    fi
}

# Print the packaging revision from appimage/PACKAGE_REVISION. Release tags are
# "<version>-<revision>", so bumping it ships packaging changes for an upstream
# version that is already released.
package_revision() {
    local revision
    # Only the trailing newline goes (command substitution drops it), so a
    # malformed value such as "1 2" fails the check instead of becoming 12.
    revision=$(< "$1/PACKAGE_REVISION")
    if [[ ! "$revision" =~ ^[1-9][0-9]*$ ]]; then
        echo "PACKAGE_REVISION must be a positive integer, got: '$revision'" >&2
        exit 1
    fi
    printf '%s\n' "$revision"
}
