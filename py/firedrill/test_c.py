"""Test C mock execution, structured recovery wiring, and evidence-derived gate."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from firedrill.bootstrap import BootstrapBranch, register_candidate_tokens
from firedrill.etcd_members import evaluate_three_healthy_etcd_members
from firedrill.mock_model import atomic_json, load_model
from firedrill.redact import (
    TokenRegistry,
    redact_text,
    redact_value,
    registry_from_environment,
)
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
from firedrill.test_c_model import (
    RESET_FLAG_PATH,
    MockBootstrapDiscriminator,
    MockRecoveryProtocols,
    TestCModelError,
    TestCModelTimeout,
    break_test_c,
    finish_recovery,
    gate_observation,
    nominated_snapshot,
    observed_running_token,
    prepare_test_c,
    record_recovery_execution,
)
from firedrill.test_c_recovery import (
    RecoveryAction,
    RecoveryContractError,
    RecoveryHalted,
    RecoveryInvariantError,
    RecoveryPolicyError,
    ResetAttemptError,
    apply_recovery_policy,
    assert_final_bootstrap_key,
    select_recovery,
)

PHASE_ORDER = ("SETUP", "BREAK", "TRIAGE", "RECOVERY", "GATE")
BAD_JOURNAL_RE = re.compile(r"different\s+token|newer\s+than\s+datastore", re.IGNORECASE)


class TestCGuardError(RuntimeError):
    """A Test C caller, evidence, or phase-order contract failed."""


class TestCPrerequisiteError(TestCGuardError):
    """The active lab no longer matches its captured baseline."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def fail(message: str) -> NoReturn:
    raise TestCGuardError(message)


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_timestamp(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise TestCGuardError(f"invalid Test C phase timestamp {value!r}") from error
    if parsed.tzinfo is None:
        fail(f"Test C phase timestamp lacks a timezone: {value!r}")
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


def test_c_evidence_dir(run_path: Path) -> Path:
    return run_path / "evidence" / "test-c"


def _sanitize_mapping(value: dict[str, object], registry: TokenRegistry) -> dict[str, object]:
    sanitized = redact_value(value, registry)
    if not isinstance(sanitized, dict):
        raise TypeError("sanitized Test C record is not a mapping")
    return sanitized


class EventRecorder:
    """Collect ordered recovery-engine records after applying the active registry."""

    def __init__(self, registry: TokenRegistry) -> None:
        self.registry = registry
        self.records: list[dict[str, object]] = []

    def __call__(self, record: dict[str, object]) -> None:
        sanitized = _sanitize_mapping(record, self.registry)
        sanitized["event_sequence"] = len(self.records) + 1
        self.records.append(sanitized)


def record_phase(
    run_path: Path,
    sequence: int,
    phase: str,
    started_at: str,
    ended_at: str,
    exit_code: int,
) -> dict[str, object]:
    if phase not in PHASE_ORDER:
        fail(f"unknown Test C phase {phase!r}")
    start = parse_timestamp(started_at)
    end = parse_timestamp(ended_at)
    duration = (end - start).total_seconds()
    if duration < 0:
        fail(f"Test C phase {phase} ended before it started")
    path = test_c_evidence_dir(run_path) / "phases.json"
    records: list[dict[str, object]] = []
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, list) or not all(isinstance(item, dict) for item in loaded):
            fail(f"invalid Test C phase evidence: {path}")
        records = loaded
    if len(records) >= len(PHASE_ORDER):
        fail("Test C phase evidence is already complete; rollback is required before rerun")
    expected = PHASE_ORDER[len(records)]
    if expected != phase:
        fail(f"Test C phase order violation: expected {expected!r}, observed {phase!r}")
    if records and sequence <= int(records[-1]["sequence"]):
        fail("Test C phase evidence sequence must increase")
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


def _test_c_prerequisites(
    baseline: dict[str, object],
    current: dict[str, object],
    state: dict[str, object],
    canonical: dict[str, object],
    snapshot_status: dict[str, bool],
) -> dict[str, object]:
    result = baseline_prerequisites(baseline, current, state, canonical, snapshot_status)
    result["event"] = "test-c-baseline-prerequisites"
    checks = result.get("checks")
    if isinstance(checks, list):
        for check in checks:
            if not isinstance(check, dict):
                continue
            raw_coverage = check.get("coverage")
            if isinstance(raw_coverage, list):
                check["coverage"] = [
                    str(item).replace("test-a-current-state", "test-c-current-state")
                    for item in raw_coverage
                ]
    return result


def command_baseline_check(args: argparse.Namespace) -> int:
    result = _test_c_prerequisites(
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
        raise TestCPrerequisiteError(str(error), error.exit_code) from error
    return 0


def _registered_candidates(old_token: str, new_token: str) -> TokenRegistry:
    registry = registry_from_environment()
    register_candidate_tokens(registry, old_token, new_token)
    return registry


def _load_model(args: argparse.Namespace) -> dict[str, Any]:
    return load_model(args.model, args.lab_id)


def _write_record(
    run_path: Path,
    name: str,
    record: dict[str, object],
    registry: TokenRegistry,
) -> dict[str, object]:
    sanitized = _sanitize_mapping(record, registry)
    atomic_json(test_c_evidence_dir(run_path) / name, sanitized)
    return sanitized


def command_model_setup(args: argparse.Namespace) -> int:
    registry = _registered_candidates(args.old_token, args.new_token)
    model = _load_model(args)
    record = prepare_test_c(model, args.old_token, args.new_token, args.recovery_form)
    sanitized = _write_record(args.run_path, "setup.json", record, registry)
    atomic_json(args.model, model)
    print(json.dumps(sanitized, sort_keys=True, separators=(",", ":")))
    return 0


def command_model_break(args: argparse.Namespace) -> int:
    registry = registry_from_environment()
    model = _load_model(args)
    record = break_test_c(model, BootstrapBranch(args.branch))
    sanitized = _write_record(args.run_path, "break.json", record, registry)
    atomic_json(args.model, model)
    print(json.dumps(sanitized, sort_keys=True, separators=(",", ":")))
    return 0


def _triage_record(
    model: dict[str, Any],
    old_token: str,
    new_token: str,
    registry: TokenRegistry,
) -> dict[str, object]:
    state = model["cluster"].get("test_c")
    if not isinstance(state, dict) or state.get("phase") != "BROKEN":
        fail("Test C TRIAGE requires a completed BREAK observation")
    broken = state.get("break_observation")
    if not isinstance(broken, dict) or broken.get("preserved_datastore_unchanged") is not True:
        fail("Test C TRIAGE refused because the third server datastore was not preserved")
    observed = tuple(model["cluster"]["bootstrap_keys"])
    discriminator = MockBootstrapDiscriminator(model)
    result = discriminator(observed, old_token, new_token, registry=registry)
    decision = select_recovery(result, paired_snapshot=nominated_snapshot(model))
    return {
        "schema_version": 1,
        "event": "test-c-triage",
        "branch": result.branch,
        "observed_key_names": list(result.observed_key_names),
        "expected_key_names": [
            result.old_candidate_key_name,
            result.new_candidate_key_name,
        ],
        "old_candidate_key_name": result.old_candidate_key_name,
        "new_candidate_key_name": result.new_candidate_key_name,
        "method": result.method,
        "source_pin": result.source_pin,
        "reason": result.reason,
        "discriminator_calls": discriminator.calls,
        "preserved_server": broken.get("preserved_server"),
        "preserved_datastore_unchanged": True,
        "decision": decision.to_evidence(),
    }


def _print_triage(record: dict[str, object]) -> None:
    decision = record.get("decision")
    if not isinstance(decision, dict):
        fail("structured Test C triage record lacks a decision")
    print(f"triage_branch={record['branch']}")
    print(f"discriminator_method={record['method']}")
    print(f"source_pin={record['source_pin']}")
    print(f"reason={record['reason']}")
    print(f"observed_key_names={json.dumps(record['observed_key_names'], separators=(',', ':'))}")
    print(f"expected_key_names={json.dumps(record['expected_key_names'], separators=(',', ':'))}")
    print(f"recovery_form={decision.get('form')}")
    print(f"selected_token_reference={decision.get('selected_token_reference')}")
    print(f"selection_reason={decision.get('reason')}")


def command_model_triage(args: argparse.Namespace) -> int:
    registry = _registered_candidates(args.old_token, args.new_token)
    model = _load_model(args)
    record = _triage_record(model, args.old_token, args.new_token, registry)
    sanitized = _write_record(args.run_path, "triage.json", record, registry)
    _print_triage(sanitized)
    decision = sanitized.get("decision")
    if not isinstance(decision, dict):
        fail("Test C triage decision evidence has an invalid shape")
    if decision.get("action") == RecoveryAction.HALT:
        raise RecoveryHalted(str(decision.get("reason")))
    return 0


def _read_triage(run_path: Path) -> dict[str, Any]:
    path = test_c_evidence_dir(run_path) / "triage.json"
    triage = read_mapping(path)
    decision = triage.get("decision")
    if not isinstance(decision, dict) or decision.get("action") != RecoveryAction.RECOVER:
        fail("Test C RECOVERY requires a structured RECOVER triage decision")
    return triage


def command_model_recover(args: argparse.Namespace) -> int:
    registry = _registered_candidates(args.old_token, args.new_token)
    model = _load_model(args)
    triage = _read_triage(args.run_path)
    state = model["cluster"].get("test_c")
    if not isinstance(state, dict):
        fail("Test C RECOVERY lacks modeled SETUP state")
    raw_branch = triage.get("branch")
    if not isinstance(raw_branch, str):
        fail("structured Test C triage result lacks its branch")
    state["triage_branch"] = BootstrapBranch(raw_branch)

    observed = tuple(model["cluster"]["bootstrap_keys"])
    pair = nominated_snapshot(model)
    preflight_discriminator = MockBootstrapDiscriminator(model)
    preflight_result = preflight_discriminator(
        observed,
        args.old_token,
        args.new_token,
        registry=registry,
    )
    preflight_decision = select_recovery(preflight_result, paired_snapshot=pair)
    if preflight_decision.to_evidence() != triage.get("decision"):
        fail("structured Test C triage decision changed before recovery mutation")

    protocols = MockRecoveryProtocols(model, args.old_token, args.new_token)
    recorder = EventRecorder(registry)
    artifact: dict[str, object]
    try:
        execution = apply_recovery_policy(
            observed,
            args.old_token,
            args.new_token,
            paired_snapshot=pair,
            reset=protocols.reset,
            observe_bootstrap_keys=protocols.observe_bootstrap_keys,
            observe_reset_flag=protocols.observe_reset_flag,
            reset_flag_path=RESET_FLAG_PATH,
            registry=registry,
            evidence=recorder,
            discriminator=MockBootstrapDiscriminator(model),
        )
    except RecoveryPolicyError as error:
        artifact = {
            "schema_version": 1,
            "event": "test-c-recovery-attempt",
            "verdict": "FAIL",
            "error_type": type(error).__name__,
            "reason": redact_text(str(error), registry),
            "events": recorder.records,
        }
        state["recovery_error"] = {
            "error_type": type(error).__name__,
            "reason": redact_text(str(error), registry),
        }
        atomic_json(args.model, model)
        _write_record(args.run_path, "recovery.json", artifact, registry)
        raise

    execution_record = execution.to_evidence()
    record_recovery_execution(model, execution_record)
    artifact = {
        "schema_version": 1,
        "event": "test-c-recovery-attempt",
        "verdict": "PASS",
        "events": recorder.records,
        "execution": execution_record,
    }
    sanitized = _write_record(args.run_path, "recovery.json", artifact, registry)
    atomic_json(args.model, model)
    decision = execution.decision
    print(f"recovery_form={decision.form}")
    print(f"selected_token_reference={decision.selected_token_reference}")
    print(f"explicit_token_required={str(decision.explicit_token_required).lower()}")
    print(f"reset_flag_before={json.dumps(execution.reset_flag_before.to_evidence('before'))}")
    print(f"reset_flag_after={json.dumps(execution.reset_flag_after.to_evidence('after'))}")
    print(f"post_reset_key_names={json.dumps(list(execution.post_reset_key_names))}")
    print(f"cleanup_required={str(decision.cleanup_required).lower()}")
    if decision.branch is BootstrapBranch.BOTH:
        print("orphan_survival_after_reset=true")
        print(f"orphan_key_name={decision.cleanup_key_name}")
    print(f"recovery_complete_after_reset={str(execution.recovery_complete).lower()}")
    if sanitized.get("verdict") != "PASS":
        fail("sanitized recovery artifact lost its PASS verdict")
    return 0


def command_model_finish(args: argparse.Namespace) -> int:
    registry = registry_from_environment()
    model = _load_model(args)
    try:
        record = finish_recovery(
            model,
            authorize_orphan_cleanup=args.authorize_orphan_cleanup,
            timeout_seconds=args.timeout,
        )
    except (TestCModelError, TestCModelTimeout) as error:
        atomic_json(args.model, model)
        artifact = {
            "schema_version": 1,
            "event": "test-c-recovery-finish",
            "verdict": "FAIL",
            "error_type": type(error).__name__,
            "reason": redact_text(str(error), registry),
        }
        _write_record(args.run_path, "recovery-finish.json", artifact, registry)
        raise
    artifact = {"schema_version": 1, "verdict": "PASS", **record}
    sanitized = _write_record(args.run_path, "recovery-finish.json", artifact, registry)
    atomic_json(args.model, model)
    print(f"cleanup_required={str(record['cleanup_required']).lower()}")
    cleanup = record.get("orphan_cleanup")
    if isinstance(cleanup, dict):
        print("orphan_cleanup_authorized=true")
        print(f"cleanup_key_name={cleanup['cleanup_key_name']}")
        print(f"cleanup_before_key_names={json.dumps(cleanup['before_key_names'])}")
        print(f"cleanup_after_key_names={json.dumps(cleanup['after_key_names'])}")
        print(f"orphan_removed={str(cleanup['removed']).lower()}")
    print(f"runtime_token_reference={record['runtime_token_reference']}")
    print(f"runtime_observer_method={record['runtime_observer_method']}")
    print(f"recovery_complete={str(record['recovery_complete']).lower()}")
    if sanitized.get("verdict") != "PASS":
        fail("sanitized recovery-finish artifact lost its PASS verdict")
    return 0


def command_model_observe(args: argparse.Namespace) -> int:
    model = _load_model(args)
    print(json.dumps(gate_observation(model), sort_keys=True, separators=(",", ":")))
    return 0


def command_model_runtime_token(args: argparse.Namespace) -> int:
    print(observed_running_token(_load_model(args)))
    return 0


@dataclass(frozen=True)
class GateCheck:
    """One Test C gate assertion with explicit evidence coverage."""

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
    """Complete Test C gate and reviewer-facing triage details."""

    verdict: str
    checks: tuple[GateCheck, ...]
    details: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "test": "test-c",
            "verdict": self.verdict,
            "evaluated_at": utc_now(),
            "details": self.details,
            "checks": [check.to_dict() for check in self.checks],
        }


def _mapping_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def evaluate_gate(
    baseline: dict[str, object],
    observation: dict[str, object],
    final_key_record: dict[str, object],
    triage: dict[str, object],
) -> GateResult:
    """Derive all Test C verdicts from persisted observations and frozen-gate output."""
    checks: list[GateCheck] = []
    broken = observation.get("break_observation")
    break_record = broken if isinstance(broken, dict) else {}
    stale = break_record.get("stale_token_servers_up")
    break_ok = (
        stale == ["server-1", "server-2"]
        and break_record.get("quorum_lost") is True
        and break_record.get("healthy_etcd_members") == []
    )
    checks.append(
        GateCheck(
            "two-stale-servers-produced-quorum-loss",
            break_ok,
            "exactly server-1 and server-2 up on OLD with zero healthy etcd members",
            f"stale_servers={stale!r}, quorum_lost={break_record.get('quorum_lost')!r}",
            (
                "evidence/test-c/break.json#/stale_token_servers_up",
                "evidence/test-c/break.json#/quorum_lost",
                "evidence/test-c/gate-observation.json#/break_observation",
            ),
        )
    )
    preserved = break_record.get("preserved_datastore_unchanged") is True and (
        break_record.get("preserved_datastore_before")
        == break_record.get("preserved_datastore_after")
    )
    checks.append(
        GateCheck(
            "third-server-datastore-preserved-through-triage",
            preserved and triage.get("preserved_datastore_unchanged") is True,
            "server-3 datastore digest and revision unchanged until structured triage",
            f"break_preserved={str(preserved).lower()}, "
            f"triage_preserved={str(triage.get('preserved_datastore_unchanged') is True).lower()}",
            (
                "evidence/test-c/break.json#/preserved_datastore_before",
                "evidence/test-c/break.json#/preserved_datastore_after",
                "evidence/test-c/triage.json#/preserved_datastore_unchanged",
            ),
        )
    )
    checks.append(
        GateCheck(
            "final-key-matches-observed-runtime-credential",
            final_key_record.get("passed") is True,
            "one key whose exact name derives from the independently observed runtime token",
            f"expected={final_key_record.get('expected_key_name')!r}, "
            f"observed={final_key_record.get('observed_key_names')!r}",
            (
                "evidence/test-c/gate-observation.json#/runtime_credential",
                "evidence/test-c/gate-observation.json#/bootstrap_keys",
                "evidence/test-c/final-bootstrap-key.json",
            ),
        )
    )

    execution = observation.get("recovery_execution")
    execution_record = execution if isinstance(execution, dict) else {}
    decision = execution_record.get("decision")
    decision_record = decision if isinstance(decision, dict) else {}
    initial_both = decision_record.get("branch") == BootstrapBranch.BOTH
    cleanup = observation.get("orphan_cleanup")
    cleanup_record = cleanup if isinstance(cleanup, dict) else {}
    post_reset = execution_record.get("post_reset_key_names")
    selected_key = decision_record.get("selected_key_name")
    cleanup_key = decision_record.get("cleanup_key_name")
    both_ok = True
    both_observed = "not applicable: initial branch was not BOTH"
    if initial_both:
        both_ok = (
            decision_record.get("cleanup_required") is True
            and isinstance(post_reset, list)
            and len(post_reset) == 2
            and set(post_reset) == {selected_key, cleanup_key}
            and cleanup_record.get("authorized") is True
            and cleanup_record.get("before_key_names") == sorted(post_reset)
            and cleanup_record.get("after_key_names") == [selected_key]
            and cleanup_record.get("removed") is True
        )
        both_observed = (
            f"post_reset={post_reset!r}, cleanup_required="
            f"{decision_record.get('cleanup_required')!r}, authorized="
            f"{cleanup_record.get('authorized')!r}, after="
            f"{cleanup_record.get('after_key_names')!r}"
        )
    checks.append(
        GateCheck(
            "both-orphan-survival-and-explicit-cleanup",
            both_ok,
            "for initial BOTH, orphan survives reset and authorized exact cleanup removes it",
            both_observed,
            (
                "evidence/test-c/recovery.json#/execution/post_reset_key_names",
                "evidence/test-c/recovery.json#/execution/decision/cleanup_required",
                "evidence/test-c/recovery-finish.json#/orphan_cleanup",
                "evidence/test-c/gate-observation.json#/orphan_cleanup",
            ),
        )
    )
    recovery_complete = observation.get("recovery_complete") is True
    checks.append(
        GateCheck(
            "structured-recovery-complete",
            recovery_complete,
            "reset, any required explicit cleanup, and bounded rejoin all completed",
            f"recovery_complete={str(recovery_complete).lower()}",
            (
                "evidence/test-c/recovery.json",
                "evidence/test-c/recovery-finish.json#/recovery_complete",
                "evidence/test-c/gate-observation.json#/recovery_complete",
            ),
        )
    )
    flag = observation.get("reset_flag")
    flag_record = flag if isinstance(flag, dict) else {}
    flag_ok = (
        flag_record.get("path") == RESET_FLAG_PATH
        and flag_record.get("present") is False
        and flag_record.get("mtime_ns") is None
    )
    checks.append(
        GateCheck(
            "no-stranded-reset-flag",
            flag_ok,
            f"exact reset flag {RESET_FLAG_PATH} absent with no mtime",
            f"path={flag_record.get('path')!r}, present={flag_record.get('present')!r}, "
            f"mtime_ns={flag_record.get('mtime_ns')!r}",
            (
                "evidence/test-c/recovery.json#/events/reset-flag-observation",
                "evidence/test-c/gate-observation.json#/reset_flag",
            ),
        )
    )

    nodes = _mapping_list(observation.get("nodes"))
    nodes_by_name = {str(node.get("name")): node for node in nodes}
    exact_nodes = len(nodes) == 5 and set(nodes_by_name) == set(EXPECTED_NODES)
    credentials = [
        nodes_by_name.get(node, {}).get("join_credential_sha256") for node in EXPECTED_NODES
    ]
    credential_shape = all(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
        for value in credentials
    )
    credential_set = {value for value in credentials if isinstance(value, str)}
    checks.append(
        GateCheck(
            "matching-normalized-join-credential-digests",
            exact_nodes and credential_shape and len(credential_set) == 1,
            "five populated normalized join-credential SHA-256 digests, all equal",
            f"populated={sum(isinstance(value, str) for value in credentials)}/5, "
            f"unique={len(credential_set)}",
            tuple(
                f"evidence/test-c/gate-observation.json#/nodes/{node}/join_credential_sha256"
                for node in EXPECTED_NODES
            ),
        )
    )

    raw_journals = observation.get("post_recovery_server_journals")
    journals = raw_journals if isinstance(raw_journals, dict) else {}
    failures: dict[str, int] = {}
    for server in EXPECTED_SERVERS:
        raw_lines = journals.get(server, [])
        lines = raw_lines if isinstance(raw_lines, list) else []
        failures[server] = sum(
            1 for line in lines if isinstance(line, str) and BAD_JOURNAL_RE.search(line)
        )
    journal_ok = set(journals) == set(EXPECTED_SERVERS) and sum(failures.values()) == 0
    checks.append(
        GateCheck(
            "clean-post-recovery-server-journals",
            journal_ok,
            'zero "different token" or "newer than datastore" lines on all three servers',
            f"per_server={failures!r}, total={sum(failures.values())}",
            tuple(
                f"evidence/test-c/gate-observation.json#/post_recovery_server_journals/{server}"
                for server in EXPECTED_SERVERS
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
                "evidence/test-c/gate-observation.json#/ca_sha256",
            ),
        )
    )
    ready_names = sorted(name for name, node in nodes_by_name.items() if node.get("ready") is True)
    checks.append(
        GateCheck(
            "five-ready-nodes",
            exact_nodes and set(ready_names) == set(EXPECTED_NODES),
            "the exact five inventory nodes are Ready",
            f"ready_count={len(ready_names)}, ready_names={ready_names!r}",
            tuple(
                f"evidence/test-c/gate-observation.json#/nodes/{node}/ready"
                for node in EXPECTED_NODES
            ),
        )
    )
    etcd_members = evaluate_three_healthy_etcd_members(
        baseline,
        observation,
        EXPECTED_SERVERS,
        "evidence/test-c/gate-observation.json#/etcd_members",
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
    details = {
        "triage_branch": triage.get("branch"),
        "discriminator_method": triage.get("method"),
        "source_pin": triage.get("source_pin"),
        "triage_reason": triage.get("reason"),
        "observed_key_names": triage.get("observed_key_names"),
        "expected_key_names": triage.get("expected_key_names"),
        "selected_token_reference": decision_record.get("selected_token_reference"),
        "recovery_form": decision_record.get("form"),
        "recovery_attempted": bool(execution_record),
        "cleanup_required": decision_record.get("cleanup_required") is True,
        "reset_flag_before": execution_record.get("reset_flag_before"),
        "reset_flag_after": execution_record.get("reset_flag_after"),
        "final_key_count": len(observation.get("bootstrap_keys", []))
        if isinstance(observation.get("bootstrap_keys"), list)
        else None,
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
    lines.extend(("", f"Overall Test C gate: **{result.verdict}**", ""))
    return "\n".join(lines)


def command_evaluate(args: argparse.Namespace) -> int:
    registry = registry_from_environment()
    registry.register(args.runtime_token)
    baseline = read_mapping(args.baseline)
    observation = read_mapping(args.observation)
    triage = read_mapping(test_c_evidence_dir(args.run_path) / "triage.json")
    recorder = EventRecorder(registry)
    with suppress(RecoveryInvariantError):
        assert_final_bootstrap_key(
            observation.get("bootstrap_keys", []),
            args.runtime_token,
            registry=registry,
            evidence=recorder,
        )
    final_records = [
        record for record in recorder.records if record.get("event") == "bootstrap-key-final-gate"
    ]
    if len(final_records) != 1:
        fail("frozen final bootstrap-key gate did not emit exactly one structured record")
    final_key_record = final_records[0]
    result = evaluate_gate(baseline, observation, final_key_record, triage)
    evidence_dir = test_c_evidence_dir(args.run_path)
    sanitized_observation = redact_value(observation, registry)
    if not isinstance(sanitized_observation, dict):
        raise TypeError("sanitized Test C gate observation is not a mapping")
    atomic_json(evidence_dir / "gate-observation.json", sanitized_observation)
    atomic_json(evidence_dir / "final-bootstrap-key.json", final_key_record)
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
    setup.add_argument("--old-token", required=True)
    setup.add_argument("--new-token", required=True)
    setup.add_argument("--recovery-form", required=True, choices=("snapshot", "membership"))
    break_parser = subparsers.add_parser("model-break")
    _add_model_arguments(break_parser, run_path=True)
    break_parser.add_argument("--branch", required=True, choices=tuple(BootstrapBranch))
    triage_parser = subparsers.add_parser("model-triage")
    _add_model_arguments(triage_parser, run_path=True)
    triage_parser.add_argument("--old-token", required=True)
    triage_parser.add_argument("--new-token", required=True)
    recover = subparsers.add_parser("model-recover")
    _add_model_arguments(recover, run_path=True)
    recover.add_argument("--old-token", required=True)
    recover.add_argument("--new-token", required=True)
    finish = subparsers.add_parser("model-finish")
    _add_model_arguments(finish, run_path=True)
    finish.add_argument("--authorize-orphan-cleanup", action="store_true")
    finish.add_argument("--timeout", required=True, type=int)
    observe = subparsers.add_parser("model-observe")
    _add_model_arguments(observe)
    runtime = subparsers.add_parser("model-runtime-token")
    _add_model_arguments(runtime)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--run-path", required=True, type=Path)
    evaluate.add_argument("--baseline", required=True, type=Path)
    evaluate.add_argument("--observation", required=True, type=Path)
    evaluate.add_argument("--runtime-token", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "timestamp":
            print(utc_now())
            return 0
        if args.command == "validate-token":
            assert_full_server_token(sys.stdin.read().rstrip("\n"), args.label)
            print("PASS: full server-token format asserted before Test C mutation")
            return 0
        if args.command == "registry-json":
            values = sys.stdin.read().splitlines()
            if len(values) != 2:
                fail("Test C registry initialization requires exactly OLD and NEW candidates")
            print(json.dumps(registry_values(values[0], values[1]), separators=(",", ":")))
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
        if args.command == "model-triage":
            return command_model_triage(args)
        if args.command == "model-recover":
            return command_model_recover(args)
        if args.command == "model-finish":
            return command_model_finish(args)
        if args.command == "model-observe":
            return command_model_observe(args)
        if args.command == "model-runtime-token":
            return command_model_runtime_token(args)
        return command_evaluate(args)
    except TestCPrerequisiteError as error:
        print(f"test-c prerequisite: {error}", file=sys.stderr)
        return error.exit_code
    except TestCModelTimeout as error:
        safe = redact_text(str(error), registry_from_environment())
        print(f"test-c timeout: {safe}", file=sys.stderr)
        return 70
    except (
        TestCGuardError,
        TestCModelError,
        TestAGuardError,
        RecoveryContractError,
        RecoveryHalted,
        RecoveryInvariantError,
        ResetAttemptError,
        OSError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        safe = redact_text(str(error), registry_from_environment())
        print(f"test-c guard: {safe}", file=sys.stderr)
        return 69


if __name__ == "__main__":
    raise SystemExit(main())
