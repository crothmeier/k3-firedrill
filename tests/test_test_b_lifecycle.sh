#!/usr/bin/env bash
set -Eeuo pipefail

TEST_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TEST_TMP=$(mktemp -d "${TMPDIR:-/tmp}/firedrill-test-b-lifecycle.XXXXXX")
export PYTHONPATH="$TEST_ROOT/py${PYTHONPATH:+:$PYTHONPATH}"
cleanup() {
    rm -rf -- "${TEST_TMP:?}"
}
trap cleanup EXIT

config=$TEST_TMP/firedrill.conf
sed "s|run_dir=./runs|run_dir=$TEST_TMP/runs|" \
    "$TEST_ROOT/firedrill.conf.example" >"$config"

"$TEST_ROOT/firedrill" --config "$config" preflight >/dev/null
"$TEST_ROOT/firedrill" --config "$config" provision >/dev/null
"$TEST_ROOT/firedrill" --config "$config" baseline >/dev/null
"$TEST_ROOT/firedrill" --config "$config" test-b >"$TEST_TMP/test-b.out"
grep -Fq 'Overall Test B gate: **PASS**' "$TEST_TMP/test-b.out"
grep -Fq '"crash_signature_observed":true' "$TEST_TMP/test-b.out"
grep -Fq '"bystanders_healthy":true' "$TEST_TMP/test-b.out"
grep -Fq '"precedence_enumeration":' "$TEST_TMP/test-b.out"
grep -Fq '"deletion_records":' "$TEST_TMP/test-b.out"
grep -Fq '"recovery_duration_seconds":' "$TEST_TMP/test-b.out"

report_path=$("$TEST_ROOT/firedrill" --config "$config" report)
[[ -s $report_path ]]
grep -Fq 'Overall Test B gate: **PASS**' "$report_path"
grep -Fq '### Test B precedence enumeration' "$report_path"
grep -Fq '### Test B exact-path deletion records' "$report_path"

lab_id=$(python3 - "$TEST_TMP/runs/current.json" <<'PY'
import json
import sys
from pathlib import Path

print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["lab_id"])
PY
)
run_path=$(python3 - "$TEST_TMP/runs/current.json" <<'PY'
import json
import sys
from pathlib import Path

print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["run_path"])
PY
)

python3 - "$run_path" "$report_path" <<'PY'
import json
import sys
from pathlib import Path

from firedrill.bootstrap import normalize_token
from firedrill.mock_model import server_token_for_epoch
from firedrill.test_b_model import CRASH_SIGNATURE

run_path = Path(sys.argv[1])
report_path = Path(sys.argv[2])
records = [
    json.loads(line)
    for line in (run_path / "evidence" / "commands.jsonl").read_text(encoding="utf-8").splitlines()
]
assert [record["sequence"] for record in records] == list(range(1, len(records) + 1))
assert any(record["label"] == "test-b-setup" for record in records)
assert any(record["label"] == "test-b-break" for record in records)
assert any(record["label"] == "test-b-recovery" for record in records)
assert any(record["label"] == "test-b-gate-evaluate" for record in records)
token_assertions = [
    json.loads(record["stdout"])
    for record in records
    if record["label"] == "test-b-token-format-assertion"
]
assert len(token_assertions) == 1
assert token_assertions[0]["verdict"] == "PASS"

evidence_dir = run_path / "evidence" / "test-b"
phases = json.loads((evidence_dir / "phases.json").read_text(encoding="utf-8"))
assert [phase["phase"] for phase in phases] == ["SETUP", "BREAK", "RECOVERY", "GATE"]
assert [phase["sequence"] for phase in phases] == sorted(
    phase["sequence"] for phase in phases
)
setup = json.loads((evidence_dir / "setup.json").read_text(encoding="utf-8"))
assert set(setup["snapshot_pairs"]) == {"server-1", "server-2", "server-3"}
assert setup["rotated_without_full_roll"] is True
broken = json.loads((evidence_dir / "break.json").read_text(encoding="utf-8"))
assert broken["crash_signature"] == CRASH_SIGNATURE
assert broken["crash_signature_observed"] is True
assert broken["bystanders_healthy"] is True
assert broken["quorum_intact"] is True
assert broken["api_served"] is True
recovery = json.loads((evidence_dir / "recovery.json").read_text(encoding="utf-8"))
manifest = json.loads((run_path / "manifest.json").read_text(encoding="utf-8"))
test_b_config = manifest["config"]["test_b"]
assert [item["path"] for item in recovery["deletion_records"]] == test_b_config[
    "deletion_allowlist"
]
assert all(item["before"]["type"] == "regular-file" for item in recovery["deletion_records"])
assert all(item["after"]["exists"] is False for item in recovery["deletion_records"])
assert [
    (item["surface"], item["path"]) for item in recovery["precedence_enumeration"]
] == [
    (item["surface"], item["path"]) for item in test_b_config["precedence_surfaces"]
]
assert recovery["recovery_duration_seconds"] >= 0
gate = json.loads((evidence_dir / "gate.json").read_text(encoding="utf-8"))
assert gate["verdict"] == "PASS"
assert len(gate["checks"]) == 13
assert all(check["verdict"] == "PASS" and check["coverage"] for check in gate["checks"])
state = json.loads((run_path / "state.json").read_text(encoding="utf-8"))
assert state["tests"]["test-b"]["verdict"] == "PASS"

raw_tokens = {server_token_for_epoch(state["lab_id"], epoch) for epoch in (0, 1)}
secret_free_paths = [run_path / "state.json", run_path / "driver" / "mock.json", report_path]
secret_free_paths.extend(path for path in (run_path / "evidence").rglob("*") if path.is_file())
for path in secret_free_paths:
    content = path.read_text(encoding="utf-8")
    for token in raw_tokens:
        assert token not in content, path
        assert normalize_token(token) not in content, path
PY

"$TEST_ROOT/firedrill" --config "$config" rollback >/dev/null
"$TEST_ROOT/firedrill" --config "$config" destroy --confirm "$lab_id" >/dev/null
python3 - "$run_path/driver/mock.json" "$run_path/state.json" <<'PY'
import json
import sys
from pathlib import Path

model = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
state = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
assert model["guests"] == {}
assert state["lifecycle"] == "destroyed"
assert state["tests"]["test-b"]["verdict"] == "PASS"
PY

printf 'PASS: Test B stale-unit-token lifecycle completed offline with exact-path evidence\n'
