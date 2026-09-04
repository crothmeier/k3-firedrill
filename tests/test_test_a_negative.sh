#!/usr/bin/env bash
set -Eeuo pipefail

TEST_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TEST_TMP=$(mktemp -d "${TMPDIR:-/tmp}/firedrill-test-a-negative.XXXXXX")
export PYTHONPATH="$TEST_ROOT/py${PYTHONPATH:+:$PYTHONPATH}"
cleanup() {
    rm -rf -- "${TEST_TMP:?}"
}
trap cleanup EXIT

expect_failure() {
    local label=$1
    local expected_status=$2
    local expected_pattern=$3
    shift 3
    local status=0
    "$@" >"$TEST_TMP/$label.out" 2>"$TEST_TMP/$label.err" || status=$?
    if ((status != expected_status)); then
        printf 'negative probe %s returned %s, expected %s\n' \
            "$label" "$status" "$expected_status" >&2
        cat "$TEST_TMP/$label.out" "$TEST_TMP/$label.err" >&2
        return 1
    fi
    if ! grep -q -- "$expected_pattern" "$TEST_TMP/$label.err"; then
        printf 'negative probe %s did not report %q\n' "$label" "$expected_pattern" >&2
        cat "$TEST_TMP/$label.err" >&2
        return 1
    fi
    printf 'NEGATIVE PROBE %s: expected failure exit=%s\n' "$label" "$status"
    cat "$TEST_TMP/$label.err"
}

expect_token_failure() {
    local label=$1
    local token=$2
    local expected_pattern=$3
    local status=0
    printf '%s' "$token" \
        | python3 -m firedrill.test_a validate-token --label probe \
            >"$TEST_TMP/$label.out" 2>"$TEST_TMP/$label.err" || status=$?
    if ((status != 69)) || ! grep -q -- "$expected_pattern" "$TEST_TMP/$label.err"; then
        printf 'negative token probe %s failed its assertion (exit=%s)\n' "$label" "$status" >&2
        cat "$TEST_TMP/$label.err" >&2
        return 1
    fi
    printf 'NEGATIVE PROBE %s: expected failure exit=%s\n' "$label" "$status"
    cat "$TEST_TMP/$label.err"
}

make_fixture() {
    local model_path=$1
    local baseline_path=$2
    local mode=$3
    python3 - "$model_path" "$baseline_path" "$mode" <<'PY'
import sys
from pathlib import Path

from firedrill.mock_model import (
    atomic_json,
    capture_paired_snapshot,
    cluster_state,
    current_server_token,
    empty_model,
    new_guest,
    proposed_server_token,
    rotate_server_token,
)
from firedrill.test_a import EXPECTED_NODES, EXPECTED_SERVERS

model_path, baseline_path, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
lab_id = "fd-negative-probes"
model = empty_model(lab_id)
roles = ("server", "server", "server", "agent", "agent")
for index, (node, role) in enumerate(zip(EXPECTED_NODES, roles, strict=True)):
    spec = {"id": 7100 + index, "short_name": node, "role": role, "name": f"k3fd-{node}"}
    item = new_guest(spec, lab_id)
    item.update(
        {
            "power": "running",
            "installed": True,
            "ready": True,
            "etcd_healthy": role == "server",
            "join_credential_sha256": model["cluster"]["join_credential_sha256"],
            "journal": [f"k3s {role} installed and Ready"],
        }
    )
    model["guests"][str(spec["id"])] = item
atomic_json(baseline_path, cluster_state(model))
if mode == "rotated":
    old_token = current_server_token(model)
    for server in EXPECTED_SERVERS:
        capture_paired_snapshot(model, server, old_token)
    rotate_server_token(
        model,
        proposed_server_token(model),
        ("server-1", "server-2", "server-3"),
    )
atomic_json(model_path, model)
PY
}

restart_all() {
    local model_path=$1
    local node
    for node in server-1 server-2 server-3 agent-1 agent-2; do
        python3 -m firedrill.mock_model --model "$model_path" \
            test-a-restart --lab-id fd-negative-probes \
            --node "$node" --timeout 30 >/dev/null
    done
}

expect_gate_failure() {
    local label=$1
    local baseline_path=$2
    local observation_path=$3
    local expected_check=$4
    local status=0
    python3 -m firedrill.test_a evaluate \
        --run-path "$TEST_TMP/$label-run" \
        --baseline "$baseline_path" \
        --observation "$observation_path" \
        --expected-order server-1,server-2,server-3 \
        >"$TEST_TMP/$label.out" 2>"$TEST_TMP/$label.err" || status=$?
    if ((status != 1)) || ! grep -q -- "\`$expected_check\`.*\*\*FAIL\*\*" \
        "$TEST_TMP/$label.out"; then
        printf 'negative gate probe %s did not fail check %s (exit=%s)\n' \
            "$label" "$expected_check" "$status" >&2
        cat "$TEST_TMP/$label.out" "$TEST_TMP/$label.err" >&2
        return 1
    fi
    printf 'NEGATIVE PROBE %s: expected gate failure exit=%s\n' "$label" "$status"
    grep -- "\`$expected_check\`" "$TEST_TMP/$label.out"
    grep -- 'Overall Test A gate:' "$TEST_TMP/$label.out"
}

valid_token=$(python3 -c \
    'from firedrill.mock_model import current_server_token, empty_model; print(current_server_token(empty_model("probe")))')
agent_token=${valid_token/::server:/::agent:}
bare_token=$(printf '%s' "$valid_token" | python3 -c \
    'import sys; from firedrill.bootstrap import normalize_token; print(normalize_token(sys.stdin.read()))')
expect_token_failure agent-token "$agent_token" 'classification=agent-token'
expect_token_failure bare-token "$bare_token" 'classification=bare-or-short-secret'
expect_token_failure malformed-token 'K10malformed::server:value' \
    'classification=malformed-full-token'

unpaired_model=$TEST_TMP/unpaired.json
unpaired_baseline=$TEST_TMP/unpaired-baseline.json
make_fixture "$unpaired_model" "$unpaired_baseline" plain
expect_failure unpaired-snapshot 69 'unpaired snapshot rejected before mutation' \
    python3 -m firedrill.mock_model --model "$unpaired_model" \
    test-a-snapshot --lab-id fd-negative-probes --node server-1

order_model=$TEST_TMP/order.json
order_baseline=$TEST_TMP/order-baseline.json
make_fixture "$order_model" "$order_baseline" rotated
expect_failure restart-order 69 'restart-order violation' \
    python3 -m firedrill.mock_model --model "$order_model" \
    test-a-restart --lab-id fd-negative-probes --node server-2 --timeout 30

timeout_model=$TEST_TMP/timeout.json
timeout_baseline=$TEST_TMP/timeout-baseline.json
make_fixture "$timeout_model" "$timeout_baseline" rotated
python3 -m firedrill.mock_model --model "$timeout_model" \
    inject-health-delay --lab-id fd-negative-probes --node server-1 --seconds 31 >/dev/null
expect_failure bounded-health-timeout 70 '"status":"timeout"' \
    python3 -m firedrill.mock_model --model "$timeout_model" \
    test-a-restart --lab-id fd-negative-probes --node server-1 --timeout 30

journal_model=$TEST_TMP/journal.json
journal_baseline=$TEST_TMP/journal-baseline.json
journal_observation=$TEST_TMP/journal-observation.json
make_fixture "$journal_model" "$journal_baseline" rotated
python3 -m firedrill.mock_model --model "$journal_model" \
    inject-decryption-failure --lab-id fd-negative-probes --node server-2 >/dev/null
restart_all "$journal_model"
python3 -m firedrill.mock_model --model "$journal_model" \
    test-a-observe --lab-id fd-negative-probes >"$journal_observation"
expect_gate_failure injected-decryption-journal "$journal_baseline" "$journal_observation" \
    zero-bootstrap-decryption-journal-failures

keys_model=$TEST_TMP/keys.json
keys_baseline=$TEST_TMP/keys-baseline.json
keys_observation=$TEST_TMP/keys-observation.json
make_fixture "$keys_model" "$keys_baseline" rotated
restart_all "$keys_model"
extra_key=$(python3 - "$keys_model" <<'PY'
import json
import sys
from pathlib import Path

existing = set(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["cluster"]["bootstrap_keys"])
print(next(key for key in ("/bootstrap/ffffffffffff", "/bootstrap/eeeeeeeeeeee") if key not in existing))
PY
)
python3 -m firedrill.mock_model --model "$keys_model" \
    inject-bootstrap-key --lab-id fd-negative-probes --key-name "$extra_key" >/dev/null
python3 -m firedrill.mock_model --model "$keys_model" \
    test-a-observe --lab-id fd-negative-probes >"$keys_observation"
expect_gate_failure two-bootstrap-keys "$keys_baseline" "$keys_observation" \
    exactly-one-bootstrap-key

raw_model=$TEST_TMP/raw.json
raw_baseline=$TEST_TMP/raw-baseline.json
raw_stdout=$TEST_TMP/raw-stdout
raw_stderr=$TEST_TMP/raw-stderr
raw_run=$TEST_TMP/raw-run
make_fixture "$raw_model" "$raw_baseline" rotated
raw_token=$(python3 -m firedrill.mock_model --model "$raw_model" \
    test-a-read-token --lab-id fd-negative-probes)
python3 -m firedrill.mock_model --model "$raw_model" \
    inject-raw-output --lab-id fd-negative-probes --value "$raw_token" >/dev/null
restart_all "$raw_model"
python3 -m firedrill.mock_model --model "$raw_model" \
    test-a-observe --lab-id fd-negative-probes >"$raw_stdout"
: >"$raw_stderr"
FIREDRILL_ACTIVE_TOKENS_JSON=$(
    printf '%s\n%s\n' "$raw_token" "$raw_token" | python3 -m firedrill.test_a registry-json
)
export FIREDRILL_ACTIVE_TOKENS_JSON
python3 -m firedrill.evidence \
    --run-path "$raw_run" --sequence 1 --label planted-modeled-output --node test-a \
    --started-at 2026-08-14T00:00:00Z --ended-at 2026-08-14T00:00:01Z \
    --exit-code 0 --stdout "$raw_stdout" --stderr "$raw_stderr" \
    -- modeled-output "$raw_token"
artifact_count=$(python3 - "$raw_run/evidence" "$raw_token" <<'PY'
import sys
from pathlib import Path

from firedrill.bootstrap import normalize_token

root, token = Path(sys.argv[1]), sys.argv[2]
artifacts = [path for path in root.rglob("*") if path.is_file()]
for artifact in artifacts:
    content = artifact.read_text(encoding="utf-8")
    assert token not in content, artifact
    assert normalize_token(token) not in content, artifact
print(len(artifacts))
PY
)
printf 'NEGATIVE PROBE planted-raw-modeled-output: PASS raw candidate absent from %s evidence artifacts\n' \
    "$artifact_count"

identity_root=$TEST_TMP/provision-identity-positive
identity_config=$identity_root/provision.conf
identity_live_config=$identity_root/live.conf
mkdir -p "$identity_root"
sed "s|run_dir=./runs|run_dir=$identity_root/runs|" \
    "$TEST_ROOT/firedrill.conf.example" >"$identity_config"
"$TEST_ROOT/firedrill" --config "$identity_config" provision >/dev/null
"$TEST_ROOT/firedrill" --config "$identity_config" baseline >/dev/null
identity_lab_id=$(python3 - "$identity_root/runs/current.json" <<'PY'
import json
import sys
from pathlib import Path

print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["lab_id"])
PY
)
identity_run_path=$(python3 - "$identity_root/runs/current.json" <<'PY'
import json
import sys
from pathlib import Path

print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["run_path"])
PY
)
for guest_id in 7100 7101 7102 7103 7104; do
    python3 -m firedrill.mock_model --model "$identity_run_path/driver/mock.json" \
        snapshot-create --lab-id "$identity_lab_id" "$guest_id" \
        post-provision-baseline >/dev/null
done
sed \
    -e 's/^snapshot_name=.*/snapshot_name=post-provision-baseline/' \
    -e 's/^server_restart_order=.*/server_restart_order=server-2,server-3,server-1/' \
    "$identity_config" >"$identity_live_config"
"$TEST_ROOT/firedrill" --config "$identity_live_config" test-a \
    >"$identity_root/test-a.out"
grep -Fq '"check":"provision-identity-and-inventory"' \
    "$identity_root/test-a.out"
grep -Fq 'Overall Test A gate: **PASS**' "$identity_root/test-a.out"
printf 'PASS: test-a SETUP accepts post-provision snapshot_name and restart-order changes under provision identity\n'

drift_root=$TEST_TMP/provision-identity-negative
drift_config=$drift_root/provision.conf
drift_live_config=$drift_root/live.conf
mkdir -p "$drift_root"
sed "s|run_dir=./runs|run_dir=$drift_root/runs|" \
    "$TEST_ROOT/firedrill.conf.example" >"$drift_config"
"$TEST_ROOT/firedrill" --config "$drift_config" provision >/dev/null
"$TEST_ROOT/firedrill" --config "$drift_config" baseline >/dev/null
sed 's/^template_vmid=.*/template_vmid=9001/' \
    "$drift_config" >"$drift_live_config"
expect_failure test-a-provision-identity-drift 69 \
    'provision-identity-and-inventory' \
    "$TEST_ROOT/firedrill" --config "$drift_live_config" test-a

collision_run=$TEST_TMP/test-a-attempt-archive-collision
python3 - "$collision_run" <<'PY'
import json
import sys
from pathlib import Path

run_path = Path(sys.argv[1])
live_dir = run_path / "evidence" / "test-a"
existing_archive = run_path / "evidence" / "test-a.attempts" / "20260902T070135Z"
live_dir.mkdir(parents=True)
existing_archive.mkdir(parents=True)
(existing_archive / "sentinel.txt").write_text("preserve me\n", encoding="utf-8")
(live_dir / "phases.json").write_text(
    json.dumps(
        [
            {
                "phase": "SETUP",
                "started_at": "2026-09-02T07:01:35.000Z",
                "ended_at": "2026-09-02T07:01:36.000Z",
            }
        ]
    )
    + "\n",
    encoding="utf-8",
)
(live_dir / "gate.json").write_text('{"test":"test-a","verdict":"PASS"}\n', encoding="utf-8")
state = {
    "lab_id": "fd-collision-probe",
    "lifecycle": "baseline",
    "preserved": {"value": "unchanged"},
    "tests": {
        "test-a": {
            "verdict": "PASS",
            "started_at": "2026-09-02T07:01:35.000Z",
            "ended_at": "2026-09-02T07:02:00.000Z",
            "phase_evidence_path": "evidence/test-a/phases.json",
            "gate_evidence_path": "evidence/test-a/gate.json",
            "gate_table_path": "evidence/test-a/gate-table.md",
        }
    },
}
(run_path / "state.json").write_text(
    json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
PY
collision_output=$(python3 -m firedrill.state archive-test-a-attempt \
    --run-path "$collision_run")
[[ $collision_output == \
    'test-a: archived prior attempt evidence to evidence/test-a.attempts/20260902T070135Z-2/' ]]
python3 - "$collision_run" <<'PY'
import json
import sys
from pathlib import Path

run_path = Path(sys.argv[1])
attempts = run_path / "evidence" / "test-a.attempts"
assert (attempts / "20260902T070135Z" / "sentinel.txt").read_text(
    encoding="utf-8"
) == "preserve me\n"
assert (attempts / "20260902T070135Z-2" / "phases.json").is_file()
assert not (run_path / "evidence" / "test-a").exists()
state = json.loads((run_path / "state.json").read_text(encoding="utf-8"))
assert state["preserved"] == {"value": "unchanged"}
assert "test-a" not in state["tests"]
history = state["tests_history"]["test-a"]
assert list(history) == ["20260902T070135Z-2"]
result = history["20260902T070135Z-2"]
assert result["phase_evidence_path"] == (
    "evidence/test-a.attempts/20260902T070135Z-2/phases.json"
)
assert result["gate_evidence_path"] == (
    "evidence/test-a.attempts/20260902T070135Z-2/gate.json"
)
PY
printf '%s\n' \
    'NEGATIVE PROBE test-a-attempt-archive-collision: suffix applied, no overwrite'
