"""Executable negative probes for the offline Test B mock contracts."""

from __future__ import annotations

import copy
from pathlib import Path

from firedrill.config import parse_config, validate
from firedrill.mock_model import (
    cluster_state,
    current_server_token,
    empty_model,
    new_guest,
    proposed_server_token,
)
from firedrill.test_a import EXPECTED_NODES
from firedrill.test_b import evaluate_gate
from firedrill.test_b_model import (
    CRASH_SIGNATURE,
    ORDINARY_STALE_AGENT_SIGNATURE,
    TIMESTAMP_TRAP_SIGNATURE,
    TestBBlastRadiusError,
    TestBDeletionGuardError,
    TestBSignatureError,
    TestBTimeout,
    break_test_b,
    gate_observation,
    prepare_test_b,
    recover_test_b,
    set_credential_type,
    set_injection,
)

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "firedrill.conf.example"


def config() -> dict[str, object]:
    value = validate(parse_config(EXAMPLE), EXAMPLE)["test_b"]
    assert isinstance(value, dict)
    return value


def model_fixture() -> dict[str, object]:
    lab_id = "fd-test-b-negative-probes"
    model = empty_model(lab_id)
    roles = ("server", "server", "server", "agent", "agent")
    for index, (node, role) in enumerate(zip(EXPECTED_NODES, roles, strict=True)):
        spec = {
            "id": 7100 + index,
            "short_name": node,
            "role": role,
            "name": f"k3fd-{node}",
        }
        item = new_guest(spec, lab_id)
        item.update(
            {
                "power": "running",
                "installed": True,
                "ready": True,
                "etcd_healthy": role == "server",
                "k3s_running": True,
                "join_credential_sha256": model["cluster"]["join_credential_sha256"],
                "running_token_reference": model["cluster"]["server_token_reference"],
                "journal": [f"k3s {role} installed and Ready"],
            }
        )
        model["guests"][str(spec["id"])] = item
    return model


def setup() -> tuple[dict[str, object], dict[str, object]]:
    model = model_fixture()
    test_b_config = config()
    prepare_test_b(
        model,
        current_server_token(model),
        proposed_server_token(model),
        test_b_config,
    )
    return model, test_b_config


def broken() -> tuple[dict[str, object], dict[str, object]]:
    model, test_b_config = setup()
    break_test_b(model)
    return model, test_b_config


def probe_missing_crash_signature() -> None:
    model, _ = setup()
    set_injection(model, "omit_crash_signature", True)
    try:
        break_test_b(model)
    except TestBSignatureError as error:
        record = model["cluster"]["test_b"]["break_observation"]
        assert record["failure_class"] == "missing-crash-signature"
        assert record["crash_signature_count"] == 0
        print(
            "NEGATIVE PROBE test-b-missing-crash-signature: expected failure "
            f"TestBSignatureError: {error}"
        )
        return
    raise AssertionError("missing-crash-signature probe unexpectedly passed")


def probe_quorum_loss() -> None:
    model, _ = setup()
    set_injection(model, "break_quorum_loss", True)
    try:
        break_test_b(model)
    except TestBBlastRadiusError as error:
        record = model["cluster"]["test_b"]["break_observation"]
        assert record["failure_class"] == "quorum-lost-during-break"
        assert record["quorum_intact"] is False
        print(
            "NEGATIVE PROBE test-b-quorum-lost-during-break: expected immediate failure "
            f"TestBBlastRadiusError: {error}"
        )
        return
    raise AssertionError("quorum-loss probe unexpectedly passed")


def probe_unhealthy_bystander() -> None:
    model, _ = setup()
    set_injection(model, "unhealthy_bystander", "server-2")
    try:
        break_test_b(model)
    except TestBBlastRadiusError as error:
        record = model["cluster"]["test_b"]["break_observation"]
        assert record["failure_class"] == "unhealthy-bystander-server"
        assert record["quorum_intact"] is True
        print(
            "NEGATIVE PROBE test-b-unhealthy-bystander: expected failure "
            f"TestBBlastRadiusError with quorum still intact: {error}"
        )
        return
    raise AssertionError("unhealthy-bystander probe unexpectedly passed")


def probe_off_allowlist() -> None:
    model, test_b_config = broken()
    before = copy.deepcopy(model)
    requested = [
        *test_b_config["deletion_allowlist"],
        "/var/lib/rancher/k3s/server/off-list",
    ]
    try:
        recover_test_b(
            model,
            test_b_config,
            int(test_b_config["recovery_timeout_seconds"]),
            requested,
        )
    except TestBDeletionGuardError as error:
        assert model == before
        print(
            "NEGATIVE PROBE test-b-off-allowlist-deletion: expected failure before mutation "
            f"TestBDeletionGuardError: {error}"
        )
        return
    raise AssertionError("off-allowlist deletion probe unexpectedly passed")


def probe_symlink() -> None:
    model, test_b_config = broken()
    path = str(test_b_config["deletion_allowlist"][0])
    set_credential_type(model, path, "symlink")
    try:
        recover_test_b(
            model,
            test_b_config,
            int(test_b_config["recovery_timeout_seconds"]),
        )
    except TestBDeletionGuardError as error:
        state = model["cluster"]["test_b"]
        assert state["local_credentials"][path]["exists"] is True
        assert state["owned_override"].get("corrected") is not True
        print(
            "NEGATIVE PROBE test-b-allowlisted-symlink: expected failure with file retained "
            f"TestBDeletionGuardError: {error}"
        )
        return
    raise AssertionError("allowlisted-symlink probe unexpectedly passed")


def probe_timestamp_trap() -> None:
    model, test_b_config = broken()
    baseline = cluster_state(model_fixture())
    set_injection(model, "skip_deletion", True)
    recover_test_b(
        model,
        test_b_config,
        int(test_b_config["recovery_timeout_seconds"]),
    )
    observation = gate_observation(model)
    result = evaluate_gate(baseline, observation, test_b_config)
    journal = observation["post_recovery_server_journals"]["server-1"]
    assert TIMESTAMP_TRAP_SIGNATURE in journal
    failed = {item.name for item in result.checks if not item.passed}
    assert "post-recovery-journal-signatures-absent" in failed
    assert "exact-allowlist-credential-deletions" in failed
    print(
        "NEGATIVE PROBE test-b-skipped-deletion-timestamp-trap: expected gate FAIL "
        f"signature={TIMESTAMP_TRAP_SIGNATURE!r} failed_checks={sorted(failed)!r}"
    )


def probe_bounded_timeout() -> None:
    model, test_b_config = broken()
    timeout = int(test_b_config["recovery_timeout_seconds"])
    set_injection(model, "health_convergence_seconds", timeout + 1)
    try:
        recover_test_b(model, test_b_config, timeout)
    except TestBTimeout as error:
        record = model["cluster"]["test_b"]["recovery_observation"]
        assert record["failure_class"] == "bounded-health-timeout"
        print(
            "NEGATIVE PROBE test-b-bounded-recovery-timeout: expected failure "
            f"TestBTimeout: {error}"
        )
        return
    raise AssertionError("bounded-timeout probe unexpectedly passed")


def probe_wrong_agent_string() -> None:
    assert ORDINARY_STALE_AGENT_SIGNATURE != CRASH_SIGNATURE
    assert "401 Unauthorized" not in ORDINARY_STALE_AGENT_SIGNATURE
    print(
        "NEGATIVE PROBE test-b-wrong-agent-signature: ordinary stale-agent and CSR-fallback "
        "strings do not satisfy the pinned server crash signature"
    )


def main() -> int:
    probe_missing_crash_signature()
    probe_quorum_loss()
    probe_unhealthy_bystander()
    probe_off_allowlist()
    probe_symlink()
    probe_timestamp_trap()
    probe_bounded_timeout()
    probe_wrong_agent_string()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
