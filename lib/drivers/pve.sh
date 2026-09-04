#!/usr/bin/env bash
# PVE ownership is one exact VM description line: firedrill-owner:<active lab_id>.
# Creation writes that marker immediately after a successful full clone. Reads
# parse the live PVE config verbatim; names, tags, and local state never imply
# ownership. All SSH traffic passes through pve_transport_ssh so offline tests
# can replace one function without opening a socket.
# Configuration-only globals are consumed through an indirect validation loop.
# shellcheck disable=SC2016,SC2034,SC2329

driver_impl_init() {
    FD_PVE_LAST_STOP_MODE=not-requested
    FD_PVE_TEST_A_ROTATED=false
    FD_PVE_TEST_A_NEW_TOKEN=
    FD_PVE_TEST_A_RESTART_ORDER_CSV=
    FD_PVE_TEST_A_SNAPSHOT_NODES=()
    FD_PVE_TEST_A_SNAPSHOT_PAIRS=()
    FD_PVE_TEST_A_RESTART_EVENTS=()
}

pve_load_config() {
    FD_PVE_HOST=$(config_get values.pve_host) || return $?
    FD_PVE_NODE=$(config_get values.pve_node) || return $?
    FD_PVE_STORAGE=$(config_get values.pve_storage) || return $?
    FD_PVE_TEMPLATE_VMID=$(config_get values.template_vmid) || return $?
    FD_PVE_SSH_USER=$(config_get values.ssh_user) || return $?
    FD_PVE_SSH_KEY=$(config_get values.ssh_key_path) || return $?
    FD_PVE_KNOWN_HOSTS=$(config_get values.ssh_known_hosts_path) || return $?
    FD_PVE_PRIVILEGE_MODE=$(config_get values.pve_privilege_mode) || return $?
    FD_PVE_CLONE_MODE=$(config_get values.pve_clone_mode) || return $?
    FD_PVE_CI_USER=$(config_get values.pve_cloud_init_user) || return $?
    FD_PVE_CI_SSHKEYS=$(config_get values.pve_cloud_init_sshkeys_path) || return $?
    FD_PVE_NET_MODEL=$(config_get values.pve_net_model) || return $?
    FD_PVE_NET_DEVICE=$(config_get values.pve_net_device) || return $?
    FD_PVE_IPCONFIG_DEVICE=$(config_get values.pve_ipconfig_device) || return $?
    FD_PVE_OS_DISK=$(config_get values.pve_os_disk) || return $?
    FD_PVE_GUEST_AGENT=$(config_get values.pve_guest_agent) || return $?
    FD_PVE_GUEST_SSH_USER=$(config_get values.guest_ssh_user) || return $?
    FD_PVE_GUEST_SSH_KEY=$(config_get values.guest_ssh_key_path) || return $?
    FD_PVE_GUEST_KNOWN_HOSTS=$(config_get values.guest_ssh_known_hosts_path) || return $?
    FD_PVE_GUEST_PRIVILEGE_MODE=$(config_get values.guest_privilege_mode) || return $?
    FD_PVE_CONNECT_TIMEOUT=$(config_get values.ssh_connect_timeout_seconds) || return $?
    FD_PVE_OPERATION_TIMEOUT=$(config_get values.pve_operation_timeout_seconds) || return $?
    FD_PVE_CLUSTER_CAPTURE_TIMEOUT=$(
        config_get values.cluster_capture_timeout_seconds
    ) || return $?
    FD_PVE_OP_CONFIG_PATH=$(config_get values.firedrill_op_config_path) || return $?
    FD_PVE_JOIN_PATH=$(config_get values.guest_join_file) || return $?
    FD_PVE_JOIN_CREDENTIAL_FILE=$(config_get values.k3s_join_credential_file) || return $?
    FD_PVE_K3S_BINARY_ARTIFACT=$(config_get values.k3s_binary_artifact_path) || return $?
    FD_PVE_K3S_BINARY_SHA256=$(config_get values.k3s_binary_sha256) || return $?
    FD_PVE_INSTALL_SCRIPT_ARTIFACT=$(
        config_get values.k3s_install_script_artifact_path
    ) || return $?
    FD_PVE_INSTALL_SCRIPT_SHA256=$(config_get values.k3s_install_script_sha256) || return $?
    FD_PVE_ETCDCTL_ARTIFACT=$(config_get values.etcdctl_artifact_path) || return $?
    FD_PVE_ETCDCTL_SHA256=$(config_get values.etcdctl_sha256) || return $?
    FD_PVE_K3S_BINARY=$(config_get values.k3s_installed_binary_path) || return $?
    FD_PVE_KUBECONFIG=$(config_get values.k3s_kubeconfig_path) || return $?
    FD_PVE_AGENT_KUBECONFIG=$(config_get values.k3s_agent_kubeconfig_path) || return $?
    FD_PVE_K3S_SERVER_TOKEN=$(config_get values.k3s_server_token_path) || return $?
    FD_PVE_K3S_SERVER_ENV=$(config_get values.k3s_server_service_env_path) || return $?
    FD_PVE_K3S_AGENT_ENV=$(config_get values.k3s_agent_service_env_path) || return $?
    FD_PVE_K3S_SERVER_UNIT=$(config_get values.k3s_server_systemd_unit) || return $?
    FD_PVE_K3S_AGENT_UNIT=$(config_get values.k3s_agent_systemd_unit) || return $?
    FD_PVE_ETCD_SNAPSHOT_DIR=$(config_get values.k3s_etcd_snapshot_dir) || return $?
    FD_PVE_TEST_A_JOURNAL_LIMIT=$(config_get values.test_a_journal_line_limit) || return $?
    FD_PVE_EXPECTED_HOSTNAME=$(config_get values.expected_hypervisor_hostname) || return $?
    FD_PVE_HYPERVISOR_HOST=$(config_get values.hypervisor_host) || return $?
    FD_PVE_BRIDGE=$(config_get values.network_bridge) || return $?
    FD_PVE_GATEWAY=$(config_get values.gateway) || return $?
    FD_PVE_ALLOWED_MIN=$(config_get allowed_id_min) || return $?
    FD_PVE_ALLOWED_MAX=$(config_get allowed_id_max) || return $?
}

pve_ensure_config() {
    if [[ -z ${FD_PVE_HOST:-} ]]; then
        pve_load_config
    fi
}

pve_reject_placeholder() {
    local key=$1
    local value=$2
    case $value in
        ''|CHANGEME|changeme|REPLACE_ME|replace_me|TODO|todo|UNSET|unset)
            printf 'pve configuration error: %s is missing or a placeholder\n' "$key" >&2
            return 69
            ;;
    esac
    if [[ $value == *'<'* || $value == *'>'* ]]; then
        printf 'pve configuration error: %s contains placeholder syntax\n' "$key" >&2
        return 69
    fi
}

pve_positive_integer() {
    local key=$1
    local value=$2
    if [[ ! $value =~ ^[0-9]+$ ]] || ((value < 1)); then
        printf 'pve configuration error: %s must be a positive integer\n' "$key" >&2
        return 69
    fi
}

driver_impl_validate_config() {
    local key value
    case ${command:-} in
        test-c)
            printf 'pve driver is not implemented for real failure-test hooks; real test hooks not yet reviewed\n' >&2
            return 69
            ;;
    esac
    pve_load_config || return $?
    for key in \
        FD_PVE_HOST FD_PVE_NODE FD_PVE_STORAGE FD_PVE_TEMPLATE_VMID \
        FD_PVE_SSH_USER FD_PVE_SSH_KEY FD_PVE_KNOWN_HOSTS FD_PVE_PRIVILEGE_MODE \
        FD_PVE_CLONE_MODE FD_PVE_CI_USER FD_PVE_CI_SSHKEYS FD_PVE_NET_MODEL \
        FD_PVE_NET_DEVICE FD_PVE_IPCONFIG_DEVICE FD_PVE_OS_DISK \
        FD_PVE_GUEST_AGENT FD_PVE_GUEST_SSH_USER FD_PVE_GUEST_SSH_KEY \
        FD_PVE_GUEST_KNOWN_HOSTS FD_PVE_GUEST_PRIVILEGE_MODE \
        FD_PVE_CONNECT_TIMEOUT FD_PVE_OPERATION_TIMEOUT \
        FD_PVE_CLUSTER_CAPTURE_TIMEOUT FD_PVE_OP_CONFIG_PATH \
        FD_PVE_JOIN_PATH FD_PVE_JOIN_CREDENTIAL_FILE \
        FD_PVE_K3S_BINARY_ARTIFACT FD_PVE_K3S_BINARY_SHA256 \
        FD_PVE_INSTALL_SCRIPT_ARTIFACT FD_PVE_INSTALL_SCRIPT_SHA256 \
        FD_PVE_ETCDCTL_ARTIFACT FD_PVE_ETCDCTL_SHA256 FD_PVE_K3S_BINARY \
        FD_PVE_KUBECONFIG FD_PVE_AGENT_KUBECONFIG \
        FD_PVE_K3S_SERVER_TOKEN FD_PVE_K3S_SERVER_ENV FD_PVE_K3S_AGENT_ENV \
        FD_PVE_K3S_SERVER_UNIT FD_PVE_K3S_AGENT_UNIT FD_PVE_ETCD_SNAPSHOT_DIR \
        FD_PVE_TEST_A_JOURNAL_LIMIT; do
        value=${!key}
        pve_reject_placeholder "$key" "$value" || return $?
    done
    if [[ $FD_PVE_HOST == *.invalid || $FD_PVE_HYPERVISOR_HOST == *.invalid ]]; then
        printf 'pve configuration error: target uses the documentation-only .invalid domain\n' >&2
        return 69
    fi
    if [[ $FD_PVE_HOST != "$FD_PVE_HYPERVISOR_HOST" ]]; then
        printf 'pve configuration error: pve_host must exactly match hypervisor_host\n' >&2
        return 69
    fi
    if [[ $FD_PVE_NODE != "$FD_PVE_EXPECTED_HOSTNAME" ]]; then
        printf 'pve configuration error: pve_node must exactly match expected hostname\n' >&2
        return 69
    fi
    if [[ $FD_PVE_CLONE_MODE != full ]]; then
        printf 'pve configuration error: only the reviewed full clone mode is enabled\n' >&2
        return 69
    fi
    for value in "$FD_PVE_PRIVILEGE_MODE" "$FD_PVE_GUEST_PRIVILEGE_MODE"; do
        case $value in
            direct|sudo-n|doas-n) ;;
            *)
                printf 'pve configuration error: privilege mode %q is unsupported\n' "$value" >&2
                return 69
                ;;
        esac
    done
    if [[ ! $FD_PVE_STORAGE =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
        printf 'pve configuration error: pve_storage contains unsafe characters\n' >&2
        return 69
    fi
    if [[ ! $FD_PVE_NET_MODEL =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
        printf 'pve configuration error: pve_net_model contains unsafe characters\n' >&2
        return 69
    fi
    if [[ ! $FD_PVE_NET_DEVICE =~ ^net[0-9]+$ ]]; then
        printf 'pve configuration error: pve_net_device must be netN\n' >&2
        return 69
    fi
    if [[ ! $FD_PVE_IPCONFIG_DEVICE =~ ^ipconfig[0-9]+$ ]]; then
        printf 'pve configuration error: pve_ipconfig_device must be ipconfigN\n' >&2
        return 69
    fi
    if [[ ! $FD_PVE_OS_DISK =~ ^(ide|sata|scsi|virtio)[0-9]+$ ]]; then
        printf 'pve configuration error: pve_os_disk has an unsupported device shape\n' >&2
        return 69
    fi
    case $FD_PVE_GUEST_AGENT in
        enabled|disabled) ;;
        *)
            printf 'pve configuration error: pve_guest_agent must be enabled or disabled\n' >&2
            return 69
            ;;
    esac
    pve_positive_integer template_vmid "$FD_PVE_TEMPLATE_VMID" || return $?
    pve_positive_integer allowed_id_min "$FD_PVE_ALLOWED_MIN" || return $?
    pve_positive_integer allowed_id_max "$FD_PVE_ALLOWED_MAX" || return $?
    pve_positive_integer ssh_connect_timeout_seconds "$FD_PVE_CONNECT_TIMEOUT" || return $?
    pve_positive_integer pve_operation_timeout_seconds "$FD_PVE_OPERATION_TIMEOUT" || return $?
    pve_positive_integer cluster_capture_timeout_seconds \
        "$FD_PVE_CLUSTER_CAPTURE_TIMEOUT" || return $?
    pve_positive_integer test_a_journal_line_limit "$FD_PVE_TEST_A_JOURNAL_LIMIT" || return $?
    if ((FD_PVE_TEMPLATE_VMID >= FD_PVE_ALLOWED_MIN && FD_PVE_TEMPLATE_VMID <= FD_PVE_ALLOWED_MAX)); then
        printf 'pve configuration error: template_vmid overlaps the guest VMID window\n' >&2
        return 69
    fi
    for value in \
        "$FD_PVE_SSH_KEY" "$FD_PVE_KNOWN_HOSTS" \
        "$FD_PVE_GUEST_SSH_KEY" "$FD_PVE_GUEST_KNOWN_HOSTS"; do
        if [[ ! -f $value || ! -r $value ]]; then
            printf 'pve configuration error: required local SSH file is unreadable: %s\n' \
                "$value" >&2
            return 69
        fi
    done
    for value in \
        "$FD_PVE_K3S_BINARY_SHA256" "$FD_PVE_INSTALL_SCRIPT_SHA256" \
        "$FD_PVE_ETCDCTL_SHA256"; do
        if [[ ! $value =~ ^[a-f0-9]{64}$ ]]; then
            printf 'pve configuration error: artifact SHA-256 pins must be 64 lowercase hex characters\n' >&2
            return 69
        fi
    done
    if ! "$FD_PYTHON" -c '
import os, stat, sys
path = sys.argv[1]
try:
    status = os.lstat(path)
except OSError:
    raise SystemExit(1)
valid = stat.S_ISREG(status.st_mode) and not stat.S_ISLNK(status.st_mode)
valid = valid and stat.S_IMODE(status.st_mode) == 0o600 and os.access(path, os.R_OK)
raise SystemExit(0 if valid else 1)
' "$FD_PVE_JOIN_CREDENTIAL_FILE"; then
        printf '%s\n' \
            'pve configuration error: join credential source must be a readable mode-0600 regular non-symlink file' >&2
        return 69
    fi
    if [[ $FD_PVE_CI_SSHKEYS != /* || $FD_PVE_CI_SSHKEYS == *'..'* ]]; then
        printf 'pve configuration error: cloud-init sshkeys path must be literal and absolute\n' >&2
        return 69
    fi
    return 0
}

pve_transport_ssh() {
    local host=$1 user=$2 key_path=$3 known_hosts_path=$4 connect_timeout=$5
    shift 5
    command ssh \
        -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes \
        -o "UserKnownHostsFile=$known_hosts_path" -o "ConnectTimeout=$connect_timeout" \
        -i "$key_path" "$user@$host" "$@"
}

pve_shell_quote() {
    local value=$1
    value=${value//\'/\'\\\'\'}
    printf "'%s'" "$value"
}

pve_build_remote_command() {
    local privilege_mode=$1 argument quoted
    shift
    FD_PVE_REMOTE_COMMAND=''
    case $privilege_mode in
        direct) ;;
        sudo-n) FD_PVE_REMOTE_COMMAND='sudo -n' ;;
        doas-n) FD_PVE_REMOTE_COMMAND='doas -n' ;;
        *)
            printf 'pve driver error: unsupported privilege mode %q\n' "$privilege_mode" >&2
            return 69
            ;;
    esac
    for argument in "$@"; do
        quoted=$(pve_shell_quote "$argument") || return $?
        if [[ -n $FD_PVE_REMOTE_COMMAND ]]; then
            FD_PVE_REMOTE_COMMAND+=" $quoted"
        else
            FD_PVE_REMOTE_COMMAND=$quoted
        fi
    done
}

pve_host_exec() {
    pve_ensure_config || return $?
    pve_build_remote_command "$FD_PVE_PRIVILEGE_MODE" "$@" || return $?
    pve_transport_ssh "$FD_PVE_HOST" "$FD_PVE_SSH_USER" "$FD_PVE_SSH_KEY" \
        "$FD_PVE_KNOWN_HOSTS" "$FD_PVE_CONNECT_TIMEOUT" "$FD_PVE_REMOTE_COMMAND"
}

pve_guest_exec_raw() {
    local address=$1 connect_timeout=$2
    shift 2
    pve_build_remote_command "$FD_PVE_GUEST_PRIVILEGE_MODE" "$@" || return $?
    pve_transport_ssh "$address" "$FD_PVE_GUEST_SSH_USER" "$FD_PVE_GUEST_SSH_KEY" \
        "$FD_PVE_GUEST_KNOWN_HOSTS" "$connect_timeout" "$FD_PVE_REMOTE_COMMAND"
}

pve_pause() {
    "$FD_PYTHON" -c 'import sys,time; time.sleep(float(sys.argv[1]))' "$1"
}

pve_json_field() {
    "$FD_PYTHON" -c \
        'import json,sys; value=json.loads(sys.argv[1])[sys.argv[2]]; print(value)' "$1" "$2"
}

pve_require_json_mapping() {
    "$FD_PYTHON" -c \
        'import json,sys; value=json.loads(sys.argv[1]); raise SystemExit(0 if isinstance(value,dict) else 1)' \
        "$1"
}

pve_owner_marker() {
    printf 'firedrill-owner:%s' "$1"
}

pve_parse_owner() {
    "$FD_PYTHON" -c '
import json,sys
value=json.loads(sys.argv[1]); description=value.get("description", "")
matches=[line[len("firedrill-owner:"):] for line in description.splitlines()
         if line.startswith("firedrill-owner:")]
if len(matches) != 1 or not matches[0]:
    print("pve ownership error: expected exactly one firedrill-owner description line", file=sys.stderr)
    raise SystemExit(69)
print(matches[0])
' "$1"
}

pve_assert_vmid_window() {
    local guest_id=$1
    pve_ensure_config || return $?
    if [[ ! $guest_id =~ ^[0-9]+$ ]] \
        || ((guest_id < FD_PVE_ALLOWED_MIN || guest_id > FD_PVE_ALLOWED_MAX)); then
        printf 'SAFETY ABORT: PVE VMID %q is outside driver window %s..%s\n' \
            "$guest_id" "$FD_PVE_ALLOWED_MIN" "$FD_PVE_ALLOWED_MAX" >&2
        return 78
    fi
}

pve_require_mutation_approval() {
    local guest_id=$1 operation=$2
    pve_assert_vmid_window "$guest_id" || return $?
    if ! declare -F safety_guard_mutation >/dev/null; then
        printf 'SAFETY ABORT: PVE mutation approval guard is unavailable\n' >&2
        return 78
    fi
    safety_guard_mutation "$guest_id" "$operation"
}

pve_host_mutation() {
    local label=$1
    shift
    evidence_exec "$label" hypervisor pve_host_exec "$@"
}

pve_guest_config_json() {
    local guest_id=$1 output status=0
    output=$(pve_host_exec pvesh get "/nodes/$FD_PVE_NODE/qemu/$guest_id/config" \
        --output-format json 2>&1) || status=$?
    if ((status == 0)); then
        printf '%s\n' "$output"
        return 0
    fi
    case $output in
        *'does not exist'*|*'not found'*|*'No such file'*|*'no such file'*) return 1 ;;
        *)
            printf 'pve driver error: guest %s existence probe failed: %s\n' \
                "$guest_id" "$output" >&2
            return 69
            ;;
    esac
}

driver_impl_probe_identity() {
    pve_ensure_config || return $?
    pve_host_exec hostname
}

driver_impl_check_reachable() {
    local version_json storage_json storage_type bridge_json bridge_type
    pve_ensure_config || return $?
    pve_host_exec true >/dev/null || {
        printf 'pve preflight error: SSH trivial command failed\n' >&2
        return 69
    }
    version_json=$(pve_host_exec pvesh get /version --output-format json) || return $?
    if ! pve_require_json_mapping "$version_json"; then
        printf 'pve preflight error: pvesh /version did not return a JSON mapping\n' >&2
        return 69
    fi
    storage_json=$(pve_host_exec pvesh get "/storage/$FD_PVE_STORAGE" \
        --output-format json) || return $?
    storage_type=$(pve_json_field "$storage_json" type) || {
        printf 'pve preflight error: storage response lacks type\n' >&2
        return 69
    }
    if [[ $storage_type != zfspool ]]; then
        printf 'pve preflight error: storage %s has type %q, expected zfspool\n' \
            "$FD_PVE_STORAGE" "$storage_type" >&2
        return 69
    fi
    bridge_json=$(pve_host_exec pvesh get \
        "/nodes/$FD_PVE_NODE/network/$FD_PVE_BRIDGE" --output-format json) || return $?
    bridge_type=$(pve_json_field "$bridge_json" type) || {
        printf 'pve preflight error: bridge response lacks type\n' >&2
        return 69
    }
    if [[ $bridge_type != bridge ]]; then
        printf 'pve preflight error: interface %s has type %q, expected bridge\n' \
            "$FD_PVE_BRIDGE" "$bridge_type" >&2
        return 69
    fi
    pve_host_exec test -r "$FD_PVE_CI_SSHKEYS" >/dev/null || {
        printf 'pve preflight error: cloud-init public-key file is unreadable on PVE host\n' >&2
        return 69
    }
}

driver_impl_template_exists() {
    local template_json template_flag
    pve_ensure_config || return $?
    template_json=$(pve_host_exec pvesh get \
        "/nodes/$FD_PVE_NODE/qemu/$FD_PVE_TEMPLATE_VMID/config" \
        --output-format json) || return $?
    template_flag=$(pve_json_field "$template_json" template) || {
        printf 'pve preflight error: template VMID %s lacks a template flag\n' \
            "$FD_PVE_TEMPLATE_VMID" >&2
        return 69
    }
    if [[ $template_flag != 1 ]]; then
        printf 'pve preflight error: VMID %s is not a template (template=%q)\n' \
            "$FD_PVE_TEMPLATE_VMID" "$template_flag" >&2
        return 69
    fi
    if ! "$FD_PYTHON" -c \
        'import json,sys; value=json.loads(sys.argv[1]); raise SystemExit(0 if sys.argv[2] in value else 1)' \
        "$template_json" "$FD_PVE_OS_DISK"; then
        printf 'pve preflight error: template VMID %s lacks configured OS disk %s\n' \
            "$FD_PVE_TEMPLATE_VMID" "$FD_PVE_OS_DISK" >&2
        return 69
    fi
}

driver_impl_guest_exists() {
    local guest_id=$1 status=0
    pve_assert_vmid_window "$guest_id" || return $?
    pve_guest_config_json "$guest_id" >/dev/null || status=$?
    return "$status"
}

driver_impl_guest_owner() {
    local guest_id=$1 config_json
    pve_assert_vmid_window "$guest_id" || return $?
    config_json=$(pve_guest_config_json "$guest_id") || return $?
    pve_parse_owner "$config_json"
}

pve_validate_spec_against_inventory() {
    "$FD_PYTHON" -c '
import json,sys
with open(sys.argv[1], encoding="utf-8") as handle:
    canonical=json.load(handle)
spec=json.loads(sys.argv[2])
matches=[item for item in canonical["inventory"] if item.get("id") == spec.get("id")]
if len(matches) != 1 or matches[0] != spec:
    print("SAFETY ABORT: PVE guest specification differs from canonical inventory", file=sys.stderr)
    raise SystemExit(78)
' "$FD_CANONICAL_CONFIG" "$1"
}

pve_parse_spec() {
    "$FD_PYTHON" -c '
import json,sys
value=json.loads(sys.argv[1])
fields=("id","name","short_name","role","vcpus","memory_mb","disk_gb","ip","cidr")
if any(field not in value for field in fields):
    raise SystemExit("PVE guest spec is missing required fields")
print("|".join(str(value[field]) for field in fields))
' "$1"
}

pve_report_wait_attempt() {
    local attempt=$1 attempts=$2
    printf 'pve wait: attempt %s/%s\n' "$attempt" "$attempts" >&2
}

pve_wait_guest_present() {
    local guest_id=$1 attempts=$2 attempt status
    for ((attempt = 1; attempt <= attempts; attempt++)); do
        pve_report_wait_attempt "$attempt" "$attempts"
        status=0
        driver_impl_guest_exists "$guest_id" || status=$?
        if ((status == 0)); then
            return 0
        fi
        if ((status != 1)); then
            return "$status"
        fi
        pve_pause 1 || return $?
    done
    printf 'pve timeout: guest %s did not appear after clone\n' "$guest_id" >&2
    return 70
}

pve_wait_guest_absent() {
    local guest_id=$1 attempts=$2 attempt status
    for ((attempt = 1; attempt <= attempts; attempt++)); do
        pve_report_wait_attempt "$attempt" "$attempts"
        status=0
        driver_impl_guest_exists "$guest_id" || status=$?
        if ((status == 1)); then
            return 0
        fi
        if ((status != 0)); then
            return "$status"
        fi
        pve_pause 1 || return $?
    done
    printf 'pve timeout: guest %s remained present after destroy\n' "$guest_id" >&2
    return 70
}

pve_wait_owner_marker() {
    local guest_id=$1 expected=$2 attempts=$3 attempt owner status
    for ((attempt = 1; attempt <= attempts; attempt++)); do
        pve_report_wait_attempt "$attempt" "$attempts"
        status=0
        owner=$(driver_impl_guest_owner "$guest_id") || status=$?
        if ((status == 0)) && [[ $owner == "$expected" ]]; then
            return 0
        fi
        if ((status != 0 && status != 69)); then
            return "$status"
        fi
        pve_pause 1 || return $?
    done
    printf 'pve timeout: ownership marker for guest %s did not converge\n' "$guest_id" >&2
    return 70
}

pve_disk_meets_spec() {
    local config_json=$1 spec_json=$2
    "$FD_PYTHON" -c '
import json,re,sys
try:
    config=json.loads(sys.argv[1]); spec=json.loads(sys.argv[2]); disk_key=sys.argv[3]
    disk=str(config.get(disk_key, ""))
    size=re.search(r"(?:^|,)size=([0-9]+(?:\.[0-9]+)?)([KMGT])(?:,|$)", disk)
    if size is None:
        raise ValueError("configured disk size is unavailable")
    required_gib=int(spec["disk_gb"])
except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
    raise SystemExit(69)
factors={"K":1/(1024*1024),"M":1/1024,"G":1,"T":1024}
disk_gib=float(size.group(1))*factors[size.group(2)]
raise SystemExit(0 if disk_gib >= required_gib else 1)
' "$config_json" "$spec_json" "$FD_PVE_OS_DISK"
}

pve_config_matches_spec() {
    local config_json=$1 spec_json=$2 marker=$3 disk_status=0
    pve_disk_meets_spec "$config_json" "$spec_json" || disk_status=$?
    if ((disk_status != 0)); then
        return 1
    fi
    "$FD_PYTHON" -c '
import json,sys
config=json.loads(sys.argv[1]); spec=json.loads(sys.argv[2])
marker,net_key,ip_key,net_model,bridge,ciuser,agent,gateway=sys.argv[3:]
description=str(config.get("description", ""))
expected_agent=1 if agent == "enabled" else 0
checks=(
    config.get("name") == spec["name"],
    int(config.get("cores", -1)) == int(spec["vcpus"]),
    int(config.get("memory", -1)) == int(spec["memory_mb"]),
    marker in description.splitlines(),
    config.get("ciuser") == ciuser,
    net_model in str(config.get(net_key, "")),
    f"bridge={bridge}" in str(config.get(net_key, "")),
    str(config.get(ip_key, "")) == "ip={}/{},gw={}".format(
        spec["ip"], spec["cidr"], gateway
    ),
    int(config.get("agent", 0)) == expected_agent,
)
raise SystemExit(0 if all(checks) else 1)
' "$config_json" "$spec_json" "$marker" "$FD_PVE_NET_DEVICE" \
        "$FD_PVE_IPCONFIG_DEVICE" "$FD_PVE_NET_MODEL" \
        "$FD_PVE_BRIDGE" "$FD_PVE_CI_USER" "$FD_PVE_GUEST_AGENT" "$FD_PVE_GATEWAY"
}

pve_wait_config_spec() {
    local guest_id=$1 spec=$2 marker=$3 attempts=$4 attempt config_json
    for ((attempt = 1; attempt <= attempts; attempt++)); do
        pve_report_wait_attempt "$attempt" "$attempts"
        config_json=$(pve_guest_config_json "$guest_id") || return $?
        if pve_config_matches_spec "$config_json" "$spec" "$marker"; then
            return 0
        fi
        pve_pause 1 || return $?
    done
    printf 'pve timeout: configured state for guest %s did not converge\n' "$guest_id" >&2
    return 70
}

pve_resize_disk_if_needed() {
    local guest_id=$1 spec=$2 disk_gb=$3 config_json disk_status=0
    config_json=$(pve_guest_config_json "$guest_id") || return $?
    pve_disk_meets_spec "$config_json" "$spec" || disk_status=$?
    case $disk_status in
        0) return 0 ;;
        1)
            pve_host_mutation pve-disk-resize qm resize \
                "$guest_id" "$FD_PVE_OS_DISK" "${disk_gb}G"
            ;;
        *)
            printf 'pve driver error: configured OS disk size is unavailable\n' >&2
            return "$disk_status"
            ;;
    esac
}

driver_impl_guest_create() {
    local spec=$1 fields guest_id name short_name role vcpus memory_mb disk_gb ip cidr
    local exists_status owner marker agent_value
    fields=$(pve_parse_spec "$spec") || return $?
    IFS='|' read -r guest_id name short_name role vcpus memory_mb disk_gb ip cidr <<<"$fields"
    : "$short_name" "$role"
    pve_assert_vmid_window "$guest_id" || return $?
    pve_validate_spec_against_inventory "$spec" || return $?
    pve_require_mutation_approval "$guest_id" create || return $?
    exists_status=0
    driver_impl_guest_exists "$guest_id" || exists_status=$?
    if ((exists_status == 0)); then
        owner=$(driver_impl_guest_owner "$guest_id") || return $?
        if [[ $owner != "$FD_LAB_ID" ]]; then
            printf 'SAFETY ABORT: existing PVE guest %s has owner %q\n' \
                "$guest_id" "$owner" >&2
            return 78
        fi
        marker=$(pve_owner_marker "$FD_LAB_ID") || return $?
        pve_wait_config_spec "$guest_id" "$spec" "$marker" 1 || return $?
        printf 'already-present\n'
        return 0
    fi
    if ((exists_status != 1)); then
        return "$exists_status"
    fi
    marker=$(pve_owner_marker "$FD_LAB_ID") || return $?
    pve_host_mutation pve-clone qm clone \
        "$FD_PVE_TEMPLATE_VMID" "$guest_id" --name "$name" --full \
        --storage "$FD_PVE_STORAGE" || return $?
    pve_wait_guest_present "$guest_id" "$FD_PVE_OPERATION_TIMEOUT" || return $?
    pve_host_mutation pve-owner-marker qm set "$guest_id" --description "$marker" || return $?
    pve_wait_owner_marker "$guest_id" "$FD_LAB_ID" "$FD_PVE_OPERATION_TIMEOUT" || return $?
    pve_resize_disk_if_needed "$guest_id" "$spec" "$disk_gb" || return $?
    agent_value=0
    if [[ $FD_PVE_GUEST_AGENT == enabled ]]; then
        agent_value=1
    fi
    pve_host_mutation pve-cloud-init-config qm set "$guest_id" \
        --name "$name" --cores "$vcpus" --memory "$memory_mb" \
        --ciuser "$FD_PVE_CI_USER" --sshkeys "$FD_PVE_CI_SSHKEYS" \
        --agent "$agent_value" \
        "--$FD_PVE_NET_DEVICE" "$FD_PVE_NET_MODEL,bridge=$FD_PVE_BRIDGE" \
        "--$FD_PVE_IPCONFIG_DEVICE" "ip=$ip/$cidr,gw=$FD_PVE_GATEWAY" || return $?
    pve_wait_config_spec \
        "$guest_id" "$spec" "$marker" "$FD_PVE_OPERATION_TIMEOUT" || return $?
    printf 'created\n'
}

pve_guest_status_value() {
    local guest_id=$1 output
    output=$(pve_host_exec qm status "$guest_id") || return $?
    if [[ $output =~ ^status:[[:space:]]*([A-Za-z]+)$ ]]; then
        printf '%s\n' "${BASH_REMATCH[1]}"
        return 0
    fi
    printf 'pve driver error: unexpected qm status output for guest %s: %s\n' \
        "$guest_id" "$output" >&2
    return 69
}

pve_wait_guest_status() {
    local guest_id=$1 expected=$2 attempts=$3 attempt observed
    for ((attempt = 1; attempt <= attempts; attempt++)); do
        pve_report_wait_attempt "$attempt" "$attempts"
        observed=$(pve_guest_status_value "$guest_id") || return $?
        if [[ $observed == "$expected" ]]; then
            return 0
        fi
        pve_pause 1 || return $?
    done
    printf 'pve timeout: guest %s did not reach status %s\n' "$guest_id" "$expected" >&2
    return 70
}

driver_impl_guest_start() {
    local guest_id=$1 status
    pve_require_mutation_approval "$guest_id" start || return $?
    status=$(pve_guest_status_value "$guest_id") || return $?
    if [[ $status == running ]]; then
        printf 'already-running\n'
        return 0
    fi
    pve_host_mutation pve-start qm start "$guest_id" || return $?
    pve_wait_guest_status "$guest_id" running "$FD_PVE_OPERATION_TIMEOUT"
}

pve_record_stop_mode() {
    FD_PVE_LAST_STOP_MODE=$1
    evidence_exec pve-stop-mode hypervisor \
        printf 'pve-stop-mode=%s\n' "$FD_PVE_LAST_STOP_MODE"
}

pve_stop_approved() {
    local guest_id=$1 timeout=$2 status wait_status
    pve_positive_integer shutdown_timeout "$timeout" || return $?
    status=$(pve_guest_status_value "$guest_id") || return $?
    if [[ $status == stopped ]]; then
        pve_record_stop_mode already-stopped
        return 0
    fi
    pve_host_mutation pve-shutdown qm shutdown "$guest_id" || return $?
    wait_status=0
    pve_wait_guest_status "$guest_id" stopped "$timeout" || wait_status=$?
    if ((wait_status == 0)); then
        pve_record_stop_mode graceful-shutdown
        return 0
    fi
    if ((wait_status != 70)); then
        return "$wait_status"
    fi
    pve_host_mutation pve-force-stop-after-timeout qm stop "$guest_id" || return $?
    pve_wait_guest_status "$guest_id" stopped "$FD_PVE_OPERATION_TIMEOUT" || return $?
    pve_record_stop_mode forced-stop-after-shutdown-timeout
}

driver_impl_guest_stop() {
    local guest_id=$1 timeout=$2
    pve_require_mutation_approval "$guest_id" stop || return $?
    pve_stop_approved "$guest_id" "$timeout"
}

driver_impl_guest_status() {
    local guest_id=$1
    pve_assert_vmid_window "$guest_id" || return $?
    pve_guest_status_value "$guest_id"
}

driver_impl_guest_delete() {
    local guest_id=$1 status
    pve_require_mutation_approval "$guest_id" delete || return $?
    status=$(pve_guest_status_value "$guest_id") || return $?
    if [[ $status != stopped ]]; then
        pve_stop_approved "$guest_id" "$FD_PVE_OPERATION_TIMEOUT" || return $?
    fi
    pve_host_mutation pve-destroy qm destroy "$guest_id" --purge || return $?
    pve_wait_guest_absent "$guest_id" "$FD_PVE_OPERATION_TIMEOUT"
}

pve_snapshot_list_json() {
    local guest_id=$1
    pve_host_exec pvesh get "/nodes/$FD_PVE_NODE/qemu/$guest_id/snapshot" \
        --output-format json
}

pve_snapshot_in_list() {
    "$FD_PYTHON" -c '
import json,sys
value=json.loads(sys.argv[1])
if not isinstance(value,list):
    raise SystemExit(69)
raise SystemExit(0 if any(isinstance(item,dict) and item.get("name") == sys.argv[2]
                          for item in value) else 1)
' "$1" "$2"
}

driver_impl_snapshot_exists() {
    local guest_id=$1 snapshot=$2 payload status=0
    pve_assert_vmid_window "$guest_id" || return $?
    payload=$(pve_snapshot_list_json "$guest_id") || return $?
    pve_snapshot_in_list "$payload" "$snapshot" || status=$?
    return "$status"
}

pve_wait_snapshot_state() {
    local guest_id=$1 snapshot=$2 expected=$3 attempts=$4 attempt status
    for ((attempt = 1; attempt <= attempts; attempt++)); do
        pve_report_wait_attempt "$attempt" "$attempts"
        status=0
        driver_impl_snapshot_exists "$guest_id" "$snapshot" || status=$?
        if [[ $expected == present && $status == 0 ]]; then
            return 0
        fi
        if [[ $expected == absent && $status == 1 ]]; then
            return 0
        fi
        if ((status != 0 && status != 1)); then
            return "$status"
        fi
        pve_pause 1 || return $?
    done
    printf 'pve timeout: snapshot %s for guest %s did not become %s\n' \
        "$snapshot" "$guest_id" "$expected" >&2
    return 70
}

driver_impl_snapshot_create() {
    local guest_id=$1 snapshot=$2 status=0
    pve_require_mutation_approval "$guest_id" snapshot-create || return $?
    driver_impl_snapshot_exists "$guest_id" "$snapshot" || status=$?
    if ((status == 0)); then
        printf 'already-present\n'
        return 0
    fi
    if ((status != 1)); then
        return "$status"
    fi
    pve_host_mutation pve-snapshot-create qm snapshot "$guest_id" "$snapshot" || return $?
    pve_wait_snapshot_state "$guest_id" "$snapshot" present "$FD_PVE_OPERATION_TIMEOUT"
}

driver_impl_snapshot_restore_prepare() {
    local guest_id=$1
    driver_impl_guest_stop "$guest_id" "$FD_PVE_OPERATION_TIMEOUT"
}

driver_impl_snapshot_restore() {
    local guest_id=$1 snapshot=$2 status
    pve_require_mutation_approval "$guest_id" snapshot-restore || return $?
    status=$(pve_guest_status_value "$guest_id") || return $?
    if [[ $status != stopped ]]; then
        printf 'pve snapshot error: guest %s must be stopped before rollback\n' \
            "$guest_id" >&2
        return 69
    fi
    if ! driver_impl_snapshot_exists "$guest_id" "$snapshot"; then
        printf 'pve snapshot error: guest %s lacks snapshot %s\n' \
            "$guest_id" "$snapshot" >&2
        return 67
    fi
    pve_host_mutation pve-snapshot-rollback qm rollback "$guest_id" "$snapshot" || return $?
    pve_wait_snapshot_state "$guest_id" "$snapshot" present "$FD_PVE_OPERATION_TIMEOUT"
}

driver_impl_snapshot_restore_finish() {
    local guest_id=$1
    driver_impl_guest_start "$guest_id"
}

driver_impl_snapshot_delete() {
    local guest_id=$1 snapshot=$2 status=0
    pve_require_mutation_approval "$guest_id" snapshot-delete || return $?
    driver_impl_snapshot_exists "$guest_id" "$snapshot" || status=$?
    if ((status == 1)); then
        printf 'already-absent\n'
        return 0
    fi
    if ((status != 0)); then
        return "$status"
    fi
    pve_host_mutation pve-snapshot-delete qm delsnapshot "$guest_id" "$snapshot" || return $?
    pve_wait_snapshot_state "$guest_id" "$snapshot" absent "$FD_PVE_OPERATION_TIMEOUT"
}

pve_node_ip() {
    local node=$1 count index candidate
    count=$(config_inventory_count) || return $?
    for ((index = 0; index < count; index++)); do
        candidate=$(config_inventory_field "$index" short_name) || return $?
        if [[ $candidate == "$node" ]]; then
            config_inventory_field "$index" ip
            return
        fi
    done
    printf 'pve driver error: node %q is absent from canonical inventory\n' "$node" >&2
    return 69
}

driver_impl_guest_wait_access() {
    local node=$1 timeout=$2 address attempt connect_timeout
    pve_positive_integer guest_access_timeout "$timeout" || return $?
    address=$(pve_node_ip "$node") || return $?
    connect_timeout=$FD_PVE_CONNECT_TIMEOUT
    if ((connect_timeout > timeout)); then
        connect_timeout=$timeout
    fi
    for ((attempt = 1; attempt <= timeout; attempt++)); do
        pve_report_wait_attempt "$attempt" "$timeout"
        if pve_guest_exec_raw "$address" "$connect_timeout" true >/dev/null 2>&1; then
            return 0
        fi
        pve_pause 1 || return $?
    done
    printf 'pve timeout: guest %s at %s did not accept SSH\n' "$node" "$address" >&2
    return 70
}

driver_impl_guest_exec() {
    local node=$1 guest_id=$2 timeout=$3 address
    shift 3
    pve_positive_integer guest_exec_timeout "$timeout" || return $?
    pve_require_mutation_approval "$guest_id" guest-exec || return $?
    address=$(pve_node_ip "$node") || return $?
    evidence_exec pve-guest-exec "$node" \
        pve_guest_exec_raw "$address" "$FD_PVE_CONNECT_TIMEOUT" \
        timeout --signal=TERM "${timeout}s" "$@"
}

pve_validate_destination() {
    local destination=$1
    if [[ ! $destination =~ ^/[A-Za-z0-9._/-]+$ \
        || $destination == *'/../'* || $destination == */.. \
        || $destination == *'/./'* || $destination == */. \
        || $destination == *'//'* ]]; then
        printf 'pve guest-put error: destination must be a normalized literal absolute path\n' >&2
        return 69
    fi
}

driver_impl_guest_put() {
    local node=$1 source=$2 destination=$3 guest_id address script
    if [[ ! -f $source || -L $source ]]; then
        printf 'pve guest-put error: source must be one regular non-symlink file\n' >&2
        return 69
    fi
    pve_validate_destination "$destination" || return $?
    guest_id=$(node_id "$node") || return $?
    pve_require_mutation_approval "$guest_id" guest-put || return $?
    address=$(pve_node_ip "$node") || return $?
    script='
set -eu
destination=$1
temporary="${destination}.firedrill.$$"
trap '\''rm -f "$temporary"'\'' EXIT HUP INT TERM
umask 077
cat >"$temporary"
chmod 0600 "$temporary"
chown 0:0 "$temporary"
mv "$temporary" "$destination"
trap - EXIT HUP INT TERM
'
    pve_build_remote_command "$FD_PVE_GUEST_PRIVILEGE_MODE" \
        sh -c "$script" sh "$destination" || return $?
    evidence_exec pve-guest-put "$node" \
        pve_transport_ssh \
        "$address" "$FD_PVE_GUEST_SSH_USER" "$FD_PVE_GUEST_SSH_KEY" \
        "$FD_PVE_GUEST_KNOWN_HOSTS" "$FD_PVE_CONNECT_TIMEOUT" \
        "$FD_PVE_REMOTE_COMMAND" <"$source"
}

pve_real_test_hook_unreviewed() {
    printf 'pve real test hooks not yet reviewed: %s\n' "${FUNCNAME[1]}" >&2
    return 69
}

pve_test_a_require_full_server_token() {
    local token=$1 label=$2
    if [[ ! $token =~ ^K10[a-f0-9]{64}::server:[^[:space:]]+$ ]]; then
        printf 'pve Test A guard: %s is not one full server token\n' "$label" >&2
        return 69
    fi
}

pve_test_a_require_node() {
    case $1 in
        server-1|server-2|server-3|agent-1|agent-2) ;;
        *)
            printf 'pve Test A guard: unknown node %q\n' "$1" >&2
            return 69
            ;;
    esac
}

pve_test_a_is_server() {
    case $1 in
        server-1|server-2|server-3) return 0 ;;
        *) return 1 ;;
    esac
}

pve_test_a_token_reference() {
    "$FD_PYTHON" -c '
import sys
from firedrill.redact import token_reference

token = sys.stdin.read().rstrip("\n")
if not token:
    raise SystemExit(69)
print(token_reference(token))
'
}

pve_test_a_server_address() {
    pve_node_ip server-1
}

pve_test_a_capture_state_raw() {
    local address
    address=$(pve_test_a_server_address) || return $?
    pve_guest_exec_raw "$address" "$FD_PVE_CONNECT_TIMEOUT" \
        timeout --signal=TERM "${FD_PVE_CLUSTER_CAPTURE_TIMEOUT}s" \
        env "FIREDRILL_OP_CONFIG_PATH=$FD_PVE_OP_CONFIG_PATH" \
        firedrill-op capture-cluster-state
}

pve_test_a_snapshot_seen() {
    local node=$1 observed
    ((${#FD_PVE_TEST_A_SNAPSHOT_NODES[@]} > 0)) || return 1
    for observed in "${FD_PVE_TEST_A_SNAPSHOT_NODES[@]}"; do
        [[ $observed != "$node" ]] || return 0
    done
    return 1
}

pve_test_a_snapshot_pair_mutation() {
    local node=$1 guest_id=$2 address observed snapshot_name discovery path digest pair
    : "$guest_id"
    address=$(pve_node_ip "$node") || return $?
    observed=$(pve_guest_exec_raw "$address" "$FD_PVE_CONNECT_TIMEOUT" \
        timeout --signal=TERM "${FD_PVE_OPERATION_TIMEOUT}s" \
        cat "$FD_PVE_K3S_SERVER_TOKEN") || return $?
    if [[ $observed != "$FD_PVE_TEST_A_OPERATION_TOKEN" ]]; then
        printf 'pve Test A guard: snapshot token is not current on %s\n' "$node" >&2
        return 69
    fi
    snapshot_name="firedrill-test-a-$node-$FD_LAB_ID"
    pve_guest_exec_raw "$address" "$FD_PVE_CONNECT_TIMEOUT" \
        timeout --signal=TERM "${FD_PVE_OPERATION_TIMEOUT}s" \
        "$FD_PVE_K3S_BINARY" etcd-snapshot save --name "$snapshot_name" \
        >/dev/null || return $?
    discovery=$(pve_guest_exec_raw "$address" "$FD_PVE_CONNECT_TIMEOUT" \
        timeout --signal=TERM "${FD_PVE_OPERATION_TIMEOUT}s" \
        sh -c '
set -eu
directory=$1
prefix=$2
count=0
selected=
for candidate in "$directory"/"$prefix"*; do
    [ -f "$candidate" ] || continue
    [ ! -L "$candidate" ] || exit 69
    count=$((count + 1))
    selected=$candidate
done
[ "$count" -eq 1 ] || exit 69
if command -v sha256sum >/dev/null 2>&1; then
    digest=$(sha256sum "$selected")
elif command -v shasum >/dev/null 2>&1; then
    digest=$(shasum -a 256 "$selected")
else
    exit 69
fi
digest=${digest%%[[:space:]]*}
printf "%s|%s\n" "$selected" "$digest"
' sh "$FD_PVE_ETCD_SNAPSHOT_DIR" "$snapshot_name") || return $?
    path=${discovery%%|*}
    digest=${discovery#*|}
    if [[ $path != "$FD_PVE_ETCD_SNAPSHOT_DIR/"* \
        || ! $digest =~ ^[a-f0-9]{64}$ ]]; then
        printf 'pve Test A guard: snapshot discovery returned an invalid pair\n' >&2
        return 69
    fi
    pair=$(printf '%s' "$FD_PVE_TEST_A_OPERATION_TOKEN" \
        | "$FD_PYTHON" -c '
import json, sys
from firedrill.redact import token_reference

node, path, digest = sys.argv[1:]
token = sys.stdin.read().rstrip("\n")
if not token:
    raise SystemExit(69)
print(json.dumps({
    "node": node,
    "path": path,
    "snapshot_sha256": digest,
    "server_token_reference": token_reference(token),
}, sort_keys=True, separators=(",", ":")))
' "$node" "$path" "$digest") || return $?
    FD_PVE_TEST_A_SNAPSHOT_NODES+=("$node")
    FD_PVE_TEST_A_SNAPSHOT_PAIRS+=("$pair")
    printf '%s\n' "$pair"
}

pve_test_a_require_snapshot_coverage() {
    local expected
    ((${#FD_PVE_TEST_A_SNAPSHOT_NODES[@]} == 3)) || {
        printf 'pve Test A guard: rotation requires three token-paired snapshots\n' >&2
        return 69
    }
    for expected in server-1 server-2 server-3; do
        pve_test_a_snapshot_seen "$expected" || {
            printf 'pve Test A guard: rotation snapshot coverage is incomplete\n' >&2
            return 69
        }
    done
}

pve_test_a_require_restart_order() {
    local first second third
    IFS=, read -r first second third <<<"$1"
    if [[ -z $first || -z $second || -z $third \
        || $third == *,* || $first == "$second" || $first == "$third" \
        || $second == "$third" ]]; then
        printf 'pve Test A guard: restart order is not an exact server permutation\n' >&2
        return 69
    fi
    if ! pve_test_a_is_server "$first" || ! pve_test_a_is_server "$second" \
        || ! pve_test_a_is_server "$third"; then
        printf 'pve Test A guard: restart order contains a non-server node\n' >&2
        return 69
    fi
}

pve_test_a_require_current_snapshot_references() {
    local reference=$1
    shift
    "$FD_PYTHON" -c '
import json, sys

reference, *raw_pairs = sys.argv[1:]
try:
    pairs = [json.loads(raw) for raw in raw_pairs]
except (TypeError, ValueError):
    raise SystemExit(69)
valid = len(pairs) == 3 and all(
    isinstance(pair, dict) and pair.get("server_token_reference") == reference
    for pair in pairs
)
raise SystemExit(0 if valid else 69)
' "$reference" "$@"
}

pve_test_a_rotate_mutation() {
    local address observed current_reference token_reference state_json keys_json record
    address=$(pve_test_a_server_address) || return $?
    observed=$(pve_guest_exec_raw "$address" "$FD_PVE_CONNECT_TIMEOUT" \
        timeout --signal=TERM "${FD_PVE_OPERATION_TIMEOUT}s" \
        cat "$FD_PVE_K3S_SERVER_TOKEN") || return $?
    if [[ $observed == "$FD_PVE_TEST_A_NEW_TOKEN" ]]; then
        printf 'pve Test A guard: proposed server token equals the current token\n' >&2
        return 69
    fi
    current_reference=$(printf '%s' "$observed" | pve_test_a_token_reference) || return $?
    if ! pve_test_a_require_current_snapshot_references \
        "$current_reference" "${FD_PVE_TEST_A_SNAPSHOT_PAIRS[@]}"; then
        printf 'pve Test A guard: snapshot token references are stale or unpaired\n' >&2
        return 69
    fi
    printf '%s\n' "$FD_PVE_TEST_A_NEW_TOKEN" \
        | pve_guest_exec_raw "$address" "$FD_PVE_CONNECT_TIMEOUT" \
            timeout --signal=TERM "${FD_PVE_OPERATION_TIMEOUT}s" \
            sh -c '
set -eu
IFS= read -r new_token
exec "$1" token rotate --new-token "$new_token"
' sh "$FD_PVE_K3S_BINARY" >/dev/null || return $?
    observed=$(pve_guest_exec_raw "$address" "$FD_PVE_CONNECT_TIMEOUT" \
        timeout --signal=TERM "${FD_PVE_OPERATION_TIMEOUT}s" \
        cat "$FD_PVE_K3S_SERVER_TOKEN") || return $?
    if [[ $observed != "$FD_PVE_TEST_A_NEW_TOKEN" ]]; then
        printf 'pve Test A guard: rotated server token did not converge exactly\n' >&2
        return 69
    fi
    state_json=$(pve_test_a_capture_state_raw) || return $?
    keys_json=$("$FD_PYTHON" -c '
import json, sys
value = json.loads(sys.argv[1])
keys = value.get("bootstrap_keys")
if not isinstance(keys, list):
    raise SystemExit(69)
print(json.dumps(keys, separators=(",", ":")))
' "$state_json") || return $?
    token_reference=$(printf '%s' "$FD_PVE_TEST_A_NEW_TOKEN" \
        | pve_test_a_token_reference) || return $?
    record=$("$FD_PYTHON" -c '
import json, sys
reference, keys_raw, order_raw = sys.argv[1:]
print(json.dumps({
    "event": "server-token-rotated",
    "server_token_reference": reference,
    "bootstrap_keys": json.loads(keys_raw),
    "configured_server_restart_order": order_raw.split(","),
}, sort_keys=True, separators=(",", ":")))
' "$token_reference" "$keys_json" "$FD_PVE_TEST_A_RESTART_ORDER_CSV") || return $?
    FD_PVE_TEST_A_ROTATED=true
    FD_PVE_TEST_A_RESTART_EVENTS=()
    printf '%s\n' "$record"
}

pve_test_a_expected_restart_node() {
    local first second third index=${#FD_PVE_TEST_A_RESTART_EVENTS[@]}
    IFS=, read -r first second third <<<"$FD_PVE_TEST_A_RESTART_ORDER_CSV"
    case $index in
        0) printf '%s\n' "$first" ;;
        1) printf '%s\n' "$second" ;;
        2) printf '%s\n' "$third" ;;
        3) printf 'agent-1\n' ;;
        4) printf 'agent-2\n' ;;
        *) return 69 ;;
    esac
}

pve_test_a_env_edit_script() {
    printf '%s\n' '
set -eu
IFS= read -r token
path=$1
tmp="${path}.firedrill.$$"
[ -f "$path" ] && [ ! -L "$path" ] || exit 69
umask 077
trap '\''rm -f "$tmp"'\'' EXIT HUP INT TERM
found=0
while IFS= read -r line || [ -n "$line" ]; do
    case $line in
        K3S_TOKEN=*)
            found=$((found + 1))
            printf "K3S_TOKEN=%s\n" "$token" >>"$tmp"
            ;;
        *) printf "%s\n" "$line" >>"$tmp" ;;
    esac
done <"$path"
[ "$found" -eq 1 ] || exit 69
chmod 0600 "$tmp"
chown 0:0 "$tmp"
mv "$tmp" "$path"
trap - EXIT HUP INT TERM
'
}

pve_test_a_write_node_credential() {
    local node=$1 address=$2 script path
    if pve_test_a_is_server "$node"; then
        path=$FD_PVE_K3S_SERVER_ENV
    else
        path=$FD_PVE_K3S_AGENT_ENV
    fi
    script=$(pve_test_a_env_edit_script) || return $?
    printf '%s\n' "$FD_PVE_TEST_A_NEW_TOKEN" \
        | pve_guest_exec_raw "$address" "$FD_PVE_CONNECT_TIMEOUT" \
            timeout --signal=TERM "${FD_PVE_OPERATION_TIMEOUT}s" \
            sh -c "$script" sh "$path"
}

pve_test_a_token_digest() {
    "$FD_PYTHON" -c '
import hashlib, sys

token = sys.stdin.read().rstrip("\n")
if not token:
    raise SystemExit(69)
print(hashlib.sha256(token.encode()).hexdigest())
'
}

pve_test_a_join_digest() {
    "$FD_PYTHON" -c '
import hashlib, sys
from firedrill.bootstrap import normalize_token

token = sys.stdin.read().rstrip("\n")
if not token:
    raise SystemExit(69)
print(hashlib.sha256(normalize_token(token).encode()).hexdigest())
'
}

pve_test_a_server_token_digest() {
    local address=$1
    pve_guest_exec_raw "$address" "$FD_PVE_CONNECT_TIMEOUT" \
        timeout --signal=TERM "${FD_PVE_OPERATION_TIMEOUT}s" \
        sh -c '
set -eu
token_file=$1
[ -f "$token_file" ] && [ ! -L "$token_file" ] || exit 69
token=$(cat "$token_file")
[ -n "$token" ] || exit 69
if command -v sha256sum >/dev/null 2>&1; then
    digest=$(printf "%s" "$token" | sha256sum)
elif command -v shasum >/dev/null 2>&1; then
    digest=$(printf "%s" "$token" | shasum -a 256)
else
    exit 69
fi
digest=${digest%%[[:space:]]*}
printf "%s\n" "$digest"
' sh "$FD_PVE_K3S_SERVER_TOKEN"
}

pve_test_a_update_runtime_digest() {
    local address=$1 digest=$2
    pve_guest_exec_raw "$address" "$FD_PVE_CONNECT_TIMEOUT" \
        timeout --signal=TERM "${FD_PVE_OPERATION_TIMEOUT}s" \
        sh -c '
set -eu
path=$1
digest=$2
tmp="${path}.firedrill.$$"
[ -f "$path" ] && [ ! -L "$path" ] || exit 69
umask 077
trap '\''rm -f "$tmp"'\'' EXIT HUP INT TERM
found=0
while IFS= read -r line || [ -n "$line" ]; do
    case $line in
        join_credential_sha256=*)
            found=$((found + 1))
            printf "join_credential_sha256=%s\n" "$digest" >>"$tmp"
            ;;
        *) printf "%s\n" "$line" >>"$tmp" ;;
    esac
done <"$path"
[ "$found" -eq 1 ] || exit 69
chmod 0600 "$tmp"
chown 0:0 "$tmp"
mv "$tmp" "$path"
trap - EXIT HUP INT TERM
' sh "$FD_PVE_OP_CONFIG_PATH" "$digest"
}

pve_test_a_publish_node_digest() {
    local node=$1 digest=$2 address label_a label_b
    address=$(pve_test_a_server_address) || return $?
    label_a=${digest:0:32}
    label_b=${digest:32:32}
    pve_guest_exec_raw "$address" "$FD_PVE_CONNECT_TIMEOUT" \
        timeout --signal=TERM "${FD_PVE_OPERATION_TIMEOUT}s" \
        "$FD_PVE_K3S_BINARY" kubectl --kubeconfig "$FD_PVE_KUBECONFIG" \
        label node "$node" \
        "firedrill.internal/join-sha256-a=$label_a" \
        "firedrill.internal/join-sha256-b=$label_b" --overwrite
}

pve_test_a_restart_event() {
    local sequence=$1 node=$2 status=$3 timeout=$4 convergence=$5
    "$FD_PYTHON" -c '
import json, sys
sequence, node, status, timeout, convergence = sys.argv[1:]
print(json.dumps({
    "sequence": int(sequence),
    "node": node,
    "status": status,
    "timeout_seconds": int(timeout),
    "convergence_seconds": int(convergence),
}, sort_keys=True, separators=(",", ":")))
' "$sequence" "$node" "$status" "$timeout" "$convergence"
}

pve_test_a_restart_mutation() {
    local node=$1 guest_id=$2 timeout=$3 address unit start_seconds convergence
    local wait_status=0 sequence event digest expected_token_digest actual_token_digest
    : "$guest_id"
    address=$(pve_node_ip "$node") || return $?
    pve_test_a_write_node_credential "$node" "$address" || return $?
    digest=$(printf '%s' "$FD_PVE_TEST_A_NEW_TOKEN" \
        | pve_test_a_join_digest) || return $?
    pve_test_a_update_runtime_digest "$address" "$digest" || return $?
    unit=$FD_PVE_K3S_AGENT_UNIT
    if pve_test_a_is_server "$node"; then
        unit=$FD_PVE_K3S_SERVER_UNIT
    fi
    pve_guest_exec_raw "$address" "$FD_PVE_CONNECT_TIMEOUT" \
        timeout --signal=TERM "${FD_PVE_OPERATION_TIMEOUT}s" \
        systemctl daemon-reload || return $?
    start_seconds=$SECONDS
    pve_guest_exec_raw "$address" "$FD_PVE_CONNECT_TIMEOUT" \
        timeout --signal=TERM "${FD_PVE_OPERATION_TIMEOUT}s" \
        systemctl restart "$unit" || return $?
    if pve_test_a_is_server "$node"; then
        expected_token_digest=$(printf '%s' "$FD_PVE_TEST_A_NEW_TOKEN" \
            | pve_test_a_token_digest) || return $?
        actual_token_digest=$(pve_test_a_server_token_digest "$address") || return $?
        if [[ ! $actual_token_digest =~ ^[a-f0-9]{64}$ \
            || $actual_token_digest != "$expected_token_digest" ]]; then
            printf 'pve Test A guard: server token did not regenerate from the configured credential\n' >&2
            return 69
        fi
    fi
    pve_guest_exec_raw "$address" "$FD_PVE_CONNECT_TIMEOUT" \
        timeout --signal=TERM "${timeout}s" \
        env "FIREDRILL_OP_CONFIG_PATH=$FD_PVE_OP_CONFIG_PATH" \
        "FIREDRILL_OP_WAIT_TIMEOUT_SECONDS=$timeout" \
        firedrill-op wait-ready >/dev/null || wait_status=$?
    convergence=$((SECONDS - start_seconds))
    sequence=$((${#FD_PVE_TEST_A_RESTART_EVENTS[@]} + 1))
    if ((wait_status == 0)); then
        pve_test_a_publish_node_digest "$node" "$digest" >/dev/null || return $?
        event=$(pve_test_a_restart_event \
            "$sequence" "$node" healthy "$timeout" "$convergence") || return $?
        FD_PVE_TEST_A_RESTART_EVENTS+=("$event")
        printf '%s\n' "$event"
        return 0
    fi
    if ((wait_status == 70 || wait_status == 124)); then
        event=$(pve_test_a_restart_event \
            "$sequence" "$node" timeout "$timeout" "$convergence") || return $?
        FD_PVE_TEST_A_RESTART_EVENTS+=("$event")
        printf '%s\n' "$event" >&2
        return 70
    fi
    return "$wait_status"
}

pve_test_a_write_json_lines() {
    local output=$1 item
    shift
    : >"$output"
    for item in "$@"; do
        printf '%s\n' "$item" >>"$output"
    done
}

pve_test_a_collect_journal() {
    local node=$1 output=$2 address
    address=$(pve_node_ip "$node") || return $?
    pve_guest_exec_raw "$address" "$FD_PVE_CONNECT_TIMEOUT" \
        timeout --signal=TERM "${FD_PVE_OPERATION_TIMEOUT}s" \
        journalctl --unit "$FD_PVE_K3S_SERVER_UNIT" --no-pager \
        --output=cat --lines "$FD_PVE_TEST_A_JOURNAL_LIMIT" >"$output"
}

pve_test_a_observe_raw() {
    local base_file events_file pairs_file journal_one journal_two journal_three
    local base_json token
    base_file=$(mktemp "${TMPDIR:-/tmp}/firedrill-test-a-base.XXXXXX") || return $?
    events_file=$(mktemp "${TMPDIR:-/tmp}/firedrill-test-a-events.XXXXXX") || return $?
    pairs_file=$(mktemp "${TMPDIR:-/tmp}/firedrill-test-a-pairs.XXXXXX") || return $?
    journal_one=$(mktemp "${TMPDIR:-/tmp}/firedrill-test-a-journal-1.XXXXXX") || return $?
    journal_two=$(mktemp "${TMPDIR:-/tmp}/firedrill-test-a-journal-2.XXXXXX") || return $?
    journal_three=$(mktemp "${TMPDIR:-/tmp}/firedrill-test-a-journal-3.XXXXXX") || return $?
    FD_TEMP_FILES+=(
        "$base_file" "$events_file" "$pairs_file" \
        "$journal_one" "$journal_two" "$journal_three"
    )
    base_json=$(pve_test_a_capture_state_raw) || return $?
    printf '%s\n' "$base_json" >"$base_file"
    pve_test_a_write_json_lines "$events_file" \
        "${FD_PVE_TEST_A_RESTART_EVENTS[@]}" || return $?
    pve_test_a_write_json_lines "$pairs_file" \
        "${FD_PVE_TEST_A_SNAPSHOT_PAIRS[@]}" || return $?
    pve_test_a_collect_journal server-1 "$journal_one" || return $?
    pve_test_a_collect_journal server-2 "$journal_two" || return $?
    pve_test_a_collect_journal server-3 "$journal_three" || return $?
    token=$FD_PVE_TEST_A_NEW_TOKEN
    printf '%s' "$token" | "$FD_PYTHON" -c '
import json, sys
from pathlib import Path
from firedrill.redact import token_reference

base_path, events_path, pairs_path, *journal_paths = map(Path, sys.argv[1:])
state = json.loads(base_path.read_text(encoding="utf-8"))

def json_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

pairs = json_lines(pairs_path)
token = sys.stdin.read().rstrip("\n")
if not token:
    raise SystemExit(69)
state.update({
    "event": "test-a-gate-observation",
    "server_journals": {
        name: path.read_text(encoding="utf-8", errors="replace").splitlines()
        for name, path in zip(("server-1", "server-2", "server-3"), journal_paths, strict=True)
    },
    "restart_events": json_lines(events_path),
    "snapshot_pairs": {pair["node"]: pair for pair in pairs},
    "server_token_reference": token_reference(token),
})
print(json.dumps(state, sort_keys=True, separators=(",", ":")))
' "$base_file" "$events_file" "$pairs_file" \
        "$journal_one" "$journal_two" "$journal_three"
}

driver_impl_test_a_read_server_token() {
    local address
    pve_ensure_config || return $?
    address=$(pve_test_a_server_address) || return $?
    pve_guest_exec_raw "$address" "$FD_PVE_CONNECT_TIMEOUT" \
        timeout --signal=TERM "${FD_PVE_OPERATION_TIMEOUT}s" \
        cat "$FD_PVE_K3S_SERVER_TOKEN"
}

driver_impl_test_a_propose_server_token() {
    local current_token ca_hash user_part new_secret proposed_token
    current_token=$(driver_impl_test_a_read_server_token) || return $?
    pve_test_a_require_full_server_token \
        "$current_token" 'current server token' || return $?
    ca_hash=${current_token#K10}
    ca_hash=${ca_hash%%::*}
    user_part=${current_token#*::}
    user_part=${user_part%%:*}
    new_secret=$("$FD_PYTHON" -c \
        'import secrets; print(secrets.token_hex(24))') || return $?
    proposed_token="K10${ca_hash}::${user_part}:${new_secret}"
    if [[ $proposed_token == "$current_token" ]]; then
        printf 'pve Test A guard: proposed server token equals the current token\n' >&2
        return 69
    fi
    printf '%s\n' "$proposed_token"
}

driver_impl_test_a_snapshot_pair() {
    local node=$1 guest_id=$2 token=$3 status=0
    pve_test_a_is_server "$node" || {
        printf 'pve Test A guard: snapshot pairing requires a server node\n' >&2
        return 69
    }
    [[ -n $guest_id ]] || {
        printf 'pve Test A guard: snapshot pairing lacks its resolved guest id\n' >&2
        return 69
    }
    pve_test_a_require_full_server_token "$token" 'snapshot token' || return $?
    if [[ $FD_PVE_TEST_A_ROTATED == true ]] || pve_test_a_snapshot_seen "$node"; then
        printf 'pve Test A guard: duplicate or post-rotation snapshot pairing refused\n' >&2
        return 69
    fi
    FD_PVE_TEST_A_OPERATION_TOKEN=$token
    evidence_exec test-a-snapshot-pair "$node" \
        pve_test_a_snapshot_pair_mutation "$node" "$guest_id" || status=$?
    unset FD_PVE_TEST_A_OPERATION_TOKEN
    return "$status"
}

driver_impl_test_a_rotate_server_token() {
    local token=$1 restart_order=$2 status=0
    pve_test_a_require_full_server_token "$token" 'rotation token' || return $?
    pve_test_a_require_restart_order "$restart_order" || return $?
    pve_test_a_require_snapshot_coverage || return $?
    if [[ $FD_PVE_TEST_A_ROTATED == true ]]; then
        printf 'pve Test A guard: this process already performed its one rotation\n' >&2
        return 69
    fi
    FD_PVE_TEST_A_NEW_TOKEN=$token
    FD_PVE_TEST_A_RESTART_ORDER_CSV=$restart_order
    evidence_exec test-a-token-rotate server-1 pve_test_a_rotate_mutation || status=$?
    if ((status != 0)); then
        FD_PVE_TEST_A_NEW_TOKEN=
        FD_PVE_TEST_A_RESTART_ORDER_CSV=
    fi
    return "$status"
}

driver_impl_test_a_restart_node() {
    local node=$1 guest_id=$2 timeout=$3 expected status=0
    pve_test_a_require_node "$node" || return $?
    [[ -n $guest_id ]] || {
        printf 'pve Test A guard: restart lacks its resolved guest id\n' >&2
        return 69
    }
    pve_positive_integer test_a_restart_timeout "$timeout" || return $?
    if [[ $FD_PVE_TEST_A_ROTATED != true || -z $FD_PVE_TEST_A_NEW_TOKEN ]]; then
        printf 'pve Test A guard: restart refused before successful rotation\n' >&2
        return 69
    fi
    expected=$(pve_test_a_expected_restart_node) || {
        printf 'pve Test A guard: every planned node was already restarted\n' >&2
        return 69
    }
    if [[ $node != "$expected" ]]; then
        printf 'pve Test A guard: restart order expected %s, observed %s\n' \
            "$expected" "$node" >&2
        return 69
    fi
    evidence_exec test-a-node-restart "$node" \
        pve_test_a_restart_mutation "$node" "$guest_id" "$timeout" || status=$?
    return "$status"
}

driver_impl_test_a_observe_gate() {
    if [[ $FD_PVE_TEST_A_ROTATED != true \
        || ${#FD_PVE_TEST_A_RESTART_EVENTS[@]} -ne 5 ]]; then
        printf 'pve Test A guard: gate observation requires five completed restarts\n' >&2
        return 69
    fi
    evidence_exec test-a-gate-observation test-a pve_test_a_observe_raw
}

driver_impl_test_b_read_server_token() { pve_real_test_hook_unreviewed; }
driver_impl_test_b_propose_server_token() { pve_real_test_hook_unreviewed; }
driver_impl_test_b_setup() { pve_real_test_hook_unreviewed; }
driver_impl_test_b_break() { pve_real_test_hook_unreviewed; }
driver_impl_test_b_recover() { pve_real_test_hook_unreviewed; }
driver_impl_test_b_observe_gate() { pve_real_test_hook_unreviewed; }

driver_impl_test_c_read_server_token() { pve_real_test_hook_unreviewed; }
driver_impl_test_c_propose_server_token() { pve_real_test_hook_unreviewed; }
driver_impl_test_c_setup() { pve_real_test_hook_unreviewed; }
driver_impl_test_c_break() { pve_real_test_hook_unreviewed; }
driver_impl_test_c_triage() { pve_real_test_hook_unreviewed; }
driver_impl_test_c_recover() { pve_real_test_hook_unreviewed; }
driver_impl_test_c_finish() { pve_real_test_hook_unreviewed; }
driver_impl_test_c_observe_gate() { pve_real_test_hook_unreviewed; }
driver_impl_test_c_observe_runtime_token() { pve_real_test_hook_unreviewed; }
