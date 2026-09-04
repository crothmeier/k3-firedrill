#!/usr/bin/env bash

test_a_timestamp() {
    "$FD_PYTHON" -m firedrill.test_a timestamp
}

test_a_emit_token_assertion() {
    printf '%s%s%s\n' \
        '{"event":"test-a-full-server-token-format-assertion","verdict":"PASS",' \
        '"pattern":"^K10[a-f0-9]{64}::server:","token_references":' \
        "$FD_TEST_A_TOKEN_REFERENCES_JSON}"
}

test_a_record_phase() {
    local phase=$1
    local started_at=$2
    local ended_at=$3
    local phase_status=$4
    local sequence
    sequence=$((FD_EVIDENCE_SEQUENCE + 1))
    evidence_exec test-a-phase test-a \
        "$FD_PYTHON" -m firedrill.test_a record-phase \
        --run-path "$FD_RUN_PATH" \
        --sequence "$sequence" \
        --phase "$phase" \
        --started-at "$started_at" \
        --ended-at "$ended_at" \
        --exit-code "$phase_status"
}

test_a_run_phase() {
    local phase=$1
    local phase_function=$2
    local started_at ended_at phase_status record_status
    started_at=$(test_a_timestamp) || return $?
    phase_status=0
    "$phase_function" || phase_status=$?
    ended_at=$(test_a_timestamp) || return $?
    record_status=0
    test_a_record_phase "$phase" "$started_at" "$ended_at" "$phase_status" || record_status=$?
    if ((record_status != 0)); then
        return "$record_status"
    fi
    return "$phase_status"
}

test_a_phase_setup() {
    local current_file snapshot_name node guest_id exists_status
    local -a snapshot_arguments
    current_file=$(mktemp "${TMPDIR:-/tmp}/firedrill-test-a-current.json.XXXXXX") || return $?
    FD_TEMP_FILES+=("$current_file")

    cluster_capture_state >"$current_file" || return $?
    snapshot_name=$(config_get values.snapshot_name) || return $?
    snapshot_arguments=()
    for node in server-1 server-2 server-3 agent-1 agent-2; do
        guest_id=$(node_id "$node") || return $?
        exists_status=0
        driver_snapshot_exists "$guest_id" "$snapshot_name" || exists_status=$?
        if ((exists_status == 0)); then
            snapshot_arguments+=(--snapshot-status "$node=true")
        elif ((exists_status == 1)); then
            snapshot_arguments+=(--snapshot-status "$node=false")
        else
            return "$exists_status"
        fi
    done
    evidence_exec test-a-baseline-prerequisites test-a \
        "$FD_PYTHON" -m firedrill.test_a baseline-check \
        --baseline "$FD_RUN_PATH/baseline/cluster-state.json" \
        --current "$current_file" \
        --state "$FD_RUN_PATH/state.json" \
        --canonical "$FD_CANONICAL_CONFIG" \
        --manifest "$FD_RUN_PATH/manifest.json" \
        "${snapshot_arguments[@]}" || return $?

    evidence_exec test-a-token-format-assertion test-a \
        test_a_emit_token_assertion || return $?
    for node in server-1 server-2 server-3; do
        driver_test_a_snapshot_pair "$node" "$FD_TEST_A_OLD_TOKEN" || return $?
    done
}

test_a_phase_break() {
    local server_one server_two server_three node
    driver_test_a_rotate_server_token \
        "$FD_TEST_A_NEW_TOKEN" "$FD_TEST_A_RESTART_ORDER" || return $?
    IFS=, read -r server_one server_two server_three <<<"$FD_TEST_A_RESTART_ORDER"
    for node in "$server_one" "$server_two" "$server_three"; do
        driver_test_a_restart_node "$node" "$FD_TEST_A_HEALTH_TIMEOUT" || return $?
    done
    for node in agent-1 agent-2; do
        driver_test_a_restart_node "$node" "$FD_TEST_A_HEALTH_TIMEOUT" || return $?
    done
}

test_a_phase_gate() {
    local gate_status
    driver_test_a_observe_gate >"$FD_TEST_A_OBSERVATION_FILE" || return $?
    gate_status=0
    evidence_exec test-a-gate-evaluate test-a \
        "$FD_PYTHON" -m firedrill.test_a evaluate \
        --run-path "$FD_RUN_PATH" \
        --baseline "$FD_RUN_PATH/baseline/cluster-state.json" \
        --observation "$FD_TEST_A_OBSERVATION_FILE" \
        --expected-order "$FD_TEST_A_RESTART_ORDER" || gate_status=$?
    return "$gate_status"
}

command_test_a() {
    local gate_status run_dir

    # An active run's prior attempt is archived before driver loading can
    # contact a guest. With no active run, retain the preflight-first guard.
    run_dir=$(config_get values.run_dir) || return $?
    if [[ -f $run_dir/current.json ]]; then
        state_require_lifecycle baseline
        if [[ -d $FD_RUN_PATH/evidence/test-a ]]; then
            evidence_exec test-a-attempt-archived test-a \
                "$FD_PYTHON" -m firedrill.state archive-test-a-attempt \
                --run-path "$FD_RUN_PATH" || return $?
        fi
    fi

    driver_load
    driver_preflight
    state_require_lifecycle baseline
    driver_impl_init

    FD_TEST_A_OLD_TOKEN=$(driver_test_a_read_server_token) || return $?
    printf '%s' "$FD_TEST_A_OLD_TOKEN" \
        | "$FD_PYTHON" -m firedrill.test_a validate-token \
            --label 'current server token' || return $?
    FD_TEST_A_NEW_TOKEN=$(driver_test_a_propose_server_token) || return $?
    printf '%s' "$FD_TEST_A_NEW_TOKEN" \
        | "$FD_PYTHON" -m firedrill.test_a validate-token \
            --label 'proposed server token' || return $?

    # Both raw candidates and both normalized secrets enter the process-only
    # registry before the first Test A evidence record is created.
    FIREDRILL_ACTIVE_TOKENS_JSON=$(
        printf '%s\n%s\n' "$FD_TEST_A_OLD_TOKEN" "$FD_TEST_A_NEW_TOKEN" \
            | "$FD_PYTHON" -m firedrill.test_a registry-json
    ) || return $?
    export FIREDRILL_ACTIVE_TOKENS_JSON
    FD_TEST_A_TOKEN_REFERENCES_JSON=$(
        printf '%s\n%s\n' "$FD_TEST_A_OLD_TOKEN" "$FD_TEST_A_NEW_TOKEN" \
            | "$FD_PYTHON" -m firedrill.test_a references-json
    ) || return $?

    FD_TEST_A_RESTART_ORDER=$(config_get values.server_restart_order) || return $?
    FD_TEST_A_RESTART_ORDER=${FD_TEST_A_RESTART_ORDER//[[:space:]]/}
    FD_TEST_A_HEALTH_TIMEOUT=$(config_get values.node_ready_timeout_seconds) || return $?
    FD_TEST_A_OBSERVATION_FILE=$(
        mktemp "${TMPDIR:-/tmp}/firedrill-test-a-gate.json.XXXXXX"
    ) || return $?
    FD_TEMP_FILES+=("$FD_TEST_A_OBSERVATION_FILE")

    test_a_run_phase SETUP test_a_phase_setup || return $?
    test_a_run_phase BREAK test_a_phase_break || return $?
    gate_status=0
    test_a_run_phase GATE test_a_phase_gate || gate_status=$?

    "$FD_PYTHON" -m firedrill.state test-result \
        --run-path "$FD_RUN_PATH" \
        --gate "$FD_RUN_PATH/evidence/test-a/gate.json" \
        --phases "$FD_RUN_PATH/evidence/test-a/phases.json" || return $?
    if ((gate_status != 0)); then
        return "$gate_status"
    fi
    printf 'PASS: Test A clean server-token rotation satisfied every evidence gate\n'
}
