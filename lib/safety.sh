#!/usr/bin/env bash

safety_check_configured_targets() {
    "$FD_PYTHON" -m firedrill.safety \
        --canonical "$FD_CANONICAL_CONFIG" \
        --check-denylist
}

safety_check_identity() {
    local expected observed
    expected=$(config_get values.expected_hypervisor_hostname)
    observed=$(driver_impl_probe_identity)
    if [[ $observed != "$expected" ]]; then
        printf 'SAFETY ABORT: hypervisor identity mismatch: expected %q, observed %q\n' \
            "$expected" "$observed" >&2
        return 78
    fi
}

safety_check_guest_id() {
    "$FD_PYTHON" -m firedrill.safety \
        --canonical "$FD_CANONICAL_CONFIG" \
        --check-id "$1"
}

safety_guard_common() {
    safety_check_configured_targets
    safety_check_identity
}

safety_guard_mutation() {
    local guest_id=$1
    local operation=$2
    local existing_owner exists_status
    safety_guard_common
    safety_check_guest_id "$guest_id"

    exists_status=0
    # Exit 1 means absent by contract; any other nonzero status is a driver failure.
    driver_impl_guest_exists "$guest_id" || exists_status=$?
    if ((exists_status == 0)); then
        existing_owner=$(driver_impl_guest_owner "$guest_id")
        if [[ $existing_owner != "$FD_LAB_ID" ]]; then
            printf 'SAFETY ABORT: guest %s is owned by %q, not current lab %q\n' \
                "$guest_id" "$existing_owner" "$FD_LAB_ID" >&2
            return 78
        fi
    elif ((exists_status != 1)); then
        printf 'SAFETY ABORT: ownership probe failed for guest %s with status %s\n' \
            "$guest_id" "$exists_status" >&2
        return 78
    elif [[ $operation != create ]]; then
        printf 'SAFETY ABORT: refusing %s for absent guest %s\n' "$operation" "$guest_id" >&2
        return 78
    fi
}
