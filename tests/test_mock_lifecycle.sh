#!/usr/bin/env bash
set -Eeuo pipefail

TEST_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TEST_TMP=$(mktemp -d "${TMPDIR:-/tmp}/firedrill-lifecycle.XXXXXX")
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
"$TEST_ROOT/firedrill" --config "$config" provision | grep -q '^NO-OP:'
"$TEST_ROOT/firedrill" --config "$config" baseline >/dev/null
"$TEST_ROOT/firedrill" --config "$config" baseline | grep -q '^NO-OP:'
"$TEST_ROOT/firedrill" --config "$config" test-a >"$TEST_TMP/test-a.out"
grep -Fq 'Overall Test A gate: **PASS**' "$TEST_TMP/test-a.out"

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
"$TEST_ROOT/firedrill" --config "$config" rollback >/dev/null
"$TEST_ROOT/firedrill" --config "$config" test-a >"$TEST_TMP/test-a-reattempt.out"
grep -Fq \
    'test-a: archived prior attempt evidence to evidence/test-a.attempts/' \
    "$TEST_TMP/test-a-reattempt.out"
grep -Fq 'Overall Test A gate: **PASS**' "$TEST_TMP/test-a-reattempt.out"
report_path=$("$TEST_ROOT/firedrill" --config "$config" report)
[[ -s $report_path ]]
grep -Fq 'Overall Test A gate: **PASS**' "$report_path"

[[ -s $run_path/evidence/commands.jsonl ]]
[[ -s $run_path/baseline/ca.sha256 ]]
[[ -s $run_path/evidence/test-a/gate.json ]]
[[ -s $run_path/evidence/test-a/gate-table.md ]]
[[ -s $run_path/evidence/test-a/phases.json ]]
python3 - "$run_path" "$report_path" <<'PY'
import datetime as dt
import json
import sys
from pathlib import Path

from firedrill.bootstrap import normalize_token
from firedrill.mock_model import server_token_for_epoch

run_path = Path(sys.argv[1])
report_path = Path(sys.argv[2])
records = [
    json.loads(line)
    for line in (run_path / "evidence" / "commands.jsonl").read_text(encoding="utf-8").splitlines()
]
assert [record["sequence"] for record in records] == list(range(1, len(records) + 1))
assert all(record["command"] for record in records)
assert any("firedrill.mock_model" in record["command"] for record in records)
assert any("firedrill.test_a" in record["command"] for record in records)
archive_dirs = sorted(
    path
    for path in (run_path / "evidence" / "test-a.attempts").iterdir()
    if path.is_dir()
)
assert len(archive_dirs) == 1
archive_dir = archive_dirs[0]
archived_phases = json.loads(
    (archive_dir / "phases.json").read_text(encoding="utf-8")
)
assert [phase["phase"] for phase in archived_phases] == ["SETUP", "BREAK", "GATE"]
assert (archive_dir / "gate.json").is_file()
archived_gate = json.loads((archive_dir / "gate.json").read_text(encoding="utf-8"))
assert archived_gate["verdict"] == "PASS"
first_started_at = dt.datetime.fromisoformat(
    archived_phases[0]["started_at"].replace("Z", "+00:00")
)
assert archive_dir.name == first_started_at.astimezone(dt.UTC).strftime(
    "%Y%m%dT%H%M%SZ"
)
phases = json.loads((run_path / "evidence" / "test-a" / "phases.json").read_text(encoding="utf-8"))
assert [phase["phase"] for phase in phases] == ["SETUP", "BREAK", "GATE"]
assert [phase["sequence"] for phase in phases] == sorted(phase["sequence"] for phase in phases)
phase_records = [record for record in records if record["label"] == "test-a-phase"]
assert [record["sequence"] for record in phase_records] == [
    phase["sequence"] for phase in archived_phases + phases
]
archive_records = [
    record for record in records if record["label"] == "test-a-attempt-archived"
]
assert len(archive_records) == 1
assert archive_records[0]["node"] == "test-a"
assert archive_records[0]["sequence"] < phases[0]["sequence"]
gate = json.loads((run_path / "evidence" / "test-a" / "gate.json").read_text(encoding="utf-8"))
assert gate["verdict"] == "PASS"
assert len(gate["checks"]) == 7
assert all(check["verdict"] == "PASS" and check["coverage"] for check in gate["checks"])
state = json.loads((run_path / "state.json").read_text(encoding="utf-8"))
assert state["tests"]["test-a"]["verdict"] == "PASS"
assert state["tests"]["test-a"]["started_at"] == phases[0]["started_at"]
history = state["tests_history"]["test-a"]
assert list(history) == [archive_dir.name]
first_result = history[archive_dir.name]
assert first_result["verdict"] == "PASS"
assert first_result["started_at"] == archived_phases[0]["started_at"]
assert first_result["ended_at"] == archived_phases[-1]["ended_at"]
assert first_result["phase_evidence_path"] == (
    f"evidence/test-a.attempts/{archive_dir.name}/phases.json"
)
assert first_result["gate_evidence_path"] == (
    f"evidence/test-a.attempts/{archive_dir.name}/gate.json"
)

model_text = (run_path / "driver" / "mock.json").read_text(encoding="utf-8")
raw_tokens = {server_token_for_epoch(state["lab_id"], epoch) for epoch in (0, 1, 2)}
for token in raw_tokens:
    assert token not in model_text
    assert normalize_token(token) not in model_text
secret_free_paths = [run_path / "state.json", report_path]
secret_free_paths.extend(
    path for path in (run_path / "evidence").rglob("*") if path.is_file()
)
for path in secret_free_paths:
    content = path.read_text(encoding="utf-8")
    for token in raw_tokens:
        assert token not in content, path
        assert normalize_token(token) not in content, path
PY
printf 'PASS: test-a re-attempt archived prior evidence and started a clean phase ledger\n'
"$TEST_ROOT/firedrill" --config "$config" rollback >/dev/null
if "$TEST_ROOT/firedrill" --config "$config" destroy --confirm wrong-lab \
    >"$TEST_TMP/out" 2>"$TEST_TMP/err"; then
    echo 'destroy with the wrong confirmation unexpectedly succeeded' >&2
    exit 1
fi
grep -q 'refusing destroy' "$TEST_TMP/err"
"$TEST_ROOT/firedrill" --config "$config" destroy --confirm "$lab_id" >/dev/null

python3 - "$run_path/driver/mock.json" "$run_path/state.json" <<'PY'
import json
import sys
from pathlib import Path

model = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
state = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
assert model["guests"] == {}
assert state["lifecycle"] == "destroyed"
PY
