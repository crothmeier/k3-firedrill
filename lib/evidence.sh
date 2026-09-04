#!/usr/bin/env bash

evidence_timestamp() {
    date -u '+%Y-%m-%dT%H:%M:%SZ'
}

evidence_cleanup_in_flight() {
    local exit_code=$1 ended_at writer_status=0
    [[ $FD_EVIDENCE_IN_FLIGHT == true ]] || return 0

    printf 'firedrill: FATAL: shell exited during evidence label=%s node=%s status=%s\n' \
        "$FD_EVIDENCE_IN_FLIGHT_LABEL" "$FD_EVIDENCE_IN_FLIGHT_NODE" \
        "$exit_code" >&7
    if [[ -s $FD_EVIDENCE_IN_FLIGHT_STDERR ]]; then
        cat "$FD_EVIDENCE_IN_FLIGHT_STDERR" >&7
    fi
    ended_at=$(evidence_timestamp)
    FD_EVIDENCE_SEQUENCE=$((FD_EVIDENCE_SEQUENCE + 1))
    if "$FD_PYTHON" -m firedrill.evidence \
        --run-path "$FD_RUN_PATH" \
        --sequence "$FD_EVIDENCE_SEQUENCE" \
        --label "${FD_EVIDENCE_IN_FLIGHT_LABEL}-shell-death" \
        --node "$FD_EVIDENCE_IN_FLIGHT_NODE" \
        --started-at "$FD_EVIDENCE_IN_FLIGHT_STARTED_AT" \
        --ended-at "$ended_at" \
        --exit-code "$exit_code" \
        --stdout "$FD_EVIDENCE_IN_FLIGHT_STDOUT" \
        --stderr "$FD_EVIDENCE_IN_FLIGHT_STDERR" \
        -- "${FD_EVIDENCE_IN_FLIGHT_COMMAND[@]}"; then
        writer_status=0
    else
        writer_status=$?
        printf 'firedrill: FATAL: failed to write shell-death evidence status=%s\n' \
            "$writer_status" >&7
    fi
    rm -f -- \
        "$FD_EVIDENCE_IN_FLIGHT_STDOUT" "$FD_EVIDENCE_IN_FLIGHT_STDERR"
    FD_EVIDENCE_IN_FLIGHT=false
    FD_EVIDENCE_IN_FLIGHT_LABEL=
    FD_EVIDENCE_IN_FLIGHT_NODE=
    FD_EVIDENCE_IN_FLIGHT_STDOUT=
    FD_EVIDENCE_IN_FLIGHT_STDERR=
    FD_EVIDENCE_IN_FLIGHT_STARTED_AT=
    FD_EVIDENCE_IN_FLIGHT_COMMAND=()
    return "$writer_status"
}

evidence_exec() {
    local label=$1
    local node=$2
    shift 2
    local stdout_file stderr_file started_at ended_at exit_code
    stdout_file=$(mktemp "${TMPDIR:-/tmp}/firedrill-stdout.XXXXXX")
    stderr_file=$(mktemp "${TMPDIR:-/tmp}/firedrill-stderr.XXXXXX")
    started_at=$(evidence_timestamp)

    # A command failure is evidence. Running it as the if-condition suppresses
    # both errexit and ERR for the complete nested call while preserving the
    # exact status for the writer below. `set +e` alone does not suppress ERR.
    FD_EVIDENCE_IN_FLIGHT=true
    FD_EVIDENCE_IN_FLIGHT_LABEL=$label
    FD_EVIDENCE_IN_FLIGHT_NODE=$node
    FD_EVIDENCE_IN_FLIGHT_STDOUT=$stdout_file
    FD_EVIDENCE_IN_FLIGHT_STDERR=$stderr_file
    FD_EVIDENCE_IN_FLIGHT_STARTED_AT=$started_at
    FD_EVIDENCE_IN_FLIGHT_COMMAND=("$@")
    if "$@" >"$stdout_file" 2>"$stderr_file"; then
        exit_code=0
    else
        exit_code=$?
    fi
    FD_EVIDENCE_IN_FLIGHT=false
    FD_EVIDENCE_IN_FLIGHT_LABEL=
    FD_EVIDENCE_IN_FLIGHT_NODE=
    FD_EVIDENCE_IN_FLIGHT_STDOUT=
    FD_EVIDENCE_IN_FLIGHT_STDERR=
    FD_EVIDENCE_IN_FLIGHT_STARTED_AT=
    FD_EVIDENCE_IN_FLIGHT_COMMAND=()
    ended_at=$(evidence_timestamp)
    FD_EVIDENCE_SEQUENCE=$((FD_EVIDENCE_SEQUENCE + 1))
    "$FD_PYTHON" -m firedrill.evidence \
        --run-path "$FD_RUN_PATH" \
        --sequence "$FD_EVIDENCE_SEQUENCE" \
        --label "$label" \
        --node "$node" \
        --started-at "$started_at" \
        --ended-at "$ended_at" \
        --exit-code "$exit_code" \
        --stdout "$stdout_file" \
        --stderr "$stderr_file" \
        -- "$@"
    FD_TEMP_FILES+=("$stdout_file" "$stderr_file")
    local evidence_prefix redacted_stdout redacted_stderr
    printf -v evidence_prefix '%06d' "$FD_EVIDENCE_SEQUENCE"
    redacted_stdout=$FD_RUN_PATH/evidence/commands/$evidence_prefix.stdout.log
    redacted_stderr=$FD_RUN_PATH/evidence/commands/$evidence_prefix.stderr.log
    cat "$redacted_stdout"
    if [[ -s $redacted_stderr ]]; then
        cat "$redacted_stderr" >&2
    fi
    return "$exit_code"
}
