#!/usr/bin/env bash
set -Eeuo pipefail

TEST_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TEST_TMP=$(mktemp -d "${TMPDIR:-/tmp}/firedrill-safety.XXXXXX")
cleanup() {
    rm -rf -- "${TEST_TMP:?}"
}
trap cleanup EXIT

config=$TEST_TMP/firedrill.conf
sed "s|run_dir=./runs|run_dir=$TEST_TMP/runs|" \
    "$TEST_ROOT/firedrill.conf.example" >"$config"

printf 'mock-hypervisor\n' >"$TEST_TMP/firedrill.denylist"
if "$TEST_ROOT/firedrill" --config "$config" preflight >"$TEST_TMP/out" 2>"$TEST_TMP/err"; then
    echo 'denylisted preflight unexpectedly succeeded' >&2
    exit 1
fi
grep -q 'SAFETY ABORT' "$TEST_TMP/err"

rm "$TEST_TMP/firedrill.denylist"
wrong_config=$TEST_TMP/wrong.conf
sed 's/expected_hypervisor_hostname=mock-hypervisor/expected_hypervisor_hostname=wrong-host/' \
    "$config" >"$wrong_config"
if "$TEST_ROOT/firedrill" --config "$wrong_config" preflight >"$TEST_TMP/out" 2>"$TEST_TMP/err"; then
    echo 'identity-mismatched preflight unexpectedly succeeded' >&2
    exit 1
fi
grep -q 'hypervisor identity mismatch' "$TEST_TMP/err"

for command in test-b test-all; do
    status=0
    "$TEST_ROOT/firedrill" --config "$config" "$command" \
        >"$TEST_TMP/$command.out" 2>"$TEST_TMP/$command.err" || status=$?
    if ((status != 69)); then
        printf '%s returned %s instead of fail-closed exit 69\n' "$command" "$status" >&2
        exit 1
    fi
    grep -q 'intentionally not implemented' "$TEST_TMP/$command.err"
done

real_config=$TEST_TMP/pve.conf
sed \
    -e 's/^driver=mock$/driver=pve/' \
    -e 's/^hypervisor_host=mock-hypervisor.invalid$/hypervisor_host=pve-lab.example/' \
    -e 's/^expected_hypervisor_hostname=mock-hypervisor$/expected_hypervisor_hostname=pve-lab/' \
    -e 's/^pve_host=CHANGEME$/pve_host=pve-lab.example/' \
    -e 's/^pve_node=CHANGEME$/pve_node=pve-lab/' \
    -e 's/^pve_storage=CHANGEME$/pve_storage=zfs-lab/' \
    -e 's/^template_vmid=CHANGEME$/template_vmid=9000/' \
    -e 's/^ssh_user=CHANGEME$/ssh_user=root/' \
    -e 's|^ssh_key_path=CHANGEME$|ssh_key_path=/tmp/nonexistent-fd-key|' \
    "$config" >"$real_config"
status=0
"$TEST_ROOT/firedrill" --config "$real_config" test-a \
    >"$TEST_TMP/pve-test-a.out" 2>"$TEST_TMP/pve-test-a.err" || status=$?
# Real Test A hooks landed in 06ee682, so pve test-a no longer stops at the
# unreviewed-hook gate. It now fails closed one step EARLIER, in the generic
# configuration layer, on this fixture's unfilled artifact and etcd placeholders
# — which proves the artifact-pinning configuration added by that increment is
# mandatory. Note the layer: this is py/firedrill/config.py rejecting a required
# placeholder and exiting 65, NOT the pve driver's pve_reject_placeholder, which
# returns 69 and never runs because config validation aborts first. Match the
# generic placeholder phrase rather than a specific key: the message names
# whichever key fails first, and that ordering shifts every time a config key is
# added. The no-state-before-failure invariant below is unchanged and is the point.
if ((status != 65)); then
    printf 'pve test-a returned %s instead of fail-closed exit 65\n' "$status" >&2
    exit 1
fi
if ! grep -q 'is a placeholder' "$TEST_TMP/pve-test-a.err"; then
    printf 'pve test-a exited 65 without reporting a placeholder rejection; stderr was:\n' >&2
    cat "$TEST_TMP/pve-test-a.err" >&2
    exit 1
fi
if [[ -e $TEST_TMP/runs/current.json ]]; then
    printf 'pve test-a created state before its configuration rejection\n' >&2
    exit 1
fi
status=0
"$TEST_ROOT/firedrill" --config "$real_config" test-c \
    >"$TEST_TMP/pve-test-c.out" 2>"$TEST_TMP/pve-test-c.err" || status=$?
# Same layer, same reason as test-a above: configuration validation is
# command-agnostic, so the artifact and etcd placeholders in this fixture abort
# at exit 65 before any driver dispatch, and test-c never reaches its exit-69
# stub. Changing this expectation does NOT weaken the guarantee that test-c's
# real hooks stay fail-closed — tests/test_pve_driver.sh probes all ten
# driver_impl_test_c_* hooks directly, bypassing config load, and those probes
# are strictly stronger than this single end-to-end check.
if ((status != 65)); then
    printf 'pve test-c returned %s instead of fail-closed exit 65\n' "$status" >&2
    exit 1
fi
if ! grep -q 'is a placeholder' "$TEST_TMP/pve-test-c.err"; then
    printf 'pve test-c exited 65 without reporting a placeholder rejection; stderr was:\n' >&2
    cat "$TEST_TMP/pve-test-c.err" >&2
    exit 1
fi
if [[ -e $TEST_TMP/runs/current.json ]]; then
    printf 'pve test-c created state before its configuration rejection\n' >&2
    exit 1
fi
printf 'PASS: test-b and test-all remain fail-closed at exit 69; pve test-a and test-c fail closed at exit 65 on placeholder configuration before any driver dispatch\n'
