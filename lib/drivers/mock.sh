#!/usr/bin/env bash
# Driver hooks are loaded dynamically through interface.sh.
# shellcheck disable=SC2329

driver_impl_init() {
    if [[ -n ${FD_RUN_PATH:-} ]]; then
        FD_MOCK_MODEL=$FD_RUN_PATH/driver/mock.json
    else
        FD_MOCK_MODEL=/nonexistent/firedrill-preflight-mock.json
    fi
}

driver_impl_validate_config() {
    return 0
}

driver_impl_probe_identity() {
    "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" identity
}

driver_impl_check_reachable() {
    return 0
}

driver_impl_template_exists() {
    "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" template-exists >/dev/null
}

driver_impl_guest_exists() {
    "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" exists "$1"
}

driver_impl_guest_owner() {
    "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" owner "$1"
}

driver_impl_guest_create() {
    evidence_exec driver-create hypervisor \
        "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" \
        create --lab-id "$FD_LAB_ID" --spec "$1"
}

driver_impl_guest_start() {
    evidence_exec driver-start hypervisor \
        "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" \
        start --lab-id "$FD_LAB_ID" "$1"
}

driver_impl_guest_stop() {
    evidence_exec driver-stop hypervisor \
        "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" \
        stop --lab-id "$FD_LAB_ID" "$1"
}

driver_impl_guest_status() {
    "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" status "$1"
}

driver_impl_guest_delete() {
    evidence_exec driver-delete hypervisor \
        "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" \
        delete --lab-id "$FD_LAB_ID" "$1"
}

driver_impl_snapshot_exists() {
    "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" \
        snapshot-exists --lab-id "$FD_LAB_ID" "$1" "$2"
}

driver_impl_snapshot_create() {
    evidence_exec snapshot-create hypervisor \
        "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" \
        snapshot-create --lab-id "$FD_LAB_ID" "$1" "$2"
}

driver_impl_snapshot_restore_prepare() {
    return 0
}

driver_impl_snapshot_restore() {
    evidence_exec snapshot-restore hypervisor \
        "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" \
        snapshot-restore --lab-id "$FD_LAB_ID" "$1" "$2"
}

driver_impl_snapshot_restore_finish() {
    return 0
}

driver_impl_guest_wait_access() {
    local node=$1
    local timeout=$2
    local guest_id
    guest_id=$(node_id "$node")
    "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" \
        guest-exec --lab-id "$FD_LAB_ID" "$guest_id" wait-access "$timeout" >/dev/null
}

driver_impl_guest_exec() {
    local node=$1
    local guest_id=$2
    local timeout=$3
    shift 3
    if [[ ${1:-} != firedrill-op ]]; then
        printf 'mock driver error: guest commands must use the firedrill-op protocol\n' >&2
        return 69
    fi
    shift
    evidence_exec guest-command "$node" \
        "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" \
        guest-exec --lab-id "$FD_LAB_ID" "$guest_id" "$@" "$timeout"
}

driver_impl_guest_put() {
    printf 'mock driver error: guest file transfer is not implemented in this increment\n' >&2
    return 69
}

driver_impl_test_a_read_server_token() {
    "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" \
        test-a-read-token --lab-id "$FD_LAB_ID"
}

driver_impl_test_a_propose_server_token() {
    "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" \
        test-a-propose-token --lab-id "$FD_LAB_ID"
}

driver_impl_test_a_snapshot_pair() {
    local node=$1
    local guest_id=$2
    local token=$3
    [[ -n $guest_id ]] || return 69
    evidence_exec test-a-snapshot-pair "$node" \
        "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" \
        test-a-snapshot --lab-id "$FD_LAB_ID" --node "$node" --token "$token"
}

driver_impl_test_a_rotate_server_token() {
    local token=$1
    local restart_order=$2
    evidence_exec test-a-token-rotate server-1 \
        "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" \
        test-a-rotate --lab-id "$FD_LAB_ID" --token "$token" \
        --restart-order "$restart_order"
}

driver_impl_test_a_restart_node() {
    local node=$1
    local guest_id=$2
    local timeout=$3
    [[ -n $guest_id ]] || return 69
    evidence_exec test-a-node-restart "$node" \
        "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" \
        test-a-restart --lab-id "$FD_LAB_ID" --node "$node" --timeout "$timeout"
}

driver_impl_test_a_observe_gate() {
    evidence_exec test-a-gate-observation test-a \
        "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" \
        test-a-observe --lab-id "$FD_LAB_ID"
}

driver_impl_test_c_read_server_token() {
    "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" \
        test-a-read-token --lab-id "$FD_LAB_ID"
}

driver_impl_test_c_propose_server_token() {
    "$FD_PYTHON" -m firedrill.mock_model --model "$FD_MOCK_MODEL" \
        test-a-propose-token --lab-id "$FD_LAB_ID"
}

driver_impl_test_c_setup() {
    local old_token=$1
    local new_token=$2
    local recovery_form=$3
    evidence_exec test-c-setup test-c \
        "$FD_PYTHON" -m firedrill.test_c model-setup \
        --model "$FD_MOCK_MODEL" --lab-id "$FD_LAB_ID" --run-path "$FD_RUN_PATH" \
        --old-token "$old_token" --new-token "$new_token" \
        --recovery-form "$recovery_form"
}

driver_impl_test_c_break() {
    evidence_exec test-c-break test-c \
        "$FD_PYTHON" -m firedrill.test_c model-break \
        --model "$FD_MOCK_MODEL" --lab-id "$FD_LAB_ID" --run-path "$FD_RUN_PATH" \
        --branch "$1"
}

driver_impl_test_c_triage() {
    local old_token=$1
    local new_token=$2
    evidence_exec test-c-triage test-c \
        "$FD_PYTHON" -m firedrill.test_c model-triage \
        --model "$FD_MOCK_MODEL" --lab-id "$FD_LAB_ID" --run-path "$FD_RUN_PATH" \
        --old-token "$old_token" --new-token "$new_token"
}

driver_impl_test_c_recover() {
    local old_token=$1
    local new_token=$2
    evidence_exec test-c-cluster-reset test-c \
        "$FD_PYTHON" -m firedrill.test_c model-recover \
        --model "$FD_MOCK_MODEL" --lab-id "$FD_LAB_ID" --run-path "$FD_RUN_PATH" \
        --old-token "$old_token" --new-token "$new_token"
}

driver_impl_test_c_finish() {
    local authorize_cleanup=$1
    local timeout=$2
    if [[ $authorize_cleanup == true ]]; then
        evidence_exec test-c-recovery-finish test-c \
            "$FD_PYTHON" -m firedrill.test_c model-finish \
            --model "$FD_MOCK_MODEL" --lab-id "$FD_LAB_ID" --run-path "$FD_RUN_PATH" \
            --timeout "$timeout" --authorize-orphan-cleanup
        return
    fi
    evidence_exec test-c-recovery-finish test-c \
        "$FD_PYTHON" -m firedrill.test_c model-finish \
        --model "$FD_MOCK_MODEL" --lab-id "$FD_LAB_ID" --run-path "$FD_RUN_PATH" \
        --timeout "$timeout"
}

driver_impl_test_c_observe_gate() {
    evidence_exec test-c-gate-observation test-c \
        "$FD_PYTHON" -m firedrill.test_c model-observe \
        --model "$FD_MOCK_MODEL" --lab-id "$FD_LAB_ID"
}

driver_impl_test_c_observe_runtime_token() {
    "$FD_PYTHON" -m firedrill.test_c model-runtime-token \
        --model "$FD_MOCK_MODEL" --lab-id "$FD_LAB_ID"
}
