#!/usr/bin/env bash
set -Eeuo pipefail

TEST_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TEST_TMP=$(mktemp -d "${TMPDIR:-/tmp}/firedrill-test-c-lifecycle.XXXXXX")
export PYTHONPATH="$TEST_ROOT/py${PYTHONPATH:+:$PYTHONPATH}"
cleanup() {
    rm -rf -- "${TEST_TMP:?}"
}
trap cleanup EXIT

run_case() {
    local name=$1
    shift
    local case_root config output report_path lab_id run_path
    case_root=$TEST_TMP/$name
    mkdir -p "$case_root"
    config=$case_root/firedrill.conf
    sed "s|run_dir=./runs|run_dir=$case_root/runs|" \
        "$TEST_ROOT/firedrill.conf.example" >"$config"

    "$TEST_ROOT/firedrill" --config "$config" preflight >/dev/null
    "$TEST_ROOT/firedrill" --config "$config" provision >/dev/null
    "$TEST_ROOT/firedrill" --config "$config" baseline >/dev/null
    output=$case_root/test-c.out
    "$TEST_ROOT/firedrill" --config "$config" test-c "$@" >"$output"
    grep -Fq 'Overall Test C gate: **PASS**' "$output"
    grep -Fq 'triage_branch=' "$output"
    grep -Fq 'discriminator_method=' "$output"
    grep -Fq 'source_pin=' "$output"
    grep -Fq 'selected_token_reference=<redacted-token ' "$output"
    grep -Fq 'recovery_form=' "$output"

    report_path=$("$TEST_ROOT/firedrill" --config "$config" report)
    grep -Fq 'Overall Test C gate: **PASS**' "$report_path"
    lab_id=$(python3 - "$case_root/runs/current.json" <<'PY'
import json
import sys
from pathlib import Path

print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["lab_id"])
PY
)
    run_path=$(python3 - "$case_root/runs/current.json" <<'PY'
import json
import sys
from pathlib import Path

print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["run_path"])
PY
)
    python3 - "$run_path" "$report_path" "$name" <<'PY'
import json
import sys
from pathlib import Path

from firedrill.bootstrap import normalize_token
from firedrill.mock_model import server_token_for_epoch

run_path, report_path, name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
phases = json.loads((run_path / "evidence/test-c/phases.json").read_text(encoding="utf-8"))
assert [phase["phase"] for phase in phases] == [
    "SETUP",
    "BREAK",
    "TRIAGE",
    "RECOVERY",
    "GATE",
]
assert [phase["sequence"] for phase in phases] == sorted(
    phase["sequence"] for phase in phases
)
gate = json.loads((run_path / "evidence/test-c/gate.json").read_text(encoding="utf-8"))
assert gate["verdict"] == "PASS"
assert len(gate["checks"]) == 11
assert all(check["verdict"] == "PASS" and check["coverage"] for check in gate["checks"])
state = json.loads((run_path / "state.json").read_text(encoding="utf-8"))
assert state["tests"]["test-c"]["verdict"] == "PASS"
records = [
    json.loads(line)
    for line in (run_path / "evidence/commands.jsonl").read_text(encoding="utf-8").splitlines()
]
assert [record["sequence"] for record in records] == list(range(1, len(records) + 1))
phase_records = [record for record in records if record["label"] == "test-c-phase"]
assert [record["sequence"] for record in phase_records] == [
    phase["sequence"] for phase in phases
]
setup = json.loads((run_path / "evidence/test-c/setup.json").read_text(encoding="utf-8"))
pair = setup["paired_snapshot"]
assert pair["path"].startswith("/var/lib/rancher/k3s/server/db/snapshots/")
assert len(pair["snapshot_sha256"]) == 64
assert pair["paired"] is True
broken = json.loads((run_path / "evidence/test-c/break.json").read_text(encoding="utf-8"))
assert broken["stale_token_servers_up"] == ["server-1", "server-2"]
assert broken["quorum_lost"] is True
assert broken["preserved_datastore_unchanged"] is True
if name == "both":
    recovery = json.loads(
        (run_path / "evidence/test-c/recovery.json").read_text(encoding="utf-8")
    )
    finish = json.loads(
        (run_path / "evidence/test-c/recovery-finish.json").read_text(encoding="utf-8")
    )
    assert recovery["execution"]["decision"]["cleanup_required"] is True
    assert len(recovery["execution"]["post_reset_key_names"]) == 2
    assert finish["orphan_cleanup"]["authorized"] is True
    assert len(finish["orphan_cleanup"]["before_key_names"]) == 2
    assert len(finish["orphan_cleanup"]["after_key_names"]) == 1

raw_tokens = {server_token_for_epoch(state["lab_id"], epoch) for epoch in (0, 1)}
secret_free_paths = [run_path / "state.json", report_path]
secret_free_paths.extend(path for path in (run_path / "evidence").rglob("*") if path.is_file())
secret_free_paths.append(run_path / "driver/mock.json")
for path in secret_free_paths:
    content = path.read_text(encoding="utf-8")
    for token in raw_tokens:
        assert token not in content, path
        assert normalize_token(token) not in content, path
PY

    "$TEST_ROOT/firedrill" --config "$config" rollback >/dev/null
    "$TEST_ROOT/firedrill" --config "$config" destroy --confirm "$lab_id" >/dev/null
}

run_case snapshot
run_case both --branch BOTH --recovery-form membership --authorize-orphan-cleanup
printf 'PASS: Test C snapshot and BOTH membership lifecycles completed offline with secret-free evidence\n'
