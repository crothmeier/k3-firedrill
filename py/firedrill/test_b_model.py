"""Offline Test B stale-systemd-token world for the mock driver."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import re
import time
from pathlib import PurePosixPath
from typing import Any, NoReturn

from firedrill.mock_model import (
    cluster_state,
    current_server_token,
    guest_by_name,
    join_credential_sha256,
    proposed_server_token,
)
from firedrill.redact import token_reference
from firedrill.test_a import EXPECTED_NODES, EXPECTED_SERVERS, assert_full_server_token

CRASH_SIGNATURE = "bootstrap data already found and encrypted with different token"
TIMESTAMP_TRAP_SIGNATURE = "newer than datastore"
ORDINARY_STALE_AGENT_SIGNATURE = (
    "failed to retrieve configuration from server: not authorized"
)
CSR_FALLBACK_SIGNATURE = "401 Unauthorized"
REGULAR_FILE_TYPE = "regular-file"
ABSENT_FILE_TYPE = "absent"


class TestBModelError(RuntimeError):
    """The requested Test B transition violates the modeled contract."""


class TestBSignatureError(TestBModelError):
    """The intended stale-token crash signature was not independently observed."""


class TestBBlastRadiusError(TestBModelError):
    """The break escaped its intended one-server blast radius."""


class TestBDeletionGuardError(TestBModelError):
    """A requested credential deletion is not exactly allowlisted and regular."""


class TestBTimeout(TestBModelError):
    """The bounded Test B health wait did not converge."""


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def fail(message: str) -> NoReturn:
    raise TestBModelError(message)


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{label} must be a mapping")
    return value


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        fail(f"{label} must be a list of strings")
    return list(value)


def validate_test_b_config(value: object) -> dict[str, Any]:
    config = _mapping(value, "canonical Test B configuration")
    target = config.get("target_server")
    if target not in EXPECTED_SERVERS:
        fail("canonical Test B target must be exactly one expected server")
    data_dir = config.get("data_dir")
    if not isinstance(data_dir, str):
        fail("canonical Test B data directory is missing")
    allowlist = _string_list(config.get("deletion_allowlist"), "Test B deletion allowlist")
    expected = [f"{data_dir}/server/cred/passwd", f"{data_dir}/server/token"]
    if allowlist != expected:
        fail("Test B deletion allowlist differs from the two source-pinned paths")
    surfaces = config.get("precedence_surfaces")
    if not isinstance(surfaces, list) or not surfaces:
        fail("canonical Test B precedence surface is empty")
    seen: set[tuple[str, str]] = set()
    for entry in surfaces:
        mapping = _mapping(entry, "Test B precedence entry")
        surface = mapping.get("surface")
        path = mapping.get("path")
        if not isinstance(surface, str) or not isinstance(path, str):
            fail("Test B precedence entry lacks a surface or path")
        pair = (surface, path)
        if pair in seen:
            fail("Test B precedence configuration contains a duplicate entry")
        seen.add(pair)
    override_path = config.get("owned_override_path")
    if not isinstance(override_path, str):
        fail("canonical Test B owned override path is missing")
    timeout = config.get("recovery_timeout_seconds")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
        fail("canonical Test B recovery timeout must be a positive integer")
    return config


def _test_state(model: dict[str, Any]) -> dict[str, Any]:
    state = model.get("cluster", {}).get("test_b")
    if not isinstance(state, dict):
        fail("mock Test B state is unavailable before SETUP")
    return state


def _injections(model: dict[str, Any]) -> dict[str, Any]:
    injections = model.setdefault("injections", {}).setdefault("test_b", {})
    if not isinstance(injections, dict):
        fail("mock Test B injection state is invalid")
    return injections


def set_injection(model: dict[str, Any], name: str, value: object) -> None:
    allowed = {
        "omit_crash_signature",
        "break_quorum_loss",
        "unhealthy_bystander",
        "skip_deletion",
        "health_convergence_seconds",
    }
    if name not in allowed:
        fail(f"unknown Test B injection {name!r}")
    _injections(model)[name] = value


def set_credential_type(model: dict[str, Any], path: str, file_type: str) -> None:
    state = _test_state(model)
    files = _mapping(state.get("local_credentials"), "Test B local credential state")
    if path not in files:
        raise TestBDeletionGuardError(
            f"cannot inject a type for off-allowlist credential path {path!r}"
        )
    metadata = _mapping(files[path], f"credential metadata for {path}")
    metadata["type"] = file_type


def _healthy_server(item: dict[str, Any]) -> bool:
    return bool(
        item.get("power") == "running"
        and item.get("installed")
        and item.get("k3s_running")
        and item.get("ready")
        and item.get("etcd_healthy")
    )


def _healthy_etcd_member(item: dict[str, Any]) -> bool:
    return bool(
        item.get("power") == "running"
        and item.get("installed")
        and item.get("k3s_running")
        and item.get("etcd_healthy")
    )


def _snapshot_pair(
    model: dict[str, Any], node: str, old_reference: str
) -> dict[str, object]:
    path = f"/var/lib/rancher/k3s/server/db/snapshots/test-b-{node}.db"
    digest_input = f"{model['lab_id']}:{node}:{old_reference}:{model['cluster']['ca_sha256']}"
    return {
        "node": node,
        "path": path,
        "snapshot_sha256": hashlib.sha256(digest_input.encode()).hexdigest(),
        "server_token_reference": old_reference,
    }


def prepare_test_b(
    model: dict[str, Any],
    old_token: str,
    new_token: str,
    test_b_config: object,
) -> dict[str, object]:
    """Pair snapshots and rotate configuration references without rolling all nodes."""
    config = validate_test_b_config(test_b_config)
    assert_full_server_token(old_token, "Test B current server token")
    assert_full_server_token(new_token, "Test B proposed server token")
    if old_token != current_server_token(model):
        fail("Test B SETUP current-token observation changed before mutation")
    if new_token != proposed_server_token(model) or new_token == old_token:
        fail("Test B SETUP proposed token is not the next modeled server token")
    if model["cluster"].get("test_b") is not None:
        fail("Test B SETUP already exists for this baseline")
    if {str(item.get("short_name")) for item in model.get("guests", {}).values()} != set(
        EXPECTED_NODES
    ):
        fail("Test B SETUP requires the exact five-node mock inventory")
    unhealthy = [
        server for server in EXPECTED_SERVERS if not _healthy_server(guest_by_name(model, server))
    ]
    if unhealthy:
        fail(f"Test B SETUP requires three healthy servers; unhealthy={unhealthy!r}")

    old_reference = token_reference(old_token)
    new_reference = token_reference(new_token)
    pairs = {
        server: _snapshot_pair(model, server, old_reference) for server in EXPECTED_SERVERS
    }
    for server, pair in pairs.items():
        guest_by_name(model, server)["etcd_snapshots"][str(pair["path"])] = copy.deepcopy(pair)

    next_epoch = int(model["cluster"].get("rotation_count", 0)) + 1
    model["cluster"]["server_token_epoch"] = next_epoch
    model["cluster"]["rotation_count"] = next_epoch
    model["cluster"]["server_token_reference"] = new_reference
    model["cluster"]["join_credential_sha256"] = join_credential_sha256(new_token)
    from firedrill.bootstrap import bootstrap_key_name

    model["cluster"]["bootstrap_keys"] = [bootstrap_key_name(new_token)]
    for node in EXPECTED_NODES:
        item = guest_by_name(model, node)
        item["join_credential_sha256"] = model["cluster"]["join_credential_sha256"]

    allowlist = _string_list(config["deletion_allowlist"], "Test B deletion allowlist")
    local_credentials = {
        path: {
            "path": path,
            "exists": True,
            "type": REGULAR_FILE_TYPE,
            "owner": "root:root",
            "mode": "0600",
            "mtime": "2026-08-30T00:00:00.000Z",
            "token_reference": old_reference,
        }
        for path in allowlist
    }
    state: dict[str, Any] = {
        "phase": "SETUP",
        "target_server": config["target_server"],
        "old_token_reference": old_reference,
        "new_token_reference": new_reference,
        "snapshot_pairs": pairs,
        "rotated_without_full_roll": True,
        "non_restarted_nodes": list(EXPECTED_NODES),
        "test_b_config": copy.deepcopy(config),
        "local_credentials": local_credentials,
        "owned_override": None,
        "break_observation": None,
        "recovery_observation": None,
    }
    model["cluster"]["test_b"] = state
    return {
        "schema_version": 1,
        "event": "test-b-setup",
        "target_server": config["target_server"],
        "old_token_reference": old_reference,
        "new_token_reference": new_reference,
        "snapshot_pairs": copy.deepcopy(pairs),
        "rotated_without_full_roll": True,
        "non_restarted_nodes": list(EXPECTED_NODES),
    }


def break_test_b(model: dict[str, Any]) -> dict[str, object]:
    """Restart exactly one stale-override server and prove the contained blast radius."""
    state = _test_state(model)
    if state.get("phase") != "SETUP":
        fail("Test B BREAK requires completed SETUP state")
    target = str(state["target_server"])
    config = validate_test_b_config(state.get("test_b_config"))
    injections = _injections(model)
    target_item = guest_by_name(model, target)
    journal_start = len(target_item["journal"])
    state["owned_override"] = {
        "path": config["owned_override_path"],
        "owner_lab_id": model["lab_id"],
        "server": target,
        "execstart_token_reference": state["old_token_reference"],
        "argument_name": "--token",
        "assignment_operator": "=",
    }
    target_item["journal"].append("Test B owned systemd override installed for one server")
    target_item["restart_count"] = int(target_item.get("restart_count", 0)) + 1
    target_item["ready"] = False
    target_item["k3s_running"] = False
    target_item["etcd_healthy"] = False
    if injections.get("omit_crash_signature") is True:
        target_item["journal"].append("k3s exited without the pinned stale-token signature")
    else:
        target_item["journal"].append(CRASH_SIGNATURE)

    bystanders = [server for server in EXPECTED_SERVERS if server != target]
    unhealthy_bystander = injections.get("unhealthy_bystander")
    if unhealthy_bystander is not None:
        if unhealthy_bystander not in bystanders:
            fail("unhealthy-bystander injection must select one untouched server")
        guest_by_name(model, str(unhealthy_bystander))["ready"] = False
    if injections.get("break_quorum_loss") is True:
        lost = guest_by_name(model, bystanders[0])
        lost["ready"] = False
        lost["etcd_healthy"] = False

    bystander_proof = {
        server: {
            "ready": guest_by_name(model, server).get("ready") is True,
            "etcd_healthy": guest_by_name(model, server).get("etcd_healthy") is True,
            "k3s_running": guest_by_name(model, server).get("k3s_running") is True,
        }
        for server in bystanders
    }
    bystanders_healthy = all(all(values.values()) for values in bystander_proof.values())
    healthy_members = [
        server
        for server in EXPECTED_SERVERS
        if _healthy_etcd_member(guest_by_name(model, server))
    ]
    quorum_intact = len(healthy_members) >= 2
    api_served = quorum_intact
    target_window = copy.deepcopy(target_item["journal"][journal_start:])
    crash_count = sum(line == CRASH_SIGNATURE for line in target_window)
    crash_observed = crash_count >= 1
    failure_class: str | None = None
    if not quorum_intact:
        failure_class = "quorum-lost-during-break"
    elif not bystanders_healthy:
        failure_class = "unhealthy-bystander-server"
    elif not crash_observed:
        failure_class = "missing-crash-signature"
    record = {
        "schema_version": 1,
        "event": "test-b-break",
        "verdict": "PASS" if failure_class is None else "FAIL",
        "failure_class": failure_class,
        "target_server": target,
        "owned_override": copy.deepcopy(state["owned_override"]),
        "stale_override_server_count": 1,
        "target_journal_window": target_window,
        "crash_signature": CRASH_SIGNATURE,
        "crash_signature_count": crash_count,
        "crash_signature_observed": crash_observed,
        "bystander_servers": bystanders,
        "bystander_health": bystander_proof,
        "bystanders_healthy": bystanders_healthy,
        "healthy_etcd_members": healthy_members,
        "quorum_intact": quorum_intact,
        "api_served": api_served,
    }
    state["break_observation"] = copy.deepcopy(record)
    state["phase"] = "BROKEN" if failure_class is None else "BREAK_FAILED"
    if failure_class == "quorum-lost-during-break":
        raise TestBBlastRadiusError(
            "Test B blast-radius abort: quorum lost during BREAK; recovery not attempted"
        )
    if failure_class == "unhealthy-bystander-server":
        raise TestBBlastRadiusError(
            "Test B blast-radius abort: an untouched bystander server is unhealthy"
        )
    if failure_class == "missing-crash-signature":
        raise TestBSignatureError(
            f"Test B BREAK did not observe required crash signature: {CRASH_SIGNATURE}"
        )
    return record


def _assert_literal_path(path: str) -> None:
    if not path.startswith("/") or any(character in path for character in "*?[]{}"):
        raise TestBDeletionGuardError(
            f"Test B deletion path is not a literal absolute path: {path!r}"
        )
    if not re.fullmatch(r"/[A-Za-z0-9._/-]+", path):
        raise TestBDeletionGuardError(
            f"Test B deletion path contains unsupported characters: {path!r}"
        )
    components = path.split("/")[1:]
    if any(component in {"", ".", ".."} for component in components):
        raise TestBDeletionGuardError(
            f"Test B deletion path contains traversal or empty components: {path!r}"
        )
    if str(PurePosixPath(path)) != path:
        raise TestBDeletionGuardError(f"Test B deletion path is not normalized: {path!r}")


def _validate_deletion_request(config: dict[str, Any], requested: list[str]) -> list[str]:
    allowlist = _string_list(config.get("deletion_allowlist"), "Test B deletion allowlist")
    if len(requested) != len(set(requested)):
        raise TestBDeletionGuardError("Test B deletion request contains a duplicate path")
    for path in requested:
        _assert_literal_path(path)
        if path not in allowlist:
            raise TestBDeletionGuardError(
                f"Test B deletion rejected off-allowlist path: {path}"
            )
    if requested != allowlist:
        raise TestBDeletionGuardError(
            "Test B deletion request must equal the configured exact-path allowlist"
        )
    return allowlist


def _precedence_enumeration(state: dict[str, Any]) -> list[dict[str, object]]:
    config = validate_test_b_config(state.get("test_b_config"))
    override = _mapping(state.get("owned_override"), "Test B owned override")
    allowlist = _string_list(config["deletion_allowlist"], "Test B deletion allowlist")
    result: list[dict[str, object]] = []
    for raw in config["precedence_surfaces"]:
        entry = _mapping(raw, "Test B precedence entry")
        path = str(entry["path"])
        occurrences: list[dict[str, object]] = []
        if entry["surface"] == "systemd-drop-in-directory" and str(
            override["path"]
        ).startswith(f"{path}/"):
            occurrences.append(
                {
                    "source_path": override["path"],
                    "location": "ExecStart token argument",
                    "argument_name": "--token",
                    "assignment_operator": "=",
                    "token_reference": override["execstart_token_reference"],
                    "owned_by_lab": True,
                }
            )
        if entry["surface"] == "role-token-file" and path == allowlist[1]:
            occurrences.append(
                {
                    "source_path": path,
                    "location": "file-content",
                    "token_reference": state["old_token_reference"],
                    "owned_by_lab": False,
                }
            )
        result.append(
            {
                "surface": entry["surface"],
                "path": path,
                "occurrence_count": len(occurrences),
                "occurrences": occurrences,
            }
        )
    return result


def _absent_metadata(path: str) -> dict[str, object]:
    return {
        "path": path,
        "exists": False,
        "type": ABSENT_FILE_TYPE,
        "owner": None,
        "mode": None,
        "mtime": None,
    }


def recover_test_b(
    model: dict[str, Any],
    test_b_config: object,
    timeout_seconds: int,
    requested_deletions: list[str] | None = None,
) -> dict[str, object]:
    """Enumerate, guard, delete, reload, restart, and measure one-server recovery."""
    state = _test_state(model)
    if state.get("phase") != "BROKEN":
        fail("Test B RECOVERY requires a successful contained BREAK")
    config = validate_test_b_config(test_b_config)
    if config != validate_test_b_config(state.get("test_b_config")):
        fail("canonical Test B configuration changed after SETUP")
    if timeout_seconds != config["recovery_timeout_seconds"]:
        fail("Test B recovery timeout differs from canonical configuration")
    allowlist = _string_list(config["deletion_allowlist"], "Test B deletion allowlist")
    requested = list(allowlist if requested_deletions is None else requested_deletions)
    _validate_deletion_request(config, requested)

    started_at = utc_now()
    started_ns = time.monotonic_ns()
    target = str(state["target_server"])
    target_item = guest_by_name(model, target)
    target_item["k3s_running"] = False
    target_item["ready"] = False
    target_item["etcd_healthy"] = False
    target_item["journal"].append("Test B recovery explicitly stopped K3s on failed server")
    precedence = _precedence_enumeration(state)

    files = _mapping(state.get("local_credentials"), "Test B local credential state")
    deletion_records: list[dict[str, object]] = []
    invalid: list[str] = []
    for path in allowlist:
        before = copy.deepcopy(_mapping(files.get(path), f"credential metadata for {path}"))
        file_type = before.get("type")
        if before.get("exists") is True and file_type != REGULAR_FILE_TYPE:
            invalid.append(f"{path}:{file_type}")
        deletion_records.append({"path": path, "before": before})
    if invalid:
        ended_at = utc_now()
        record = {
            "schema_version": 1,
            "event": "test-b-recovery",
            "verdict": "FAIL",
            "failure_class": "unsafe-allowlisted-path-type",
            "clock_started_at": started_at,
            "clock_stopped_at": ended_at,
            "precedence_enumeration": precedence,
            "deletion_records": deletion_records,
            "reason": f"non-regular allowlisted paths rejected: {invalid!r}",
        }
        state["recovery_observation"] = record
        state["phase"] = "RECOVERY_FAILED"
        raise TestBDeletionGuardError(str(record["reason"]))

    state["owned_override"] = {
        **_mapping(state["owned_override"], "Test B owned override"),
        "corrected": True,
        "action": "removed-owned-override",
    }
    skip_deletion = _injections(model).get("skip_deletion") is True
    for item in deletion_records:
        path = str(item["path"])
        before = _mapping(item["before"], f"credential metadata for {path}")
        if skip_deletion:
            item["action"] = "skipped-by-negative-injection"
            item["after"] = copy.deepcopy(before)
        elif before.get("exists") is True:
            item["action"] = "deleted"
            files[path] = _absent_metadata(path)
            item["after"] = copy.deepcopy(files[path])
        else:
            item["action"] = "already-absent"
            files[path] = _absent_metadata(path)
            item["after"] = copy.deepcopy(files[path])

    post_journal_start = len(target_item["journal"])
    convergence = _injections(model).get("health_convergence_seconds", 1)
    if not isinstance(convergence, int) or isinstance(convergence, bool) or convergence < 0:
        fail("Test B mock health convergence injection must be a non-negative integer")
    if convergence > timeout_seconds:
        ended_at = utc_now()
        duration = (time.monotonic_ns() - started_ns) / 1_000_000_000
        record = {
            "schema_version": 1,
            "event": "test-b-recovery",
            "verdict": "FAIL",
            "failure_class": "bounded-health-timeout",
            "clock_started_at": started_at,
            "clock_stopped_at": ended_at,
            "recovery_duration_seconds": round(duration, 6),
            "timeout_seconds": timeout_seconds,
            "modeled_convergence_seconds": convergence,
            "precedence_enumeration": precedence,
            "deletion_records": deletion_records,
            "systemd_daemon_reload": True,
        }
        state["post_recovery_journal_start"] = post_journal_start
        state["recovery_observation"] = record
        state["phase"] = "RECOVERY_FAILED"
        raise TestBTimeout(
            f"Test B recovery health timeout: convergence={convergence}s, "
            f"bound={timeout_seconds}s"
        )

    target_item["k3s_running"] = True
    target_item["ready"] = True
    target_item["etcd_healthy"] = True
    target_item["running_token_reference"] = state["new_token_reference"]
    target_item["join_credential_sha256"] = model["cluster"]["join_credential_sha256"]
    target_item["journal"].append("Test B recovered server rejoined with corrected token source")
    if skip_deletion:
        target_item["journal"].append(TIMESTAMP_TRAP_SIGNATURE)
    ended_at = utc_now()
    duration = (time.monotonic_ns() - started_ns) / 1_000_000_000
    record = {
        "schema_version": 1,
        "event": "test-b-recovery",
        "verdict": "PASS",
        "failure_class": None,
        "target_server": target,
        "clock_started_at": started_at,
        "clock_stopped_at": ended_at,
        "recovery_duration_seconds": round(duration, 6),
        "timeout_seconds": timeout_seconds,
        "modeled_convergence_seconds": convergence,
        "stopped_failed_server_only": True,
        "healthy_servers_restarted": False,
        "precedence_enumeration": precedence,
        "precedence_entry_count": len(precedence),
        "deletion_allowlist": allowlist,
        "deletion_records": deletion_records,
        "owned_override_correction": copy.deepcopy(state["owned_override"]),
        "systemd_daemon_reload": True,
        "failed_server_started": True,
        "all_nodes_ready_observed": cluster_state(model)["all_nodes_ready"],
    }
    state["post_recovery_journal_start"] = post_journal_start
    state["recovery_observation"] = copy.deepcopy(record)
    state["phase"] = "RECOVERED"
    return record


def gate_observation(model: dict[str, Any]) -> dict[str, object]:
    """Capture all Test B gate inputs without exposing either token candidate."""
    state = _test_state(model)
    if state.get("phase") != "RECOVERED":
        fail("Test B gate observation requires completed RECOVERY state")
    start = state.get("post_recovery_journal_start")
    if not isinstance(start, int) or isinstance(start, bool) or start < 0:
        fail("Test B post-recovery journal start marker is invalid")
    target = str(state["target_server"])
    result = cluster_state(model)
    result.update(
        {
            "schema_version": 1,
            "event": "test-b-gate-observation",
            "target_server": target,
            "old_token_reference": state["old_token_reference"],
            "new_token_reference": state["new_token_reference"],
            "setup_observation": {
                "snapshot_pairs": copy.deepcopy(state["snapshot_pairs"]),
                "rotated_without_full_roll": state["rotated_without_full_roll"],
                "non_restarted_nodes": copy.deepcopy(state["non_restarted_nodes"]),
            },
            "break_observation": copy.deepcopy(state["break_observation"]),
            "recovery_observation": copy.deepcopy(state["recovery_observation"]),
            "post_recovery_server_journals": {
                server: copy.deepcopy(
                    guest_by_name(model, server)["journal"][start:]
                    if server == target
                    else []
                )
                for server in EXPECTED_SERVERS
            },
        }
    )
    raw_output = model.get("injections", {}).get("raw_output")
    if raw_output is not None:
        result["modeled_diagnostic"] = raw_output
    return result
