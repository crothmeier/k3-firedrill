"""Offline-only Test C failure and recovery contracts for the mock driver."""

from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from firedrill.bootstrap import (
    BootstrapBranch,
    BootstrapDiscriminatorResult,
    bootstrap_key_name,
    detect_bootstrap_era,
)
from firedrill.mock_model import (
    cluster_state,
    current_server_token,
    guest_by_name,
    join_credential_sha256,
    proposed_server_token,
    server_token_for_epoch,
)
from firedrill.redact import TokenRegistry, token_reference
from firedrill.test_a import EXPECTED_NODES, EXPECTED_SERVERS, assert_full_server_token
from firedrill.test_c_recovery import (
    PairedSnapshot,
    RecoveryContractError,
    ResetFlagObservation,
    TokenCandidate,
)

RESET_FLAG_PATH = "/var/lib/rancher/k3s/server/db/reset-flag"
PRE_ROTATION_SNAPSHOT_PATH = (
    "/var/lib/rancher/k3s/server/db/snapshots/test-c-pre-rotation-server-3.db"
)
PRESERVED_SERVER = "server-3"
STALE_SERVERS = ("server-1", "server-2")
UNKNOWN_BOOTSTRAP_KEY = "/bootstrap/000000000000"
KEY_NAME_RE = re.compile(r"/bootstrap/[0-9a-f]{12}")


class TestCModelError(RuntimeError):
    """A modeled Test C operation violated its offline contract."""


class TestCModelTimeout(TestCModelError):
    """A bounded modeled recovery wait expired."""


def _validate_exact_path(path: str) -> None:
    if not path.startswith("/") or path == "/" or "//" in path:
        raise TestCModelError("modeled snapshot path must be an exact non-root absolute path")
    parsed = PurePosixPath(path)
    if str(parsed) != path or ".." in parsed.parts or any(char in path for char in "*?[]"):
        raise TestCModelError("modeled snapshot path must be canonical and contain no pattern")


@dataclass(frozen=True)
class ModeledEtcdSnapshot:
    """A secret-free modeled snapshot and its optional candidate pairing."""

    path: str
    snapshot_sha256: str
    token_candidate: TokenCandidate | None
    token_reference: str | None
    paired: bool

    def __post_init__(self) -> None:
        _validate_exact_path(self.path)
        if re.fullmatch(r"[0-9a-f]{64}", self.snapshot_sha256) is None:
            raise TestCModelError("modeled snapshot must carry a lowercase SHA-256 digest")
        if not isinstance(self.paired, bool):
            raise TestCModelError("modeled snapshot paired marker must be boolean")
        has_pair = isinstance(self.token_candidate, TokenCandidate) and isinstance(
            self.token_reference, str
        )
        if self.paired != has_pair:
            raise TestCModelError(
                "modeled snapshot pairing requires both a candidate and redacted reference"
            )
        if self.paired and not str(self.token_reference).startswith("<redacted-token "):
            raise TestCModelError("modeled snapshot pairing may store only a redacted reference")

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "snapshot_sha256": self.snapshot_sha256,
            "token_candidate": self.token_candidate,
            "token_reference": self.token_reference,
            "paired": self.paired,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> ModeledEtcdSnapshot:
        raw_candidate = value.get("token_candidate")
        candidate = TokenCandidate(raw_candidate) if isinstance(raw_candidate, str) else None
        raw_reference = value.get("token_reference")
        reference = raw_reference if isinstance(raw_reference, str) else None
        return cls(
            path=str(value.get("path", "")),
            snapshot_sha256=str(value.get("snapshot_sha256", "")),
            token_candidate=candidate,
            token_reference=reference,
            paired=value.get("paired") is True,
        )

    def as_recovery_pair(self) -> PairedSnapshot:
        if not self.paired or self.token_candidate is None or self.token_reference is None:
            raise TestCModelError(
                f"unpaired snapshot is ineligible as a recovery source: {self.path}"
            )
        return PairedSnapshot(
            restore_path=self.path,
            snapshot_sha256=self.snapshot_sha256,
            token_candidate=self.token_candidate,
            token_reference=self.token_reference,
        )


def resolve_nominated_snapshot(
    snapshots: Iterable[ModeledEtcdSnapshot],
    nominated_paths: Iterable[str],
) -> PairedSnapshot | None:
    """Resolve exactly zero or one nominated pair without mutating a model."""
    catalog = tuple(snapshots)
    nominations = tuple(nominated_paths)
    if len(nominations) > 1:
        raise TestCModelError(
            "more than one nominated snapshot pair rejected before recovery mutation"
        )
    if not nominations:
        return None
    matches = tuple(item for item in catalog if item.path == nominations[0])
    if len(matches) != 1:
        raise TestCModelError(
            "nominated snapshot must identify exactly one modeled snapshot before mutation"
        )
    return matches[0].as_recovery_pair()


def _test_state(model: dict[str, Any]) -> dict[str, Any]:
    value = model.get("cluster", {}).get("test_c")
    if not isinstance(value, dict):
        raise TestCModelError("Test C SETUP has not produced structured mock state")
    return value


def _candidate_epoch(state: dict[str, Any], candidate: TokenCandidate) -> int:
    key = "old_token_epoch" if candidate is TokenCandidate.OLD else "new_token_epoch"
    value = state.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TestCModelError(f"mock Test C state has invalid {key}")
    return value


def candidate_token(model: dict[str, Any], candidate: TokenCandidate) -> str:
    state = _test_state(model)
    return server_token_for_epoch(str(model["lab_id"]), _candidate_epoch(state, candidate))


def snapshot_catalog(model: dict[str, Any]) -> tuple[ModeledEtcdSnapshot, ...]:
    state = _test_state(model)
    raw = state.get("snapshot_catalog")
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise TestCModelError("mock Test C snapshot catalog is invalid")
    return tuple(ModeledEtcdSnapshot.from_dict(item) for item in raw)


def nominated_snapshot(model: dict[str, Any]) -> PairedSnapshot | None:
    state = _test_state(model)
    raw_paths = state.get("nominated_snapshot_paths")
    if not isinstance(raw_paths, list) or not all(isinstance(item, str) for item in raw_paths):
        raise TestCModelError("mock Test C snapshot nominations are invalid")
    return resolve_nominated_snapshot(snapshot_catalog(model), raw_paths)


def prepare_test_c(
    model: dict[str, Any],
    old_token: str,
    new_token: str,
    recovery_form: str,
) -> dict[str, object]:
    """Capture the paired snapshot and expected candidate names before rotation."""
    assert_full_server_token(old_token, "Test C current server token")
    assert_full_server_token(new_token, "Test C proposed server token")
    if recovery_form not in {"snapshot", "membership"}:
        raise TestCModelError("Test C recovery form must be snapshot or membership")
    if current_server_token(model) != old_token:
        raise TestCModelError("Test C OLD candidate is not the modeled current credential")
    if proposed_server_token(model) != new_token:
        raise TestCModelError("Test C NEW candidate is not the modeled proposed credential")
    if model["cluster"].get("test_c") is not None:
        raise TestCModelError("Test C SETUP already exists; rollback is required before rerun")
    if {guest_by_name(model, node).get("ready") for node in EXPECTED_NODES} != {True}:
        raise TestCModelError("Test C SETUP requires all five modeled nodes Ready")

    preserved = guest_by_name(model, PRESERVED_SERVER)
    old_reference = token_reference(old_token)
    new_reference = token_reference(new_token)
    digest_material = ":".join(
        (
            str(model["lab_id"]),
            PRESERVED_SERVER,
            str(preserved["datastore_sha256"]),
            str(model["cluster"]["ca_sha256"]),
            old_reference,
        )
    )
    snapshot = ModeledEtcdSnapshot(
        path=PRE_ROTATION_SNAPSHOT_PATH,
        snapshot_sha256=hashlib.sha256(digest_material.encode()).hexdigest(),
        token_candidate=TokenCandidate.OLD,
        token_reference=old_reference,
        paired=True,
    )
    nominations = (snapshot.path,) if recovery_form == "snapshot" else ()

    # Resolve caller input completely before the first model mutation.
    resolved = resolve_nominated_snapshot((snapshot,), nominations)
    old_epoch = int(model["cluster"].get("server_token_epoch", 0))
    new_epoch = int(model["cluster"].get("rotation_count", 0)) + 1
    test_state: dict[str, Any] = {
        "phase": "SETUP",
        "old_token_epoch": old_epoch,
        "new_token_epoch": new_epoch,
        "old_token_reference": old_reference,
        "new_token_reference": new_reference,
        "old_candidate_key_name": bootstrap_key_name(old_token),
        "new_candidate_key_name": bootstrap_key_name(new_token),
        "snapshot_catalog": [snapshot.to_dict()],
        "nominated_snapshot_paths": list(nominations),
        "recovery_form_requested": recovery_form,
        "baseline_ca_sha256": model["cluster"]["ca_sha256"],
        "preserved_server": PRESERVED_SERVER,
        "stale_servers": list(STALE_SERVERS),
        "reset_flag": {"path": RESET_FLAG_PATH, "present": False, "mtime_ns": None},
        "reset_attempts": 0,
        "reset_calls": [],
        "break_observation": None,
        "recovery_execution": None,
        "orphan_cleanup": None,
        "recovery_complete": False,
    }
    preserved["etcd_snapshots"][snapshot.path] = snapshot.to_dict()
    model["cluster"]["test_c"] = test_state
    model["injections"].setdefault("test_c", {})
    return {
        "event": "test-c-setup",
        "old_candidate_key_name": test_state["old_candidate_key_name"],
        "new_candidate_key_name": test_state["new_candidate_key_name"],
        "old_token_reference": old_reference,
        "new_token_reference": new_reference,
        "paired_snapshot": snapshot.to_dict(),
        "nominated_snapshot": (
            {
                "restore_path": resolved.restore_path,
                "snapshot_sha256": resolved.snapshot_sha256,
                "token_candidate": resolved.token_candidate,
                "token_reference": resolved.token_reference,
            }
            if resolved is not None
            else None
        ),
        "recovery_form_requested": recovery_form,
        "preserved_server": PRESERVED_SERVER,
    }


def _branch_keys(
    state: dict[str, Any], branch: BootstrapBranch, model: dict[str, Any]
) -> list[str]:
    old_key = str(state["old_candidate_key_name"])
    new_key = str(state["new_candidate_key_name"])
    if branch is BootstrapBranch.OLD_ONLY:
        return [old_key]
    if branch is BootstrapBranch.NEW_ONLY:
        return [new_key]
    if branch is BootstrapBranch.BOTH:
        return sorted((old_key, new_key))
    if branch is BootstrapBranch.ZERO:
        return []
    injected = model["injections"].get("test_c", {}).get("anomalous_key_names")
    if injected is None:
        return [UNKNOWN_BOOTSTRAP_KEY]
    if not isinstance(injected, list) or not all(isinstance(item, str) for item in injected):
        raise TestCModelError("anomalous key-name injection must be a list of strings")
    return copy.deepcopy(injected)


def break_test_c(model: dict[str, Any], branch: BootstrapBranch) -> dict[str, object]:
    """Model two stale-token servers, quorum loss, and one preserved datastore."""
    if not isinstance(branch, BootstrapBranch):
        raise TestCModelError("Test C BREAK requires a named discriminator branch")
    state = _test_state(model)
    if state.get("phase") != "SETUP":
        raise TestCModelError("Test C BREAK requires a fresh completed SETUP")

    preserved = guest_by_name(model, PRESERVED_SERVER)
    before = {
        "revision": preserved["datastore_revision"],
        "sha256": preserved["datastore_sha256"],
    }
    keys = _branch_keys(state, branch, model)
    model["cluster"]["server_token_epoch"] = state["new_token_epoch"]
    model["cluster"]["server_token_reference"] = state["new_token_reference"]
    new_token = candidate_token(model, TokenCandidate.NEW)
    model["cluster"]["rotation_count"] = state["new_token_epoch"]
    model["cluster"]["join_credential_sha256"] = join_credential_sha256(new_token)
    model["cluster"]["bootstrap_keys"] = keys

    for node in STALE_SERVERS:
        item = guest_by_name(model, node)
        item["k3s_running"] = True
        item["running_token_reference"] = state["old_token_reference"]
        item["ready"] = False
        item["etcd_healthy"] = False
        item["journal"].append(
            "Test C stale OLD credential start observed; embedded-etcd quorum unavailable"
        )
    preserved["k3s_running"] = False
    preserved["ready"] = False
    preserved["etcd_healthy"] = False
    for node in ("agent-1", "agent-2"):
        guest_by_name(model, node)["ready"] = False

    after = {
        "revision": preserved["datastore_revision"],
        "sha256": preserved["datastore_sha256"],
    }
    observation = {
        "event": "test-c-break-observation",
        "requested_branch": branch,
        "observed_bootstrap_key_names": copy.deepcopy(keys),
        "stale_token_servers_up": list(STALE_SERVERS),
        "stale_token_reference": state["old_token_reference"],
        "healthy_etcd_members": [],
        "quorum_lost": True,
        "preserved_server": PRESERVED_SERVER,
        "preserved_datastore_before": before,
        "preserved_datastore_after": after,
        "preserved_datastore_unchanged": before == after,
    }
    state["phase"] = "BROKEN"
    state["break_observation"] = observation
    return copy.deepcopy(observation)


class MockBootstrapDiscriminator:
    """Frozen-discriminator protocol adapter bound to one mock observation."""

    def __init__(self, model: dict[str, Any]) -> None:
        self.model = model
        self.calls = 0

    def __call__(
        self,
        observed_key_names: Iterable[str],
        old_token_candidate: str,
        new_token_candidate: str,
        *,
        registry: TokenRegistry,
    ) -> BootstrapDiscriminatorResult:
        supplied = tuple(observed_key_names)
        modeled = tuple(self.model["cluster"]["bootstrap_keys"])
        if supplied != modeled:
            raise RecoveryContractError(
                "mock discriminator input differs from the exact modeled key observation"
            )
        self.calls += 1
        return detect_bootstrap_era(
            supplied,
            old_token_candidate,
            new_token_candidate,
            registry=registry,
        )


class MockRecoveryProtocols:
    """Reset and observer protocol implementations over the offline model."""

    def __init__(self, model: dict[str, Any], old_token: str, new_token: str) -> None:
        self.model = model
        self.old_token = old_token
        self.new_token = new_token

    @property
    def state(self) -> dict[str, Any]:
        return _test_state(self.model)

    def observe_bootstrap_keys(self) -> Iterable[str]:
        return tuple(self.model["cluster"]["bootstrap_keys"])

    def observe_reset_flag(self, path: str) -> ResetFlagObservation:
        flag = self.state["reset_flag"]
        return ResetFlagObservation(
            path=str(flag["path"]),
            present=flag["present"] is True,
            mtime_ns=flag.get("mtime_ns"),
        )

    def reset(self, *, token: str, restore_path: str | None) -> None:
        state = self.state
        if token == self.old_token:
            selected = TokenCandidate.OLD
        elif token == self.new_token:
            selected = TokenCandidate.NEW
        else:
            raise TestCModelError(f"mock reset rejected unknown explicit token {token}")
        expected_reference = state[f"{selected.value.lower()}_token_reference"]
        if token_reference(token) != expected_reference:
            raise TestCModelError("mock reset explicit token reference does not match SETUP")

        pair = nominated_snapshot(self.model)
        expected_path = pair.restore_path if pair is not None else None
        if restore_path != expected_path:
            raise TestCModelError(
                "mock reset restore path differs from the exact nominated recovery source"
            )
        state["reset_attempts"] = int(state.get("reset_attempts", 0)) + 1
        state["reset_calls"].append(
            {
                "explicit_token": True,
                "selected_candidate": selected,
                "selected_token_reference": token_reference(token),
                "restore_path": restore_path,
            }
        )
        injections = self.model["injections"].get("test_c", {})
        if injections.get("reset_failure") is True:
            mtime_ns = injections.get("reset_flag_mtime_ns", 1_700_000_000_123_456_789)
            if not isinstance(mtime_ns, int) or isinstance(mtime_ns, bool):
                raise TestCModelError("reset-flag mtime injection must be an integer")
            state["reset_flag"] = {
                "path": RESET_FLAG_PATH,
                "present": True,
                "mtime_ns": mtime_ns,
            }
            raise TestCModelError(f"injected reset failure for explicit token {token}")

        result_branch = BootstrapBranch(str(state["triage_branch"]))
        selected_key = str(state[f"{selected.value.lower()}_candidate_key_name"])
        if result_branch is BootstrapBranch.BOTH:
            if injections.get("orphan_vanish_during_reset") is True:
                self.model["cluster"]["bootstrap_keys"] = [selected_key]
        else:
            self.model["cluster"]["bootstrap_keys"] = [selected_key]
        state["reset_selected_candidate"] = selected
        state["reset_selected_token_reference"] = token_reference(token)
        state["reset_restore_path"] = restore_path


def set_preexisting_reset_flag(model: dict[str, Any], mtime_ns: int) -> None:
    """Inject an exact stranded reset flag for a refusal probe."""
    if not isinstance(mtime_ns, int) or isinstance(mtime_ns, bool):
        raise TestCModelError("pre-existing reset flag mtime must be an integer")
    _test_state(model)["reset_flag"] = {
        "path": RESET_FLAG_PATH,
        "present": True,
        "mtime_ns": mtime_ns,
    }


def record_recovery_execution(model: dict[str, Any], execution: dict[str, object]) -> None:
    state = _test_state(model)
    state["recovery_execution"] = copy.deepcopy(execution)
    state["phase"] = "RESET"


def _cleanup_orphan(
    model: dict[str, Any], cleanup_key_name: str, *, authorized: bool
) -> dict[str, object]:
    if KEY_NAME_RE.fullmatch(cleanup_key_name) is None:
        raise TestCModelError("orphan cleanup requires one exact bootstrap key name")
    state = _test_state(model)
    execution = state.get("recovery_execution")
    if not isinstance(execution, dict):
        raise TestCModelError("orphan cleanup requires a structured recovery execution")
    decision = execution.get("decision")
    if not isinstance(decision, dict) or decision.get("cleanup_key_name") != cleanup_key_name:
        raise TestCModelError("orphan cleanup key differs from the structured decision")
    if not authorized:
        raise TestCModelError(
            "cleanup_required is recorded; explicit orphan cleanup authorization is absent"
        )
    before = tuple(sorted(self_name for self_name in model["cluster"]["bootstrap_keys"]))
    selected_key = decision.get("selected_key_name")
    if set(before) != {selected_key, cleanup_key_name} or len(before) != 2:
        raise TestCModelError(
            "explicit orphan cleanup requires both selected and non-selected exact keys"
        )
    model["cluster"]["bootstrap_keys"] = [selected_key]
    after = tuple(model["cluster"]["bootstrap_keys"])
    result = {
        "event": "test-c-explicit-orphan-cleanup",
        "authorized": True,
        "cleanup_key_name": cleanup_key_name,
        "before_key_names": list(before),
        "after_key_names": list(after),
        "removed": cleanup_key_name not in after,
    }
    state["orphan_cleanup"] = result
    return result


def finish_recovery(
    model: dict[str, Any],
    *,
    authorize_orphan_cleanup: bool,
    timeout_seconds: int,
) -> dict[str, object]:
    """Perform separately authorized cleanup and bounded modeled rejoin."""
    if timeout_seconds < 1:
        raise TestCModelError("mock recovery timeout must be at least one second")
    state = _test_state(model)
    execution = state.get("recovery_execution")
    if not isinstance(execution, dict):
        raise TestCModelError("recovery finish requires a structured reset execution")
    decision = execution.get("decision")
    if not isinstance(decision, dict):
        raise TestCModelError("recovery finish lacks its structured decision")
    cleanup_required = decision.get("cleanup_required") is True
    cleanup: dict[str, object] | None = None
    if cleanup_required:
        cleanup_name = decision.get("cleanup_key_name")
        if not isinstance(cleanup_name, str):
            raise TestCModelError("structured recovery decision lacks an orphan key name")
        cleanup = _cleanup_orphan(
            model,
            cleanup_name,
            authorized=authorize_orphan_cleanup,
        )

    injections = model["injections"].get("test_c", {})
    convergence = injections.get("rejoin_convergence_seconds", 1)
    if not isinstance(convergence, int) or isinstance(convergence, bool) or convergence < 0:
        raise TestCModelError("mock recovery convergence must be a non-negative integer")
    if convergence > timeout_seconds:
        raise TestCModelTimeout(
            f"mock recovery health timeout: convergence={convergence}s, bound={timeout_seconds}s"
        )

    raw_selected = decision.get("selected_candidate")
    if not isinstance(raw_selected, str):
        raise TestCModelError("structured recovery decision lacks a selected candidate")
    selected = TokenCandidate(raw_selected)
    raw_runtime = injections.get("runtime_candidate_override", selected.value)
    if not isinstance(raw_runtime, str):
        raise TestCModelError("runtime credential override must name OLD or NEW")
    try:
        runtime = TokenCandidate(raw_runtime)
    except ValueError as error:
        raise TestCModelError("runtime credential override must name OLD or NEW") from error
    selected_token = candidate_token(model, selected)
    runtime_token = candidate_token(model, runtime)
    selected_digest = join_credential_sha256(selected_token)
    other = TokenCandidate.NEW if selected is TokenCandidate.OLD else TokenCandidate.OLD
    mismatch_digest = join_credential_sha256(candidate_token(model, other))
    mismatch_node = injections.get("join_credential_mismatch_node")
    not_ready_node = injections.get("not_ready_node")
    unhealthy_member = injections.get("unhealthy_member")
    journal_lines = injections.get("post_recovery_journal_lines", {})
    if not isinstance(journal_lines, dict):
        raise TestCModelError("post-recovery journal injection must be a mapping")

    journal_starts: dict[str, int] = {}
    for node in EXPECTED_NODES:
        item = guest_by_name(model, node)
        journal_starts[node] = len(item["journal"])
        item["power"] = "running"
        item["installed"] = True
        item["k3s_running"] = True
        item["running_token_reference"] = token_reference(runtime_token)
        item["join_credential_sha256"] = (
            mismatch_digest if node == mismatch_node else selected_digest
        )
        item["ready"] = node != not_ready_node
        item["etcd_healthy"] = item["role"] == "server" and node != unhealthy_member
        item["journal"].append("Test C post-recovery k3s process converged Ready")
        extra = journal_lines.get(node, [])
        if not isinstance(extra, list) or not all(isinstance(line, str) for line in extra):
            raise TestCModelError(f"post-recovery journal injection for {node} is invalid")
        item["journal"].extend(extra)

    model["cluster"]["server_token_epoch"] = _candidate_epoch(state, runtime)
    model["cluster"]["server_token_reference"] = token_reference(runtime_token)
    model["cluster"]["join_credential_sha256"] = selected_digest
    if injections.get("ca_hash_changed") is True:
        model["cluster"]["ca_sha256"] = hashlib.sha256(
            f"changed-ca:{model['lab_id']}".encode()
        ).hexdigest()
    final_keys = injections.get("final_bootstrap_keys")
    if final_keys is not None:
        if not isinstance(final_keys, list) or not all(
            isinstance(item, str) for item in final_keys
        ):
            raise TestCModelError("final bootstrap-key injection must be a list of strings")
        model["cluster"]["bootstrap_keys"] = copy.deepcopy(final_keys)

    state["runtime_token_candidate"] = runtime
    state["runtime_token_reference"] = token_reference(runtime_token)
    state["runtime_observer_method"] = "mock-k3s-process-explicit-token-observer"
    state["post_recovery_journal_start"] = journal_starts
    state["recovery_complete"] = True
    state["phase"] = "RECOVERED"
    return {
        "event": "test-c-recovery-finish",
        "selected_candidate": selected,
        "runtime_candidate_observed": runtime,
        "runtime_token_reference": token_reference(runtime_token),
        "runtime_observer_method": state["runtime_observer_method"],
        "cleanup_required": cleanup_required,
        "orphan_cleanup": cleanup,
        "rejoin_timeout_seconds": timeout_seconds,
        "rejoin_convergence_seconds": convergence,
        "recovery_complete": True,
    }


def observed_running_token(model: dict[str, Any]) -> str:
    """Return the raw in-process credential reported by the mock process observer."""
    state = _test_state(model)
    raw_candidate = state.get("runtime_token_candidate")
    if not isinstance(raw_candidate, str):
        raise TestCModelError("mock runtime credential is unavailable before recovery finish")
    candidate = TokenCandidate(raw_candidate)
    token = candidate_token(model, candidate)
    if token_reference(token) != state.get("runtime_token_reference"):
        raise TestCModelError("mock runtime credential reference is internally inconsistent")
    return token


def gate_observation(model: dict[str, Any]) -> dict[str, object]:
    """Capture every modeled Test C gate input without exposing a token value."""
    state = _test_state(model)
    starts = state.get("post_recovery_journal_start", {})
    if not isinstance(starts, dict):
        raise TestCModelError("post-recovery journal window markers are invalid")
    journals: dict[str, list[str]] = {}
    for server in EXPECTED_SERVERS:
        item = guest_by_name(model, server)
        start = starts.get(server)
        if not isinstance(start, int) or isinstance(start, bool) or start < 0:
            raise TestCModelError(f"post-recovery journal window is absent for {server}")
        journals[server] = copy.deepcopy(item["journal"][start:])

    observation = cluster_state(model)
    observation.update(
        {
            "event": "test-c-gate-observation",
            "break_observation": copy.deepcopy(state.get("break_observation")),
            "recovery_execution": copy.deepcopy(state.get("recovery_execution")),
            "orphan_cleanup": copy.deepcopy(state.get("orphan_cleanup")),
            "recovery_complete": state.get("recovery_complete") is True,
            "reset_flag": copy.deepcopy(state.get("reset_flag")),
            "runtime_credential": {
                "candidate": state.get("runtime_token_candidate"),
                "token_reference": state.get("runtime_token_reference"),
                "method": state.get("runtime_observer_method"),
            },
            "post_recovery_server_journals": journals,
        }
    )
    raw_output = model["injections"].get("raw_output")
    if raw_output is not None:
        observation["modeled_diagnostic"] = raw_output
    return observation
