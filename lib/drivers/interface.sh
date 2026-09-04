#!/usr/bin/env bash

driver_load() {
    local driver driver_file
    driver=$(config_get values.driver)
    driver_file=$FD_ROOT/lib/drivers/$driver.sh
    if [[ ! -r $driver_file ]]; then
        printf 'driver error: implementation is unavailable: %s\n' "$driver" >&2
        return 69
    fi
    # Driver paths are selected only from the validated fixed enum.
    # shellcheck source=/dev/null
    source "$driver_file"
    driver_impl_init
}

driver_preflight() {
    local count index guest_id
    driver_impl_validate_config
    safety_guard_common
    count=$(config_inventory_count)
    for ((index = 0; index < count; index++)); do
        guest_id=$(config_inventory_field "$index" id)
        safety_check_guest_id "$guest_id"
    done
    driver_impl_check_reachable
    driver_impl_template_exists
}

driver_guest_exists() {
    driver_impl_guest_exists "$1"
}

driver_guest_create() {
    local spec=$1
    local guest_id
    guest_id=$("$FD_PYTHON" -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$spec")
    safety_guard_mutation "$guest_id" create
    driver_impl_guest_create "$spec"
}

driver_guest_start() {
    safety_guard_mutation "$1" start
    driver_impl_guest_start "$1"
}

driver_guest_stop() {
    safety_guard_mutation "$1" stop
    driver_impl_guest_stop "$1" "$2"
}

driver_guest_status() {
    driver_impl_guest_status "$1"
}

driver_guest_delete() {
    safety_guard_mutation "$1" delete
    driver_impl_guest_delete "$1"
}

driver_snapshot_exists() {
    driver_impl_snapshot_exists "$1" "$2"
}

driver_snapshot_create() {
    safety_guard_mutation "$1" snapshot-create
    driver_impl_snapshot_create "$1" "$2"
}

driver_snapshot_restore_prepare() {
    driver_impl_snapshot_restore_prepare "$1" "$2"
}

driver_snapshot_restore() {
    safety_guard_mutation "$1" snapshot-restore
    driver_impl_snapshot_restore "$1" "$2"
}

driver_snapshot_restore_finish() {
    driver_impl_snapshot_restore_finish "$1" "$2"
}

driver_guest_wait_access() {
    driver_impl_guest_wait_access "$1" "$2"
}

driver_guest_exec() {
    local node=$1
    local timeout=$2
    shift 2
    if [[ ${1:-} == -- ]]; then
        shift
    fi
    local guest_id
    guest_id=$(node_id "$node")
    safety_guard_mutation "$guest_id" guest-exec
    driver_impl_guest_exec "$node" "$guest_id" "$timeout" "$@"
}

driver_guest_put() {
    local node=$1
    local guest_id
    shift
    guest_id=$(node_id "$node")
    safety_guard_mutation "$guest_id" guest-put
    driver_impl_guest_put "$node" "$@"
}

driver_test_a_read_server_token() {
    driver_impl_test_a_read_server_token
}

driver_test_a_propose_server_token() {
    driver_impl_test_a_propose_server_token
}

driver_test_a_snapshot_pair() {
    local node=$1
    local token=$2
    local guest_id
    guest_id=$(node_id "$node")
    safety_guard_mutation "$guest_id" test-a-snapshot
    driver_impl_test_a_snapshot_pair "$node" "$guest_id" "$token"
}

driver_test_a_rotate_server_token() {
    local token=$1
    local restart_order=$2
    local guest_id
    guest_id=$(node_id server-1)
    safety_guard_mutation "$guest_id" test-a-token-rotate
    driver_impl_test_a_rotate_server_token "$token" "$restart_order"
}

driver_test_a_restart_node() {
    local node=$1
    local timeout=$2
    local guest_id
    guest_id=$(node_id "$node")
    safety_guard_mutation "$guest_id" test-a-restart
    driver_impl_test_a_restart_node "$node" "$guest_id" "$timeout"
}

driver_test_a_observe_gate() {
    safety_guard_common
    driver_impl_test_a_observe_gate
}

driver_test_c_read_server_token() {
    driver_impl_test_c_read_server_token
}

driver_test_c_propose_server_token() {
    driver_impl_test_c_propose_server_token
}

driver_test_c_setup() {
    local guest_id
    guest_id=$(node_id server-3)
    safety_guard_mutation "$guest_id" test-c-snapshot-pair
    driver_impl_test_c_setup "$1" "$2" "$3"
}

driver_test_c_break() {
    local node guest_id
    for node in server-1 server-2 server-3; do
        guest_id=$(node_id "$node")
        safety_guard_mutation "$guest_id" test-c-quorum-break
    done
    driver_impl_test_c_break "$1"
}

driver_test_c_triage() {
    safety_guard_common
    driver_impl_test_c_triage "$1" "$2"
}

driver_test_c_recover() {
    local guest_id
    guest_id=$(node_id server-3)
    safety_guard_mutation "$guest_id" test-c-cluster-reset
    driver_impl_test_c_recover "$1" "$2"
}

driver_test_c_finish() {
    local node guest_id
    for node in server-1 server-2 server-3 agent-1 agent-2; do
        guest_id=$(node_id "$node")
        safety_guard_mutation "$guest_id" test-c-recovery-finish
    done
    driver_impl_test_c_finish "$1" "$2"
}

driver_test_c_observe_gate() {
    safety_guard_common
    driver_impl_test_c_observe_gate
}

driver_test_c_observe_runtime_token() {
    safety_guard_common
    driver_impl_test_c_observe_runtime_token
}
