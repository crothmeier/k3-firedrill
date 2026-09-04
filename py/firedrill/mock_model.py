"""Offline hypervisor and K3s state model used by the mock driver."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from firedrill.bootstrap import bootstrap_key_name, normalize_token
from firedrill.redact import token_reference
from firedrill.test_a import (
    EXPECTED_NODES,
    EXPECTED_SERVERS,
    TestAGuardError,
    assert_full_server_token,
)


class MockError(RuntimeError):
    """The requested mock transition is invalid."""


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


def initial_server_token(lab_id: str) -> str:
    ca_hash = hashlib.sha256(f"mock-token-ca:{lab_id}".encode()).hexdigest()
    secret = hashlib.sha256(f"mock-token-secret:{lab_id}".encode()).hexdigest()
    return f"K10{ca_hash}::server:{secret}"


def server_token_for_epoch(lab_id: str, epoch: int) -> str:
    if epoch == 0:
        return initial_server_token(lab_id)
    ca_hash = hashlib.sha256(f"mock-rotated-ca:{lab_id}:{epoch}".encode()).hexdigest()
    secret = hashlib.sha256(f"mock-rotated-secret:{lab_id}:{epoch}".encode()).hexdigest()
    return f"K10{ca_hash}::server:{secret}"


def current_server_token(model: dict[str, Any]) -> str:
    epoch = int(model["cluster"].get("server_token_epoch", 0))
    return server_token_for_epoch(str(model["lab_id"]), epoch)


def proposed_server_token(model: dict[str, Any]) -> str:
    cluster = model["cluster"]
    epoch = int(cluster.get("rotation_count", 0)) + 1
    return server_token_for_epoch(str(model["lab_id"]), epoch)


def join_credential_sha256(token: str) -> str:
    return hashlib.sha256(normalize_token(token).encode()).hexdigest()


def datastore_sha256(lab_id: str, node: str, revision: int) -> str:
    """Return a stable, content-address-like marker for modeled server data."""
    return hashlib.sha256(f"mock-datastore:{lab_id}:{node}:{revision}".encode()).hexdigest()


def etcd_member_name(lab_id: str, node: str) -> str:
    """Return the stable k3s-style embedded-etcd member name for a mock server."""
    suffix = hashlib.sha256(f"mock-etcd-member:{lab_id}:{node}".encode()).hexdigest()[:8]
    return f"{node}-{suffix}"


def empty_model(lab_id: str) -> dict[str, Any]:
    token = initial_server_token(lab_id)
    return {
        "schema_version": 3,
        "identity": "mock-hypervisor",
        "lab_id": lab_id,
        "guests": {},
        "cluster": {
            "ca_sha256": hashlib.sha256(f"mock-ca:{lab_id}".encode()).hexdigest(),
            "server_token_epoch": 0,
            "server_token_reference": token_reference(token),
            "rotation_count": 0,
            "bootstrap_keys": [bootstrap_key_name(token)],
            "join_credential_sha256": join_credential_sha256(token),
            "test_a": None,
        },
        "injections": {
            "bootstrap_decryption_failure_nodes": [],
            "health_convergence_seconds": {},
            "raw_output": None,
            "test_c": {},
        },
    }


def migrate_model(model: dict[str, Any]) -> dict[str, Any]:
    """Supply Test A fields when reading a foundation-era disposable mock model."""
    lab_id = str(model["lab_id"])
    cluster = model.setdefault("cluster", {})
    cluster.pop("server_token", None)
    cluster.setdefault("server_token_epoch", int(cluster.get("rotation_count", 0)))
    token = server_token_for_epoch(lab_id, int(cluster["server_token_epoch"]))
    cluster.setdefault("server_token_reference", token_reference(token))
    cluster.setdefault("rotation_count", 0)
    cluster.setdefault("bootstrap_keys", [bootstrap_key_name(token)])
    cluster.setdefault("join_credential_sha256", join_credential_sha256(token))
    cluster.setdefault("test_a", None)
    model.setdefault(
        "injections",
        {
            "bootstrap_decryption_failure_nodes": [],
            "health_convergence_seconds": {},
            "raw_output": None,
        },
    )
    injections = model["injections"]
    injections.setdefault("bootstrap_decryption_failure_nodes", [])
    injections.setdefault("health_convergence_seconds", {})
    injections.setdefault("raw_output", None)
    injections.setdefault("test_c", {})
    for item in model.get("guests", {}).values():
        installed = bool(item.get("installed", False))
        running = item.get("power") == "running"
        node = str(item.get("short_name", "unknown"))
        role = item.get("role")
        item.setdefault("ready", installed and running)
        item.setdefault("etcd_healthy", installed and running and role == "server")
        item.setdefault(
            "join_credential_sha256",
            cluster["join_credential_sha256"] if installed else None,
        )
        item.setdefault("k3s_running", installed and running)
        item.setdefault(
            "running_token_reference",
            cluster["server_token_reference"] if installed else None,
        )
        default_revision = 1 if installed and role == "server" else 0
        item.setdefault("datastore_revision", default_revision)
        item.setdefault(
            "datastore_sha256",
            datastore_sha256(lab_id, node, int(item["datastore_revision"])),
        )
        item.setdefault("journal", [])
        item.setdefault("etcd_snapshots", {})
        item.setdefault("restart_count", 0)
    model["schema_version"] = 3
    return model


def load_model(path: Path, lab_id: str | None = None) -> dict[str, Any]:
    if path.exists():
        model = json.loads(path.read_text(encoding="utf-8"))
        if lab_id is not None and model.get("lab_id") != lab_id:
            raise MockError("mock model belongs to a different lab_id")
        return migrate_model(model)
    if lab_id is None:
        raise MockError(f"mock model does not exist: {path}")
    return empty_model(lab_id)


def guest(model: dict[str, Any], guest_id: int) -> dict[str, Any]:
    try:
        return model["guests"][str(guest_id)]
    except KeyError as error:
        raise MockError(f"guest {guest_id} does not exist") from error


def guest_by_name(model: dict[str, Any], node: str) -> dict[str, Any]:
    matches = [item for item in model["guests"].values() if item.get("short_name") == node]
    if len(matches) != 1:
        raise MockError(f"expected exactly one modeled guest named {node}, observed {len(matches)}")
    return matches[0]


def new_guest(spec: dict[str, object], lab_id: str) -> dict[str, object]:
    node = str(spec["short_name"])
    return {
        **spec,
        "owner": lab_id,
        "power": "stopped",
        "installed": False,
        "ready": False,
        "etcd_healthy": False,
        "join_credential_sha256": None,
        "k3s_running": False,
        "running_token_reference": None,
        "datastore_revision": 0,
        "datastore_sha256": datastore_sha256(lab_id, node, 0),
        "journal": [],
        "etcd_snapshots": {},
        "restart_count": 0,
        "snapshots": {},
    }


def cluster_state(model: dict[str, Any]) -> dict[str, object]:
    nodes: list[dict[str, object]] = []
    etcd_members: list[dict[str, object]] = []
    for item in sorted(model["guests"].values(), key=lambda value: value["id"]):
        ready = bool(
            item.get("power") == "running"
            and item.get("installed")
            and item.get("k3s_running")
            and item.get("ready")
        )
        nodes.append(
            {
                "name": item["short_name"],
                "role": item["role"],
                "ready": ready,
                "join_credential_sha256": item.get("join_credential_sha256"),
            }
        )
        if item["role"] == "server":
            etcd_members.append(
                {
                    "name": etcd_member_name(
                        str(model["lab_id"]), str(item["short_name"])
                    ),
                    "healthy": ready and bool(item.get("etcd_healthy")),
                }
            )
    return {
        "nodes": nodes,
        "all_nodes_ready": len(nodes) == 5 and all(bool(node["ready"]) for node in nodes),
        "etcd_members": etcd_members,
        "all_etcd_members_healthy": len(etcd_members) == 3
        and all(bool(member["healthy"]) for member in etcd_members),
        "bootstrap_keys": copy.deepcopy(model["cluster"]["bootstrap_keys"]),
        "ca_sha256": model["cluster"]["ca_sha256"],
    }


def snapshot_payload(item: dict[str, Any], cluster: dict[str, Any]) -> dict[str, object]:
    guest_fields = (
        "power",
        "installed",
        "ready",
        "etcd_healthy",
        "join_credential_sha256",
        "k3s_running",
        "running_token_reference",
        "datastore_revision",
        "datastore_sha256",
        "journal",
        "etcd_snapshots",
        "restart_count",
    )
    return {
        "guest": {field: copy.deepcopy(item.get(field)) for field in guest_fields},
        "cluster": copy.deepcopy(cluster),
    }


def capture_paired_snapshot(
    model: dict[str, Any], node: str, token: str | None
) -> tuple[dict[str, object], bool]:
    """Capture one modeled etcd snapshot only with its exact current-token pair."""
    if token is None or not token:
        raise MockError(
            "unpaired snapshot rejected before mutation: an exact current server token is required"
        )
    assert_full_server_token(token, "snapshot-pair server token")
    current = current_server_token(model)
    if token != current:
        raise MockError("snapshot pairing rejected before mutation: token is not current")
    if node not in EXPECTED_SERVERS:
        raise MockError(f"snapshot pairing requires a server node, observed {node!r}")
    item = guest_by_name(model, node)
    if not item.get("installed") or not item.get("ready"):
        raise MockError(f"snapshot pairing requires healthy installed server {node}")

    reference = token_reference(token)
    path = f"/var/lib/rancher/k3s/server/db/snapshots/test-a-{node}.db"
    digest_input = f"{model['lab_id']}:{node}:{reference}:{model['cluster']['ca_sha256']}"
    pair = {
        "node": node,
        "path": path,
        "snapshot_sha256": hashlib.sha256(digest_input.encode()).hexdigest(),
        "server_token_reference": reference,
    }
    existing = item["etcd_snapshots"].get(path)
    if existing is not None:
        if existing != pair:
            raise MockError(f"snapshot path {path} already exists with a different token pair")
        return pair, False

    test_state = model["cluster"].get("test_a")
    if test_state is None:
        test_state = {
            "snapshot_pairs": {},
            "rotated": False,
            "expected_server_restart_order": [],
            "restart_events": [],
        }
        model["cluster"]["test_a"] = test_state
    if test_state.get("rotated"):
        raise MockError("snapshot pairing is forbidden after Test A rotation")
    item["etcd_snapshots"][path] = copy.deepcopy(pair)
    test_state["snapshot_pairs"][node] = copy.deepcopy(pair)
    return pair, True


def rotate_server_token(
    model: dict[str, Any], new_token: str, restart_order: tuple[str, ...]
) -> dict[str, object]:
    assert_full_server_token(new_token, "rotation server token")
    if len(restart_order) != 3 or set(restart_order) != set(EXPECTED_SERVERS):
        raise MockError("rotation requires an exact three-server restart-order permutation")
    cluster = model["cluster"]
    test_state = cluster.get("test_a")
    if not isinstance(test_state, dict):
        raise MockError("rotation refused: no token-paired Test A snapshots exist")
    pairs = test_state.get("snapshot_pairs")
    if not isinstance(pairs, dict) or set(pairs) != set(EXPECTED_SERVERS):
        raise MockError("rotation refused: all three servers require token-paired snapshots")
    current = current_server_token(model)
    expected_reference = token_reference(current)
    if any(pair.get("server_token_reference") != expected_reference for pair in pairs.values()):
        raise MockError("rotation refused: a snapshot/token reference is stale or unpaired")
    if new_token == current:
        raise MockError("rotation refused: proposed server token equals the current token")
    if test_state.get("rotated"):
        raise MockError("rotation refused: Test A already rotated this baseline")

    next_epoch = int(cluster.get("rotation_count", 0)) + 1
    if new_token != server_token_for_epoch(str(model["lab_id"]), next_epoch):
        raise MockError("mock rotation accepts only its prevalidated proposed token")
    cluster["server_token_epoch"] = next_epoch
    cluster["server_token_reference"] = token_reference(new_token)
    cluster["rotation_count"] = next_epoch
    cluster["bootstrap_keys"] = [bootstrap_key_name(new_token)]
    cluster["join_credential_sha256"] = join_credential_sha256(new_token)
    test_state["rotated"] = True
    test_state["expected_server_restart_order"] = list(restart_order)
    test_state["restart_events"] = []
    return {
        "event": "server-token-rotated",
        "server_token_reference": cluster["server_token_reference"],
        "bootstrap_keys": copy.deepcopy(cluster["bootstrap_keys"]),
        "configured_server_restart_order": list(restart_order),
    }


def restart_node(
    model: dict[str, Any], node: str, timeout_seconds: int
) -> tuple[dict[str, object], int]:
    """Model an ordered restart and bounded health convergence without sleeping."""
    if timeout_seconds < 1:
        raise MockError("node health timeout must be at least one second")
    if node not in EXPECTED_NODES:
        raise MockError(f"restart requested for unknown node {node!r}")
    test_state = model["cluster"].get("test_a")
    if not isinstance(test_state, dict) or not test_state.get("rotated"):
        raise MockError("restart refused before a completed Test A token rotation")
    events = test_state.get("restart_events")
    if not isinstance(events, list):
        raise MockError("mock restart history is invalid")
    expected_order = [*test_state["expected_server_restart_order"], "agent-1", "agent-2"]
    if len(events) >= len(expected_order):
        raise MockError("restart-order violation: every Test A node was already restarted")
    expected_node = expected_order[len(events)]
    if node != expected_node:
        raise MockError(
            f"restart-order violation: expected {expected_node} next, observed {node}; "
            "no restart mutation performed"
        )

    item = guest_by_name(model, node)
    if item.get("power") != "running" or not item.get("installed"):
        raise MockError(f"restart requires a running installed node, observed {node}")
    item["ready"] = False
    item["k3s_running"] = False
    if item["role"] == "server":
        item["etcd_healthy"] = False
    item["restart_count"] = int(item.get("restart_count", 0)) + 1
    item["journal"].append("k3s stopping for clean server-token rotation restart")

    delays = model["injections"].get("health_convergence_seconds", {})
    convergence_seconds = int(delays.get(node, 1))
    if convergence_seconds > timeout_seconds:
        event = {
            "sequence": len(events) + 1,
            "node": node,
            "status": "timeout",
            "timeout_seconds": timeout_seconds,
            "convergence_seconds": convergence_seconds,
        }
        events.append(event)
        item["journal"].append("bounded mock health wait expired before Ready")
        return event, 70

    item["ready"] = True
    item["k3s_running"] = True
    item["running_token_reference"] = model["cluster"]["server_token_reference"]
    if item["role"] == "server":
        item["etcd_healthy"] = True
    item["join_credential_sha256"] = model["cluster"]["join_credential_sha256"]
    item["journal"].append("k3s restart converged Ready with healthy membership")
    injected_nodes = model["injections"].get("bootstrap_decryption_failure_nodes", [])
    if node in injected_nodes:
        item["journal"].append(
            "failed to decrypt bootstrap data: cipher: message authentication failed"
        )
    event = {
        "sequence": len(events) + 1,
        "node": node,
        "status": "healthy",
        "timeout_seconds": timeout_seconds,
        "convergence_seconds": convergence_seconds,
    }
    events.append(event)
    output = copy.deepcopy(event)
    raw_output = model["injections"].get("raw_output")
    if raw_output is not None:
        output["modeled_diagnostic"] = raw_output
    return output, 0


def gate_observation(model: dict[str, Any]) -> dict[str, object]:
    state = cluster_state(model)
    test_state = model["cluster"].get("test_a")
    restart_events: list[dict[str, object]] = []
    snapshot_pairs: dict[str, object] = {}
    if isinstance(test_state, dict):
        restart_events = copy.deepcopy(test_state.get("restart_events", []))
        snapshot_pairs = copy.deepcopy(test_state.get("snapshot_pairs", {}))
    state.update(
        {
            "event": "test-a-gate-observation",
            "server_journals": {
                server: copy.deepcopy(guest_by_name(model, server).get("journal", []))
                for server in EXPECTED_SERVERS
            },
            "restart_events": restart_events,
            "snapshot_pairs": snapshot_pairs,
            "server_token_reference": model["cluster"]["server_token_reference"],
        }
    )
    raw_output = model["injections"].get("raw_output")
    if raw_output is not None:
        state["modeled_diagnostic"] = raw_output
    return state


def restore_snapshot(item: dict[str, Any], snapshot: dict[str, Any], model: dict[str, Any]) -> None:
    if "guest" in snapshot:
        for field, value in snapshot["guest"].items():
            item[field] = copy.deepcopy(value)
    else:
        item["power"] = snapshot["power"]
        item["installed"] = snapshot["installed"]
    model["cluster"] = copy.deepcopy(snapshot["cluster"])


def handle(args: argparse.Namespace) -> int:  # noqa: C901, PLR0912
    path: Path = args.model
    if args.command == "identity":
        print("mock-hypervisor")
        return 0
    if args.command == "template-exists":
        print("true")
        return 0
    if args.command == "exists" and not path.exists():
        return 1

    model = load_model(path, getattr(args, "lab_id", None))
    changed = False
    exit_code = 0
    if args.command == "exists":
        return 0 if str(args.guest_id) in model["guests"] else 1
    if args.command == "owner":
        print(guest(model, args.guest_id)["owner"])
    elif args.command == "create":
        spec = json.loads(args.spec)
        key = str(spec["id"])
        desired = new_guest(spec, args.lab_id)
        if key in model["guests"]:
            existing = model["guests"][key]
            comparable = {key_name: existing.get(key_name) for key_name in desired}
            if comparable != desired:
                raise MockError(f"guest {key} exists with a different specification")
            print("already-present")
        else:
            model["guests"][key] = desired
            changed = True
            print("created")
    elif args.command == "start":
        item = guest(model, args.guest_id)
        item["power"] = "running"
        changed = True
        print("started")
    elif args.command == "stop":
        item = guest(model, args.guest_id)
        item["power"] = "stopped"
        item["ready"] = False
        item["k3s_running"] = False
        item["etcd_healthy"] = False
        changed = True
        print("stopped")
    elif args.command == "status":
        print(json.dumps(guest(model, args.guest_id), separators=(",", ":")))
    elif args.command == "delete":
        del model["guests"][str(args.guest_id)]
        changed = True
        print("deleted")
    elif args.command == "snapshot-create":
        item = guest(model, args.guest_id)
        if args.snapshot in item["snapshots"]:
            print("already-present")
        else:
            item["snapshots"][args.snapshot] = snapshot_payload(item, model["cluster"])
            changed = True
            print("snapshotted")
    elif args.command == "snapshot-exists":
        return 0 if args.snapshot in guest(model, args.guest_id)["snapshots"] else 1
    elif args.command == "snapshot-restore":
        item = guest(model, args.guest_id)
        try:
            snapshot = item["snapshots"][args.snapshot]
        except KeyError as error:
            raise MockError(
                f"snapshot {args.snapshot!r} does not exist for guest {args.guest_id}"
            ) from error
        restore_snapshot(item, snapshot, model)
        changed = True
        print("restored")
    elif args.command == "guest-exec":
        item = guest(model, args.guest_id)
        if item["power"] != "running":
            raise MockError(f"guest {args.guest_id} is not running")
        operation = args.operation
        if operation == "install-k3s":
            item["installed"] = True
            item["ready"] = True
            item["k3s_running"] = True
            item["etcd_healthy"] = item["role"] == "server"
            item["join_credential_sha256"] = model["cluster"]["join_credential_sha256"]
            item["running_token_reference"] = model["cluster"]["server_token_reference"]
            if item["role"] == "server":
                item["datastore_revision"] = 1
                item["datastore_sha256"] = datastore_sha256(
                    str(model["lab_id"]), str(item["short_name"]), 1
                )
            item["journal"].append(f"k3s {item['role']} installed and Ready")
            changed = True
            print(f"installed {args.operation_args[0]} on {item['short_name']}")
        elif operation in {"wait-access", "wait-ready"}:
            if operation == "wait-ready" and not item.get("ready"):
                raise MockError(f"guest {args.guest_id} is not Ready")
            print("ready")
        elif operation == "capture-cluster-state":
            print(json.dumps(cluster_state(model), separators=(",", ":")))
        else:
            raise MockError(f"unsupported mock guest operation: {operation}")
    elif args.command == "cluster-state":
        print(json.dumps(cluster_state(model), separators=(",", ":")))
    elif args.command == "test-a-read-token":
        print(current_server_token(model))
    elif args.command == "test-a-propose-token":
        print(proposed_server_token(model))
    elif args.command == "test-a-snapshot":
        pair, changed = capture_paired_snapshot(model, args.node, args.token)
        print(json.dumps(pair, sort_keys=True, separators=(",", ":")))
    elif args.command == "test-a-rotate":
        order = tuple(item.strip() for item in args.restart_order.split(","))
        record = rotate_server_token(model, args.token, order)
        changed = True
        print(json.dumps(record, sort_keys=True, separators=(",", ":")))
    elif args.command == "test-a-restart":
        record, exit_code = restart_node(model, args.node, args.timeout)
        changed = True
        stream = sys.stdout if exit_code == 0 else sys.stderr
        print(json.dumps(record, sort_keys=True, separators=(",", ":")), file=stream)
    elif args.command == "test-a-observe":
        print(json.dumps(gate_observation(model), sort_keys=True, separators=(",", ":")))
    elif args.command == "inject-decryption-failure":
        nodes = model["injections"]["bootstrap_decryption_failure_nodes"]
        if args.node not in nodes:
            nodes.append(args.node)
            changed = True
        print(f"injected bootstrap-decryption journal failure for {args.node}")
    elif args.command == "inject-bootstrap-key":
        if not re.fullmatch(r"/bootstrap/[a-f0-9]{12}", args.key_name):
            raise MockError("injected bootstrap key must match /bootstrap/ plus 12 lowercase hex")
        if args.key_name not in model["cluster"]["bootstrap_keys"]:
            model["cluster"]["bootstrap_keys"].append(args.key_name)
            changed = True
        print("injected additional bootstrap key")
    elif args.command == "inject-health-delay":
        model["injections"]["health_convergence_seconds"][args.node] = args.seconds
        changed = True
        print(f"injected health convergence delay for {args.node}: {args.seconds}s")
    elif args.command == "inject-raw-output":
        model["injections"]["raw_output"] = args.value
        changed = True
        print("injected raw modeled diagnostic")
    else:
        raise MockError(f"unsupported command: {args.command}")

    if changed:
        atomic_json(path, model)
    return exit_code


def add_lab_id(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lab-id", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("identity")
    subparsers.add_parser("template-exists")
    for name in ("exists", "owner", "status"):
        command = subparsers.add_parser(name)
        command.add_argument("guest_id", type=int)
    create = subparsers.add_parser("create")
    add_lab_id(create)
    create.add_argument("--spec", required=True)
    for name in ("start", "stop", "delete"):
        command = subparsers.add_parser(name)
        add_lab_id(command)
        command.add_argument("guest_id", type=int)
    for name in ("snapshot-create", "snapshot-exists", "snapshot-restore"):
        command = subparsers.add_parser(name)
        add_lab_id(command)
        command.add_argument("guest_id", type=int)
        command.add_argument("snapshot")
    guest_exec = subparsers.add_parser("guest-exec")
    add_lab_id(guest_exec)
    guest_exec.add_argument("guest_id", type=int)
    guest_exec.add_argument("operation")
    guest_exec.add_argument("operation_args", nargs="*")
    cluster = subparsers.add_parser("cluster-state")
    add_lab_id(cluster)
    for name in ("test-a-read-token", "test-a-propose-token", "test-a-observe"):
        command = subparsers.add_parser(name)
        add_lab_id(command)
    paired = subparsers.add_parser("test-a-snapshot")
    add_lab_id(paired)
    paired.add_argument("--node", required=True)
    paired.add_argument("--token")
    rotate = subparsers.add_parser("test-a-rotate")
    add_lab_id(rotate)
    rotate.add_argument("--token", required=True)
    rotate.add_argument("--restart-order", required=True)
    restart = subparsers.add_parser("test-a-restart")
    add_lab_id(restart)
    restart.add_argument("--node", required=True)
    restart.add_argument("--timeout", required=True, type=int)
    decryption = subparsers.add_parser("inject-decryption-failure")
    add_lab_id(decryption)
    decryption.add_argument("--node", required=True, choices=EXPECTED_SERVERS)
    bootstrap = subparsers.add_parser("inject-bootstrap-key")
    add_lab_id(bootstrap)
    bootstrap.add_argument("--key-name", required=True)
    delay = subparsers.add_parser("inject-health-delay")
    add_lab_id(delay)
    delay.add_argument("--node", required=True, choices=EXPECTED_NODES)
    delay.add_argument("--seconds", required=True, type=int)
    raw_output = subparsers.add_parser("inject-raw-output")
    add_lab_id(raw_output)
    raw_output.add_argument("--value", required=True)
    return parser


def main() -> int:
    try:
        return handle(build_parser().parse_args())
    except (
        MockError,
        TestAGuardError,
        OSError,
        json.JSONDecodeError,
        KeyError,
        IndexError,
    ) as error:
        print(f"mock driver error: {error}", file=sys.stderr)
        return 69


if __name__ == "__main__":
    raise SystemExit(main())
