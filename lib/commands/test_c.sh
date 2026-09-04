#!/usr/bin/env bash

test_c_timestamp() {
    "$FD_PYTHON" -m firedrill.test_c timestamp
}

test_c_record_phase() {
    local phase=$1
    local started_at=$2
    local ended_at=$3
    local phase_status=$4
    local sequence
    sequence=$((FD_EVIDENCE_SEQUENCE + 1))
    evidence_exec test-c-phase test-c \
        "$FD_PYTHON" -m firedrill.test_c record-phase \
        --run-path "$FD_RUN_PATH" \
        --sequence "$sequence" \
        --phase "$phase" \
        --started-at "$started_at" \
        --ended-at "$ended_at" \
        --exit-code "$phase_status"
}

test_c_run_phase() {
    local phase=$1
    local phase_function=$2
    local started_at ended_at phase_status record_status
    started_at=$(test_c_timestamp) || return $?
    phase_status=0
    "$phase_function" || phase_status=$?
    ended_at=$(test_c_timestamp) || return $?
    record_status=0
    test_c_record_phase "$phase" "$started_at" "$ended_at" "$phase_status" || record_status=$?
    if ((record_status != 0)); then
        return "$record_status"
    fi
    return "$phase_status"
}

test_c_phase_setup() {
    local current_file snapshot_name node guest_id exists_status
    local -a snapshot_arguments
    current_file=$(mktemp "${TMPDIR:-/tmp}/firedrill-test-c-current.json.XXXXXX") || return $?
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
    evidence_exec test-c-baseline-prerequisites test-c \
        "$FD_PYTHON" -m firedrill.test_c baseline-check \
        --baseline "$FD_RUN_PATH/baseline/cluster-state.json" \
        --current "$current_file" \
        --state "$FD_RUN_PATH/state.json" \
        --canonical "$FD_CANONICAL_CONFIG" \
        "${snapshot_arguments[@]}" || return $?

    driver_test_c_setup \
        "$FD_TEST_C_OLD_TOKEN" "$FD_TEST_C_NEW_TOKEN" "$FD_TEST_C_RECOVERY_FORM"
}

test_c_phase_break() {
    driver_test_c_break "$FD_TEST_C_BRANCH"
}

test_c_phase_triage() {
    driver_test_c_triage "$FD_TEST_C_OLD_TOKEN" "$FD_TEST_C_NEW_TOKEN"
}

test_c_phase_recovery() {
    driver_test_c_recover "$FD_TEST_C_OLD_TOKEN" "$FD_TEST_C_NEW_TOKEN" || return $?
    driver_test_c_finish "$FD_TEST_C_AUTHORIZE_ORPHAN_CLEANUP" "$FD_TEST_C_HEALTH_TIMEOUT"
}

test_c_phase_gate() {
    local gate_status
    driver_test_c_observe_gate >"$FD_TEST_C_OBSERVATION_FILE" || return $?
    FD_TEST_C_RUNTIME_TOKEN=$(driver_test_c_observe_runtime_token) || return $?
    gate_status=0
    evidence_exec test-c-gate-evaluate test-c \
        "$FD_PYTHON" -m firedrill.test_c evaluate \
        --run-path "$FD_RUN_PATH" \
        --baseline "$FD_RUN_PATH/baseline/cluster-state.json" \
        --observation "$FD_TEST_C_OBSERVATION_FILE" \
        --runtime-token "$FD_TEST_C_RUNTIME_TOKEN" || gate_status=$?
    return "$gate_status"
}

command_test_c() {
    local gate_status

    FD_TEST_C_BRANCH=OLD_ONLY
    FD_TEST_C_RECOVERY_FORM=snapshot
    FD_TEST_C_AUTHORIZE_ORPHAN_CLEANUP=false
    while (($# > 0)); do
        case $1 in
            --branch)
                if (($# < 2)); then
                    printf 'test-c usage error: --branch requires a value\n' >&2
                    return 64
                fi
                case $2 in
                    OLD_ONLY|NEW_ONLY|BOTH|ZERO|ANOMALOUS) FD_TEST_C_BRANCH=$2 ;;
                    *)
                        printf 'test-c usage error: unsupported branch %q\n' "$2" >&2
                        return 64
                        ;;
                esac
                shift 2
                ;;
            --recovery-form)
                if (($# < 2)); then
                    printf 'test-c usage error: --recovery-form requires a value\n' >&2
                    return 64
                fi
                case $2 in
                    snapshot|membership) FD_TEST_C_RECOVERY_FORM=$2 ;;
                    *)
                        printf 'test-c usage error: unsupported recovery form %q\n' "$2" >&2
                        return 64
                        ;;
                esac
                shift 2
                ;;
            --authorize-orphan-cleanup)
                FD_TEST_C_AUTHORIZE_ORPHAN_CLEANUP=true
                shift
                ;;
            *)
                printf 'test-c usage error: unknown option %q\n' "$1" >&2
                return 64
                ;;
        esac
    done

    # The real drivers fail here, before state lookup or any Test C mutation.
    driver_load
    driver_preflight
    state_require_lifecycle baseline
    driver_impl_init

    FD_TEST_C_OLD_TOKEN=$(driver_test_c_read_server_token) || return $?
    printf '%s' "$FD_TEST_C_OLD_TOKEN" \
        | "$FD_PYTHON" -m firedrill.test_c validate-token \
            --label 'Test C current server token' >/dev/null || return $?
    FD_TEST_C_NEW_TOKEN=$(driver_test_c_propose_server_token) || return $?
    printf '%s' "$FD_TEST_C_NEW_TOKEN" \
        | "$FD_PYTHON" -m firedrill.test_c validate-token \
            --label 'Test C proposed server token' >/dev/null || return $?

    # Raw candidates and normalized secrets enter process-only memory before
    # the first Test C evidence command or direct Test C artifact write.
    FIREDRILL_ACTIVE_TOKENS_JSON=$(
        printf '%s\n%s\n' "$FD_TEST_C_OLD_TOKEN" "$FD_TEST_C_NEW_TOKEN" \
            | "$FD_PYTHON" -m firedrill.test_c registry-json
    ) || return $?
    export FIREDRILL_ACTIVE_TOKENS_JSON

    FD_TEST_C_HEALTH_TIMEOUT=$(config_get values.node_ready_timeout_seconds) || return $?
    FD_TEST_C_OBSERVATION_FILE=$(
        mktemp "${TMPDIR:-/tmp}/firedrill-test-c-gate.json.XXXXXX"
    ) || return $?
    FD_TEMP_FILES+=("$FD_TEST_C_OBSERVATION_FILE")

    test_c_run_phase SETUP test_c_phase_setup || return $?
    test_c_run_phase BREAK test_c_phase_break || return $?
    test_c_run_phase TRIAGE test_c_phase_triage || return $?
    test_c_run_phase RECOVERY test_c_phase_recovery || return $?
    gate_status=0
    test_c_run_phase GATE test_c_phase_gate || gate_status=$?

    "$FD_PYTHON" -m firedrill.state test-result \
        --run-path "$FD_RUN_PATH" \
        --test test-c \
        --gate "$FD_RUN_PATH/evidence/test-c/gate.json" \
        --phases "$FD_RUN_PATH/evidence/test-c/phases.json" || return $?
    if ((gate_status != 0)); then
        return "$gate_status"
    fi
    printf 'PASS: Test C mock quorum-loss recovery satisfied every evidence gate\n'
}
