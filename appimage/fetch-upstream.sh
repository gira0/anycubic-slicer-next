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

# The version becomes a release tag, a file name and a workflow output, so
# reject anything that is not a plain Debian-style version string.
validate_version() {
    if [[ ! "$1" =~ ^[0-9][0-9A-Za-z.+~-]*$ ]]; then
        echo "Refusing unexpected upstream version string: $1" >&2
        exit 1
    fi
}
