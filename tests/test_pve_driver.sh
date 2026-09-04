#!/usr/bin/env bash
set -Eeuo pipefail

TEST_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TEST_TMP=$(mktemp -d "${TMPDIR:-/tmp}/firedrill-pve-driver.XXXXXX")
export PYTHONPATH="$TEST_ROOT/py${PYTHONPATH:+:$PYTHONPATH}"
cleanup() {
    rm -rf -- "${TEST_TMP:?}"
}
trap cleanup EXIT

bash "$TEST_ROOT/tests/test_guest_firedrill_op.sh"

FD_PYTHON=python3
FD_TEMP_FILES=()
FD_LAB_ID=fd-pve-driver-unit
FD_CANONICAL_CONFIG=$TEST_TMP/canonical.json
CALL_LOG=$TEST_TMP/transport.log
KEY_PATH=$TEST_TMP/id_ed25519
KNOWN_HOSTS_PATH=$TEST_TMP/known_hosts
GUEST_KEY_PATH=$TEST_TMP/guest_ed25519
GUEST_KNOWN_HOSTS_PATH=$TEST_TMP/guest_known_hosts
JOIN_CREDENTIAL_PATH=$TEST_TMP/join-credential
: >"$KEY_PATH"
: >"$KNOWN_HOSTS_PATH"
: >"$GUEST_KEY_PATH"
: >"$GUEST_KNOWN_HOSTS_PATH"
: >"$JOIN_CREDENTIAL_PATH"
: >"$CALL_LOG"
chmod 0600 "$JOIN_CREDENTIAL_PATH"

CFG_PVE_HOST=pve-lab.example
CFG_HYPERVISOR_HOST=pve-lab.example
CFG_PVE_NODE=pve-lab
CFG_EXPECTED_HOSTNAME=pve-lab
CFG_PVE_STORAGE=labtank
CFG_TEMPLATE_VMID=9000
CFG_PVE_PRIVILEGE_MODE=direct
CFG_PVE_CLONE_MODE=full
CFG_PVE_CI_USER=ubuntu
CFG_PVE_CI_SSHKEYS=/root/.ssh/firedrill.pub
CFG_PVE_NET_MODEL=virtio
CFG_PVE_NET_DEVICE=net0
CFG_PVE_IPCONFIG_DEVICE=ipconfig0
CFG_PVE_OS_DISK=scsi0
CFG_PVE_GUEST_AGENT=enabled
CFG_GUEST_PRIVILEGE_MODE=direct
CFG_CONNECT_TIMEOUT=2
CFG_OPERATION_TIMEOUT=3
CFG_CLUSTER_CAPTURE_TIMEOUT=3
CFG_ARTIFACT_SHA=$(printf 'a%.0s' {1..64})
CFG_INSTALL_SHA=$(printf 'b%.0s' {1..64})
CFG_ETCDCTL_SHA=$(printf 'c%.0s' {1..64})
command=''

config_get() {
    case $1 in
        values.pve_host) printf '%s\n' "$CFG_PVE_HOST" ;;
        values.hypervisor_host) printf '%s\n' "$CFG_HYPERVISOR_HOST" ;;
        values.pve_node) printf '%s\n' "$CFG_PVE_NODE" ;;
        values.expected_hypervisor_hostname) printf '%s\n' "$CFG_EXPECTED_HOSTNAME" ;;
        values.pve_storage) printf '%s\n' "$CFG_PVE_STORAGE" ;;
        values.template_vmid) printf '%s\n' "$CFG_TEMPLATE_VMID" ;;
        values.ssh_user) printf 'root\n' ;;
        values.ssh_key_path) printf '%s\n' "$KEY_PATH" ;;
        values.ssh_known_hosts_path) printf '%s\n' "$KNOWN_HOSTS_PATH" ;;
        values.pve_privilege_mode) printf '%s\n' "$CFG_PVE_PRIVILEGE_MODE" ;;
        values.pve_clone_mode) printf '%s\n' "$CFG_PVE_CLONE_MODE" ;;
        values.pve_cloud_init_user) printf '%s\n' "$CFG_PVE_CI_USER" ;;
        values.pve_cloud_init_sshkeys_path) printf '%s\n' "$CFG_PVE_CI_SSHKEYS" ;;
        values.pve_net_model) printf '%s\n' "$CFG_PVE_NET_MODEL" ;;
        values.pve_net_device) printf '%s\n' "$CFG_PVE_NET_DEVICE" ;;
        values.pve_ipconfig_device) printf '%s\n' "$CFG_PVE_IPCONFIG_DEVICE" ;;
        values.pve_os_disk) printf '%s\n' "$CFG_PVE_OS_DISK" ;;
        values.pve_guest_agent) printf '%s\n' "$CFG_PVE_GUEST_AGENT" ;;
        values.guest_ssh_user) printf 'ubuntu\n' ;;
        values.guest_ssh_key_path) printf '%s\n' "$GUEST_KEY_PATH" ;;
        values.guest_ssh_known_hosts_path) printf '%s\n' "$GUEST_KNOWN_HOSTS_PATH" ;;
        values.guest_privilege_mode) printf '%s\n' "$CFG_GUEST_PRIVILEGE_MODE" ;;
        values.ssh_connect_timeout_seconds) printf '%s\n' "$CFG_CONNECT_TIMEOUT" ;;
        values.pve_operation_timeout_seconds) printf '%s\n' "$CFG_OPERATION_TIMEOUT" ;;
        values.cluster_capture_timeout_seconds) printf '%s\n' "$CFG_CLUSTER_CAPTURE_TIMEOUT" ;;
        values.firedrill_op_config_path) printf '/etc/firedrill/op.env\n' ;;
        values.guest_join_file) printf '/etc/firedrill/join.env\n' ;;
        values.k3s_join_credential_file) printf '%s\n' "$JOIN_CREDENTIAL_PATH" ;;
        values.k3s_api_port) printf '6443\n' ;;
        values.k3s_binary_artifact_path) printf '/opt/firedrill/artifacts/k3s\n' ;;
        values.k3s_binary_sha256) printf '%s\n' "$CFG_ARTIFACT_SHA" ;;
        values.k3s_install_script_artifact_path) printf '/opt/firedrill/artifacts/install.sh\n' ;;
        values.k3s_install_script_sha256) printf '%s\n' "$CFG_INSTALL_SHA" ;;
        values.etcdctl_artifact_path) printf '/opt/firedrill/artifacts/etcdctl\n' ;;
        values.etcdctl_sha256) printf '%s\n' "$CFG_ETCDCTL_SHA" ;;
        values.k3s_installed_binary_path) printf '/usr/local/bin/k3s\n' ;;
        values.k3s_kubeconfig_path) printf '/etc/rancher/k3s/k3s.yaml\n' ;;
        values.k3s_agent_kubeconfig_path) printf '/var/lib/rancher/k3s/agent/kubelet.kubeconfig\n' ;;
        values.k3s_server_ca_path) printf '/var/lib/rancher/k3s/server/tls/server-ca.crt\n' ;;
        values.k3s_server_token_path) printf '/var/lib/rancher/k3s/server/token\n' ;;
        values.k3s_server_service_env_path) printf '/etc/systemd/system/k3s.service.env\n' ;;
        values.k3s_agent_service_env_path) printf '/etc/systemd/system/k3s-agent.service.env\n' ;;
        values.k3s_server_systemd_unit) printf 'k3s\n' ;;
        values.k3s_agent_systemd_unit) printf 'k3s-agent\n' ;;
        values.k3s_etcd_endpoint) printf 'https://127.0.0.1:2379\n' ;;
        values.k3s_etcd_ca_path) printf '/var/lib/rancher/k3s/server/tls/etcd/server-ca.crt\n' ;;
        values.k3s_etcd_client_cert_path) printf '/var/lib/rancher/k3s/server/tls/etcd/client.crt\n' ;;
        values.k3s_etcd_client_key_path) printf '/var/lib/rancher/k3s/server/tls/etcd/client.key\n' ;;
        values.k3s_etcd_snapshot_dir) printf '/var/lib/rancher/k3s/server/db/snapshots\n' ;;
        values.test_a_journal_line_limit) printf '1000\n' ;;
        values.driver) printf 'pve\n' ;;
        values.k3s_version) printf 'v1.34.4+k3s1\n' ;;
        values.k3s_install_timeout_seconds) printf '3\n' ;;
        values.node_ready_timeout_seconds) printf '3\n' ;;
        values.network_bridge) printf 'vmbr1\n' ;;
        values.gateway) printf '192.0.2.1\n' ;;
        allowed_id_min) printf '7100\n' ;;
        allowed_id_max) printf '7104\n' ;;
        *) printf 'test config_get missing path: %s\n' "$1" >&2; return 65 ;;
    esac
}

config_inventory_count() {
    printf '5\n'
}

config_inventory_field() {
    local index=$1 field=$2
    local -a names=(server-1 server-2 server-3 agent-1 agent-2)
    local -a ips=(192.0.2.10 192.0.2.11 192.0.2.12 192.0.2.13 192.0.2.14)
    local -a roles=(server server server agent agent)
    case $field in
        short_name) printf '%s\n' "${names[$index]}" ;;
        ip) printf '%s\n' "${ips[$index]}" ;;
        id) printf '%s\n' "$((7100 + index))" ;;
        role) printf '%s\n' "${roles[$index]}" ;;
        *) return 65 ;;
    esac
}

# shellcheck source=lib/safety.sh
source "$TEST_ROOT/lib/safety.sh"
# shellcheck source=lib/nodes.sh
source "$TEST_ROOT/lib/nodes.sh"
# shellcheck source=lib/drivers/pve.sh
source "$TEST_ROOT/lib/drivers/pve.sh"

SCENARIO=normal
GUEST_PRESENT=0
GUEST_DESCRIPTION=''
GUEST_CONFIGURED=0
TEMPLATE_DISK_GIB=3.5
GUEST_DISK_GIB=3.5
GUEST_STATUS=stopped
SNAPSHOT_PRESENT=0
TOKEN_CA_OLD=$(printf '1%.0s' {1..64})
TEST_A_OLD_TOKEN="K10${TOKEN_CA_OLD}::server:fixture-old-secret"
TEST_A_NEW_TOKEN="K10${TOKEN_CA_OLD}::server:fixture-new-secret"
CLUSTER_TOKEN_FILE=$TEST_TMP/cluster-token
printf '%s\n' "$TEST_A_OLD_TOKEN" >"$CLUSTER_TOKEN_FILE"
printf '%s\n' "$TEST_A_OLD_TOKEN" >"$JOIN_CREDENTIAL_PATH"
TEST_A_SERVER_ENV_EDIT_LOG=$TEST_TMP/test-a-server-env-edits
TEST_A_SERVER_ENV_COMMAND_LOG=$TEST_TMP/test-a-server-env-commands
TEST_A_SERVER_RESTART_LOG=$TEST_TMP/test-a-server-restarts
: >"$TEST_A_SERVER_ENV_EDIT_LOG"
: >"$TEST_A_SERVER_ENV_COMMAND_LOG"
: >"$TEST_A_SERVER_RESTART_LOG"
TEST_A_SNAPSHOT_DIGEST=$(printf 'd%.0s' {1..64})
TEST_A_CA_DIGEST=$(printf 'e%.0s' {1..64})

# MEASURED SAMPLE F-TA-6 / F-TBC-1 (the cluster-state stub below models
# embedded-etcd member naming).
# Source: Nexus EXEC_LOG_2026-09-02_P06_TEST_A_ATTEMPTS_2_3.md §3/§5 and
# EXEC_LOG_2026-09-04_P06_TEST_B.md §0; the 2026-08-30 capture is committed
# at runs/fd-20260830t151047z-370455/baseline/cluster-state.json.
# Command (RECONSTRUCTED from guest/firedrill-op and the committed manifest):
# ETCDCTL_ENDPOINTS=https://127.0.0.1:2379 \
# ETCDCTL_CACERT=/var/lib/rancher/k3s/server/tls/etcd/server-ca.crt \
# ETCDCTL_CERT=/var/lib/rancher/k3s/server/tls/etcd/client.crt \
# ETCDCTL_KEY=/var/lib/rancher/k3s/server/tls/etcd/client.key \
# /opt/firedrill/artifacts/etcdctl member list --write-out=simple
# host: server-1 (198.51.100.10)   dates: 2026-09-02 (attempt 3 verify) and 2026-09-04 11:16:22Z
# member list: server-1-d1dfa965, server-2-3ee0262b, server-3-9b17da5b   all started, IS LEARNER false
# gate mapping accepted at e4b9fbe: ['server-1←server-1-d1dfa965','server-2←server-2-3ee0262b','server-3←server-3-9b17da5b'], unmapped_names=[]
stub_cluster_state() {
    local token secret digest_output digest key_output key
    IFS= read -r token <"$CLUSTER_TOKEN_FILE"
    secret=${token##*:}
    digest_output=$(printf '%s' "$secret" | shasum -a 256)
    digest=${digest_output%%[[:space:]]*}
    key_output=$(printf '%s' "$secret" | shasum -a 256)
    key=${key_output%%[[:space:]]*}
    key=${key:0:12}
    printf '%s' '{"nodes":['
    printf '{"name":"server-1","role":"server","ready":true,"join_credential_sha256":"%s"},' "$digest"
    printf '{"name":"server-2","role":"server","ready":true,"join_credential_sha256":"%s"},' "$digest"
    printf '{"name":"server-3","role":"server","ready":true,"join_credential_sha256":"%s"},' "$digest"
    printf '{"name":"agent-1","role":"agent","ready":true,"join_credential_sha256":"%s"},' "$digest"
    printf '{"name":"agent-2","role":"agent","ready":true,"join_credential_sha256":"%s"}' "$digest"
    printf '%s' '],"all_nodes_ready":true,"etcd_members":['
    printf '%s' '{"name":"server-1","healthy":true},{"name":"server-2","healthy":true},{"name":"server-3","healthy":true}'
    printf '],"all_etcd_members_healthy":true,"bootstrap_keys":["/bootstrap/%s"],"ca_sha256":"%s"}\n' \
        "$key" "$TEST_A_CA_DIGEST"
}

# MEASURED SAMPLE F-TA-4 (the token stub below models server/token
# regeneration from the configured systemd environment at k3s start).
# Sources: Nexus EXEC_LOG_2026-09-02_P06_TEST_A_FIRST_CONTACT.md §3–§4 and
# EXEC_LOG_2026-09-04_P06_TEST_B.md §0.1.
# Commands (RECONSTRUCTED):
# stat -c '%n %s %a %y' /var/lib/rancher/k3s/server/token /var/lib/rancher/k3s/server/cred/passwd /etc/systemd/system/k3s.service.env
# sha256sum /var/lib/rancher/k3s/server/token | cut -c1-12
# systemctl cat k3s
# journalctl -u k3s --no-pager
# host: server-2 (198.51.100.11)   date: 2026-09-02 ~07:05Z   after the harness wrote NEW into server/token and restarted
# /var/lib/rancher/k3s/server/token   mtime 07:02:28Z   content digest 0b0ff4b8d018 (= OLD, identical to untouched server-3)
# /etc/systemd/system/k3s.service.env unchanged since 2026-08-30, exactly one K3S_TOKEN= line; no /etc/rancher/k3s/config.yaml.d
# systemctl: activating, NRestarts=38, NotReady; etcd endpoint refused
# journal: 07:02:29Z level=error msg="Shutdown request received: failed to save bootstrap data: bootstrap data already found and encrypted with different token"
#          07:02:34Z level=fatal msg="/var/lib/rancher/k3s/server/cred/passwd newer than datastore and could cause a cluster outage. Remove the file(s) from disk and restart to be recreated from datastore."
#
# host: server-2 (198.51.100.11)   date: 2026-09-04 11:17:28Z   read-only, fresh boot from p06-baseline
# systemctl cat k3s: EnvironmentFile=-/etc/systemd/system/k3s.service.env ; no --token in ExecStart ; no k3s.service.d
# k3s.service.env: 113 B, 0600, mtime 2026-08-30 15:31, exactly one K3S_TOKEN= line
# /var/lib/rancher/k3s/server/cred/passwd   175 B   mtime 2026-08-30 15:30:55Z
# /var/lib/rancher/k3s/server/token         141 B   mtime 2026-09-04 11:12:52Z   (regenerated at this boot)
test_a_stub_server_token() {
    local address=$1
    if [[ $SCENARIO == test-a-server-token-not-regenerated ]]; then
        printf '%s\n' "$TEST_A_OLD_TOKEN"
    elif [[ $address == 192.0.2.10 ]]; then
        sed -n '1p' "$CLUSTER_TOKEN_FILE"
    elif grep -Fqx "$address" "$TEST_A_SERVER_ENV_EDIT_LOG" \
        && grep -Fqx "$address" "$TEST_A_SERVER_RESTART_LOG"; then
        printf '%s\n' "$TEST_A_NEW_TOKEN"
    else
        printf '%s\n' "$TEST_A_OLD_TOKEN"
    fi
}

pve_transport_ssh() {
    local address=$1 remote=${!#} supplied_token
    printf '%s\n' "$remote" >>"$CALL_LOG"
    if [[ $remote == *"$FD_PVE_K3S_SERVER_ENV"* \
        && $remote == *'K3S_TOKEN='* ]]; then
        printf '%s\n<END>\n' "$remote" >>"$TEST_A_SERVER_ENV_COMMAND_LOG"
        IFS= read -r supplied_token
        : "$supplied_token"
        printf '%s\n' "$address" >>"$TEST_A_SERVER_ENV_EDIT_LOG"
        return 0
    fi
    # The dollar expression in the first pattern is literal remote-script text.
    # shellcheck disable=SC2016
    case $remote in
        *'token_file=$1'*)
            test_a_stub_server_token "$address" | pve_test_a_token_digest
            ;;
        *"'cat' '/var/lib/rancher/k3s/server/token'"*)
            if [[ $SCENARIO == test-a-token-read-failure ]]; then
                printf 'injected Test A token read failure\n' >&2
                return 73
            fi
            test_a_stub_server_token "$address"
            ;;
        *"'/usr/local/bin/k3s' 'etcd-snapshot' 'save'"*)
            if [[ $SCENARIO == test-a-snapshot-failure ]]; then
                printf 'injected Test A snapshot failure\n' >&2
                return 73
            fi
            printf 'snapshot saved\n'
            ;;
        *"'/var/lib/rancher/k3s/server/db/snapshots'"*"'firedrill-test-a-"*)
            printf '/var/lib/rancher/k3s/server/db/snapshots/firedrill-test-a-fixture.db|%s\n' \
                "$TEST_A_SNAPSHOT_DIGEST"
            ;;
        *"token rotate --new-token"*)
            if [[ $SCENARIO == test-a-rotate-failure ]]; then
                printf 'injected Test A rotation failure\n' >&2
                return 73
            fi
            IFS= read -r supplied_token
            printf '%s\n' "$supplied_token" >"$CLUSTER_TOKEN_FILE"
            ;;
        *"firedrill-op' 'capture-cluster-state'"*)
            if [[ $SCENARIO == test-a-observe-failure ]]; then
                printf 'injected Test A observation failure\n' >&2
                return 73
            fi
            stub_cluster_state
            ;;
        *"cat >"*)
            cat >"$TEST_TMP/guest-put-capture"
            ;;
        *"join_credential_sha256"*) : ;;
        *"chown 0:0"*)
            IFS= read -r supplied_token
            : "$supplied_token"
            ;;
        *"'kubectl' '--kubeconfig'"*"'label' 'node'"*) : ;;
        *"'systemctl' 'daemon-reload'"*) : ;;
        *"'systemctl' 'restart' 'k3s'"*)
            if [[ $SCENARIO == test-a-restart-failure ]]; then
                printf 'injected Test A restart failure\n' >&2
                return 73
            fi
            printf '%s\n' "$address" >>"$TEST_A_SERVER_RESTART_LOG"
            ;;
        *"'systemctl' 'restart'"*)
            if [[ $SCENARIO == test-a-restart-failure ]]; then
                printf 'injected Test A restart failure\n' >&2
                return 73
            fi
            ;;
        *"firedrill-op' 'wait-ready'"*)
            if [[ $SCENARIO == test-a-wait-timeout ]]; then
                printf 'bounded guest wait expired\n' >&2
                return 70
            fi
            printf 'ready\n'
            ;;
        *"'journalctl' '--unit' 'k3s'"*) printf 'clean Test A journal window\n' ;;
        *"'hostname'"*)
            if [[ $SCENARIO == identity-mismatch ]]; then
                printf 'wrong-pve-node\n'
            else
                printf 'pve-lab\n'
            fi
            ;;
        *"'/version'"*) printf '{"version":"9.2.5"}\n' ;;
        *"'/storage/labtank'"*)
            if [[ $SCENARIO == wrong-storage-type ]]; then
                printf '{"type":"dir"}\n'
            else
                printf '{"type":"zfspool"}\n'
            fi
            ;;
        *"'/nodes/pve-lab/network/vmbr1'"*) printf '{"type":"bridge"}\n' ;;
        *"'/nodes/pve-lab/qemu/9000/config'"*)
            if [[ $SCENARIO == non-template ]]; then
                printf '{"template":0,"scsi0":"labtank:base-9000-disk-0,size=%sG"}\n' \
                    "$TEMPLATE_DISK_GIB"
            else
                printf '{"template":1,"scsi0":"labtank:base-9000-disk-0,size=%sG"}\n' \
                    "$TEMPLATE_DISK_GIB"
            fi
            ;;
        *"/snapshot'"*)
            if ((SNAPSHOT_PRESENT == 1)); then
                printf '[{"name":"firedrill-baseline"}]\n'
            else
                printf '[]\n'
            fi
            ;;
        *"'/nodes/pve-lab/qemu/7100/config'"*)
            if ((GUEST_PRESENT == 0)); then
                printf 'Configuration file does not exist\n' >&2
                return 2
            fi
            if [[ $SCENARIO == disk-size-unavailable ]]; then
                printf '{"description":"%s"}\n' "$GUEST_DESCRIPTION"
                return 0
            fi
            if ((GUEST_CONFIGURED == 1)); then
                printf '{"description":"%s","name":"k3fd-server-1","cores":2,"memory":4096,"ciuser":"ubuntu","agent":1,"net0":"virtio,bridge=vmbr1","ipconfig0":"ip=192.0.2.10/24,gw=192.0.2.1","scsi0":"labtank:vm-7100-disk-0,size=%sG"}\n' \
                    "$GUEST_DESCRIPTION" "$GUEST_DISK_GIB"
            else
                printf '{"description":"%s","scsi0":"labtank:vm-7100-disk-0,size=%sG"}\n' \
                    "$GUEST_DESCRIPTION" "$GUEST_DISK_GIB"
            fi
            ;;
        *"'qm' 'clone'"*) GUEST_PRESENT=1; GUEST_DISK_GIB=$TEMPLATE_DISK_GIB ;;
        *"'qm' 'set'"*"'--description'"*) GUEST_DESCRIPTION="firedrill-owner:$FD_LAB_ID" ;;
        *"'qm' 'resize' '7100' 'scsi0' '20G'"*)
            if [[ $SCENARIO == resize-failure ]]; then
                return 73
            fi
            GUEST_DISK_GIB=20
            ;;
        *"'qm' 'set'"*) GUEST_CONFIGURED=1 ;;
        *"'qm' 'status'"*) printf 'status: %s\n' "$GUEST_STATUS" ;;
        *"'qm' 'start'"*) GUEST_STATUS=running ;;
        *"'qm' 'shutdown'"*)
            if [[ $SCENARIO != stop-escalation ]]; then
                GUEST_STATUS=stopped
            fi
            ;;
        *"'qm' 'stop'"*) GUEST_STATUS=stopped ;;
        *"'qm' 'destroy'"*) GUEST_PRESENT=0 ;;
        *"'qm' 'snapshot'"*) SNAPSHOT_PRESENT=1 ;;
        *"'qm' 'rollback'"*) : ;;
        *"'qm' 'delsnapshot'"*) SNAPSHOT_PRESENT=0 ;;
        *"'true'"*|*"'test' '-r'"*) : ;;
        *) printf 'unexpected stubbed PVE transport command: %s\n' "$remote" >&2; return 69 ;;
    esac
}

evidence_exec() {
    local label=$1 node=$2
    shift 2
    printf 'EVIDENCE %s %s\n' "$label" "$node" >>"$CALL_LOG"
    "$@"
}

pve_pause() {
    :
}

safety_guard_mutation() {
    return 0
}

pve_validate_spec_against_inventory() {
    return 0
}

expect_failure() {
    local label=$1 expected_status=$2 expected_pattern=$3
    shift 3
    local status=0
    "$@" >"$TEST_TMP/$label.out" 2>"$TEST_TMP/$label.err" || status=$?
    if ((status != expected_status)) || ! grep -q -- "$expected_pattern" "$TEST_TMP/$label.err"; then
        printf 'negative PVE probe %s failed assertion (exit=%s expected=%s)\n' \
            "$label" "$status" "$expected_status" >&2
        cat "$TEST_TMP/$label.out" "$TEST_TMP/$label.err" >&2
        return 1
    fi
    printf 'NEGATIVE PROBE pve-%s: expected failure exit=%s\n' "$label" "$status"
    cat "$TEST_TMP/$label.err"
}

reset_valid_config() {
    CFG_PVE_HOST=pve-lab.example
    CFG_HYPERVISOR_HOST=pve-lab.example
    CFG_PVE_STORAGE=labtank
    CFG_PVE_CLONE_MODE=full
    CFG_ARTIFACT_SHA=$(printf 'a%.0s' {1..64})
    CFG_INSTALL_SHA=$(printf 'b%.0s' {1..64})
    CFG_ETCDCTL_SHA=$(printf 'c%.0s' {1..64})
    chmod 0600 "$JOIN_CREDENTIAL_PATH"
    SCENARIO=normal
    command=''
    unset FD_PVE_HOST
}

reset_valid_config
CFG_PVE_STORAGE=''
expect_failure missing-config 69 'missing or a placeholder' driver_impl_validate_config
reset_valid_config
CFG_PVE_STORAGE=CHANGEME
expect_failure placeholder-config 69 'missing or a placeholder' driver_impl_validate_config
reset_valid_config
CFG_ARTIFACT_SHA=CHANGEME
expect_failure artifact-pin-placeholder 69 'missing or a placeholder' \
    driver_impl_validate_config
reset_valid_config
chmod 0644 "$JOIN_CREDENTIAL_PATH"
expect_failure join-source-wrong-mode 69 'mode-0600 regular non-symlink' \
    driver_impl_validate_config
reset_valid_config
CFG_PVE_HOST=pve-lab.invalid
CFG_HYPERVISOR_HOST=pve-lab.invalid
expect_failure invalid-target 69 'documentation-only .invalid' driver_impl_validate_config

reset_valid_config
driver_impl_validate_config
SCENARIO=identity-mismatch
expect_failure identity-mismatch 78 'hypervisor identity mismatch' safety_check_identity
SCENARIO=non-template
expect_failure non-template-vmid 69 'is not a template' driver_impl_template_exists
SCENARIO=wrong-storage-type
expect_failure storage-wrong-type 69 'expected zfspool' driver_impl_check_reachable

reset_valid_config
driver_impl_validate_config
outside_spec='{"id":7200,"name":"k3fd-outside","short_name":"outside","role":"server","vcpus":2,"memory_mb":4096,"disk_gb":20,"ip":"192.0.2.99","cidr":24}'
expect_failure vmid-window 78 'outside driver window' driver_impl_guest_create "$outside_spec"

GUEST_PRESENT=0
GUEST_DESCRIPTION=''
GUEST_CONFIGURED=0
TEMPLATE_DISK_GIB=3.5
GUEST_DISK_GIB=3.5
: >"$CALL_LOG"
spec='{"index":0,"id":7100,"name":"k3fd-server-1","short_name":"server-1","role":"server","vcpus":2,"memory_mb":4096,"disk_gb":20,"ip":"192.0.2.10","cidr":24}'
driver_impl_guest_create "$spec" >"$TEST_TMP/create.out"
owner=$(driver_impl_guest_owner 7100)
[[ $owner == "$FD_LAB_ID" ]]
grep -Fq "'qm' 'clone' '9000' '7100' '--name' 'k3fd-server-1' '--full' '--storage' 'labtank'" "$CALL_LOG"
grep -Fq "'qm' 'set' '7100' '--description' 'firedrill-owner:$FD_LAB_ID'" "$CALL_LOG"
[[ $(grep -Fc "'qm' 'resize' '7100' 'scsi0' '20G'" "$CALL_LOG") == 1 ]]
grep -Fq 'EVIDENCE pve-disk-resize hypervisor' "$CALL_LOG"
printf 'PASS: smaller PVE template produced exactly one absolute disk resize\n'
printf 'PASS: PVE ownership marker round-trip returned %s\n' "$owner"

GUEST_PRESENT=0
GUEST_DESCRIPTION=''
GUEST_CONFIGURED=0
TEMPLATE_DISK_GIB=30
GUEST_DISK_GIB=30
: >"$CALL_LOG"
driver_impl_guest_create "$spec" >"$TEST_TMP/create-larger.out"
if grep -Fq "'qm' 'resize'" "$CALL_LOG" \
    || grep -Fq 'EVIDENCE pve-disk-resize hypervisor' "$CALL_LOG"; then
    printf 'larger PVE template unexpectedly produced a resize mutation\n' >&2
    exit 1
fi
printf 'NEGATIVE PROBE pve-disk-resize-larger-template: no resize at or above specification\n'

attempt_status=0
attempt_sentinel='sensitive-config-sentinel'
(
    pve_guest_config_json() {
        printf '{"scsi0":"labtank:vm-disk,size=1G"}\n'
    }
    pve_config_matches_spec() {
        return 1
    }
    pve_pause() {
        :
    }
    pve_wait_config_spec "$attempt_sentinel" "$attempt_sentinel" "$attempt_sentinel" 2
) >"$TEST_TMP/attempt-counter.out" 2>"$TEST_TMP/attempt-counter.err" || attempt_status=$?
[[ $attempt_status == 70 ]]
attempt_lines=$(grep '^pve wait: attempt ' "$TEST_TMP/attempt-counter.err")
expected_attempt_lines=$(printf 'pve wait: attempt 1/2\npve wait: attempt 2/2')
if [[ $attempt_lines != "$expected_attempt_lines" \
    || $attempt_lines == *"$attempt_sentinel"* ]]; then
    printf 'PVE attempt-counter output was missing, malformed, or value-bearing\n' >&2
    printf '%s\n' "$attempt_lines" >&2
    exit 1
fi
printf 'PASS: PVE wait attempt counters contain counters and bounds only\n'

SCENARIO=disk-size-unavailable
GUEST_PRESENT=0
GUEST_DESCRIPTION=''
GUEST_CONFIGURED=0
TEMPLATE_DISK_GIB=3.5
GUEST_DISK_GIB=3.5
: >"$CALL_LOG"
expect_failure disk-size-unavailable 69 'configured OS disk size is unavailable' \
    driver_impl_guest_create "$spec"
if grep -Fq "'qm' 'resize'" "$CALL_LOG"; then
    printf 'unavailable PVE disk size unexpectedly produced a resize mutation\n' >&2
    exit 1
fi

SNAPSHOT_PRESENT=0
driver_impl_snapshot_create 7100 firedrill-baseline >/dev/null
driver_impl_snapshot_restore 7100 firedrill-baseline >/dev/null
driver_impl_snapshot_delete 7100 firedrill-baseline >/dev/null
grep -Fq "'qm' 'snapshot' '7100' 'firedrill-baseline'" "$CALL_LOG"
grep -Fq "'qm' 'rollback' '7100' 'firedrill-baseline'" "$CALL_LOG"
grep -Fq "'qm' 'delsnapshot' '7100' 'firedrill-baseline'" "$CALL_LOG"
printf 'PASS: PVE snapshot create/restore/delete call shapes and state polling verified\n'

# MEASURED SAMPLE F-A03-1 (the rollback transport stub and ordering probes
# below model PVE's behavior for a running guest and a disk-only snapshot).
# Source: Nexus EXEC_LOG_2026-09-02_P06_A0_3_ROLLBACK.md §2–§3; exact argv
# from runs/fd-20260830t151047z-370455/evidence/commands.jsonl seq 54–58.
# Exact recorded argv:
# ["--", "pve_host_exec", "qm", "rollback", "7100", "p06-baseline"]
# ["--", "pve_host_exec", "qm", "rollback", "7101", "p06-baseline"]
# ["--", "pve_host_exec", "qm", "rollback", "7102", "p06-baseline"]
# ["--", "pve_host_exec", "qm", "rollback", "7103", "p06-baseline"]
# ["--", "pve_host_exec", "qm", "rollback", "7104", "p06-baseline"]
# host: lab-hv01   date: 2026-09-02   guests were RUNNING before each command
# PVE 9.2.5, 203.0.113.40; all timestamps UTC.
# qm rollback 7100 p06-baseline    05:15:50 → 05:15:52   exit 0   stdout/stderr empty
# qm rollback 7101 p06-baseline    05:16:03 → 05:16:05   exit 0   stdout/stderr empty
# qm rollback 7102 p06-baseline    05:16:16 → 05:16:17   exit 0   stdout/stderr empty
# qm rollback 7103 p06-baseline    05:16:28 → 05:16:30   exit 0   stdout/stderr empty
# qm rollback 7104 p06-baseline    05:16:41 → 05:16:42   exit 0   stdout/stderr empty
# PVE task log: five "VM 71xx - Rollback" tasks, each ~1 s, all OK
# post-run (~05:18Z): 7100–7104  stopped  PID 0        (999, 9000 unchanged)
# qm listsnapshot ×5: firedrill-baseline → p06-baseline → current
# Observation: PVE 9.2.5 did not refuse the disk-only rollback on running guests. It stopped each guest itself, rolled the disk back, and left it stopped (qm rollback --start exists for exactly this reason).
SNAPSHOT_PRESENT=1
GUEST_STATUS=running
: >"$CALL_LOG"
expect_failure rollback-running-without-stop 69 'must be stopped before rollback' \
    driver_impl_snapshot_restore 7100 firedrill-baseline
if grep -Fq "'qm' 'rollback' '7100' 'firedrill-baseline'" "$CALL_LOG"; then
    printf 'running PVE guest reached qm rollback without a preceding stop\n' >&2
    exit 1
fi

GUEST_STATUS=running
: >"$CALL_LOG"
driver_impl_snapshot_restore_prepare 7100 firedrill-baseline >/dev/null
driver_impl_snapshot_restore 7100 firedrill-baseline >/dev/null
driver_impl_snapshot_restore_finish 7100 firedrill-baseline >/dev/null
python3 - "$CALL_LOG" <<'PY'
import sys
from pathlib import Path

lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
shutdown = next(i for i, line in enumerate(lines) if "'qm' 'shutdown' '7100'" in line)
rollback = next(
    i
    for i, line in enumerate(lines)
    if "'qm' 'rollback' '7100' 'firedrill-baseline'" in line
)
start = next(i for i, line in enumerate(lines) if "'qm' 'start' '7100'" in line)
assert shutdown < rollback < start
PY
[[ $GUEST_STATUS == running ]]
printf 'PASS: PVE restore stopped a running guest before qm rollback and started it afterwards\n'

GUEST_STATUS=stopped
: >"$CALL_LOG"
driver_impl_snapshot_restore_prepare 7100 firedrill-baseline >/dev/null
[[ $FD_PVE_LAST_STOP_MODE == already-stopped ]]
grep -Fq 'EVIDENCE pve-stop-mode hypervisor' "$CALL_LOG"
if grep -Fq "'qm' 'shutdown' '7100'" "$CALL_LOG"; then
    printf 'already-stopped PVE guest unexpectedly received qm shutdown\n' >&2
    exit 1
fi
printf 'PASS: PVE restore recorded already-stopped without issuing qm shutdown\n'

rollback_sequence_log=$TEST_TMP/rollback-sequence.log
: >"$rollback_sequence_log"
(
    state_require_lifecycle() {
        return 0
    }
    driver_load() {
        return 0
    }
    driver_preflight() {
        return 0
    }
    config_get() {
        case $1 in
            values.snapshot_name) printf 'firedrill-baseline\n' ;;
            values.cluster_capture_timeout_seconds) printf '3\n' ;;
            *) return 65 ;;
        esac
    }
    config_inventory_count() {
        printf '5\n'
    }
    config_inventory_field() {
        local index=$1 field=$2
        local -a roles=(server server server agent agent)
        case $field in
            id) printf '%s\n' "$((7100 + index))" ;;
            role) printf '%s\n' "${roles[$index]}" ;;
            *) return 65 ;;
        esac
    }
    driver_snapshot_exists() {
        printf 'EXISTS %s\n' "$1" >>"$rollback_sequence_log"
    }
    driver_snapshot_restore_prepare() {
        printf 'STOP %s\n' "$1" >>"$rollback_sequence_log"
    }
    driver_snapshot_restore() {
        printf 'ROLLBACK %s\n' "$1" >>"$rollback_sequence_log"
    }
    driver_snapshot_restore_finish() {
        printf 'START %s\n' "$1" >>"$rollback_sequence_log"
    }
    driver_guest_wait_access() {
        printf 'WAIT_ACCESS %s %s\n' "$1" "$2" >>"$rollback_sequence_log"
    }
    cluster_capture_state() {
        printf 'CAPTURE\n' >>"$rollback_sequence_log"
        printf '{}\n'
    }
    cluster_assert_healthy_file() {
        [[ -s $1 ]]
    }
    # shellcheck source=lib/commands/rollback.sh
    source "$TEST_ROOT/lib/commands/rollback.sh"
    command_rollback >/dev/null
)
python3 - "$rollback_sequence_log" <<'PY'
import sys
from pathlib import Path

events = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
expected_ids = [str(value) for value in range(7100, 7105)]
assert events[:5] == [f"EXISTS {value}" for value in expected_ids]
assert events[5:10] == [f"STOP {value}" for value in expected_ids]
assert events[10:15] == [f"ROLLBACK {value}" for value in expected_ids]
assert events[15:18] == [f"START {value}" for value in expected_ids[:3]]
assert events[18:20] == [f"START {value}" for value in expected_ids[3:]]
assert events[20:] == ["WAIT_ACCESS server-1 3", "CAPTURE"]
PY
printf 'PASS: rollback phased all stops, rollbacks, server starts, agent starts, SSH wait, and capture\n'

SCENARIO=stop-escalation
GUEST_STATUS=running
driver_impl_guest_stop 7100 2 >/dev/null
[[ $FD_PVE_LAST_STOP_MODE == forced-stop-after-shutdown-timeout ]]
grep -Fq 'EVIDENCE pve-force-stop-after-timeout hypervisor' "$CALL_LOG"
grep -Fq 'EVIDENCE pve-stop-mode hypervisor' "$CALL_LOG"
printf 'PASS: PVE shutdown timeout escalated to qm stop and recorded forced mode\n'

SCENARIO=resize-failure
GUEST_PRESENT=0
GUEST_DESCRIPTION=''
GUEST_CONFIGURED=0
TEMPLATE_DISK_GIB=3.5
GUEST_DISK_GIB=3.5
: >"$CALL_LOG"
resize_status=0
(
    pve_wait_config_spec() {
        printf 'WAIT_CONFIG_REACHED\n' >>"$CALL_LOG"
        return 0
    }
    driver_impl_guest_create "$spec"
) >"$TEST_TMP/resize-failure.out" 2>"$TEST_TMP/resize-failure.err" || resize_status=$?
if ((resize_status != 73)) || grep -Fq 'WAIT_CONFIG_REACHED' "$CALL_LOG"; then
    printf 'failing PVE resize did not abort create before config convergence (exit=%s)\n' \
        "$resize_status" >&2
    cat "$TEST_TMP/resize-failure.out" "$TEST_TMP/resize-failure.err" >&2
    exit 1
fi
[[ $(grep -Fc "'qm' 'resize' '7100' 'scsi0' '20G'" "$CALL_LOG") == 1 ]]
printf 'NEGATIVE PROBE pve-disk-resize-failure: expected failure exit=%s before config wait\n' \
    "$resize_status"

node_calls=$TEST_TMP/node-handoff-calls.log
node_runtime_capture=$TEST_TMP/node-runtime.env
node_join_before_remove=$TEST_TMP/node-join-before-remove.env
node_join_live=$TEST_TMP/node-join-live.env
: >"$node_calls"
(
    driver_guest_put() {
        local node=$1 source=$2 destination=$3
        printf 'PUT <%s> <%s>\n' "$node" "$destination" >>"$node_calls"
        case $destination in
            /etc/firedrill/op.env) cp "$source" "$node_runtime_capture" ;;
            /etc/firedrill/join.env)
                cp "$source" "$node_join_before_remove"
                cp "$source" "$node_join_live"
                ;;
            *) return 69 ;;
        esac
    }
    driver_guest_exec() {
        local argument install_seen=false remove_seen=false
        printf 'EXEC' >>"$node_calls"
        for argument in "$@"; do
            printf ' <%s>' "$argument" >>"$node_calls"
            [[ $argument != install-k3s ]] || install_seen=true
            [[ $argument != /etc/firedrill/join.env ]] || remove_seen=true
        done
        printf '\n' >>"$node_calls"
        if [[ ${NODE_INSTALL_FAIL:-false} == true && $install_seen == true ]]; then
            return 73
        fi
        if [[ $remove_seen == true ]]; then
            rm -f -- "$node_join_live"
        fi
    }
    node_install_k3s server-1 server-cluster-init
)
grep -Fq 'server_endpoint=https://192.0.2.10:6443' "$node_join_before_remove"
grep -Fq "join_credential=$TEST_A_OLD_TOKEN" "$node_join_before_remove"
grep -Fq 'node_name=server-1' "$node_runtime_capture"
grep -Fq 'cluster_node_roles=server-1:server,server-2:server,server-3:server,agent-1:agent,agent-2:agent' \
    "$node_runtime_capture"
grep -Fq '<firedrill-op> <install-k3s> <server-cluster-init> <v1.34.4+k3s1>' \
    "$node_calls"
grep -Fq '<rm> <-f> <--> </etc/firedrill/join.env>' "$node_calls"
[[ ! -e $node_join_live ]]
if grep -Fq "$TEST_A_OLD_TOKEN" "$node_calls" \
    || grep -Fq 'https://192.0.2.10:6443' "$node_calls"; then
    printf 'PVE node handoff leaked a credential or endpoint into command arguments\n' >&2
    exit 1
fi
printf 'PASS: PVE node install handed off endpoint and token only in root-file payloads\n'

: >"$node_calls"
node_failure_status=0
(
    NODE_INSTALL_FAIL=true
    driver_guest_put() {
        local source=$2 destination=$3
        if [[ $destination == /etc/firedrill/join.env ]]; then
            cp "$source" "$node_join_live"
        fi
    }
    driver_guest_exec() {
        local argument
        for argument in "$@"; do
            printf '<%s>' "$argument" >>"$node_calls"
            if [[ $argument == install-k3s ]]; then
                return 73
            fi
        done
    }
    node_install_k3s server-1 server-cluster-init
) || node_failure_status=$?
[[ $node_failure_status == 73 && -e $node_join_live ]]
if grep -Fq '<rm>' "$node_calls"; then
    printf 'failed PVE install unexpectedly attempted join-file removal\n' >&2
    exit 1
fi
printf 'NEGATIVE PROBE pve-join-retained-on-install-failure: expected failure exit=73\n'

guest_put_source=$TEST_TMP/guest-put-source
printf 'non-secret payload\n' >"$guest_put_source"
: >"$CALL_LOG"
driver_impl_guest_put server-1 "$guest_put_source" /etc/firedrill/test-file
grep -Fq 'chmod 0600' "$CALL_LOG"
grep -Fq 'chown 0:0' "$CALL_LOG"
printf 'PASS: PVE guest_put enforces mode 0600 and uid/gid 0 after every write\n'

reset_test_a_state() {
    SCENARIO=normal
    printf '%s\n' "$TEST_A_OLD_TOKEN" >"$CLUSTER_TOKEN_FILE"
    : >"$CALL_LOG"
    : >"$TEST_A_SERVER_ENV_EDIT_LOG"
    : >"$TEST_A_SERVER_ENV_COMMAND_LOG"
    : >"$TEST_A_SERVER_RESTART_LOG"
    driver_impl_init
}

reset_test_a_state
SCENARIO=test-a-token-read-failure
expect_failure test-a-token-read-propagation 73 'injected Test A token read failure' \
    driver_impl_test_a_read_server_token
expect_failure test-a-propose-token-read-failure 73 'injected Test A token read failure' \
    driver_impl_test_a_propose_server_token

SCENARIO=normal
old_token_output=$(driver_impl_test_a_read_server_token)
new_token_output=$(driver_impl_test_a_propose_server_token)
old_token_prefix=${old_token_output%:*}:
new_token_prefix=${new_token_output%:*}:
old_token_secret=${old_token_output##*:}
new_token_secret=${new_token_output##*:}
[[ $old_token_output == "$TEST_A_OLD_TOKEN" ]]
[[ $new_token_output =~ ^K10[a-f0-9]{64}::server:[a-f0-9]{48}$ ]]
[[ $new_token_prefix == "$old_token_prefix" ]]
[[ $new_token_secret != "$old_token_secret" ]]
if grep -Fq "$new_token_output" "$CALL_LOG"; then
    printf 'PVE Test A proposal exposed the raw token in the transport call log\n' >&2
    exit 1
fi
printf 'PASS: PVE Test A proposal preserves the CA hash and user part and mints a fresh 48-hex secret (runbook 1.5)\n'

if grep -Fq "'token' 'generate'" "$CALL_LOG"; then
    printf 'PVE Test A proposal unexpectedly invoked k3s token generate\n' >&2
    exit 1
fi
printf 'PASS: PVE Test A proposal never invokes k3s token generate\n'

# MEASURED SAMPLE F-TA-1 (the bootstrap-shaped fixture below models the
# actual output class rejected by the full-server-token guard).
# Source: Nexus EXEC_LOG_2026-09-02_P06_TEST_A_FIRST_CONTACT.md §1.
# Command (RECONSTRUCTED from the recorded probe): /usr/local/bin/k3s token generate
# host: server-1 (198.51.100.10)   date: 2026-09-02   probe: k3s token generate (output piped to length/shape checks)
# rc=0  len=23  k10_server_full=0  dots=1
# Command (RECONSTRUCTED): /usr/local/bin/k3s token --help
# k3s token --help: describes the generated value as a "bootstrap token"
# Observation: 23 characters, one dot, no K10<ca>::server: prefix → not a server token; runbook §1.5 forbids using it for rotation.
printf 'abcdef.0123456789abcdef\n' >"$CLUSTER_TOKEN_FILE"
expect_failure test-a-propose-from-malformed-current 69 'is not one full server token' \
    driver_impl_test_a_propose_server_token
[[ ! -s $TEST_TMP/test-a-propose-from-malformed-current.out ]]

test_a_same_secret_python() {
    printf '%s\n' "$TEST_A_COLLISION_SECRET"
}
TEST_A_COLLISION_SECRET=$(printf 'a%.0s' {1..48})
printf 'K10%s::server:%s\n' \
    "$TOKEN_CA_OLD" "$TEST_A_COLLISION_SECRET" >"$CLUSTER_TOKEN_FILE"
FD_PYTHON=test_a_same_secret_python
expect_failure test-a-propose-same-token 69 \
    'proposed server token equals the current token' \
    driver_impl_test_a_propose_server_token
FD_PYTHON=python3
reset_test_a_state

expect_failure test-a-snapshot-invalid-token 69 'is not one full server token' \
    driver_impl_test_a_snapshot_pair server-1 7100 not-a-token
expect_failure test-a-snapshot-stale-token 69 'snapshot token is not current' \
    driver_impl_test_a_snapshot_pair server-1 7100 "$TEST_A_NEW_TOKEN"
SCENARIO=test-a-snapshot-failure
expect_failure test-a-snapshot-failure-propagation 73 'injected Test A snapshot failure' \
    driver_impl_test_a_snapshot_pair server-1 7100 "$TEST_A_OLD_TOKEN"
SCENARIO=normal
for node_spec in server-1:7100 server-2:7101 server-3:7102; do
    node_name=${node_spec%%:*}
    node_guest_id=${node_spec#*:}
    driver_impl_test_a_snapshot_pair \
        "$node_name" "$node_guest_id" "$TEST_A_OLD_TOKEN" \
        >"$TEST_TMP/test-a-snapshot-$node_name.json"
done
[[ $(grep -Fc 'EVIDENCE test-a-snapshot-pair' "$CALL_LOG") == 5 ]]
python3 - "$TEST_TMP/test-a-snapshot-server-1.json" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert set(value) == {"node", "path", "snapshot_sha256", "server_token_reference"}
assert value["node"] == "server-1"
assert len(value["snapshot_sha256"]) == 64
assert value["server_token_reference"].startswith("<redacted-token ")
PY
expect_failure test-a-snapshot-duplicate 69 'duplicate or post-rotation' \
    driver_impl_test_a_snapshot_pair server-1 7100 "$TEST_A_OLD_TOKEN"

expect_failure test-a-rotate-order 69 'restart order contains a non-server' \
    driver_impl_test_a_rotate_server_token \
        "$TEST_A_NEW_TOKEN" server-1,server-2,agent-1
expect_failure test-a-rotate-same-token 69 'proposed server token equals the current token' \
    driver_impl_test_a_rotate_server_token \
        "$TEST_A_OLD_TOKEN" server-1,server-2,server-3
SCENARIO=test-a-rotate-failure
expect_failure test-a-rotate-failure-propagation 73 'injected Test A rotation failure' \
    driver_impl_test_a_rotate_server_token \
        "$TEST_A_NEW_TOKEN" server-1,server-2,server-3
SCENARIO=normal
driver_impl_test_a_rotate_server_token \
    "$TEST_A_NEW_TOKEN" server-2,server-3,server-1 \
    >"$TEST_TMP/test-a-rotate.json"
python3 - "$TEST_TMP/test-a-rotate.json" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert value["event"] == "server-token-rotated"
assert value["configured_server_restart_order"] == ["server-2", "server-3", "server-1"]
assert len(value["bootstrap_keys"]) == 1
assert value["server_token_reference"].startswith("<redacted-token ")
PY
expect_failure test-a-rotate-twice 69 'already performed its one rotation' \
    driver_impl_test_a_rotate_server_token \
        "$TEST_A_NEW_TOKEN" server-1,server-2,server-3

expect_failure test-a-restart-order 69 'restart order expected server-2' \
    driver_impl_test_a_restart_node server-1 7100 3
old_full_token_digest=$(printf '%s' "$TEST_A_OLD_TOKEN" | pve_test_a_token_digest)
server_two_token_digest=$(pve_test_a_server_token_digest 192.0.2.11)
[[ $server_two_token_digest == "$old_full_token_digest" ]]
for node_spec in server-2:7101 server-3:7102 server-1:7100 agent-1:7103 agent-2:7104; do
    node_name=${node_spec%%:*}
    node_guest_id=${node_spec#*:}
    driver_impl_test_a_restart_node "$node_name" "$node_guest_id" 3 \
        >"$TEST_TMP/test-a-restart-$node_name.json"
done
[[ $(grep -Fc 'EVIDENCE test-a-node-restart' "$CALL_LOG") == 5 ]]
grep -Fq "'systemctl' 'restart' 'k3s-agent'" "$CALL_LOG"
grep -Fq "'FIREDRILL_OP_WAIT_TIMEOUT_SECONDS=3' 'firedrill-op' 'wait-ready'" "$CALL_LOG"
[[ $(grep -Fc "$FD_PVE_K3S_SERVER_ENV" "$TEST_A_SERVER_ENV_COMMAND_LOG") == 3 ]]
# The dollar expressions are literal remote-script text.
# shellcheck disable=SC2016
[[ $(grep -Fc 'printf "K3S_TOKEN=%s\\n" "$token" >>"$tmp"' \
    "$TEST_A_SERVER_ENV_COMMAND_LOG") == 3 ]]
# shellcheck disable=SC2016
grep -Fq '[ "$found" -eq 1 ] || exit 69' "$TEST_A_SERVER_ENV_COMMAND_LOG"
if grep -Fq "$FD_PVE_K3S_SERVER_TOKEN" "$TEST_A_SERVER_ENV_COMMAND_LOG"; then
    printf 'PVE Test A server env edit directly referenced server/token\n' >&2
    exit 1
fi
grep -Fqx '192.0.2.11' "$TEST_A_SERVER_ENV_EDIT_LOG"
grep -Fqx '192.0.2.11' "$TEST_A_SERVER_RESTART_LOG"
printf 'PASS: PVE Test A server restart edits K3S_TOKEN in the server env file and verifies server/token regenerated\n'

test_a_invalid_server_env_token_counts() {
    local fixture=$TEST_TMP/test-a-server-env-count script
    local status_zero=0 status_two=0
    script=$(pve_test_a_env_edit_script)
    printf 'K3S_URL=https://192.0.2.10:6443\n' >"$fixture"
    printf '%s\n' "$TEST_A_NEW_TOKEN" \
        | sh -c "$script" sh "$fixture" || status_zero=$?
    printf 'K3S_TOKEN=first\nK3S_TOKEN=second\n' >"$fixture"
    printf '%s\n' "$TEST_A_NEW_TOKEN" \
        | sh -c "$script" sh "$fixture" || status_two=$?
    if ((status_zero != 69 || status_two != 69)); then
        printf 'server env count fixture returned zero=%s two=%s; expected 69/69\n' \
            "$status_zero" "$status_two" >&2
        return 1
    fi
    printf 'server env editor rejected zero and two K3S_TOKEN lines\n' >&2
    return 69
}
expect_failure test-a-server-env-token-count 69 \
    'rejected zero and two K3S_TOKEN lines' \
    test_a_invalid_server_env_token_counts

driver_impl_test_a_observe_gate >"$TEST_TMP/test-a-observe.json"
python3 - "$TEST_TMP/test-a-observe.json" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert value["event"] == "test-a-gate-observation"
assert len(value["nodes"]) == 5
assert len(value["etcd_members"]) == 3
assert len(value["restart_events"]) == 5
assert set(value["server_journals"]) == {"server-1", "server-2", "server-3"}
assert set(value["snapshot_pairs"]) == {"server-1", "server-2", "server-3"}
assert value["server_token_reference"].startswith("<redacted-token ")
PY
printf 'PASS: all six PVE Test A hooks emitted the mock-contract shapes through stubbed transport\n'

if grep -Fq "$TEST_A_OLD_TOKEN" "$CALL_LOG" \
    || grep -Fq "$TEST_A_NEW_TOKEN" "$CALL_LOG" \
    || grep -Fq "$TEST_A_OLD_TOKEN" "$TEST_TMP"/test-a-*.json \
    || grep -Fq "$TEST_A_NEW_TOKEN" "$TEST_TMP"/test-a-*.json; then
    printf 'PVE Test A command or evidence-shaped output exposed a raw token\n' >&2
    exit 1
fi
printf 'PASS: PVE Test A command shapes and evidence-shaped outputs contain no raw token\n'

reset_test_a_state
FD_PVE_TEST_A_ROTATED=true
FD_PVE_TEST_A_NEW_TOKEN=$TEST_A_NEW_TOKEN
FD_PVE_TEST_A_RESTART_ORDER_CSV=server-2,server-3,server-1
SCENARIO=test-a-server-token-not-regenerated
expect_failure test-a-server-token-not-regenerated 69 \
    'server token did not regenerate from the configured credential' \
    driver_impl_test_a_restart_node server-2 7101 3

reset_test_a_state
expect_failure test-a-restart-before-rotation 69 'before successful rotation' \
    driver_impl_test_a_restart_node server-1 7100 3
expect_failure test-a-observe-before-restarts 69 'requires five completed restarts' \
    driver_impl_test_a_observe_gate

FD_PVE_TEST_A_ROTATED=true
FD_PVE_TEST_A_NEW_TOKEN=$TEST_A_NEW_TOKEN
FD_PVE_TEST_A_RESTART_ORDER_CSV=server-1,server-2,server-3
printf '%s\n' "$TEST_A_NEW_TOKEN" >"$CLUSTER_TOKEN_FILE"
SCENARIO=test-a-wait-timeout
expect_failure test-a-bounded-restart-timeout 70 '"status":"timeout"' \
    driver_impl_test_a_restart_node server-1 7100 3
SCENARIO=test-a-restart-failure
FD_PVE_TEST_A_RESTART_EVENTS=()
expect_failure test-a-restart-failure-propagation 73 'injected Test A restart failure' \
    driver_impl_test_a_restart_node server-1 7100 3
SCENARIO=test-a-observe-failure
FD_PVE_TEST_A_RESTART_EVENTS=(one two three four five)
expect_failure test-a-observe-failure-propagation 73 'injected Test A observation failure' \
    driver_impl_test_a_observe_gate

unreviewed_hooks=(
    driver_impl_test_b_read_server_token
    driver_impl_test_b_propose_server_token
    driver_impl_test_b_setup
    driver_impl_test_b_break
    driver_impl_test_b_recover
    driver_impl_test_b_observe_gate
    driver_impl_test_c_read_server_token
    driver_impl_test_c_propose_server_token
    driver_impl_test_c_setup
    driver_impl_test_c_break
    driver_impl_test_c_triage
    driver_impl_test_c_recover
    driver_impl_test_c_finish
    driver_impl_test_c_observe_gate
    driver_impl_test_c_observe_runtime_token
)
for hook in "${unreviewed_hooks[@]}"; do
    expect_failure "$hook" 69 'real test hooks not yet reviewed' "$hook"
done

pve_config=$TEST_TMP/pve-test-b.conf
sed \
    -e 's/^driver=mock$/driver=pve/' \
    -e 's/^hypervisor_host=mock-hypervisor.invalid$/hypervisor_host=pve-lab.example/' \
    -e 's/^expected_hypervisor_hostname=mock-hypervisor$/expected_hypervisor_hostname=pve-lab/' \
    -e 's/^pve_host=CHANGEME$/pve_host=pve-lab.example/' \
    -e 's/^pve_node=CHANGEME$/pve_node=pve-lab/' \
    -e 's/^pve_storage=CHANGEME$/pve_storage=labtank/' \
    -e 's/^template_vmid=CHANGEME$/template_vmid=9000/' \
    -e 's/^pve_privilege_mode=CHANGEME$/pve_privilege_mode=direct/' \
    -e 's/^pve_cloud_init_user=CHANGEME$/pve_cloud_init_user=ubuntu/' \
    -e 's|^pve_cloud_init_sshkeys_path=CHANGEME$|pve_cloud_init_sshkeys_path=/root/.ssh/firedrill.pub|' \
    -e 's/^pve_net_model=CHANGEME$/pve_net_model=virtio/' \
    -e 's/^pve_net_device=CHANGEME$/pve_net_device=net0/' \
    -e 's/^pve_ipconfig_device=CHANGEME$/pve_ipconfig_device=ipconfig0/' \
    -e 's/^pve_os_disk=CHANGEME$/pve_os_disk=scsi0/' \
    -e 's/^pve_guest_agent=CHANGEME$/pve_guest_agent=enabled/' \
    -e "s|^ssh_known_hosts_path=CHANGEME$|ssh_known_hosts_path=$KNOWN_HOSTS_PATH|" \
    -e 's/^guest_ssh_user=CHANGEME$/guest_ssh_user=ubuntu/' \
    -e "s|^guest_ssh_key_path=CHANGEME$|guest_ssh_key_path=$GUEST_KEY_PATH|" \
    -e "s|^guest_ssh_known_hosts_path=CHANGEME$|guest_ssh_known_hosts_path=$GUEST_KNOWN_HOSTS_PATH|" \
    -e 's/^guest_privilege_mode=CHANGEME$/guest_privilege_mode=direct/' \
    -e "s|^k3s_join_credential_file=CHANGEME$|k3s_join_credential_file=$JOIN_CREDENTIAL_PATH|" \
    -e "s/^k3s_binary_sha256=CHANGEME$/k3s_binary_sha256=$CFG_ARTIFACT_SHA/" \
    -e "s/^k3s_install_script_sha256=CHANGEME$/k3s_install_script_sha256=$CFG_INSTALL_SHA/" \
    -e "s/^etcdctl_sha256=CHANGEME$/etcdctl_sha256=$CFG_ETCDCTL_SHA/" \
    -e 's/^ssh_user=CHANGEME$/ssh_user=root/' \
    -e "s|^ssh_key_path=CHANGEME$|ssh_key_path=$KEY_PATH|" \
    -e 's/^network_bridge=vmbr-lab$/network_bridge=vmbr1/' \
    -e "s|run_dir=./runs|run_dir=$TEST_TMP/pve-runs|" \
    "$TEST_ROOT/firedrill.conf.example" >"$pve_config"

status=0
"$TEST_ROOT/firedrill" --config "$pve_config" test-b \
    >"$TEST_TMP/pve-test-b.out" 2>"$TEST_TMP/pve-test-b.err" || status=$?
if ((status != 69)) || ! grep -q 'real test hooks not yet reviewed for driver pve' \
    "$TEST_TMP/pve-test-b.err"; then
    printf 'PVE test-b fail-closed probe failed (exit=%s)\n' "$status" >&2
    cat "$TEST_TMP/pve-test-b.out" "$TEST_TMP/pve-test-b.err" >&2
    exit 1
fi
[[ ! -e $TEST_TMP/pve-runs/current.json ]]
printf 'NEGATIVE PROBE pve-test-b-real-driver: expected failure exit=69 before state or network\n'
cat "$TEST_TMP/pve-test-b.err"

fake_bin=$TEST_TMP/fake-bin
fake_ssh_log=$TEST_TMP/fake-ssh.log
mkdir -p "$fake_bin"
# The single-quoted strings are the literal body of the generated SSH stub.
# shellcheck disable=SC2016
printf '%s\n' \
    '#!/usr/bin/env bash' \
    'set -Eeuo pipefail' \
    'remote=${!#}' \
    'printf "%s\n" "$remote" >>"${FIREDRILL_FAKE_SSH_LOG:?}"' \
    'case $remote in' \
    '  *"hostname"*) printf "pve-lab\n" ;;' \
    '  *"/version"*) printf "{\"version\":\"9.2.5\"}\n" ;;' \
    '  *"/storage/labtank"*) printf "{\"type\":\"zfspool\"}\n" ;;' \
    '  *"/network/vmbr1"*) printf "{\"type\":\"bridge\"}\n" ;;' \
    '  *"/qemu/9000/config"*) printf "{\"template\":1,\"scsi0\":\"labtank:base,size=4G\"}\n" ;;' \
    '  *"true"*|*"test"*) : ;;' \
    '  *) printf "unexpected fake ssh command: %s\n" "$remote" >&2; exit 69 ;;' \
    'esac' >"$fake_bin/ssh"
chmod 0755 "$fake_bin/ssh"
: >"$fake_ssh_log"

status=0
FIREDRILL_FAKE_SSH_LOG="$fake_ssh_log" PATH="$fake_bin:$PATH" \
    "$TEST_ROOT/firedrill" --config "$pve_config" test-c \
    >"$TEST_TMP/pve-test-c.out" 2>"$TEST_TMP/pve-test-c.err" || status=$?
if ((status != 69)) || ! grep -Fq 'real test hooks not yet reviewed' \
    "$TEST_TMP/pve-test-c.err" || [[ -s $fake_ssh_log ]]; then
    printf 'PVE test-c fail-closed probe failed (exit=%s)\n' "$status" >&2
    sed -n '1,120p' "$TEST_TMP/pve-test-c.out" "$TEST_TMP/pve-test-c.err" >&2
    exit 1
fi
printf 'NEGATIVE PROBE pve-test-c-real-driver: expected failure exit=69 before transport\n'
sed -n '1,120p' "$TEST_TMP/pve-test-c.err"

: >"$fake_ssh_log"
status=0
FIREDRILL_FAKE_SSH_LOG="$fake_ssh_log" PATH="$fake_bin:$PATH" \
    "$TEST_ROOT/firedrill" --config "$pve_config" test-a \
    >"$TEST_TMP/pve-test-a-command.out" 2>"$TEST_TMP/pve-test-a-command.err" || status=$?
if ((status != 66)) || grep -Fq 'real test hooks not yet reviewed' \
    "$TEST_TMP/pve-test-a-command.err" || [[ ! -s $fake_ssh_log ]]; then
    printf 'PVE test-a implemented-hook gate probe failed (exit=%s)\n' "$status" >&2
    sed -n '1,160p' \
        "$TEST_TMP/pve-test-a-command.out" "$TEST_TMP/pve-test-a-command.err" >&2
    exit 1
fi
printf 'NEGATIVE PROBE pve-test-a-no-baseline: expected state failure exit=66 after preflight transport\n'
sed -n '1,120p' "$TEST_TMP/pve-test-a-command.err"

printf 'PASS: PVE driver transport-stub suite completed without network access\n'
