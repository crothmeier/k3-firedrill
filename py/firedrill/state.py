"""Persistent run state with atomic updates."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

from firedrill.config import provision_identity


class StateError(RuntimeError):
    """Persistent state is missing or inconsistent."""


def now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise StateError(f"state file not found: {path}") from error
    except json.JSONDecodeError as error:
        raise StateError(f"invalid JSON state file {path}: {error}") from error


def current_pointer(run_dir: Path) -> dict[str, str]:
    pointer = read_json(run_dir / "current.json")
    if not isinstance(pointer, dict) or not {"run_path", "lab_id"} <= pointer.keys():
        raise StateError("current.json is missing run_path or lab_id")
    return {"run_path": str(pointer["run_path"]), "lab_id": str(pointer["lab_id"])}


def begin(config_path: Path) -> dict[str, object]:
    config = read_json(config_path)
    values = config["values"]
    assert isinstance(values, dict)
    run_dir = Path(str(values["run_dir"]))
    pointer_path = run_dir / "current.json"
    if pointer_path.exists():
        pointer = current_pointer(run_dir)
        state_path = Path(pointer["run_path"]) / "state.json"
        state = read_json(state_path)
        if state.get("lifecycle") != "destroyed":
            active_identity = state.get("provision_identity_sha256")
            if active_identity is None:
                manifest = read_json(state_path.parent / "manifest.json")
                if not isinstance(manifest, dict) or not isinstance(
                    manifest.get("config"), dict
                ):
                    raise StateError("manifest.json is missing its canonical config")
                active_identity = provision_identity(manifest["config"])[
                    "provision_identity_sha256"
                ]
            if active_identity != config.get("provision_identity_sha256"):
                raise StateError(
                    "an active lab exists with a different configuration; destroy it explicitly"
                )
            return {
                "created": False,
                "lab_id": state["lab_id"],
                "run_path": str(state_path.parent),
                "lifecycle": state["lifecycle"],
            }

    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    lab_id = f"fd-{timestamp.lower()}-{secrets.token_hex(3)}"
    run_path = run_dir / lab_id
    run_path.mkdir(parents=True, exist_ok=False)
    (run_path / "driver").mkdir()
    (run_path / "evidence" / "commands").mkdir(parents=True)
    state = {
        "schema_version": 1,
        "lab_id": lab_id,
        "run_id": lab_id,
        "run_path": str(run_path),
        "driver": values["driver"],
        "k3s_version": values["k3s_version"],
        "config_sha256": config["config_sha256"],
        "provision_identity_sha256": config["provision_identity_sha256"],
        "inventory": config["inventory"],
        "created_at": now(),
        "updated_at": now(),
        "lifecycle": "initializing",
        "baseline": None,
        "tests": {},
    }
    atomic_json(run_path / "manifest.json", {"config": config, "lab_id": lab_id})
    atomic_json(run_path / "state.json", state)
    atomic_json(pointer_path, {"lab_id": lab_id, "run_path": str(run_path)})
    return {
        "created": True,
        "lab_id": lab_id,
        "run_path": str(run_path),
        "lifecycle": "initializing",
    }


def update_lifecycle(run_path: Path, lifecycle: str) -> None:
    state_path = run_path / "state.json"
    state = read_json(state_path)
    state["lifecycle"] = lifecycle
    state["updated_at"] = now()
    atomic_json(state_path, state)


def set_baseline(run_path: Path, cluster_state_path: Path, snapshot_name: str) -> None:
    state_path = run_path / "state.json"
    state = read_json(state_path)
    cluster_state = read_json(cluster_state_path)
    baseline = {
        "captured_at": now(),
        "snapshot_name": snapshot_name,
        "ca_sha256": cluster_state["ca_sha256"],
        "cluster_state": cluster_state,
    }
    baseline_dir = run_path / "baseline"
    baseline_dir.mkdir(exist_ok=True)
    atomic_json(baseline_dir / "cluster-state.json", cluster_state)
    (baseline_dir / "ca.sha256").write_text(f"{cluster_state['ca_sha256']}\n", encoding="utf-8")
    atomic_json(
        baseline_dir / "snapshots.json",
        {"snapshot_name": snapshot_name, "captured_at": baseline["captured_at"]},
    )
    state["baseline"] = baseline
    state["lifecycle"] = "baseline"
    state["updated_at"] = now()
    atomic_json(state_path, state)


def _test_a_attempt_timestamp(evidence_dir: Path) -> str:
    phases_path = evidence_dir / "phases.json"
    if not phases_path.exists():
        return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    phases = read_json(phases_path)
    if not isinstance(phases, list) or not all(isinstance(item, dict) for item in phases):
        raise StateError("Test A phase evidence has an invalid JSON shape")
    if not phases:
        return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    started_at: list[dt.datetime] = []
    for phase in phases:
        value = phase.get("started_at")
        if not isinstance(value, str):
            raise StateError("Test A phase evidence is missing started_at")
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise StateError(f"invalid Test A phase started_at timestamp: {value!r}") from error
        if parsed.tzinfo is None:
            raise StateError(f"Test A phase started_at lacks a timezone: {value!r}")
        started_at.append(parsed)
    return min(started_at).astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def _archive_test_a_evidence_paths(value: object, archive_key: str) -> object:
    live_prefix = "evidence/test-a/"
    archive_prefix = f"evidence/test-a.attempts/{archive_key}/"
    if isinstance(value, dict):
        return {
            key: _archive_test_a_evidence_paths(item, archive_key)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_archive_test_a_evidence_paths(item, archive_key) for item in value]
    if isinstance(value, str) and value.startswith(live_prefix):
        return f"{archive_prefix}{value.removeprefix(live_prefix)}"
    return copy.deepcopy(value)


def archive_test_a_attempt(run_path: Path) -> str:
    """Archive Test A evidence and its live state result under one attempt key."""
    evidence_dir = run_path / "evidence" / "test-a"
    if not evidence_dir.is_dir() or evidence_dir.is_symlink():
        raise StateError(f"Test A evidence directory is missing or unsafe: {evidence_dir}")

    state_path = run_path / "state.json"
    state = read_json(state_path)
    if not isinstance(state, dict):
        raise StateError("state.json is not a mapping")
    tests = state.get("tests")
    if not isinstance(tests, dict):
        raise StateError("state tests field is not a mapping")
    live_result = tests.get("test-a")
    if live_result is not None and not isinstance(live_result, dict):
        raise StateError("state Test A result is not a mapping")

    history = state.get("tests_history")
    if history is not None and not isinstance(history, dict):
        raise StateError("state tests_history field is not a mapping")
    test_a_history: object = None if history is None else history.get("test-a")
    if test_a_history is not None and not isinstance(test_a_history, dict):
        raise StateError("state Test A history is not a mapping")
    history_keys = set() if test_a_history is None else set(test_a_history)

    timestamp = _test_a_attempt_timestamp(evidence_dir)
    attempts_dir = run_path / "evidence" / "test-a.attempts"
    archive_key = timestamp
    suffix = 2
    destination = attempts_dir / archive_key
    while destination.exists() or archive_key in history_keys:
        archive_key = f"{timestamp}-{suffix}"
        suffix += 1
        destination = attempts_dir / archive_key

    updated_state: dict[str, object] | None = None
    if live_result is not None:
        updated_state = copy.deepcopy(state)
        updated_tests = updated_state["tests"]
        assert isinstance(updated_tests, dict)
        archived_result = _archive_test_a_evidence_paths(
            updated_tests.pop("test-a"), archive_key
        )
        updated_history = updated_state.setdefault("tests_history", {})
        assert isinstance(updated_history, dict)
        updated_test_a_history = updated_history.setdefault("test-a", {})
        assert isinstance(updated_test_a_history, dict)
        updated_test_a_history[archive_key] = archived_result

    attempts_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.rename(destination)
    if updated_state is not None:
        try:
            atomic_json(state_path, updated_state)
        except Exception:
            try:
                destination.rename(evidence_dir)
            except OSError as rollback_error:
                raise StateError(
                    "Test A evidence archived but state history update failed; "
                    "automatic rollback also failed"
                ) from rollback_error
            raise
    return f"evidence/test-a.attempts/{archive_key}/"


def set_test_result(
    run_path: Path,
    gate_path: Path,
    phases_path: Path,
    test_name: str = "test-a",
) -> None:
    """Persist one secret-free test verdict and its evidence references."""
    state_path = run_path / "state.json"
    state = read_json(state_path)
    gate = read_json(gate_path)
    phases = read_json(phases_path)
    if not isinstance(state, dict) or not isinstance(gate, dict) or not isinstance(phases, list):
        raise StateError("Test A result inputs have invalid JSON shapes")
    phase_orders = {
        "test-a": ["SETUP", "BREAK", "GATE"],
        "test-b": ["SETUP", "BREAK", "RECOVERY", "GATE"],
        "test-c": ["SETUP", "BREAK", "TRIAGE", "RECOVERY", "GATE"],
    }
    if test_name not in phase_orders:
        raise StateError(f"unsupported test result name: {test_name}")
    if gate.get("test") != test_name or gate.get("verdict") not in {"PASS", "FAIL"}:
        raise StateError(f"{test_name} gate evidence is missing a stable verdict")
    observed_phases = [item.get("phase") for item in phases if isinstance(item, dict)]
    if observed_phases != phase_orders[test_name]:
        raise StateError(f"{test_name} phase evidence is incomplete or out of order")
    tests = state.setdefault("tests", {})
    if not isinstance(tests, dict):
        raise StateError("state tests field is not a mapping")
    evidence_name = test_name
    tests[test_name] = {
        "verdict": gate["verdict"],
        "started_at": phases[0]["started_at"],
        "ended_at": phases[-1]["ended_at"],
        "phase_evidence_path": f"evidence/{evidence_name}/phases.json",
        "gate_evidence_path": f"evidence/{evidence_name}/gate.json",
        "gate_table_path": f"evidence/{evidence_name}/gate-table.md",
        "details": gate.get("details", {}),
        "checks": gate.get("checks", []),
    }
    state["updated_at"] = now()
    atomic_json(state_path, state)


def output_current(run_dir: Path) -> None:
    pointer = current_pointer(run_dir)
    state = read_json(Path(pointer["run_path"]) / "state.json")
    print(json.dumps(state, separators=(",", ":")))


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    begin_parser = subparsers.add_parser("begin")
    begin_parser.add_argument("--canonical", required=True, type=Path)
    current_parser = subparsers.add_parser("current")
    current_parser.add_argument("--run-dir", required=True, type=Path)
    update_parser = subparsers.add_parser("lifecycle")
    update_parser.add_argument("--run-path", required=True, type=Path)
    update_parser.add_argument("--value", required=True)
    baseline_parser = subparsers.add_parser("baseline")
    baseline_parser.add_argument("--run-path", required=True, type=Path)
    baseline_parser.add_argument("--cluster-state", required=True, type=Path)
    baseline_parser.add_argument("--snapshot-name", required=True)
    archive_test_a_parser = subparsers.add_parser("archive-test-a-attempt")
    archive_test_a_parser.add_argument("--run-path", required=True, type=Path)
    test_result_parser = subparsers.add_parser("test-result")
    test_result_parser.add_argument("--run-path", required=True, type=Path)
    test_result_parser.add_argument(
        "--test", choices=("test-a", "test-b", "test-c"), default="test-a"
    )
    test_result_parser.add_argument("--gate", required=True, type=Path)
    test_result_parser.add_argument("--phases", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "begin":
            print(json.dumps(begin(args.canonical), separators=(",", ":")))
        elif args.command == "current":
            output_current(args.run_dir)
        elif args.command == "lifecycle":
            update_lifecycle(args.run_path, args.value)
        elif args.command == "baseline":
            set_baseline(args.run_path, args.cluster_state, args.snapshot_name)
        elif args.command == "archive-test-a-attempt":
            archive_path = archive_test_a_attempt(args.run_path)
            print(f"test-a: archived prior attempt evidence to {archive_path}")
        else:
            set_test_result(args.run_path, args.gate, args.phases, args.test)
        return 0
    except (StateError, OSError, KeyError, TypeError) as error:
        print(f"state error: {error}", file=sys.stderr)
        return 66


if __name__ == "__main__":
    raise SystemExit(main())
