#!/usr/bin/env bash
set -Eeuo pipefail

TEST_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TEST_TMP=$(mktemp -d "${TMPDIR:-/tmp}/firedrill-guest-op.XXXXXX")
OP=$TEST_ROOT/guest/firedrill-op
cleanup() {
    rm -rf -- "${TEST_TMP:?}"
}
trap cleanup EXIT

stat_uid() {
    stat -c '%u' "$1" 2>/dev/null || stat -f '%u' "$1"
}

sha_file() {
    local output
    if command -v shasum >/dev/null 2>&1; then
        output=$(shasum -a 256 "$1")
    else
        output=$(sha256sum "$1")
    fi
    printf '%s\n' "${output%%[[:space:]]*}"
}

expect_failure() {
    local label=$1 expected_status=$2 expected_pattern=$3 status=0
    shift 3
    "$@" >"$TEST_TMP/$label.out" 2>"$TEST_TMP/$label.err" || status=$?
    if ((status != expected_status)) \
        || ! grep -Fq -- "$expected_pattern" "$TEST_TMP/$label.err"; then
        printf 'guest firedrill-op negative probe %s failed (exit=%s expected=%s)\n' \
            "$label" "$status" "$expected_status" >&2
        sed -n '1,120p' "$TEST_TMP/$label.out" "$TEST_TMP/$label.err" >&2
        return 1
    fi
    printf 'NEGATIVE PROBE guest-op-%s: expected failure exit=%s\n' \
        "$label" "$status"
    sed -n '1,120p' "$TEST_TMP/$label.err"
}

ARTIFACT_DIR=$TEST_TMP/artifacts
INSTALL_DIR=$TEST_TMP/bin
CONFIG_PATH=$TEST_TMP/op.env
JOIN_PATH=$TEST_TMP/join.env
K3S_ARTIFACT=$ARTIFACT_DIR/k3s
INSTALL_ARTIFACT=$ARTIFACT_DIR/install.sh
ETCDCTL_ARTIFACT=$ARTIFACT_DIR/etcdctl
INSTALLED_K3S=$INSTALL_DIR/k3s
KUBECONFIG=$TEST_TMP/k3s.yaml
SERVER_CA=$TEST_TMP/server-ca.crt
SERVER_TOKEN=$TEST_TMP/server-token
SERVER_ENV=$TEST_TMP/k3s.service.env
AGENT_ENV=$TEST_TMP/k3s-agent.service.env
ETCD_CA=$TEST_TMP/etcd-ca.crt
ETCD_CERT=$TEST_TMP/etcd-client.crt
ETCD_KEY=$TEST_TMP/etcd-client.key
SNAPSHOT_DIR=$TEST_TMP/snapshots
INSTALL_LOG=$TEST_TMP/install.log
ANNOTATION_LOG=$TEST_TMP/annotations.log
NODES_FIXTURE=$TEST_TMP/nodes.fixture
ETCD_FIXTURE=$TEST_TMP/etcd.fixture
BOOTSTRAP_FIXTURE=$TEST_TMP/bootstrap.fixture
TEST_UID=$(stat_uid "$TEST_TMP")
TOKEN_VALUE=fixture-join-secret
JOIN_DIGEST_OUTPUT=$(printf '%s' "$TOKEN_VALUE" | shasum -a 256)
JOIN_DIGEST=${JOIN_DIGEST_OUTPUT%%[[:space:]]*}

mkdir -p "$ARTIFACT_DIR" "$INSTALL_DIR" "$SNAPSHOT_DIR"
printf '%s\n' '#!/usr/bin/env sh' 'exit 0' >"$K3S_ARTIFACT"
# The single-quoted strings are the literal body of the generated fixture.
# shellcheck disable=SC2016
printf '%s\n' \
    '#!/usr/bin/env sh' \
    'set -eu' \
    ': "${K3S_TOKEN:?}" "${INSTALL_K3S_EXEC:?}" "${FIREDRILL_OP_INSTALL_LOG:?}"' \
    'printf "%s\n" "$INSTALL_K3S_EXEC" >>"$FIREDRILL_OP_INSTALL_LOG"' \
    'case $INSTALL_K3S_EXEC in' \
    '  agent*) printf "K3S_TOKEN=%s\n" "$K3S_TOKEN" >"$FIREDRILL_OP_AGENT_ENV" ;;' \
    '  *) printf "%s\n" "$K3S_TOKEN" >"$FIREDRILL_OP_SERVER_TOKEN" ;;' \
    'esac' \
    'chmod 0600 "$FIREDRILL_OP_AGENT_ENV" "$FIREDRILL_OP_SERVER_TOKEN" 2>/dev/null || true' \
    'exit 0' >"$INSTALL_ARTIFACT"
printf '%s\n' '#!/usr/bin/env sh' 'exit 0' >"$ETCDCTL_ARTIFACT"
chmod 0755 "$K3S_ARTIFACT" "$INSTALL_ARTIFACT" "$ETCDCTL_ARTIFACT"
printf 'fixture kubeconfig\n' >"$KUBECONFIG"
printf 'fixture server ca\n' >"$SERVER_CA"
printf 'fixture etcd ca\n' >"$ETCD_CA"
printf 'fixture etcd cert\n' >"$ETCD_CERT"
printf 'fixture etcd key\n' >"$ETCD_KEY"
: >"$SERVER_ENV"
: >"$AGENT_ENV"
: >"$INSTALL_LOG"
: >"$ANNOTATION_LOG"

K3S_SHA=$(sha_file "$K3S_ARTIFACT")
INSTALL_SHA=$(sha_file "$INSTALL_ARTIFACT")
ETCDCTL_SHA=$(sha_file "$ETCDCTL_ARTIFACT")

write_config() {
    local role=$1 k3s_sha=${2:-$K3S_SHA} k3s_path=${3:-$K3S_ARTIFACT}
    {
        printf 'node_name=server-1\n'
        printf 'node_role=%s\n' "$role"
        printf 'cluster_node_roles=server-1:server,server-2:server,server-3:server,agent-1:agent,agent-2:agent\n'
        printf 'join_credential_sha256=%s\n' "$JOIN_DIGEST"
        printf 'guest_join_file=%s\n' "$JOIN_PATH"
        printf 'k3s_version=v1.34.4+k3s1\n'
        printf 'node_ready_timeout_seconds=2\n'
        printf 'k3s_binary_artifact_path=%s\n' "$k3s_path"
        printf 'k3s_binary_sha256=%s\n' "$k3s_sha"
        printf 'k3s_install_script_artifact_path=%s\n' "$INSTALL_ARTIFACT"
        printf 'k3s_install_script_sha256=%s\n' "$INSTALL_SHA"
        printf 'etcdctl_artifact_path=%s\n' "$ETCDCTL_ARTIFACT"
        printf 'etcdctl_sha256=%s\n' "$ETCDCTL_SHA"
        printf 'k3s_installed_binary_path=%s\n' "$INSTALLED_K3S"
        printf 'k3s_kubeconfig_path=%s\n' "$KUBECONFIG"
        printf 'k3s_agent_kubeconfig_path=%s\n' "$KUBECONFIG"
        printf 'k3s_server_ca_path=%s\n' "$SERVER_CA"
        printf 'k3s_server_token_path=%s\n' "$SERVER_TOKEN"
        printf 'k3s_server_service_env_path=%s\n' "$SERVER_ENV"
        printf 'k3s_agent_service_env_path=%s\n' "$AGENT_ENV"
        printf 'k3s_server_systemd_unit=k3s\n'
        printf 'k3s_agent_systemd_unit=k3s-agent\n'
        printf 'k3s_etcd_endpoint=https://127.0.0.1:2379\n'
        printf 'k3s_etcd_ca_path=%s\n' "$ETCD_CA"
        printf 'k3s_etcd_client_cert_path=%s\n' "$ETCD_CERT"
        printf 'k3s_etcd_client_key_path=%s\n' "$ETCD_KEY"
        printf 'k3s_etcd_snapshot_dir=%s\n' "$SNAPSHOT_DIR"
    } >"$CONFIG_PATH"
    chmod 0600 "$CONFIG_PATH"
}

write_join() {
    {
        printf 'server_endpoint=https://192.0.2.10:6443\n'
        printf 'join_credential=%s\n' "$TOKEN_VALUE"
    } >"$JOIN_PATH"
    chmod 0600 "$JOIN_PATH"
}

run_op() {
    FIREDRILL_OP_TESTING=1 \
    FIREDRILL_OP_TEST_UID="$TEST_UID" \
    FIREDRILL_OP_CONFIG_PATH="$CONFIG_PATH" \
    FIREDRILL_OP_INSTALL_LOG="$INSTALL_LOG" \
    FIREDRILL_OP_SERVER_TOKEN="$SERVER_TOKEN" \
    FIREDRILL_OP_AGENT_ENV="$AGENT_ENV" \
    FIREDRILL_OP_ANNOTATION_LOG="$ANNOTATION_LOG" \
    FIREDRILL_OP_NODES_FIXTURE="$NODES_FIXTURE" \
    FIREDRILL_OP_ETCD_MEMBERS_FIXTURE="$ETCD_FIXTURE" \
    FIREDRILL_OP_BOOTSTRAP_FIXTURE="$BOOTSTRAP_FIXTURE" \
        bash "$OP" "$@"
}

write_config server-cluster-init
write_join
install_output=$(run_op install-k3s server-cluster-init v1.34.4+k3s1)
[[ $install_output == 'installed server-cluster-init v1.34.4+k3s1' ]]
[[ $(sha_file "$INSTALLED_K3S") == "$K3S_SHA" ]]
grep -Fq 'server --cluster-init --node-name server-1' "$INSTALL_LOG"
printf 'PASS: guest-op offline cluster-init used the verified staged artifacts\n'

write_config server-join
write_join
run_op install-k3s server-join v1.34.4+k3s1 >/dev/null
grep -Fq 'server --node-name server-1' "$INSTALL_LOG"
write_config agent
write_join
run_op install-k3s agent v1.34.4+k3s1 >/dev/null
grep -Fq 'agent --node-name server-1' "$INSTALL_LOG"
printf 'PASS: guest-op install output contracts cover all three reviewed roles\n'

write_config server-cluster-init
write_join
expect_failure unknown-role 64 'install-k3s role is unknown' \
    run_op install-k3s mystery v1.34.4+k3s1

write_config server-cluster-init "$(printf '0%.0s' {1..64})"
write_join
expect_failure artifact-hash-mismatch 69 'K3s binary artifact SHA-256 mismatch' \
    run_op install-k3s server-cluster-init v1.34.4+k3s1

write_config server-cluster-init CHANGEME
write_join
expect_failure artifact-hash-placeholder 69 'SHA-256 pin is missing, malformed, or a placeholder' \
    run_op install-k3s server-cluster-init v1.34.4+k3s1

write_config server-cluster-init "$K3S_SHA" "$TEST_TMP/missing-k3s"
write_join
expect_failure artifact-missing 69 'K3s binary artifact is absent' \
    run_op install-k3s server-cluster-init v1.34.4+k3s1

write_config server-cluster-init
rm -f -- "$JOIN_PATH"
expect_failure join-missing 69 'join file is missing' \
    run_op install-k3s server-cluster-init v1.34.4+k3s1

write_join
chmod 0644 "$JOIN_PATH"
expect_failure join-wrong-mode 69 'join file must be owned' \
    run_op install-k3s server-cluster-init v1.34.4+k3s1

write_config server-cluster-init
write_join
run_op install-k3s server-cluster-init v1.34.4+k3s1 >/dev/null
expect_failure wait-ready-timeout 70 'wait-ready timed out after 2 seconds' \
    env FIREDRILL_OP_READY_AFTER_ATTEMPT=99 FIREDRILL_OP_ETCD_HEALTHY_AFTER_ATTEMPT=99 \
    FIREDRILL_OP_TESTING=1 FIREDRILL_OP_TEST_UID="$TEST_UID" \
    FIREDRILL_OP_CONFIG_PATH="$CONFIG_PATH" bash "$OP" wait-ready

FIREDRILL_OP_READY_AFTER_ATTEMPT=1 FIREDRILL_OP_ETCD_HEALTHY_AFTER_ATTEMPT=1 \
    run_op wait-ready >"$TEST_TMP/wait-ready.out"
[[ $(sed -n '1p' "$TEST_TMP/wait-ready.out") == ready ]]
printf 'PASS: guest-op bounded wait converged with the role credential digest verified\n'

credential_digest=$JOIN_DIGEST
{
    printf 'server-1|server|true|%s\n' "$credential_digest"
    printf 'server-2|server|true|%s\n' "$credential_digest"
    printf 'server-3|server|true|%s\n' "$credential_digest"
    printf 'agent-1|agent|true|%s\n' "$credential_digest"
    printf 'agent-2|agent|true|%s\n' "$credential_digest"
} >"$NODES_FIXTURE"
printf '%s\n' 'server-1|true' 'server-2|true' 'server-3|true' >"$ETCD_FIXTURE"
printf '/bootstrap/aaaaaaaaaaaa\n' >"$BOOTSTRAP_FIXTURE"
run_op capture-cluster-state >"$TEST_TMP/cluster-state.json"
python3 - "$TEST_TMP/cluster-state.json" <<'PY'
import json
import sys
from pathlib import Path

state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert set(state) == {
    "nodes",
    "all_nodes_ready",
    "etcd_members",
    "all_etcd_members_healthy",
    "bootstrap_keys",
    "ca_sha256",
}
assert len(state["nodes"]) == 5 and state["all_nodes_ready"] is True
assert len(state["etcd_members"]) == 3 and state["all_etcd_members_healthy"] is True
assert state["bootstrap_keys"] == ["/bootstrap/aaaaaaaaaaaa"]
assert len(state["ca_sha256"]) == 64
assert all(set(item) == {"name", "role", "ready", "join_credential_sha256"} for item in state["nodes"])
assert all(set(item) == {"name", "healthy"} for item in state["etcd_members"])
PY
printf 'PASS: guest-op capture-cluster-state emitted exactly the six-field contract\n'

if grep -Eqi 'curl|wget|fetch|https?://get\.k3s' "$OP"; then
    printf 'guest firedrill-op unexpectedly contains a download path\n' >&2
    exit 1
fi
printf 'PASS: guest-op contains no download implementation\n'
