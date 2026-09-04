#!/usr/bin/env bash

command_destroy() {
    local confirmation=${1:-}
    local count index guest_id exists_status
    state_load_current
    if [[ $FD_LIFECYCLE == destroyed ]]; then
        printf 'NO-OP: lab %s is already destroyed\n' "$FD_LAB_ID"
        return 0
    fi
    if [[ $confirmation != "$FD_LAB_ID" ]]; then
        printf 'refusing destroy: pass --confirm %s exactly\n' "$FD_LAB_ID" >&2
        return 64
    fi
    driver_load
    driver_preflight
    count=$(config_inventory_count)
    for ((index = count - 1; index >= 0; index--)); do
        guest_id=$(config_inventory_field "$index" id)
        exists_status=0
        # Exit 1 is an idempotent absence; another error must stop destruction.
        driver_guest_exists "$guest_id" || exists_status=$?
        if ((exists_status == 0)); then
            driver_guest_delete "$guest_id"
        elif ((exists_status != 1)); then
            printf 'destroy error: existence probe failed for guest %s with status %s\n' \
                "$guest_id" "$exists_status" >&2
            return "$exists_status"
        fi
    done
    state_set_lifecycle destroyed
    printf 'PASS: removed all harness-owned guests for lab %s; evidence retained at %s\n' \
        "$FD_LAB_ID" "$FD_RUN_PATH"
}
