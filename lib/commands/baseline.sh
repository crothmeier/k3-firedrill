#!/usr/bin/env bash

command_baseline() {
    local snapshot_name count index guest_id cluster_state_file
    state_load_current
    driver_load
    if [[ $FD_LIFECYCLE == baseline ]]; then
        printf 'NO-OP: baseline already captured for lab %s\n' "$FD_LAB_ID"
        return 0
    fi
    if [[ $FD_LIFECYCLE != provisioned ]]; then
        printf 'state error: baseline requires provisioned lifecycle, observed %s\n' \
            "$FD_LIFECYCLE" >&2
        return 66
    fi
    driver_preflight
    snapshot_name=$(config_get values.snapshot_name)
    count=$(config_inventory_count)
    for ((index = 0; index < count; index++)); do
        guest_id=$(config_inventory_field "$index" id)
        driver_snapshot_create "$guest_id" "$snapshot_name"
    done
    cluster_state_file=$(mktemp "${TMPDIR:-/tmp}/firedrill-baseline.json.XXXXXX")
    FD_TEMP_FILES+=("$cluster_state_file")
    cluster_capture_state >"$cluster_state_file"
    cluster_assert_healthy_file "$cluster_state_file"
    "$FD_PYTHON" -m firedrill.state baseline \
        --run-path "$FD_RUN_PATH" \
        --cluster-state "$cluster_state_file" \
        --snapshot-name "$snapshot_name"
    printf 'PASS: baseline %s captured for all five guests\n' "$snapshot_name"
}

