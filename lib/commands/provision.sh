#!/usr/bin/env bash

command_provision() {
    local count index spec node role guest_id state_file access_timeout ready_timeout

    # Preflight occurs before creating even local run state, preserving the mutation boundary.
    driver_load
    driver_preflight
    state_begin_or_resume
    driver_impl_init
    access_timeout=$(config_get values.guest_access_timeout_seconds)
    ready_timeout=$(config_get values.node_ready_timeout_seconds)

    if [[ $FD_RUN_CREATED == false ]]; then
        state_load_current
        if [[ $FD_LIFECYCLE == provisioned || $FD_LIFECYCLE == baseline ]]; then
            printf 'NO-OP: active lab %s is already %s\n' "$FD_LAB_ID" "$FD_LIFECYCLE"
            return 0
        fi
    fi

    count=$(config_inventory_count)
    for ((index = 0; index < count; index++)); do
        spec=$(config_get "inventory.${index}")
        driver_guest_create "$spec"
    done
    for ((index = 0; index < count; index++)); do
        guest_id=$(config_inventory_field "$index" id)
        node=$(config_inventory_field "$index" short_name)
        driver_guest_start "$guest_id"
        driver_guest_wait_access "$node" "$access_timeout"
    done

    for node in server-1 server-2 server-3 agent-1 agent-2; do
        role=agent
        if [[ $node == server-* ]]; then
            role=server-join
        fi
        if [[ $node == server-1 ]]; then
            role=server-cluster-init
        fi
        node_install_k3s "$node" "$role"
        node_wait_ready "$node" "$ready_timeout"
    done

    state_file=$(mktemp "${TMPDIR:-/tmp}/firedrill-cluster-state.json.XXXXXX")
    FD_TEMP_FILES+=("$state_file")
    cluster_capture_state >"$state_file"
    cluster_assert_healthy_file "$state_file"
    state_set_lifecycle provisioned
    printf 'PASS: mock lab %s provisioned with five Ready nodes\n' "$FD_LAB_ID"
}
