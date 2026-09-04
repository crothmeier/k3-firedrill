#!/usr/bin/env bash

state_evidence_sequence() {
    local commands_log
    commands_log=$1/evidence/commands.jsonl
    if [[ ! -f $commands_log ]]; then
        printf '0\n'
        return
    fi
    wc -l <"$commands_log" | tr -d ' '
}

state_begin_or_resume() {
    local result
    result=$("$FD_PYTHON" -m firedrill.state begin --canonical "$FD_CANONICAL_CONFIG")
    FD_RUN_PATH=$("$FD_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["run_path"])' <<<"$result")
    # Safety, driver, and command modules consume the active lab identifier.
    # shellcheck disable=SC2034
    FD_LAB_ID=$("$FD_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["lab_id"])' <<<"$result")
    # command_provision in lib/commands/provision.sh consumes this resume flag.
    # shellcheck disable=SC2034
    FD_RUN_CREATED=$("$FD_PYTHON" -c 'import json,sys; print(str(json.load(sys.stdin)["created"]).lower())' <<<"$result")
    # evidence_exec in lib/evidence.sh consumes this cross-file sequence counter.
    # shellcheck disable=SC2034
    FD_EVIDENCE_SEQUENCE=$(state_evidence_sequence "$FD_RUN_PATH")
}

state_load_current() {
    local run_dir current
    run_dir=$(config_get values.run_dir)
    current=$("$FD_PYTHON" -m firedrill.state current --run-dir "$run_dir")
    FD_RUN_PATH=$("$FD_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["run_path"])' <<<"$current")
    # Safety, driver, and command modules consume the active lab identifier.
    # shellcheck disable=SC2034
    FD_LAB_ID=$("$FD_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["lab_id"])' <<<"$current")
    FD_LIFECYCLE=$("$FD_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["lifecycle"])' <<<"$current")
    # evidence_exec in lib/evidence.sh consumes this cross-file sequence counter.
    # shellcheck disable=SC2034
    FD_EVIDENCE_SEQUENCE=$(state_evidence_sequence "$FD_RUN_PATH")
}

state_require_lifecycle() {
    local expected=$1
    state_load_current
    if [[ $FD_LIFECYCLE != "$expected" ]]; then
        printf 'state error: command requires lifecycle %s, observed %s\n' \
            "$expected" "$FD_LIFECYCLE" >&2
        return 66
    fi
}

state_set_lifecycle() {
    "$FD_PYTHON" -m firedrill.state lifecycle --run-path "$FD_RUN_PATH" --value "$1"
    FD_LIFECYCLE=$1
}
