#!/usr/bin/env bash

node_index() {
    case $1 in
        server-1) printf '0\n' ;;
        server-2) printf '1\n' ;;
        server-3) printf '2\n' ;;
        agent-1) printf '3\n' ;;
        agent-2) printf '4\n' ;;
        *)
            printf 'node error: unknown node %q\n' "$1" >&2
            return 64
            ;;
    esac
}

node_id() {
    local index
    index=$(node_index "$1")
    config_inventory_field "$index" id
}

node_read_join_credential() {
    local credential_path=$1 credential extra
    if [[ ! -f $credential_path || -L $credential_path ]]; then
        printf 'node install error: join credential source must be one regular non-symlink file\n' >&2
        return 69
    fi
    {
        IFS= read -r credential || {
            printf 'node install error: join credential source is empty\n' >&2
            return 69
        }
        if IFS= read -r extra; then
            : "$extra"
            printf 'node install error: join credential source must contain exactly one line\n' >&2
            return 69
        fi
    } <"$credential_path"
    if [[ -z $credential || $credential == *[[:space:]]* ]]; then
        printf 'node install error: join credential must be non-empty and contain no whitespace\n' >&2
        return 69
    fi
    printf '%s' "$credential"
}

node_register_join_values() {
    local credential=$1 endpoint=$2
    FIREDRILL_ACTIVE_TOKENS_JSON=$(
        printf '%s\n%s\n' "$credential" "$endpoint" \
            | "$FD_PYTHON" -c '
import json, os, sys
from firedrill.bootstrap import normalize_token

lines = sys.stdin.read().splitlines()
if len(lines) != 2 or not all(lines):
    raise SystemExit("join redaction registry requires credential and endpoint")
values = json.loads(os.environ.get("FIREDRILL_ACTIVE_TOKENS_JSON", "[]"))
for value in (lines[0], normalize_token(lines[0]), lines[1]):
    if value not in values:
        values.append(value)
print(json.dumps(values, separators=(",", ":")))
'
    ) || return $?
    export FIREDRILL_ACTIVE_TOKENS_JSON
}

node_join_credential_digest() {
    printf '%s' "$1" | "$FD_PYTHON" -c '
import hashlib, sys
from firedrill.bootstrap import normalize_token

credential = sys.stdin.read()
if not credential:
    raise SystemExit(69)
print(hashlib.sha256(normalize_token(credential).encode()).hexdigest())
'
}

node_cluster_roles() {
    local count index node role result separator
    count=$(config_inventory_count) || return $?
    result=
    separator=
    for ((index = 0; index < count; index++)); do
        node=$(config_inventory_field "$index" short_name) || return $?
        role=$(config_inventory_field "$index" role) || return $?
        result+="$separator$node:$role"
        separator=,
    done
    printf '%s\n' "$result"
}

node_write_runtime_config() {
    local output=$1 node=$2 role=$3 join_digest=$4 key value cluster_roles
    cluster_roles=$(node_cluster_roles) || return $?
    {
        printf 'node_name=%s\n' "$node"
        printf 'node_role=%s\n' "$role"
        printf 'cluster_node_roles=%s\n' "$cluster_roles"
        printf 'join_credential_sha256=%s\n' "$join_digest"
        for key in \
            guest_join_file k3s_version node_ready_timeout_seconds \
            k3s_binary_artifact_path k3s_binary_sha256 \
            k3s_install_script_artifact_path k3s_install_script_sha256 \
            etcdctl_artifact_path etcdctl_sha256 k3s_installed_binary_path \
            k3s_kubeconfig_path k3s_agent_kubeconfig_path k3s_server_ca_path \
            k3s_server_token_path \
            k3s_server_service_env_path k3s_agent_service_env_path \
            k3s_server_systemd_unit k3s_agent_systemd_unit k3s_etcd_endpoint \
            k3s_etcd_ca_path k3s_etcd_client_cert_path \
            k3s_etcd_client_key_path k3s_etcd_snapshot_dir; do
            value=$(config_get "values.$key") || return $?
            printf '%s=%s\n' "$key" "$value"
        done
    } >"$output"
}

node_install_k3s_pve() {
    local node=$1 role=$2 version=$3 timeout=$4
    local credential_path credential join_digest server_ip api_port endpoint
    local runtime_path join_path runtime_file join_file status
    credential_path=$(config_get values.k3s_join_credential_file) || return $?
    credential=$(node_read_join_credential "$credential_path") || return $?
    server_ip=$(config_inventory_field 0 ip) || return $?
    api_port=$(config_get values.k3s_api_port) || return $?
    endpoint="https://$server_ip:$api_port"
    node_register_join_values "$credential" "$endpoint" || return $?
    join_digest=$(node_join_credential_digest "$credential") || return $?

    runtime_path=$(config_get values.firedrill_op_config_path) || return $?
    join_path=$(config_get values.guest_join_file) || return $?
    runtime_file=$(mktemp "${TMPDIR:-/tmp}/firedrill-op-config.XXXXXX") || return $?
    join_file=$(mktemp "${TMPDIR:-/tmp}/firedrill-join.XXXXXX") || return $?
    FD_TEMP_FILES+=("$runtime_file" "$join_file")
    node_write_runtime_config "$runtime_file" "$node" "$role" "$join_digest" || return $?
    {
        printf 'server_endpoint=%s\n' "$endpoint"
        printf 'join_credential=%s\n' "$credential"
    } >"$join_file"
    unset credential

    driver_guest_put "$node" "$runtime_file" "$runtime_path" || return $?
    driver_guest_put "$node" "$join_file" "$join_path" || return $?
    status=0
    driver_guest_exec "$node" "$timeout" -- \
        env "FIREDRILL_OP_CONFIG_PATH=$runtime_path" \
        firedrill-op install-k3s "$role" "$version" || status=$?
    if ((status != 0)); then
        return "$status"
    fi
    driver_guest_exec "$node" "$timeout" -- rm -f -- "$join_path"
}

node_install_k3s() {
    local node=$1
    local role=$2
    local version timeout driver
    version=$(config_get values.k3s_version)
    timeout=$(config_get values.k3s_install_timeout_seconds)
    driver=$(config_get values.driver)
    if [[ $driver == pve ]]; then
        node_install_k3s_pve "$node" "$role" "$version" "$timeout"
        return
    fi
    driver_guest_exec "$node" "$timeout" -- \
        firedrill-op install-k3s "$role" "$version"
}

node_wait_ready() {
    local node=$1
    local timeout=${2:-}
    local driver runtime_path
    if [[ -z $timeout ]]; then
        timeout=$(config_get values.node_ready_timeout_seconds)
    fi
    driver=$(config_get values.driver)
    if [[ $driver == pve ]]; then
        runtime_path=$(config_get values.firedrill_op_config_path)
        driver_guest_exec "$node" "$timeout" -- \
            env "FIREDRILL_OP_CONFIG_PATH=$runtime_path" firedrill-op wait-ready
        return
    fi
    driver_guest_exec "$node" "$timeout" -- firedrill-op wait-ready
}

cluster_capture_state() {
    local timeout driver runtime_path
    timeout=$(config_get values.cluster_capture_timeout_seconds)
    driver=$(config_get values.driver)
    if [[ $driver == pve ]]; then
        runtime_path=$(config_get values.firedrill_op_config_path)
        driver_guest_exec server-1 "$timeout" -- \
            env "FIREDRILL_OP_CONFIG_PATH=$runtime_path" \
            firedrill-op capture-cluster-state
        return
    fi
    driver_guest_exec server-1 "$timeout" -- firedrill-op capture-cluster-state
}

cluster_assert_healthy_file() {
    local state_file=$1
    "$FD_PYTHON" - "$state_file" <<'PY'
import json
import sys
from pathlib import Path

state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if len(state.get("nodes", [])) != 5 or not state.get("all_nodes_ready"):
    raise SystemExit("health assertion failed: expected all five nodes Ready")
if len(state.get("etcd_members", [])) != 3 or not state.get("all_etcd_members_healthy"):
    raise SystemExit("health assertion failed: expected all three etcd members healthy")
if len(state.get("bootstrap_keys", [])) != 1:
    raise SystemExit("health assertion failed: expected exactly one bootstrap key")
if not state.get("ca_sha256"):
    raise SystemExit("health assertion failed: CA hash is absent")
PY
}
