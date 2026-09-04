#!/usr/bin/env bash
set -Eeuo pipefail

TEST_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export PYTHONPATH="$TEST_ROOT/py${PYTHONPATH:+:$PYTHONPATH}"

case ${1:-} in
run-guest-exec-255|run-shell-death-unbound|run-shell-death-exit)
    exec 7>&2
    FD_PYTHON=python3
    FD_TEMP_FILES=()
    FD_EVIDENCE_SEQUENCE=0
    FD_RUN_PATH=$2
    FD_PVE_CONNECT_TIMEOUT=1
    FD_EVIDENCE_IN_FLIGHT=false
    FD_EVIDENCE_IN_FLIGHT_LABEL=
    FD_EVIDENCE_IN_FLIGHT_NODE=
    FD_EVIDENCE_IN_FLIGHT_STDOUT=
    FD_EVIDENCE_IN_FLIGHT_STDERR=
    FD_EVIDENCE_IN_FLIGHT_STARTED_AT=
    FD_EVIDENCE_IN_FLIGHT_COMMAND=()

    # Invoked indirectly by the EXIT trap.
    # shellcheck disable=SC2329
    child_cleanup() {
        local status=$?
        local shell_death=false
        if [[ $FD_EVIDENCE_IN_FLIGHT == true ]]; then
            shell_death=true
            ((status != 0)) || status=1
            if evidence_cleanup_in_flight "$status"; then
                :
            else
                :
            fi
        fi
        if ((${#FD_TEMP_FILES[@]} > 0)); then
            rm -f -- "${FD_TEMP_FILES[@]}"
        fi
        if [[ $shell_death == true ]]; then
            trap - EXIT
            exit "$status"
        fi
    }

    # Invoked indirectly by the ERR trap.
    # shellcheck disable=SC2329
    on_error() {
        local status=$?
        local line=${BASH_LINENO[0]:-unknown}
        printf 'firedrill: command failed at line %s with exit status %s\n' \
            "$line" "$status" >&2
        exit "$status"
    }
    trap child_cleanup EXIT
    trap on_error ERR

    # shellcheck source=lib/evidence.sh
    source "$TEST_ROOT/lib/evidence.sh"

    if [[ $1 == run-shell-death-unbound ]]; then
        # Invoked indirectly by evidence_exec.
        # shellcheck disable=SC2329
        shell_death_unbound() {
            # shellcheck disable=SC2154
            printf '%s\n' "$FIREDRILL_TEST_UNBOUND_VALUE"
        }
        evidence_exec shell-death-unbound-probe test-node shell_death_unbound
        printf 'unbound-variable shell-death probe unexpectedly returned\n' >&2
        exit 1
    fi

    if [[ $1 == run-shell-death-exit ]]; then
        # Invoked indirectly by evidence_exec.
        # shellcheck disable=SC2329
        shell_death_exit_builtin() {
            printf 'injected exit builtin shell death\n' >&2
            exit 3
        }
        evidence_exec shell-death-exit-probe test-node shell_death_exit_builtin
        printf 'exit-builtin shell-death probe unexpectedly returned\n' >&2
        exit 1
    fi

    # shellcheck source=lib/drivers/pve.sh
    source "$TEST_ROOT/lib/drivers/pve.sh"

    pve_require_mutation_approval() {
        return 0
    }
    pve_node_ip() {
        printf '192.0.2.10\n'
    }
    # Invoked indirectly by driver_impl_guest_exec.
    # shellcheck disable=SC2329
    pve_guest_exec_raw() {
        printf 'injected guest transport failure\n' >&2
        "$BASH" -c 'exit 255'
    }

    driver_impl_guest_exec server-1 7100 3 true
    exit 0
    ;;
esac

TEST_TMP=$(mktemp -d "${TMPDIR:-/tmp}/firedrill-evidence-failure.XXXXXX")
cleanup() {
    rm -rf -- "${TEST_TMP:?}"
}
trap cleanup EXIT

run_path=$TEST_TMP/run
stdout_file=$TEST_TMP/stdout.log
stderr_file=$TEST_TMP/stderr.log
status=0
"$BASH" "$0" run-guest-exec-255 "$run_path" \
    >"$stdout_file" 2>"$stderr_file" || status=$?

if ((status != 255)); then
    printf 'guest-exec failure returned %s instead of 255\n' "$status" >&2
    cat "$stdout_file" "$stderr_file" >&2
    exit 1
fi
failure=false
if ! grep -Fq 'injected guest transport failure' "$stderr_file" \
    || ! grep -Eq '^firedrill: command failed at line [^ ]+ with exit status 255$' \
        "$stderr_file"; then
    printf 'guest-exec exit 255 did not emit both required stderr lines\n' >&2
    cat "$stdout_file" "$stderr_file" >&2
    failure=true
fi
if [[ ! -s $run_path/evidence/commands.jsonl ]]; then
    printf 'guest-exec exit 255 did not write an evidence row\n' >&2
    failure=true
fi
if [[ $failure == true ]]; then
    exit 1
fi
python3 - "$run_path/evidence/commands.jsonl" <<'PY'
import json
import sys
from pathlib import Path

records = [
    json.loads(line)
    for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
]
assert len(records) == 1
record = records[0]
assert record["label"] == "pve-guest-exec"
assert record["node"] == "server-1"
assert record["exit_code"] == 255
assert record["stderr"] == "injected guest transport failure\n"
PY

printf 'PASS: PVE guest-exec exit 255 emitted stderr failure and an evidence row\n'

assert_shell_death() {
    local mode=$1 expected_status=$2 label=$3 expected_stderr=$4 marker=$5
    local probe_run=$TEST_TMP/$mode-run
    local probe_stdout=$TEST_TMP/$mode.stdout probe_stderr=$TEST_TMP/$mode.stderr
    local status=0
    "$BASH" "$0" "$mode" "$probe_run" \
        >"$probe_stdout" 2>"$probe_stderr" || status=$?
    if ((status != expected_status)); then
        printf '%s returned %s instead of %s\n' \
            "$mode" "$status" "$expected_status" >&2
        cat "$probe_stdout" "$probe_stderr" >&2
        return 1
    fi
    if ! grep -Fq \
        "firedrill: FATAL: shell exited during evidence label=$label node=test-node status=$expected_status" \
        "$probe_stderr" || ! grep -Fq "$expected_stderr" "$probe_stderr"; then
        printf '%s did not emit the FATAL line and replayed stderr\n' "$mode" >&2
        cat "$probe_stdout" "$probe_stderr" >&2
        return 1
    fi
    if [[ ! -s $probe_run/evidence/commands.jsonl ]]; then
        printf '%s did not write shell-death evidence\n' "$mode" >&2
        return 1
    fi
    python3 - "$probe_run/evidence/commands.jsonl" \
        "$label-shell-death" "$expected_status" "$expected_stderr" <<'PY'
import json
import sys
from pathlib import Path

records = [
    json.loads(line)
    for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
]
assert len(records) == 1
record = records[0]
assert record["label"] == sys.argv[2]
assert record["node"] == "test-node"
assert record["exit_code"] == int(sys.argv[3])
assert sys.argv[4] in record["stderr"]
PY
    printf '%s\n' "$marker"
}

assert_shell_death \
    run-shell-death-unbound 1 shell-death-unbound-probe 'unbound variable' \
    'PASS: shell death inside evidence_exec emitted FATAL line, replayed stderr, and wrote an evidence row (unbound variable)'
assert_shell_death \
    run-shell-death-exit 3 shell-death-exit-probe \
    'injected exit builtin shell death' \
    'PASS: shell death inside evidence_exec emitted FATAL line, replayed stderr, and wrote an evidence row (exit builtin)'
