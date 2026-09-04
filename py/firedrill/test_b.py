"""Test B orchestration, artifacts, phase timing, and evidence-derived gate."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from firedrill.etcd_members import evaluate_three_healthy_etcd_members
from firedrill.mock_model import load_model
from firedrill.redact import (
    TokenRegistry,
    redact_text,
    redact_value,
    registry_from_environment,
    token_reference,
)
from firedrill.state import atomic_json
from firedrill.test_a import (
    EXPECTED_NODES,
    EXPECTED_SERVERS,
    TestAGuardError,
    TestAPrerequisiteError,
    assert_baseline_prerequisites,
    assert_full_server_token,
    baseline_prerequisites,
    parse_snapshot_status,
    registry_values,
)
from firedrill.test_b_model import (
    ABSENT_FILE_TYPE,
    CRASH_SIGNATURE,
    REGULAR_FILE_TYPE,
    TIMESTAMP_TRAP_SIGNATURE,
    TestBBlastRadiusError,
    TestBDeletionGuardError,
    TestBModelError,
    TestBSignatureError,
    TestBTimeout,
    break_test_b,
    gate_observation,
    prepare_test_b,
    recover_test_b,
    validate_test_b_config,
)

PHASE_ORDER = ("SETUP", "BREAK", "RECOVERY", "GATE")


class TestBGuardError(RuntimeError):
    """A Test B orchestration or evidence contract was not satisfied."""


class TestBPrerequisiteError(TestBGuardError):
    """The active lab differs from its captured baseline."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def fail(message: str) -> NoReturn:
    raise TestBGuardError(message)


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_timestamp(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise TestBGuardError(f"invalid Test B timestamp {value!r}") from error
    if parsed.tzinfo is None:
        fail(f"Test B timestamp lacks a timezone: {value!r}")
    return parsed


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def read_mapping(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail(f"expected a JSON mapping in {path}")
    return value


def test_b_evidence_dir(run_path: Path) -> Path:
    return run_path / "evidence" / "test-b"


def _sanitize_mapping(record: dict[str, object], registry: TokenRegistry) -> dict[str, object]:
    sanitized = redact_value(record, registry)
    if not isinstance(sanitized, dict):
        raise TypeError("sanitized Test B artifact is not a mapping")
    return sanitized


def _write_record(
    run_path: Path,
    name: str,
    record: dict[str, object],
    registry: TokenRegistry,
) -> dict[str, object]:
    sanitized = _sanitize_mapping(record, registry)
    atomic_json(test_b_evidence_dir(run_path) / name, sanitized)
    return sanitized


def _registered_candidates(old_token: str, new_token: str) -> TokenRegistry:
    registry = registry_from_environment()
    for value in registry_values(old_token, new_token):
        registry.register(value)
    return registry


def _canonical_test_b(path: Path) -> dict[str, Any]:
    canonical = read_mapping(path)
    return validate_test_b_config(canonical.get("test_b"))


def _test_b_prerequisites(
    baseline: dict[str, object],
    current: dict[str, object],
    state: dict[str, object],
    canonical: dict[str, object],
    snapshot_status: dict[str, bool],
) -> dict[str, object]:
    result = baseline_prerequisites(
        baseline,
        current,
        state,
        canonical,
        snapshot_status,
    )
    result["event"] = "test-b-baseline-prerequisites"
    checks = result.get("checks")
    if isinstance(checks, list):
        for check in checks:
            if not isinstance(check, dict):
                continue
            coverage = check.get("coverage")
            if isinstance(coverage, list):
                check["coverage"] = [
                    str(item).replace("test-a-current-state", "test-b-current-state")
                    for item in coverage
                ]
    return result


def command_baseline_check(args: argparse.Namespace) -> int:
    result = _test_b_prerequisites(
        read_mapping(args.baseline),
        read_mapping(args.current),
        read_mapping(args.state),
        read_mapping(args.canonical),
        parse_snapshot_status(args.snapshot_status),
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    try:
        assert_baseline_prerequisites(result)
    except TestAPrerequisiteError as error:
        raise TestBPrerequisiteError(str(error), error.exit_code) from error
    return 0


def record_phase(
    run_path: Path,
    sequence: int,
    phase: str,
    started_at: str,
    ended_at: str,
    exit_code: int,
) -> dict[str, object]:
    if phase not in PHASE_ORDER:
        fail(f"unknown Test B phase {phase!r}")
    start = parse_timestamp(started_at)
    end = parse_timestamp(ended_at)
    duration = (end - start).total_seconds()
    if duration < 0:
        fail(f"Test B phase {phase} ended before it started")
    path = test_b_evidence_dir(run_path) / "phases.json"
    records: list[dict[str, object]] = []
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, list) or not all(isinstance(item, dict) for item in loaded):
            fail(f"invalid Test B phase evidence: {path}")
        records = loaded
    expected = PHASE_ORDER[len(records)] if len(records) < len(PHASE_ORDER) else None
    if expected != phase:
        fail(f"Test B phase order violation: expected {expected!r}, observed {phase!r}")
    if records and sequence <= int(records[-1]["sequence"]):
        fail("Test B phase evidence sequence must increase")
    record = {
        "schema_version": 1,
        "sequence": sequence,
        "phase": phase,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": duration,
        "exit_code": exit_code,
        "verdict": "PASS" if exit_code == 0 else "FAIL",
        "coverage": [f"evidence/commands.jsonl#sequence={sequence}"],
    }
    records.append(record)
    atomic_json(path, records)
    return record


def command_model_setup(args: argparse.Namespace) -> int:
    registry = _registered_candidates(args.old_token, args.new_token)
    model = load_model(args.model, args.lab_id)
    record = prepare_test_b(
        model,
        args.old_token,
        args.new_token,
        _canonical_test_b(args.canonical),
    )
    sanitized = _write_record(args.run_path, "setup.json", record, registry)
    atomic_json(args.model, model)
    print(json.dumps(sanitized, sort_keys=True, separators=(",", ":")))
    return 0


def _stored_test_b_record(model: dict[str, Any], key: str) -> dict[str, object] | None:
    state = model.get("cluster", {}).get("test_b")
    if not isinstance(state, dict):
        return None
    record = state.get(key)
    return record if isinstance(record, dict) else None


def command_model_break(args: argparse.Namespace) -> int:
    registry = registry_from_environment()
    model = load_model(args.model, args.lab_id)
    try:
        record = break_test_b(model)
    except (TestBBlastRadiusError, TestBSignatureError):
        record = _stored_test_b_record(model, "break_observation")
        if record is None:
            fail("failed Test B BREAK did not retain a structured observation")
        _write_record(args.run_path, "break.json", record, registry)
        atomic_json(args.model, model)
        raise
    sanitized = _write_record(args.run_path, "break.json", record, registry)
    atomic_json(args.model, model)
    print(json.dumps(sanitized, sort_keys=True, separators=(",", ":")))
    return 0


def command_model_recover(args: argparse.Namespace) -> int:
    registry = registry_from_environment()
    model = load_model(args.model, args.lab_id)
    requested = args.requested_delete if args.requested_delete else None
    try:
        record = recover_test_b(
            model,
            _canonical_test_b(args.canonical),
            args.timeout,
            requested,
        )
    except (TestBDeletionGuardError, TestBTimeout) as error:
        record = _stored_test_b_record(model, "recovery_observation")
        if record is None:
            record = {
                "schema_version": 1,
                "event": "test-b-recovery",
                "verdict": "FAIL",
                "failure_class": type(error).__name__,
                "reason": redact_text(str(error), registry),
            }
        _write_record(args.run_path, "recovery.json", record, registry)
        atomic_json(args.model, model)
        raise
    sanitized = _write_record(args.run_path, "recovery.json", record, registry)
    atomic_json(args.model, model)
    print(json.dumps(sanitized, sort_keys=True, separators=(",", ":")))
    return 0


def command_model_observe(args: argparse.Namespace) -> int:
    model = load_model(args.model, args.lab_id)
    print(json.dumps(gate_observation(model), sort_keys=True, separators=(",", ":")))
    return 0


@dataclass(frozen=True)
class GateCheck:
    """One Test B assertion derived from named evidence artifacts."""

    name: str
    passed: bool
    expected: str
    observed: str
    coverage: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "check": self.name,
            "verdict": "PASS" if self.passed else "FAIL",
            "expected": self.expected,
            "observed": self.observed,
            "coverage": list(self.coverage),
        }


@dataclass(frozen=True)
class GateResult:
    """Complete Test B verdict plus concise report details."""

    verdict: str
    checks: tuple[GateCheck, ...]
    details: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "test": "test-b",
            "verdict": self.verdict,
            "evaluated_at": utc_now(),
            "details": self.details,
            "checks": [check.to_dict() for check in self.checks],
        }


def _mapping_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _mapping_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def evaluate_gate(
    baseline: dict[str, object],
    observation: dict[str, object],
    canonical_test_b: object,
) -> GateResult:
    """Derive Test B solely from baseline, canonical config, and recorded observations."""
    config = validate_test_b_config(canonical_test_b)
    target = str(config["target_server"])
    bystanders = sorted(server for server in EXPECTED_SERVERS if server != target)
    setup = _mapping_value(observation.get("setup_observation"))
    broken = _mapping_value(observation.get("break_observation"))
    recovery = _mapping_value(observation.get("recovery_observation"))
    checks: list[GateCheck] = []

    pairs = _mapping_value(setup.get("snapshot_pairs"))
    references = {
        str(pair.get("server_token_reference"))
        for pair in pairs.values()
        if isinstance(pair, dict)
    }
    snapshot_ok = (
        set(pairs) == set(EXPECTED_SERVERS)
        and len(references) == 1
        and setup.get("rotated_without_full_roll") is True
        and set(setup.get("non_restarted_nodes", [])) == set(EXPECTED_NODES)
    )
    checks.append(
        GateCheck(
            "paired-snapshots-and-rotate-without-full-roll",
            snapshot_ok,
            "three token-paired snapshots and one rotation with zero node restarts",
            f"paired_servers={sorted(pairs)!r}, references={len(references)}, "
            f"non_restarted={setup.get('non_restarted_nodes')!r}",
            (
                "evidence/test-b/setup.json#/snapshot_pairs",
                "evidence/test-b/setup.json#/rotated_without_full_roll",
                "evidence/test-b/setup.json#/non_restarted_nodes",
            ),
        )
    )

    owned_override = _mapping_value(broken.get("owned_override"))
    crash_ok = (
        broken.get("verdict") == "PASS"
        and broken.get("target_server") == target
        and broken.get("stale_override_server_count") == 1
        and owned_override.get("server") == target
        and owned_override.get("path") == config["owned_override_path"]
        and broken.get("crash_signature") == CRASH_SIGNATURE
        and isinstance(broken.get("crash_signature_count"), int)
        and int(broken.get("crash_signature_count", 0)) >= 1
        and broken.get("crash_signature_observed") is True
    )
    checks.append(
        GateCheck(
            "one-owned-stale-override-and-required-crash-signature",
            crash_ok,
            "one owned old --token= override on the configured server and the pinned crash line",
            f"target={broken.get('target_server')!r}, override_count="
            f"{broken.get('stale_override_server_count')!r}, "
            f"crash_count={broken.get('crash_signature_count')!r}",
            (
                "evidence/test-b/break.json#/owned_override",
                "evidence/test-b/break.json#/stale_override_server_count",
                "evidence/test-b/break.json#/target_journal_window",
            ),
        )
    )

    bystander_health = _mapping_value(broken.get("bystander_health"))
    proof_ok = set(bystander_health) == set(bystanders) and all(
        isinstance(values, dict) and all(values.get(key) is True for key in (
            "ready",
            "etcd_healthy",
            "k3s_running",
        ))
        for values in bystander_health.values()
    )
    blast_ok = (
        proof_ok
        and broken.get("bystanders_healthy") is True
        and broken.get("quorum_intact") is True
        and broken.get("api_served") is True
        and set(broken.get("healthy_etcd_members", [])) == set(bystanders)
    )
    checks.append(
        GateCheck(
            "bystanders-healthy-quorum-intact-and-api-served",
            blast_ok,
            "both untouched servers healthy, exactly those two sustaining quorum and API",
            f"bystanders={sorted(bystander_health)!r}, quorum="
            f"{broken.get('quorum_intact')!r}, api={broken.get('api_served')!r}",
            (
                "evidence/test-b/break.json#/bystander_health",
                "evidence/test-b/break.json#/healthy_etcd_members",
                "evidence/test-b/break.json#/quorum_intact",
                "evidence/test-b/break.json#/api_served",
            ),
        )
    )

    precedence = _mapping_list(recovery.get("precedence_enumeration"))
    expected_pairs = [
        (str(item["surface"]), str(item["path"])) for item in config["precedence_surfaces"]
    ]
    actual_pairs = [(str(item.get("surface")), str(item.get("path"))) for item in precedence]
    count_shapes = all(
        isinstance(item.get("occurrences"), list)
        and item.get("occurrence_count") == len(item["occurrences"])
        for item in precedence
    )
    occurrences = [
        occurrence
        for entry in precedence
        for occurrence in entry.get("occurrences", [])
        if isinstance(occurrence, dict)
    ]
    occurrence_paths = {str(item.get("source_path")) for item in occurrences}
    expected_occurrence_paths = {
        str(config["owned_override_path"]),
        str(config["deletion_allowlist"][1]),
    }
    precedence_ok = (
        actual_pairs == expected_pairs
        and count_shapes
        and occurrence_paths == expected_occurrence_paths
        and all(
            str(item.get("token_reference", "")).startswith("<redacted-token ")
            for item in occurrences
        )
    )
    checks.append(
        GateCheck(
            "full-token-precedence-surface-enumerated",
            precedence_ok,
            "every canonical surface once, with all modeled token occurrences cross-checked",
            f"entries={len(precedence)}/{len(expected_pairs)}, "
            f"occurrence_paths={sorted(occurrence_paths)!r}",
            (
                "manifest.json#/config/test_b/precedence_surfaces",
                "evidence/test-b/recovery.json#/precedence_enumeration",
                "evidence/test-b/break.json#/owned_override",
            ),
        )
    )

    deletions = _mapping_list(recovery.get("deletion_records"))
    deletion_paths = [str(item.get("path")) for item in deletions]
    metadata_ok = True
    for item in deletions:
        before = _mapping_value(item.get("before"))
        after = _mapping_value(item.get("after"))
        metadata_ok = metadata_ok and bool(
            before.get("path") == item.get("path")
            and before.get("exists") is True
            and before.get("type") == REGULAR_FILE_TYPE
            and isinstance(before.get("owner"), str)
            and re.fullmatch(r"[0-7]{4}", str(before.get("mode", "")))
            and isinstance(before.get("mtime"), str)
            and item.get("action") == "deleted"
            and after.get("exists") is False
            and after.get("type") == ABSENT_FILE_TYPE
        )
    deletion_ok = deletion_paths == config["deletion_allowlist"] and metadata_ok
    checks.append(
        GateCheck(
            "exact-allowlist-credential-deletions",
            deletion_ok,
            "exactly two reviewed paths, regular-file metadata before and absence after",
            f"paths={deletion_paths!r}, metadata_complete={str(metadata_ok).lower()}",
            (
                "manifest.json#/config/test_b/deletion_allowlist",
                "evidence/test-b/recovery.json#/deletion_records",
            ),
        )
    )

    nodes = _mapping_list(observation.get("nodes"))
    nodes_by_name = {str(node.get("name")): node for node in nodes}
    exact_nodes = len(nodes) == 5 and set(nodes_by_name) == set(EXPECTED_NODES)
    target_node = nodes_by_name.get(target, {})
    rejoined = (
        recovery.get("verdict") == "PASS"
        and recovery.get("failed_server_started") is True
        and recovery.get("stopped_failed_server_only") is True
        and recovery.get("healthy_servers_restarted") is False
        and target_node.get("ready") is True
    )
    checks.append(
        GateCheck(
            "failed-server-rejoined-without-healthy-server-restarts",
            rejoined,
            "failed server Ready after recovery; healthy servers neither stopped nor restarted",
            f"target_ready={target_node.get('ready')!r}, stopped_failed_only="
            f"{recovery.get('stopped_failed_server_only')!r}, healthy_restarted="
            f"{recovery.get('healthy_servers_restarted')!r}",
            (
                "evidence/test-b/recovery.json#/stopped_failed_server_only",
                "evidence/test-b/recovery.json#/healthy_servers_restarted",
                f"evidence/test-b/gate-observation.json#/nodes/{target}/ready",
            ),
        )
    )

    raw_keys = observation.get("bootstrap_keys")
    keys = raw_keys if isinstance(raw_keys, list) else []
    keys_ok = len(keys) == 1 and isinstance(keys[0], str) and keys[0].startswith("/bootstrap/")
    checks.append(
        GateCheck(
            "exactly-one-bootstrap-key",
            keys_ok,
            "exactly one /bootstrap/ key name",
            f"count={len(keys)}, names={keys!r}",
            ("evidence/test-b/gate-observation.json#/bootstrap_keys",),
        )
    )

    credentials = [
        nodes_by_name.get(name, {}).get("join_credential_sha256") for name in EXPECTED_NODES
    ]
    populated = all(
        isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)
        for value in credentials
    )
    unique_credentials = {value for value in credentials if isinstance(value, str)}
    credentials_ok = exact_nodes and populated and len(unique_credentials) == 1
    checks.append(
        GateCheck(
            "matching-normalized-join-credential-references",
            credentials_ok,
            "five populated normalized credential SHA-256 references, all equal",
            f"populated={sum(isinstance(value, str) for value in credentials)}/5, "
            f"unique={len(unique_credentials)}",
            tuple(
                f"evidence/test-b/gate-observation.json#/nodes/{name}/join_credential_sha256"
                for name in EXPECTED_NODES
            ),
        )
    )

    journals = _mapping_value(observation.get("post_recovery_server_journals"))
    journal_shape = set(journals) == set(EXPECTED_SERVERS)
    crash_after = 0
    timestamp_traps = 0
    for server in EXPECTED_SERVERS:
        lines = journals.get(server, [])
        if not isinstance(lines, list):
            journal_shape = False
            continue
        crash_after += sum(isinstance(line, str) and CRASH_SIGNATURE in line for line in lines)
        timestamp_traps += sum(
            isinstance(line, str) and TIMESTAMP_TRAP_SIGNATURE in line for line in lines
        )
    journals_ok = journal_shape and crash_after == 0 and timestamp_traps == 0
    checks.append(
        GateCheck(
            "post-recovery-journal-signatures-absent",
            journals_ok,
            "zero different-token and zero newer-than-datastore lines after recovery start",
            f"different_token={crash_after}, newer_than_datastore={timestamp_traps}",
            tuple(
                f"evidence/test-b/gate-observation.json#/post_recovery_server_journals/{server}"
                for server in EXPECTED_SERVERS
            ),
        )
    )

    ready_names = sorted(name for name, node in nodes_by_name.items() if node.get("ready") is True)
    ready_ok = exact_nodes and set(ready_names) == set(EXPECTED_NODES)
    checks.append(
        GateCheck(
            "five-ready-nodes",
            ready_ok,
            "the exact five inventory nodes are Ready",
            f"ready_count={len(ready_names)}, ready_names={ready_names!r}",
            tuple(
                f"evidence/test-b/gate-observation.json#/nodes/{name}/ready"
                for name in EXPECTED_NODES
            ),
        )
    )

    baseline_ca = baseline.get("ca_sha256")
    observed_ca = observation.get("ca_sha256")
    ca_ok = isinstance(baseline_ca, str) and bool(baseline_ca) and observed_ca == baseline_ca
    checks.append(
        GateCheck(
            "ca-hash-unchanged",
            ca_ok,
            "gate CA SHA-256 exactly equals the baselined CA SHA-256",
            f"match={str(ca_ok).lower()}",
            (
                "baseline/cluster-state.json#/ca_sha256",
                "evidence/test-b/gate-observation.json#/ca_sha256",
            ),
        )
    )

    etcd_members = evaluate_three_healthy_etcd_members(
        baseline,
        observation,
        EXPECTED_SERVERS,
        "evidence/test-b/gate-observation.json#/etcd_members",
    )
    checks.append(
        GateCheck(
            "three-healthy-etcd-members",
            etcd_members.passed,
            etcd_members.expected,
            etcd_members.observed,
            etcd_members.coverage,
        )
    )

    duration = recovery.get("recovery_duration_seconds")
    timeout = config["recovery_timeout_seconds"]
    duration_ok = (
        isinstance(duration, (int, float))
        and not isinstance(duration, bool)
        and 0 <= float(duration) <= timeout
        and isinstance(recovery.get("clock_started_at"), str)
        and isinstance(recovery.get("clock_stopped_at"), str)
    )
    checks.append(
        GateCheck(
            "measured-stop-to-all-ready-recovery-duration",
            duration_ok,
            f"measured duration from recovery stop clock through all Ready, <= {timeout}s",
            f"duration_seconds={duration!r}, timeout_seconds={timeout}",
            (
                "evidence/test-b/recovery.json#/clock_started_at",
                "evidence/test-b/recovery.json#/clock_stopped_at",
                "evidence/test-b/recovery.json#/recovery_duration_seconds",
                "manifest.json#/config/test_b/recovery_timeout_seconds",
            ),
        )
    )

    details = {
        "target_server": target,
        "crash_signature_observed": broken.get("crash_signature_observed") is True,
        "bystander_servers": bystanders,
        "bystanders_healthy": broken.get("bystanders_healthy") is True,
        "quorum_intact_during_break": broken.get("quorum_intact") is True,
        "api_served_during_break": broken.get("api_served") is True,
        "precedence_entries_enumerated": len(precedence),
        "deletion_records": deletions,
        "recovery_duration_seconds": duration,
        "recovery_timeout_seconds": timeout,
    }
    verdict = "PASS" if all(check.passed for check in checks) else "FAIL"
    return GateResult(verdict, tuple(checks), details)


def escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render_gate_table(result: GateResult) -> str:
    lines = [
        "| Check | Verdict | Coverage set (file by file) | Expected | Observed |",
        "|---|---|---|---|---|",
    ]
    for check in result.checks:
        coverage = "<br>".join(f"`{item}`" for item in check.coverage)
        lines.append(
            f"| `{check.name}` | **{'PASS' if check.passed else 'FAIL'}** | {coverage} | "
            f"{escape_table(check.expected)} | {escape_table(check.observed)} |"
        )
    lines.extend(("", f"Overall Test B gate: **{result.verdict}**", ""))
    return "\n".join(lines)


def command_evaluate(args: argparse.Namespace) -> int:
    registry = registry_from_environment()
    baseline = read_mapping(args.baseline)
    observation = read_mapping(args.observation)
    canonical = read_mapping(args.canonical)
    result = evaluate_gate(baseline, observation, canonical.get("test_b"))
    evidence_dir = test_b_evidence_dir(args.run_path)
    sanitized_observation = _sanitize_mapping(observation, registry)
    atomic_json(evidence_dir / "gate-observation.json", sanitized_observation)
    atomic_json(evidence_dir / "gate.json", result.to_dict())
    table = render_gate_table(result)
    atomic_text(evidence_dir / "gate-table.md", table)
    print(table, end="")
    return 0 if result.verdict == "PASS" else 1


def _add_model_arguments(parser: argparse.ArgumentParser, *, run_path: bool = False) -> None:
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--lab-id", required=True)
    if run_path:
        parser.add_argument("--run-path", required=True, type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("timestamp")
    validate = subparsers.add_parser("validate-token")
    validate.add_argument("--label", default="server token")
    subparsers.add_parser("registry-json")
    subparsers.add_parser("references-json")
    baseline = subparsers.add_parser("baseline-check")
    baseline.add_argument("--baseline", required=True, type=Path)
    baseline.add_argument("--current", required=True, type=Path)
    baseline.add_argument("--state", required=True, type=Path)
    baseline.add_argument("--canonical", required=True, type=Path)
    baseline.add_argument("--snapshot-status", action="append", default=[])
    phase = subparsers.add_parser("record-phase")
    phase.add_argument("--run-path", required=True, type=Path)
    phase.add_argument("--sequence", required=True, type=int)
    phase.add_argument("--phase", required=True)
    phase.add_argument("--started-at", required=True)
    phase.add_argument("--ended-at", required=True)
    phase.add_argument("--exit-code", required=True, type=int)
    setup = subparsers.add_parser("model-setup")
    _add_model_arguments(setup, run_path=True)
    setup.add_argument("--canonical", required=True, type=Path)
    setup.add_argument("--old-token", required=True)
    setup.add_argument("--new-token", required=True)
    break_parser = subparsers.add_parser("model-break")
    _add_model_arguments(break_parser, run_path=True)
    recover = subparsers.add_parser("model-recover")
    _add_model_arguments(recover, run_path=True)
    recover.add_argument("--canonical", required=True, type=Path)
    recover.add_argument("--timeout", required=True, type=int)
    recover.add_argument("--requested-delete", action="append", default=[])
    observe = subparsers.add_parser("model-observe")
    _add_model_arguments(observe)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--run-path", required=True, type=Path)
    evaluate.add_argument("--baseline", required=True, type=Path)
    evaluate.add_argument("--observation", required=True, type=Path)
    evaluate.add_argument("--canonical", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "timestamp":
            print(utc_now())
            return 0
        if args.command == "validate-token":
            assert_full_server_token(sys.stdin.read().rstrip("\n"), args.label)
            print("PASS: full server-token format asserted before Test B mutation")
            return 0
        if args.command in {"registry-json", "references-json"}:
            values = sys.stdin.read().splitlines()
            if len(values) != 2:
                fail("Test B token setup requires exactly OLD and NEW candidates")
            registry_values(values[0], values[1])
            if args.command == "registry-json":
                print(json.dumps(registry_values(values[0], values[1]), separators=(",", ":")))
            else:
                print(
                    json.dumps(
                        {"old": token_reference(values[0]), "new": token_reference(values[1])},
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
            return 0
        if args.command == "baseline-check":
            return command_baseline_check(args)
        if args.command == "record-phase":
            record = record_phase(
                args.run_path,
                args.sequence,
                args.phase,
                args.started_at,
                args.ended_at,
                args.exit_code,
            )
            print(json.dumps(record, sort_keys=True, separators=(",", ":")))
            return 0
        if args.command == "model-setup":
            return command_model_setup(args)
        if args.command == "model-break":
            return command_model_break(args)
        if args.command == "model-recover":
            return command_model_recover(args)
        if args.command == "model-observe":
            return command_model_observe(args)
        return command_evaluate(args)
    except TestBPrerequisiteError as error:
        print(f"test-b prerequisite: {error}", file=sys.stderr)
        return error.exit_code
    except TestBBlastRadiusError as error:
        print(f"test-b blast-radius failure: {error}", file=sys.stderr)
        return 71
    except TestBTimeout as error:
        print(f"test-b timeout: {error}", file=sys.stderr)
        return 70
    except TestBDeletionGuardError as error:
        print(f"test-b deletion SAFETY ABORT: {error}", file=sys.stderr)
        return 78
    except (
        TestBGuardError,
        TestBModelError,
        TestBSignatureError,
        TestAGuardError,
        OSError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        safe = redact_text(str(error), registry_from_environment())
        print(f"test-b guard: {safe}", file=sys.stderr)
        return 69


if __name__ == "__main__":
    raise SystemExit(main())
