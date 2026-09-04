#!/usr/bin/env bash
set -Eeuo pipefail

TEST_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TEST_TMP=$(mktemp -d "${TMPDIR:-/tmp}/firedrill-shell-coverage.XXXXXX")
PROBE_DIR=
cleanup() {
    if [[ -n $PROBE_DIR && -d $PROBE_DIR ]]; then
        rm -rf -- "${PROBE_DIR:?}"
    fi
    rm -rf -- "${TEST_TMP:?}"
}
trap cleanup EXIT

is_shell_shebang() {
    local line=$1 interpreter='' remainder=''

    line=${line%$'\r'}
    [[ $line == '#!'* ]] || return 1
    read -r interpreter remainder <<<"${line:2}"

    if [[ ${interpreter##*/} == env ]]; then
        read -r interpreter remainder <<<"$remainder"
        if [[ $interpreter == -S ]]; then
            read -r interpreter remainder <<<"$remainder"
        fi
    fi

    case ${interpreter##*/} in
        sh|bash|dash|ksh|zsh) return 0 ;;
        *) return 1 ;;
    esac
}

discover_shell_files() {
    local relative first_line

    while IFS= read -r -d '' relative; do
        [[ -f $TEST_ROOT/$relative && ! -L $TEST_ROOT/$relative ]] || continue
        if [[ $relative == *.sh ]]; then
            printf './%s\n' "$relative"
            continue
        fi

        first_line=
        IFS= read -r first_line <"$TEST_ROOT/$relative" || true
        if is_shell_shebang "$first_line"; then
            printf './%s\n' "$relative"
        fi
    done < <(git -C "$TEST_ROOT" ls-files -z --cached --others --exclude-standard)
}

assert_sets_match() {
    local expected=$1 declared=$2

    if ! cmp -s "$expected" "$declared"; then
        printf 'ShellCheck file set differs from independent shell-file discovery: expected=%s declared=%s\n' \
            "$expected" "$declared" >&2
        return 1
    fi
}

DISCOVERY_STARTED=$SECONDS
discover_shell_files | LC_ALL=C sort >"$TEST_TMP/expected"
DISCOVERY_WALL_SECONDS=$((SECONDS - DISCOVERY_STARTED))
printf 'discovery wall seconds: %s\n' "$DISCOVERY_WALL_SECONDS"
if ((DISCOVERY_WALL_SECONDS >= 5)); then
    printf 'Shell-file discovery exceeded the under-5-second gate: %s seconds\n' \
        "$DISCOVERY_WALL_SECONDS" >&2
    exit 1
fi

IGNORED_PROBE=runs/f-ta-7-hypothetical-ignored.sh
CONTROL_PROBE=f-ta-7-hypothetical-control.sh
if IGNORE_MATCH=$(git -C "$TEST_ROOT" check-ignore -v -- "$IGNORED_PROBE"); then
    :
else
    status=$?
    printf 'Expected ignored hypothetical path was not ignored: path=%s exit=%s\n' \
        "$IGNORED_PROBE" "$status" >&2
    exit 1
fi
IFS=$'\t' read -r IGNORE_RULE IGNORE_PATH <<<"$IGNORE_MATCH"
if [[ $IGNORE_PATH != "$IGNORED_PROBE" || ${IGNORE_RULE##*:} != runs/ ]]; then
    printf 'Hypothetical ignored path matched the wrong rule: path=%s match=%s\n' \
        "$IGNORED_PROBE" "$IGNORE_MATCH" >&2
    exit 1
fi
if CONTROL_MATCH=$(git -C "$TEST_ROOT" check-ignore -v -- "$CONTROL_PROBE" 2>&1); then
    printf 'Hypothetical control path unexpectedly matched an ignore rule: path=%s match=%s\n' \
        "$CONTROL_PROBE" "$CONTROL_MATCH" >&2
    exit 1
else
    status=$?
fi
if [[ $status -ne 1 ]]; then
    printf 'Hypothetical control path returned unexpected check-ignore status: path=%s exit=%s output=%s\n' \
        "$CONTROL_PROBE" "$status" "$CONTROL_MATCH" >&2
    exit 1
fi
printf 'ran-marker: F-TA-7-negative-probe\n'

make --no-print-directory -s -C "$TEST_ROOT" print-shell-files \
    | LC_ALL=C sort >"$TEST_TMP/declared"

assert_sets_match "$TEST_TMP/expected" "$TEST_TMP/declared"

PROBE_DIR=$(mktemp -d "$TEST_ROOT/tests/lint-coverage-probe.XXXXXX")
PROBE_PATH=$PROBE_DIR/rotate-token
PROBE_RELATIVE=${PROBE_PATH#"$TEST_ROOT"/}
PROBE_PRINTED=./$PROBE_RELATIVE
printf '%s\n' '#!/usr/bin/env bash' 'exit 0' >"$PROBE_PATH"

discover_shell_files | LC_ALL=C sort >"$TEST_TMP/expected-with-probe"
if assert_sets_match "$TEST_TMP/expected-with-probe" "$TEST_TMP/declared" >/dev/null 2>&1; then
    printf 'Shell lint coverage guard did not fail for an undeclared extensionless script.\n' >&2
    exit 1
fi

make --no-print-directory -s -C "$TEST_ROOT" print-shell-files \
    | LC_ALL=C sort >"$TEST_TMP/declared-with-probe"
if ! grep -Fqx -- "$PROBE_PRINTED" "$TEST_TMP/declared-with-probe"; then
    printf 'Makefile shell discovery missed extensionless probe: %s\n' "$PROBE_PRINTED" >&2
    exit 1
fi
assert_sets_match "$TEST_TMP/expected-with-probe" "$TEST_TMP/declared-with-probe"

rm -- "$PROBE_PATH"

discover_shell_files | LC_ALL=C sort >"$TEST_TMP/expected-after-probe"
assert_sets_match "$TEST_TMP/expected-after-probe" "$TEST_TMP/declared"
