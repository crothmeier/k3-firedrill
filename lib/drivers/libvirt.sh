#!/usr/bin/env bash
# Driver hooks are loaded dynamically through interface.sh.
# shellcheck disable=SC2329

# The libvirt implementation is intentionally deferred. These fail-closed stubs keep
# driver selection explicit without allowing this foundation increment to mutate a host.
driver_impl_init() { return 0; }
driver_impl_validate_config() {
    printf 'libvirt driver is not implemented in the reviewed foundation increment\n' >&2
    return 69
}
driver_impl_probe_identity() { return 69; }
driver_impl_check_reachable() { return 69; }
driver_impl_template_exists() { return 69; }
driver_impl_guest_exists() { return 69; }
driver_impl_guest_owner() { return 69; }
driver_impl_guest_create() { return 69; }
driver_impl_guest_start() { return 69; }
driver_impl_guest_stop() { return 69; }
driver_impl_guest_status() { return 69; }
driver_impl_guest_delete() { return 69; }
driver_impl_snapshot_exists() { return 69; }
driver_impl_snapshot_create() { return 69; }
driver_impl_snapshot_restore_prepare() { return 69; }
driver_impl_snapshot_restore() { return 69; }
driver_impl_snapshot_restore_finish() { return 69; }
driver_impl_guest_wait_access() { return 69; }
driver_impl_guest_exec() { return 69; }
driver_impl_guest_put() { return 69; }
driver_impl_test_a_read_server_token() { return 69; }
driver_impl_test_a_propose_server_token() { return 69; }
driver_impl_test_a_snapshot_pair() { return 69; }
driver_impl_test_a_rotate_server_token() { return 69; }
driver_impl_test_a_restart_node() { return 69; }
driver_impl_test_a_observe_gate() { return 69; }
