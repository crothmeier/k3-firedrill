"""Test A guards, prerequisite checks, phase records, and evidence-derived gate."""

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
from typing import NoReturn

from firedrill.bootstrap import normalize_token
from firedrill.config import provision_identity
from firedrill.etcd_members import evaluate_three_healthy_etcd_members
from firedrill.redact import token_reference
from firedrill.state import atomic_json

FULL_SERVER_TOKEN_PATTERN = r"^K10[a-f0-9]{64}::server:\S+$"
FULL_SERVER_TOKEN_RE = re.compile(FULL_SERVER_TOKEN_PATTERN)
TOKEN_ROLE_RE = re.compile(r"^K10[a-fA-F0-9]{64}::(?P<role>[^:]+):")
DECRYPTION_FAILURE_RE = re.compile(
    r"(?:failed\s+to\s+decrypt[^\n]*bootstrap)"
    r"|(?:bootstrap[^\n]*(?:decrypt|decryption)[^\n]*(?:fail|error))"
    r"|(?:bootstrap[^\n]*(?:different\s+token|newer\s+than\s+datastore))"
    r"|(?:cipher:\s*message\s+authentication\s+failed)",
    re.IGNORECASE,
)
EXPECTED_NODES = ("server-1", "server-2", "server-3", "agent-1", "agent-2")
EXPECTED_SERVERS = ("server-1", "server-2", "server-3")
PHASE_ORDER = ("SETUP", "BREAK", "GATE")


class TestAGuardError(RuntimeError):
    """A Test A pre-mutation contract was not satisfied."""


class TestAPrerequisiteError(TestAGuardError):
    """The active lab does not match its captured baseline."""

    def __init__(self, message: str, exit_code: int = 66) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def fail(message: str) -> NoReturn:
    raise TestAGuardError(message)


def classify_invalid_token(token: str) -> str:
    """Return a secret-free classification for a rejected token."""
    role_match = TOKEN_ROLE_RE.match(token)
    if role_match and role_match.group("role") in {"agent", "node"}:
        return "agent-token"
    if not token.startswith("K10"):
        return "bare-or-short-secret"
    return "malformed-full-token"


def assert_full_server_token(token: str, label: str = "server token") -> str:
    """Require the exact full-format server-token shape without echoing the value."""
    if not isinstance(token, str) or not FULL_SERVER_TOKEN_RE.fullmatch(token):
        classification = classify_invalid_token(token) if isinstance(token, str) else "non-string"
        fail(
            f"{label} rejected before mutation: expected {FULL_SERVER_TOKEN_PATTERN}; "
            f"classification={classification}"
        )
    return token


def registry_values(old_token: str, new_token: str) -> list[str]:
    """Return raw candidates and normalized secrets for the process-only registry."""
    candidates = (
        assert_full_server_token(old_token, "current server token"),
        assert_full_server_token(new_token, "proposed server token"),
    )
    values: list[str] = []
    for candidate in candidates:
        for value in (candidate, normalize_token(candidate)):
            if value not in values:
                values.append(value)
    return values


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_timestamp(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise TestAGuardError(f"invalid phase timestamp {value!r}") from error
    if parsed.tzinfo is None:
        fail(f"phase timestamp lacks a timezone: {value!r}")
    return parsed


def atomic_text(path: Path, value: str) -> None:
    """Replace a text artifact without exposing a partially written file."""
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


def read_mapping(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail(f"expected a JSON mapping in {path}")
    return value


def baseline_prerequisites(
    baseline: dict[str, object],
    current: dict[str, object],
    state: dict[str, object],
    canonical: dict[str, object],
    snapshot_status: dict[str, bool],
    *,
    manifest_config: dict[str, object] | None = None,
) -> dict[str, object]:
    """Compare independent current observations with persisted baseline/config state."""
    checks: list[dict[str, object]] = []

    def add(name: str, passed: bool, expected: str, observed: str, coverage: list[str]) -> None:
        checks.append(
            {
                "check": name,
                "verdict": "PASS" if passed else "FAIL",
                "expected": expected,
                "observed": observed,
                "coverage": coverage,
            }
        )

    inventory_matches = state.get("inventory") == canonical.get("inventory")
    if manifest_config is None:
        config_matches = state.get("config_sha256") == canonical.get("config_sha256")
        add(
            "config-and-inventory-identity",
            config_matches and inventory_matches,
            "state config digest and inventory equal the selected canonical config",
            f"config_match={str(config_matches).lower()}, inventory_match="
            f"{str(inventory_matches).lower()}",
            ["state.json#/config_sha256", "state.json#/inventory", "manifest.json#/config"],
        )
    else:
        provisioned_identity = provision_identity(manifest_config)[
            "provision_identity_sha256"
        ]
        identity_matches = provisioned_identity == canonical.get(
            "provision_identity_sha256"
        )
        add(
            "provision-identity-and-inventory",
            identity_matches and inventory_matches,
            "manifest provision identity and state inventory equal the selected canonical config",
            f"provision_identity_match={str(identity_matches).lower()}, inventory_match="
            f"{str(inventory_matches).lower()}",
            [
                "manifest.json#/config",
                "canonical-config#/provision_identity_sha256",
                "state.json#/inventory",
            ],
        )

    cluster_fields = (
        "nodes",
        "all_nodes_ready",
        "etcd_members",
        "all_etcd_members_healthy",
        "bootstrap_keys",
        "ca_sha256",
    )
    differing = [field for field in cluster_fields if current.get(field) != baseline.get(field)]
    add(
        "cluster-matches-baseline",
        not differing,
        "current health, key names, credentials, and CA equal the captured baseline",
        "matching" if not differing else f"differing_fields={','.join(differing)}",
        ["baseline/cluster-state.json", "evidence/commands.jsonl#test-a-current-state"],
    )

    expected_snapshots = set(EXPECTED_NODES)
    present_snapshots = {name for name, present in snapshot_status.items() if present}
    snapshots_match = set(snapshot_status) == expected_snapshots and (
        present_snapshots == expected_snapshots
    )
    missing = sorted(expected_snapshots - present_snapshots)
    add(
        "all-baseline-snapshots-present",
        snapshots_match,
        "one named baseline hypervisor snapshot for each of five inventory nodes",
        "all present" if snapshots_match else f"missing={missing!r}",
        [
            "baseline/snapshots.json",
            *[f"driver snapshot observation:{name}" for name in EXPECTED_NODES],
        ],
    )
    return {
        "schema_version": 1,
        "event": "test-a-baseline-prerequisites",
        "verdict": "PASS" if all(item["verdict"] == "PASS" for item in checks) else "FAIL",
        "checks": checks,
    }


def assert_baseline_prerequisites(result: dict[str, object]) -> None:
    if result["verdict"] == "PASS":
        return
    checks = result.get("checks", [])
    assert isinstance(checks, list)
    failed = [str(item["check"]) for item in checks if item.get("verdict") == "FAIL"]
    if failed == ["all-baseline-snapshots-present"]:
        raise TestAPrerequisiteError(
            "baseline prerequisite rejected missing snapshot coverage: " + ",".join(failed),
            67,
        )
    if failed == ["provision-identity-and-inventory"]:
        raise TestAPrerequisiteError(
            "baseline prerequisite rejected provision identity: " + ",".join(failed),
            69,
        )
    raise TestAPrerequisiteError(
        "baseline prerequisite mismatch: " + ",".join(failed),
        66,
    )


@dataclass(frozen=True)
class GateCheck:
    """One evidence-backed Test A gate assertion."""

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
    """Complete Test A gate result, including explicit file-level coverage."""

    verdict: str
    checks: tuple[GateCheck, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "test": "test-a",
            "verdict": self.verdict,
            "evaluated_at": utc_now(),
            "checks": [check.to_dict() for check in self.checks],
        }


def _mapping_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def evaluate_gate(
    baseline: dict[str, object],
    observation: dict[str, object],
    expected_server_order: tuple[str, ...],
) -> GateResult:
    """Derive every Test A verdict solely from baseline and gate observations."""
    if len(expected_server_order) != 3 or set(expected_server_order) != set(EXPECTED_SERVERS):
        fail("gate evaluator requires an exact server restart-order permutation")

    checks: list[GateCheck] = []
    restart_events = _mapping_list(observation.get("restart_events"))
    actual_order = [str(event.get("node", "missing")) for event in restart_events]
    expected_prefix = list(expected_server_order)
    server_order_ok = actual_order[:3] == expected_prefix
    agents_after = len(actual_order) == 5 and set(actual_order[3:]) == {"agent-1", "agent-2"}
    convergence_ok = all(event.get("status") == "healthy" for event in restart_events)
    checks.append(
        GateCheck(
            "configured-rolling-restart-order",
            server_order_ok and agents_after and convergence_ok,
            "servers in configured order with health convergence, then both agents",
            f"order={actual_order!r}, all_events_healthy={str(convergence_ok).lower()}",
            (
                "manifest.json#/config/restart_order",
                "evidence/test-a/gate-observation.json#/restart_events",
            ),
        )
    )

    journals = observation.get("server_journals")
    journal_mapping = journals if isinstance(journals, dict) else {}
    journal_failures: dict[str, int] = {}
    for server in EXPECTED_SERVERS:
        raw_lines = journal_mapping.get(server, [])
        lines = raw_lines if isinstance(raw_lines, list) else []
        journal_failures[server] = sum(
            1 for line in lines if isinstance(line, str) and DECRYPTION_FAILURE_RE.search(line)
        )
    journal_shape_ok = set(journal_mapping) == set(EXPECTED_SERVERS)
    total_failures = sum(journal_failures.values())
    checks.append(
        GateCheck(
            "zero-bootstrap-decryption-journal-failures",
            journal_shape_ok and total_failures == 0,
            "zero matching failure lines across all three server journal windows",
            f"per_server={journal_failures!r}, total={total_failures}",
            tuple(
                f"evidence/test-a/gate-observation.json#/server_journals/{server}"
                for server in EXPECTED_SERVERS
            ),
        )
    )

    raw_keys = observation.get("bootstrap_keys")
    keys = raw_keys if isinstance(raw_keys, list) else []
    keys_valid = all(isinstance(key, str) and key.startswith("/bootstrap/") for key in keys)
    checks.append(
        GateCheck(
            "exactly-one-bootstrap-key",
            keys_valid and len(keys) == 1,
            "exactly one /bootstrap/ key name",
            f"count={len(keys)}, names={keys!r}",
            ("evidence/test-a/gate-observation.json#/bootstrap_keys",),
        )
    )

    nodes = _mapping_list(observation.get("nodes"))
    nodes_by_name = {str(node.get("name")): node for node in nodes}
    exact_nodes = set(nodes_by_name) == set(EXPECTED_NODES) and len(nodes) == 5
    credentials = [
        nodes_by_name.get(name, {}).get("join_credential_sha256") for name in EXPECTED_NODES
    ]
    credential_shape = all(
        isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)
        for value in credentials
    )
    unique_credentials = {value for value in credentials if isinstance(value, str)}
    checks.append(
        GateCheck(
            "matching-normalized-join-credential-references",
            exact_nodes and credential_shape and len(unique_credentials) == 1,
            "five role-appropriate normalized credential SHA-256 references, all equal",
            f"populated={sum(isinstance(value, str) for value in credentials)}/5, "
            f"unique={len(unique_credentials)}",
            tuple(
                f"evidence/test-a/gate-observation.json#/nodes/{name}/join_credential_sha256"
                for name in EXPECTED_NODES
            ),
        )
    )

    ready_names = sorted(
        name for name, node in nodes_by_name.items() if node.get("ready") is True
    )
    checks.append(
        GateCheck(
            "five-ready-nodes",
            exact_nodes and set(ready_names) == set(EXPECTED_NODES),
            "the exact five inventory nodes are Ready",
            f"ready_count={len(ready_names)}, ready_names={ready_names!r}",
            tuple(
                f"evidence/test-a/gate-observation.json#/nodes/{name}/ready"
                for name in EXPECTED_NODES
            ),
        )
    )

    baseline_ca = baseline.get("ca_sha256")
    observed_ca = observation.get("ca_sha256")
    ca_ok = (
        isinstance(baseline_ca, str)
        and bool(baseline_ca)
        and observed_ca == baseline_ca
    )
    checks.append(
        GateCheck(
            "ca-hash-unchanged",
            ca_ok,
            "gate CA SHA-256 exactly equals the baselined CA SHA-256",
            f"match={str(ca_ok).lower()}",
            (
                "baseline/cluster-state.json#/ca_sha256",
                "evidence/test-a/gate-observation.json#/ca_sha256",
            ),
        )
    )

    etcd_members = evaluate_three_healthy_etcd_members(
        baseline,
        observation,
        EXPECTED_SERVERS,
        "evidence/test-a/gate-observation.json#/etcd_members",
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

    verdict = "PASS" if all(check.passed for check in checks) else "FAIL"
    return GateResult(verdict, tuple(checks))


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
    lines.extend(("", f"Overall Test A gate: **{result.verdict}**", ""))
    return "\n".join(lines)


def record_phase(
    run_path: Path,
    sequence: int,
    phase: str,
    started_at: str,
    ended_at: str,
    exit_code: int,
) -> dict[str, object]:
    if phase not in PHASE_ORDER:
        fail(f"unknown Test A phase {phase!r}")
    start = parse_timestamp(started_at)
    end = parse_timestamp(ended_at)
    duration = (end - start).total_seconds()
    if duration < 0:
        fail(f"phase {phase} ended before it started")
    path = run_path / "evidence" / "test-a" / "phases.json"
    records: list[dict[str, object]] = []
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, list) or not all(isinstance(item, dict) for item in loaded):
            fail(f"invalid Test A phase evidence: {path}")
        records = loaded
    if len(records) >= len(PHASE_ORDER) or PHASE_ORDER[len(records)] != phase:
        fail(f"phase order violation: expected {PHASE_ORDER[len(records)]!r}, observed {phase!r}")
    if records and sequence <= int(records[-1]["sequence"]):
        fail("phase evidence sequence must increase")
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


def parse_snapshot_status(values: list[str]) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for value in values:
        name, separator, status = value.partition("=")
        if not separator or name not in EXPECTED_NODES or status not in {"true", "false"}:
            fail(f"invalid snapshot status {value!r}")
        if name in result:
            fail(f"duplicate snapshot status for {name}")
        result[name] = status == "true"
    return result


def command_baseline_check(args: argparse.Namespace) -> int:
    manifest = read_mapping(args.manifest)
    manifest_config = manifest.get("config")
    if not isinstance(manifest_config, dict):
        fail("manifest is missing its canonical config")
    result = baseline_prerequisites(
        read_mapping(args.baseline),
        read_mapping(args.current),
        read_mapping(args.state),
        read_mapping(args.canonical),
        parse_snapshot_status(args.snapshot_status),
        manifest_config=manifest_config,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    assert_baseline_prerequisites(result)
    return 0


def command_evaluate(args: argparse.Namespace) -> int:
    baseline = read_mapping(args.baseline)
    observation = read_mapping(args.observation)
    expected_order = tuple(item.strip() for item in args.expected_order.split(","))
    result = evaluate_gate(baseline, observation, expected_order)
    evidence_dir = args.run_path / "evidence" / "test-a"
    atomic_json(evidence_dir / "gate-observation.json", observation)
    atomic_json(evidence_dir / "gate.json", result.to_dict())
    table = render_gate_table(result)
    atomic_text(evidence_dir / "gate-table.md", table)
    print(table, end="")
    return 0 if result.verdict == "PASS" else 1


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
    baseline.add_argument("--manifest", required=True, type=Path)
    baseline.add_argument("--snapshot-status", action="append", default=[])
    phase = subparsers.add_parser("record-phase")
    phase.add_argument("--run-path", required=True, type=Path)
    phase.add_argument("--sequence", required=True, type=int)
    phase.add_argument("--phase", required=True)
    phase.add_argument("--started-at", required=True)
    phase.add_argument("--ended-at", required=True)
    phase.add_argument("--exit-code", required=True, type=int)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--run-path", required=True, type=Path)
    evaluate.add_argument("--baseline", required=True, type=Path)
    evaluate.add_argument("--observation", required=True, type=Path)
    evaluate.add_argument("--expected-order", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "timestamp":
            print(utc_now())
            return 0
        if args.command == "validate-token":
            assert_full_server_token(sys.stdin.read().rstrip("\n"), args.label)
            print("PASS: full server-token format asserted before mutation")
            return 0
        if args.command == "registry-json":
            values = sys.stdin.read().splitlines()
            if len(values) != 2:
                fail("registry initialization requires exactly old and new token candidates")
            print(json.dumps(registry_values(values[0], values[1]), separators=(",", ":")))
            return 0
        if args.command == "references-json":
            values = sys.stdin.read().splitlines()
            if len(values) != 2:
                fail("token reference capture requires exactly old and new candidates")
            registry_values(values[0], values[1])
            references = {
                "old": token_reference(values[0]),
                "new": token_reference(values[1]),
            }
            print(json.dumps(references, sort_keys=True, separators=(",", ":")))
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
        return command_evaluate(args)
    except TestAPrerequisiteError as error:
        print(f"test-a prerequisite: {error}", file=sys.stderr)
        return error.exit_code
    except (TestAGuardError, OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        print(f"test-a guard: {error}", file=sys.stderr)
        return 69


if __name__ == "__main__":
    raise SystemExit(main())
