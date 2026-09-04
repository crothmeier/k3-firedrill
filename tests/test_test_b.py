from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from firedrill.config import ConfigError, parse_config, validate
from firedrill.mock_model import (
    cluster_state,
    current_server_token,
    empty_model,
    new_guest,
    proposed_server_token,
)
from firedrill.test_a import EXPECTED_NODES
from firedrill.test_b import evaluate_gate, record_phase
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

EXAMPLE = Path(__file__).parents[1] / "firedrill.conf.example"


def test_config() -> dict[str, object]:
    result = validate(parse_config(EXAMPLE), EXAMPLE)
    value = result["test_b"]
    assert isinstance(value, dict)
    return value


def provisioned_model() -> dict[str, object]:
    lab_id = "fd-test-b-unit"
    model = empty_model(lab_id)
    roles = ("server", "server", "server", "agent", "agent")
    token_reference = model["cluster"]["server_token_reference"]
    credential_digest = model["cluster"]["join_credential_sha256"]
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
                "join_credential_sha256": credential_digest,
                "running_token_reference": token_reference,
                "journal": [f"k3s {role} installed and Ready"],
            }
        )
        model["guests"][str(spec["id"])] = item
    return model


def setup_and_break() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    model = provisioned_model()
    baseline = cluster_state(model)
    config = test_config()
    prepare_test_b(model, current_server_token(model), proposed_server_token(model), config)
    break_test_b(model)
    return model, baseline, config


def check(result: object, name: str) -> object:
    return next(item for item in result.checks if item.name == name)


class TestBSetupAndBreakTests(unittest.TestCase):
    def test_setup_pairs_snapshots_and_rotates_without_restarts(self) -> None:
        model = provisioned_model()
        old_token = current_server_token(model)
        new_token = proposed_server_token(model)
        record = prepare_test_b(model, old_token, new_token, test_config())
        self.assertEqual(set(record["snapshot_pairs"]), {"server-1", "server-2", "server-3"})
        self.assertTrue(record["rotated_without_full_roll"])
        self.assertEqual(set(record["non_restarted_nodes"]), set(EXPECTED_NODES))
        self.assertNotIn(old_token, json.dumps(model))
        self.assertNotIn(new_token, json.dumps(model))
        self.assertTrue(
            all(item["restart_count"] == 0 for item in model["guests"].values())
        )

    def test_break_observes_exact_signature_and_contained_quorum(self) -> None:
        model = provisioned_model()
        prepare_test_b(
            model,
            current_server_token(model),
            proposed_server_token(model),
            test_config(),
        )
        record = break_test_b(model)
        self.assertEqual(record["crash_signature"], CRASH_SIGNATURE)
        self.assertEqual(record["crash_signature_count"], 1)
        self.assertTrue(record["bystanders_healthy"])
        self.assertTrue(record["quorum_intact"])
        self.assertTrue(record["api_served"])
        self.assertEqual(record["stale_override_server_count"], 1)

    def test_missing_crash_signature_is_rejected(self) -> None:
        model = provisioned_model()
        prepare_test_b(
            model,
            current_server_token(model),
            proposed_server_token(model),
            test_config(),
        )
        set_injection(model, "omit_crash_signature", True)
        with self.assertRaisesRegex(TestBSignatureError, "required crash signature"):
            break_test_b(model)
        record = model["cluster"]["test_b"]["break_observation"]
        self.assertEqual(record["failure_class"], "missing-crash-signature")
        self.assertNotIn(CRASH_SIGNATURE, record["target_journal_window"])

    def test_quorum_loss_is_a_distinct_immediate_failure(self) -> None:
        model = provisioned_model()
        prepare_test_b(
            model,
            current_server_token(model),
            proposed_server_token(model),
            test_config(),
        )
        set_injection(model, "break_quorum_loss", True)
        with self.assertRaisesRegex(TestBBlastRadiusError, "quorum lost"):
            break_test_b(model)
        record = model["cluster"]["test_b"]["break_observation"]
        self.assertEqual(record["failure_class"], "quorum-lost-during-break")
        self.assertFalse(record["quorum_intact"])

    def test_unhealthy_bystander_fails_even_when_etcd_quorum_remains(self) -> None:
        model = provisioned_model()
        prepare_test_b(
            model,
            current_server_token(model),
            proposed_server_token(model),
            test_config(),
        )
        set_injection(model, "unhealthy_bystander", "server-2")
        with self.assertRaisesRegex(TestBBlastRadiusError, "bystander"):
            break_test_b(model)
        record = model["cluster"]["test_b"]["break_observation"]
        self.assertEqual(record["failure_class"], "unhealthy-bystander-server")
        self.assertTrue(record["quorum_intact"])
        self.assertFalse(record["bystanders_healthy"])

    def test_wrong_stale_agent_line_never_satisfies_server_crash_guard(self) -> None:
        self.assertNotEqual(ORDINARY_STALE_AGENT_SIGNATURE, CRASH_SIGNATURE)
        self.assertNotIn("401 Unauthorized", ORDINARY_STALE_AGENT_SIGNATURE)


class TestBRecoveryGuardTests(unittest.TestCase):
    def test_recovery_enumerates_every_surface_and_deletes_exact_paths(self) -> None:
        model, _, config = setup_and_break()
        record = recover_test_b(model, config, int(config["recovery_timeout_seconds"]))
        expected = [(item["surface"], item["path"]) for item in config["precedence_surfaces"]]
        observed = [
            (item["surface"], item["path"]) for item in record["precedence_enumeration"]
        ]
        self.assertEqual(observed, expected)
        self.assertEqual(
            [item["path"] for item in record["deletion_records"]],
            config["deletion_allowlist"],
        )
        self.assertTrue(all(item["action"] == "deleted" for item in record["deletion_records"]))
        self.assertGreaterEqual(record["recovery_duration_seconds"], 0)

    def test_off_allowlist_deletion_is_rejected_before_mutation(self) -> None:
        model, _, config = setup_and_break()
        before = copy.deepcopy(model)
        requested = [*config["deletion_allowlist"], "/var/lib/rancher/k3s/server/other"]
        with self.assertRaisesRegex(TestBDeletionGuardError, "off-allowlist"):
            recover_test_b(
                model,
                config,
                int(config["recovery_timeout_seconds"]),
                requested,
            )
        self.assertEqual(model, before)

    def test_allowlisted_symlink_is_rejected_without_deletion(self) -> None:
        model, _, config = setup_and_break()
        path = str(config["deletion_allowlist"][0])
        set_credential_type(model, path, "symlink")
        with self.assertRaisesRegex(TestBDeletionGuardError, "non-regular"):
            recover_test_b(model, config, int(config["recovery_timeout_seconds"]))
        state = model["cluster"]["test_b"]
        self.assertEqual(state["local_credentials"][path]["type"], "symlink")
        self.assertNotEqual(state["owned_override"].get("corrected"), True)

    def test_bounded_recovery_timeout_is_distinct(self) -> None:
        model, _, config = setup_and_break()
        timeout = int(config["recovery_timeout_seconds"])
        set_injection(model, "health_convergence_seconds", timeout + 1)
        with self.assertRaisesRegex(TestBTimeout, "health timeout"):
            recover_test_b(model, config, timeout)
        record = model["cluster"]["test_b"]["recovery_observation"]
        self.assertEqual(record["failure_class"], "bounded-health-timeout")


class TestBGateTests(unittest.TestCase):
    def passing_result(self) -> object:
        model, baseline, config = setup_and_break()
        recover_test_b(model, config, int(config["recovery_timeout_seconds"]))
        return evaluate_gate(baseline, gate_observation(model), config)

    def test_passing_world_satisfies_every_evidence_gate(self) -> None:
        result = self.passing_result()
        self.assertEqual(result.verdict, "PASS")
        self.assertEqual(len(result.checks), 13)
        self.assertTrue(all(item.passed and item.coverage for item in result.checks))

    def test_skipped_deletion_emits_timestamp_trap_and_fails_gate(self) -> None:
        model, baseline, config = setup_and_break()
        set_injection(model, "skip_deletion", True)
        recover_test_b(model, config, int(config["recovery_timeout_seconds"]))
        observation = gate_observation(model)
        target_lines = observation["post_recovery_server_journals"]["server-1"]
        self.assertIn(TIMESTAMP_TRAP_SIGNATURE, target_lines)
        result = evaluate_gate(baseline, observation, config)
        self.assertFalse(check(result, "post-recovery-journal-signatures-absent").passed)
        self.assertFalse(check(result, "exact-allowlist-credential-deletions").passed)

    def test_crash_signature_missing_from_break_evidence_fails_gate(self) -> None:
        model, baseline, config = setup_and_break()
        recover_test_b(model, config, int(config["recovery_timeout_seconds"]))
        observation = gate_observation(model)
        observation["break_observation"]["crash_signature_count"] = 0
        observation["break_observation"]["crash_signature_observed"] = False
        result = evaluate_gate(baseline, observation, config)
        target = "one-owned-stale-override-and-required-crash-signature"
        self.assertFalse(check(result, target).passed)

    def test_phase_order_and_measured_duration_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = record_phase(
                root,
                1,
                "SETUP",
                "2026-08-30T00:00:00.000Z",
                "2026-08-30T00:00:01.250Z",
                0,
            )
            self.assertEqual(first["duration_seconds"], 1.25)
            with self.assertRaisesRegex(Exception, "phase order violation"):
                record_phase(
                    root,
                    2,
                    "RECOVERY",
                    "2026-08-30T00:00:02.000Z",
                    "2026-08-30T00:00:03.000Z",
                    0,
                )


class TestBConfigurationTests(unittest.TestCase):
    def test_allowlist_rejects_an_off_list_third_path(self) -> None:
        values = parse_config(EXAMPLE)
        values["test_b_deletion_allowlist"] += ",/var/lib/rancher/k3s/server/other"
        with self.assertRaisesRegex(ConfigError, "must contain exactly"):
            validate(values, EXAMPLE)

    def test_allowlist_rejects_traversal(self) -> None:
        values = parse_config(EXAMPLE)
        values["test_b_deletion_allowlist"] = (
            "/var/lib/rancher/k3s/server/cred/passwd,"
            "/var/lib/rancher/k3s/server/../server/token"
        )
        with self.assertRaisesRegex(ConfigError, "parent path components"):
            validate(values, EXAMPLE)


if __name__ == "__main__":
    unittest.main()
