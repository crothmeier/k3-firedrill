#!/usr/bin/env bash

test_b_timestamp() {
    "$FD_PYTHON" -m firedrill.test_b timestamp
}

test_b_emit_token_assertion() {
    printf '%s%s%s%s\n' \
        '{"event":"test-b-full-server-token-format-assertion","verdict":"PASS",' \
        '"pattern":"^K10[a-f0-9]{64}::server:","token_references":' \
        "$FD_TEST_B_TOKEN_REFERENCES_JSON" '}'
}

test_b_record_phase() {
    local phase=$1
    local started_at=$2
    local ended_at=$3
    local phase_status=$4
    local sequence
    sequence=$((FD_EVIDENCE_SEQUENCE + 1))
    evidence_exec test-b-phase test-b \
        "$FD_PYTHON" -m firedrill.test_b record-phase \
        --run-path "$FD_RUN_PATH" \
        --sequence "$sequence" \
        --phase "$phase" \
        --started-at "$started_at" \
        --ended-at "$ended_at" \
        --exit-code "$phase_status"
}

test_b_run_phase() {
    local phase=$1
    local phase_function=$2
    local started_at ended_at phase_status record_status
    started_at=$(test_b_timestamp) || return $?
    phase_status=0
    "$phase_function" || phase_status=$?
    ended_at=$(test_b_timestamp) || return $?
    record_status=0
    test_b_record_phase "$phase" "$started_at" "$ended_at" "$phase_status" || record_status=$?
    if ((record_status != 0)); then
        return "$record_status"
    fi
    return "$phase_status"
}

test_b_guard_node() {
    local node=$1
    local operation=$2
    local guest_id
    guest_id=$(node_id "$node") || return $?
    safety_guard_mutation "$guest_id" "$operation"
}

test_b_phase_setup() {
    local current_file snapshot_name node guest_id exists_status
    local -a snapshot_arguments
    current_file=$(mktemp "${TMPDIR:-/tmp}/firedrill-test-b-current.json.XXXXXX") || return $?
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
    evidence_exec test-b-baseline-prerequisites test-b \
        "$FD_PYTHON" -m firedrill.test_b baseline-check \
        --baseline "$FD_RUN_PATH/baseline/cluster-state.json" \
        --current "$current_file" \
        --state "$FD_RUN_PATH/state.json" \
        --canonical "$FD_CANONICAL_CONFIG" \
        "${snapshot_arguments[@]}" || return $?

    evidence_exec test-b-token-format-assertion test-b \
        test_b_emit_token_assertion || return $?
    for node in server-1 server-2 server-3; do
        test_b_guard_node "$node" test-b-snapshot-and-rotate || return $?
    done
    evidence_exec test-b-setup test-b \
        "$FD_PYTHON" -m firedrill.test_b model-setup \
        --model "$FD_MOCK_MODEL" --lab-id "$FD_LAB_ID" --run-path "$FD_RUN_PATH" \
        --canonical "$FD_CANONICAL_CONFIG" \
        --old-token "$FD_TEST_B_OLD_TOKEN" --new-token "$FD_TEST_B_NEW_TOKEN"
}

test_b_phase_break() {
    test_b_guard_node "$FD_TEST_B_TARGET" test-b-stale-systemd-override || return $?
    evidence_exec test-b-break test-b \
        "$FD_PYTHON" -m firedrill.test_b model-break \
        --model "$FD_MOCK_MODEL" --lab-id "$FD_LAB_ID" --run-path "$FD_RUN_PATH"
}

test_b_phase_recovery() {
    test_b_guard_node "$FD_TEST_B_TARGET" test-b-recover-stale-server || return $?
    evidence_exec test-b-recovery test-b \
        "$FD_PYTHON" -m firedrill.test_b model-recover \
        --model "$FD_MOCK_MODEL" --lab-id "$FD_LAB_ID" --run-path "$FD_RUN_PATH" \
        --canonical "$FD_CANONICAL_CONFIG" --timeout "$FD_TEST_B_HEALTH_TIMEOUT"
}

test_b_phase_gate() {
    local gate_status
    safety_guard_common || return $?
    evidence_exec test-b-gate-observation test-b \
        "$FD_PYTHON" -m firedrill.test_b model-observe \
        --model "$FD_MOCK_MODEL" --lab-id "$FD_LAB_ID" \
        >"$FD_TEST_B_OBSERVATION_FILE" || return $?
    gate_status=0
    evidence_exec test-b-gate-evaluate test-b \
        "$FD_PYTHON" -m firedrill.test_b evaluate \
        --run-path "$FD_RUN_PATH" \
        --baseline "$FD_RUN_PATH/baseline/cluster-state.json" \
        --observation "$FD_TEST_B_OBSERVATION_FILE" \
        --canonical "$FD_CANONICAL_CONFIG" || gate_status=$?
    return "$gate_status"
}

command_test_b() {
    local driver_name gate_status run_dir

    if (($# != 0)); then
        printf 'test-b usage error: no options are accepted in this increment\n' >&2
        return 64
    fi
    driver_name=$(config_get values.driver) || return $?
    if [[ $driver_name != mock ]]; then
        printf 'test-b real test hooks not yet reviewed for driver %s\n' "$driver_name" >&2
        return 69
    fi
    run_dir=$(config_get values.run_dir) || return $?
    if [[ ! -f $run_dir/current.json ]]; then
        printf '%s\n' \
            'test-b is intentionally not implemented without an active baselined mock lab' >&2
        return 69
    fi

    driver_load
    driver_preflight
    state_require_lifecycle baseline
    driver_impl_init

    FD_TEST_B_OLD_TOKEN=$(driver_test_a_read_server_token) || return $?
    printf '%s' "$FD_TEST_B_OLD_TOKEN" \
        | "$FD_PYTHON" -m firedrill.test_b validate-token \
            --label 'Test B current server token' >/dev/null || return $?
    FD_TEST_B_NEW_TOKEN=$(driver_test_a_propose_server_token) || return $?
    printf '%s' "$FD_TEST_B_NEW_TOKEN" \
        | "$FD_PYTHON" -m firedrill.test_b validate-token \
            --label 'Test B proposed server token' >/dev/null || return $?

    FIREDRILL_ACTIVE_TOKENS_JSON=$(
        printf '%s\n%s\n' "$FD_TEST_B_OLD_TOKEN" "$FD_TEST_B_NEW_TOKEN" \
            | "$FD_PYTHON" -m firedrill.test_b registry-json
    ) || return $?
    export FIREDRILL_ACTIVE_TOKENS_JSON
    FD_TEST_B_TOKEN_REFERENCES_JSON=$(
        printf '%s\n%s\n' "$FD_TEST_B_OLD_TOKEN" "$FD_TEST_B_NEW_TOKEN" \
            | "$FD_PYTHON" -m firedrill.test_b references-json
    ) || return $?

    FD_TEST_B_TARGET=$(config_get test_b.target_server) || return $?
    FD_TEST_B_HEALTH_TIMEOUT=$(config_get test_b.recovery_timeout_seconds) || return $?
    FD_TEST_B_OBSERVATION_FILE=$(
        mktemp "${TMPDIR:-/tmp}/firedrill-test-b-gate.json.XXXXXX"
    ) || return $?
    FD_TEMP_FILES+=("$FD_TEST_B_OBSERVATION_FILE")

    test_b_run_phase SETUP test_b_phase_setup || return $?
    test_b_run_phase BREAK test_b_phase_break || return $?
    test_b_run_phase RECOVERY test_b_phase_recovery || return $?
    gate_status=0
    test_b_run_phase GATE test_b_phase_gate || gate_status=$?

    "$FD_PYTHON" -m firedrill.state test-result \
        --run-path "$FD_RUN_PATH" \
        --test test-b \
        --gate "$FD_RUN_PATH/evidence/test-b/gate.json" \
        --phases "$FD_RUN_PATH/evidence/test-b/phases.json" || return $?
    if ((gate_status != 0)); then
        return "$gate_status"
    fi
    printf 'PASS: Test B stale-systemd-token recovery satisfied every evidence gate\n'
}
