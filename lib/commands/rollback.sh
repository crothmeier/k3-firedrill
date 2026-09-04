#!/usr/bin/env bash

command_rollback() {
    local snapshot_name count index guest_id role restore_role capture_timeout state_file
    state_require_lifecycle baseline
    driver_load
    driver_preflight
    snapshot_name=$(config_get values.snapshot_name)
    count=$(config_inventory_count)

    # Prove every restore point before stopping any guest. A partial snapshot
    # set must fail without changing the running cluster.
    for ((index = 0; index < count; index++)); do
        guest_id=$(config_inventory_field "$index" id)
        if ! driver_snapshot_exists "$guest_id" "$snapshot_name"; then
            printf 'rollback error: guest %s lacks baseline snapshot %s\n' \
                "$guest_id" "$snapshot_name" >&2
            return 67
        fi
    done

    for ((index = 0; index < count; index++)); do
        guest_id=$(config_inventory_field "$index" id)
        driver_snapshot_restore_prepare "$guest_id" "$snapshot_name"
    done

    for ((index = 0; index < count; index++)); do
        guest_id=$(config_inventory_field "$index" id)
        driver_snapshot_restore "$guest_id" "$snapshot_name"
    done

    # Start every server before either agent, independent of inventory order.
    for restore_role in server agent; do
        for ((index = 0; index < count; index++)); do
            role=$(config_inventory_field "$index" role)
            if [[ $role == "$restore_role" ]]; then
                guest_id=$(config_inventory_field "$index" id)
                driver_snapshot_restore_finish "$guest_id" "$snapshot_name"
            fi
        done
    done

    capture_timeout=$(config_get values.cluster_capture_timeout_seconds)
    driver_guest_wait_access server-1 "$capture_timeout"
    state_file=$(mktemp "${TMPDIR:-/tmp}/firedrill-rollback.json.XXXXXX")
    FD_TEMP_FILES+=("$state_file")
    cluster_capture_state >"$state_file"
    cluster_assert_healthy_file "$state_file"
    printf 'PASS: baseline restored and cluster health verified\n'
}
