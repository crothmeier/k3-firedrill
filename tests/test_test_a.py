from __future__ import annotations

import copy
import re
import tempfile
import unittest
from pathlib import Path

from firedrill.bootstrap import normalize_token
from firedrill.config import parse_config, validate
from firedrill.mock_model import (
    MockError,
    capture_paired_snapshot,
    cluster_state,
    current_server_token,
    empty_model,
    gate_observation,
    new_guest,
    proposed_server_token,
    restart_node,
    rotate_server_token,
)
from firedrill.redact import TokenRegistry, redact_value
from firedrill.test_a import (
    EXPECTED_NODES,
    EXPECTED_SERVERS,
    TestAGuardError,
    TestAPrerequisiteError,
    assert_baseline_prerequisites,
    assert_full_server_token,
    baseline_prerequisites,
    evaluate_gate,
    record_phase,
    registry_values,
)

LAB_ID = "fd-test-a-unit"
SERVER_ORDER = ("server-1", "server-2", "server-3")
SUFFIXED_MEMBER_NAMES = (
    "server-1-0123abcd",
    "server-2-4567cdef",
    "server-3-89abcdef",
)
EXAMPLE = Path(__file__).parents[1] / "firedrill.conf.example"


def provisioned_model() -> dict[str, object]:
    model = empty_model(LAB_ID)
    roles = ("server", "server", "server", "agent", "agent")
    for index, (node, role) in enumerate(zip(EXPECTED_NODES, roles, strict=True)):
        spec = {
            "id": 7100 + index,
            "short_name": node,
            "role": role,
            "name": f"k3fd-{node}",
        }
        item = new_guest(spec, LAB_ID)
        item["power"] = "running"
        item["installed"] = True
        item["ready"] = True
        item["etcd_healthy"] = role == "server"
        item["join_credential_sha256"] = model["cluster"]["join_credential_sha256"]
        item["journal"] = [f"k3s {role} installed and Ready"]
        model["guests"][str(spec["id"])] = item
    return model


def pair_and_rotate(model: dict[str, object]) -> str:
    old_token = current_server_token(model)
    for server in EXPECTED_SERVERS:
        capture_paired_snapshot(model, server, old_token)
    new_token = proposed_server_token(model)
    rotate_server_token(model, new_token, SERVER_ORDER)
    return new_token


def passing_observation() -> tuple[dict[str, object], dict[str, object]]:
    model = provisioned_model()
    baseline = cluster_state(model)
    pair_and_rotate(model)
    for node in EXPECTED_NODES:
        _, status = restart_node(model, node, 30)
        if status != 0:
            raise AssertionError(f"fixture restart failed for {node}: {status}")
    return baseline, gate_observation(model)


def check(result: object, name: str) -> object:
    matches = [item for item in result.checks if item.name == name]
    if len(matches) != 1:
        raise AssertionError(f"missing unique gate check {name}")
    return matches[0]


def set_etcd_member_names(
    baseline: dict[str, object],
    observation: dict[str, object],
    names: tuple[str, str, str],
) -> None:
    for document in (baseline, observation):
        members = document.get("etcd_members")
        if not isinstance(members, list) or len(members) != len(names):
            raise AssertionError("fixture requires exactly three etcd members")
        for member, name in zip(members, names, strict=True):
            if not isinstance(member, dict):
                raise AssertionError("fixture etcd member must be a mapping")
            member["name"] = name


def etcd_member_names(document: dict[str, object]) -> tuple[str, ...]:
    members = document.get("etcd_members")
    if not isinstance(members, list):
        raise AssertionError("fixture etcd members must be a list")
    names: list[str] = []
    for member in members:
        if not isinstance(member, dict) or not isinstance(member.get("name"), str):
            raise AssertionError("fixture etcd member must have a string name")
        names.append(member["name"])
    return tuple(names)


class TokenGuardTests(unittest.TestCase):
    def test_valid_full_server_token_is_accepted(self) -> None:
        token = current_server_token(empty_model(LAB_ID))
        self.assertEqual(assert_full_server_token(token), token)

    def test_agent_token_is_rejected(self) -> None:
        token = current_server_token(empty_model(LAB_ID)).replace(
            "::server:", "::agent:"
        )
        with self.assertRaisesRegex(TestAGuardError, "classification=agent-token"):
            assert_full_server_token(token)

    def test_bare_secret_is_rejected(self) -> None:
        token = current_server_token(empty_model(LAB_ID))
        with self.assertRaisesRegex(TestAGuardError, "classification=bare-or-short-secret"):
            assert_full_server_token(normalize_token(token))

    def test_malformed_full_token_is_rejected(self) -> None:
        with self.assertRaisesRegex(TestAGuardError, "classification=malformed-full-token"):
            assert_full_server_token("K10not-a-full-token::server:value")

    def test_registry_contains_candidates_and_normalized_secrets(self) -> None:
        model = empty_model(LAB_ID)
        old_token = current_server_token(model)
        new_token = proposed_server_token(model)
        values = registry_values(old_token, new_token)
        self.assertEqual(
            values,
            [old_token, normalize_token(old_token), new_token, normalize_token(new_token)],
        )


class MockTransitionGuardTests(unittest.TestCase):
    def test_unpaired_snapshot_is_rejected_without_mutation(self) -> None:
        model = provisioned_model()
        before = copy.deepcopy(model)
        with self.assertRaisesRegex(MockError, "unpaired snapshot rejected before mutation"):
            capture_paired_snapshot(model, "server-1", None)
        self.assertEqual(model, before)

    def test_stale_snapshot_token_is_rejected_without_mutation(self) -> None:
        model = provisioned_model()
        before = copy.deepcopy(model)
        stale = proposed_server_token(model)
        with self.assertRaisesRegex(MockError, "token is not current"):
            capture_paired_snapshot(model, "server-1", stale)
        self.assertEqual(model, before)

    def test_rotation_requires_three_independent_pairs(self) -> None:
        model = provisioned_model()
        old_token = current_server_token(model)
        capture_paired_snapshot(model, "server-1", old_token)
        before = copy.deepcopy(model)
        with self.assertRaisesRegex(MockError, "all three servers require"):
            rotate_server_token(model, proposed_server_token(model), SERVER_ORDER)
        self.assertEqual(model, before)

    def test_restart_order_violation_is_detected_without_restart(self) -> None:
        model = provisioned_model()
        pair_and_rotate(model)
        before = copy.deepcopy(model)
        with self.assertRaisesRegex(MockError, "restart-order violation"):
            restart_node(model, "server-2", 30)
        self.assertEqual(model, before)

    def test_agent_restart_before_servers_is_detected(self) -> None:
        model = provisioned_model()
        pair_and_rotate(model)
        with self.assertRaisesRegex(MockError, "expected server-1 next"):
            restart_node(model, "agent-1", 30)

    def test_mock_health_wait_is_bounded_and_configurable(self) -> None:
        model = provisioned_model()
        pair_and_rotate(model)
        model["injections"]["health_convergence_seconds"]["server-1"] = 31
        event, status = restart_node(model, "server-1", 30)
        self.assertEqual(status, 70)
        self.assertEqual(event["status"], "timeout")
        server = next(
            item for item in model["guests"].values() if item["short_name"] == "server-1"
        )
        self.assertFalse(server["ready"])


class BaselinePrerequisiteTests(unittest.TestCase):
    def inputs(
        self,
    ) -> tuple[
        dict[str, object],
        dict[str, object],
        dict[str, object],
        dict[str, object],
        dict[str, object],
    ]:
        model = provisioned_model()
        baseline = cluster_state(model)
        canonical = validate(parse_config(EXAMPLE), EXAMPLE)
        state = {
            "config_sha256": canonical["config_sha256"],
            "inventory": copy.deepcopy(canonical["inventory"]),
        }
        return baseline, copy.deepcopy(baseline), state, canonical, copy.deepcopy(canonical)

    def test_independent_baseline_observations_pass(self) -> None:
        baseline, current, state, canonical, manifest_config = self.inputs()
        snapshots = dict.fromkeys(EXPECTED_NODES, True)
        result = baseline_prerequisites(
            baseline,
            current,
            state,
            canonical,
            snapshots,
            manifest_config=manifest_config,
        )
        self.assertEqual(result["verdict"], "PASS")
        assert_baseline_prerequisites(result)

    def test_missing_hypervisor_snapshot_returns_snapshot_class(self) -> None:
        baseline, current, state, canonical, manifest_config = self.inputs()
        snapshots = dict.fromkeys(EXPECTED_NODES, True)
        snapshots["server-2"] = False
        result = baseline_prerequisites(
            baseline,
            current,
            state,
            canonical,
            snapshots,
            manifest_config=manifest_config,
        )
        with self.assertRaises(TestAPrerequisiteError) as raised:
            assert_baseline_prerequisites(result)
        self.assertEqual(raised.exception.exit_code, 67)

    def test_post_provision_snapshot_and_restart_changes_pass_identity(self) -> None:
        baseline, current, state, _, manifest_config = self.inputs()
        values = parse_config(EXAMPLE)
        values["snapshot_name"] = "post-provision-baseline"
        values["server_restart_order"] = "server-2,server-3,server-1"
        canonical = validate(values, EXAMPLE)
        snapshots = dict.fromkeys(EXPECTED_NODES, True)
        result = baseline_prerequisites(
            baseline,
            current,
            state,
            canonical,
            snapshots,
            manifest_config=manifest_config,
        )
        identity = next(
            item
            for item in result["checks"]
            if item["check"] == "provision-identity-and-inventory"
        )
        self.assertEqual((result["verdict"], identity["verdict"]), ("PASS", "PASS"))

    def test_template_vmid_provision_identity_drift_fails(self) -> None:
        baseline, current, state, _, manifest_config = self.inputs()
        values = parse_config(EXAMPLE)
        values["template_vmid"] = "9001"
        canonical = validate(values, EXAMPLE)
        snapshots = dict.fromkeys(EXPECTED_NODES, True)
        result = baseline_prerequisites(
            baseline,
            current,
            state,
            canonical,
            snapshots,
            manifest_config=manifest_config,
        )
        with self.assertRaises(TestAPrerequisiteError) as raised:
            assert_baseline_prerequisites(result)
        self.assertEqual(
            (
                raised.exception.exit_code,
                [
                    item["check"]
                    for item in result["checks"]
                    if item["verdict"] == "FAIL"
                ],
            ),
            (69, ["provision-identity-and-inventory"]),
        )

    def test_state_inventory_drift_fails_provision_identity_check(self) -> None:
        baseline, current, state, canonical, manifest_config = self.inputs()
        state_inventory = copy.deepcopy(state["inventory"])
        state_inventory[0]["ip"] = "192.0.2.99"
        state["inventory"] = state_inventory
        snapshots = dict.fromkeys(EXPECTED_NODES, True)
        result = baseline_prerequisites(
            baseline,
            current,
            state,
            canonical,
            snapshots,
            manifest_config=manifest_config,
        )
        with self.assertRaises(TestAPrerequisiteError) as raised:
            assert_baseline_prerequisites(result)
        self.assertEqual(
            (
                raised.exception.exit_code,
                [
                    item["check"]
                    for item in result["checks"]
                    if item["verdict"] == "FAIL"
                ],
            ),
            (69, ["provision-identity-and-inventory"]),
        )


class GateEvaluationTests(unittest.TestCase):
    def test_clean_rotation_passes_every_gate(self) -> None:
        baseline, observation = passing_observation()
        result = evaluate_gate(baseline, observation, SERVER_ORDER)
        self.assertEqual(result.verdict, "PASS")
        self.assertEqual(len(result.checks), 7)
        self.assertTrue(all(item.passed and item.coverage for item in result.checks))

    def test_restart_order_observation_fails(self) -> None:
        baseline, observation = passing_observation()
        observation["restart_events"][0], observation["restart_events"][1] = (
            observation["restart_events"][1],
            observation["restart_events"][0],
        )
        result = evaluate_gate(baseline, observation, SERVER_ORDER)
        self.assertFalse(check(result, "configured-rolling-restart-order").passed)

    def test_injected_decryption_failure_line_fails(self) -> None:
        baseline, observation = passing_observation()
        observation["server_journals"]["server-2"].append(
            "failed to decrypt bootstrap data: cipher: message authentication failed"
        )
        result = evaluate_gate(baseline, observation, SERVER_ORDER)
        self.assertFalse(check(result, "zero-bootstrap-decryption-journal-failures").passed)

    def test_two_bootstrap_keys_fail(self) -> None:
        baseline, observation = passing_observation()
        observation["bootstrap_keys"].append("/bootstrap/0123456789ab")
        result = evaluate_gate(baseline, observation, SERVER_ORDER)
        self.assertFalse(check(result, "exactly-one-bootstrap-key").passed)

    def test_join_credential_mismatch_fails(self) -> None:
        baseline, observation = passing_observation()
        observation["nodes"][4]["join_credential_sha256"] = "f" * 64
        result = evaluate_gate(baseline, observation, SERVER_ORDER)
        target = "matching-normalized-join-credential-references"
        self.assertFalse(check(result, target).passed)

    def test_not_ready_node_fails(self) -> None:
        baseline, observation = passing_observation()
        observation["nodes"][3]["ready"] = False
        result = evaluate_gate(baseline, observation, SERVER_ORDER)
        self.assertFalse(check(result, "five-ready-nodes").passed)

    def test_changed_ca_fails(self) -> None:
        baseline, observation = passing_observation()
        observation["ca_sha256"] = "0" * 64
        result = evaluate_gate(baseline, observation, SERVER_ORDER)
        self.assertFalse(check(result, "ca-hash-unchanged").passed)

    def test_unhealthy_etcd_member_fails(self) -> None:
        baseline, observation = passing_observation()
        observation["etcd_members"][1]["healthy"] = False
        result = evaluate_gate(baseline, observation, SERVER_ORDER)
        self.assertFalse(check(result, "three-healthy-etcd-members").passed)

    def test_ran_marker_suffixed_names_matching_baseline_pass(self) -> None:
        baseline, observation = passing_observation()
        baseline_member_names = etcd_member_names(baseline)
        self.assertEqual(baseline_member_names, etcd_member_names(observation))
        for server, member_name in zip(
            EXPECTED_SERVERS, baseline_member_names, strict=True
        ):
            self.assertRegex(member_name, rf"^{re.escape(server)}-[0-9a-f]{{8}}$")
        result = evaluate_gate(baseline, observation, SERVER_ORDER)
        member_check = check(result, "three-healthy-etcd-members")
        self.assertTrue(member_check.passed)
        self.assertEqual(
            member_check.expected,
            "the exact three baselined etcd members, one per server, all healthy",
        )
        for server, member_name in zip(
            EXPECTED_SERVERS, baseline_member_names, strict=True
        ):
            self.assertIn(f"{server}\u2190{member_name}", member_check.observed)

    def test_ran_marker_missing_baselined_member_fails(self) -> None:
        baseline, observation = passing_observation()
        set_etcd_member_names(baseline, observation, SUFFIXED_MEMBER_NAMES)
        observation["etcd_members"].pop()
        result = evaluate_gate(baseline, observation, SERVER_ORDER)
        self.assertFalse(check(result, "three-healthy-etcd-members").passed)

    def test_ran_marker_fourth_member_fails(self) -> None:
        baseline, observation = passing_observation()
        set_etcd_member_names(baseline, observation, SUFFIXED_MEMBER_NAMES)
        observation["etcd_members"].append(
            {"name": "server-1-deadbeef", "healthy": True}
        )
        result = evaluate_gate(baseline, observation, SERVER_ORDER)
        self.assertFalse(check(result, "three-healthy-etcd-members").passed)

    def test_ran_marker_unexpected_server_prefix_fails(self) -> None:
        baseline, observation = passing_observation()
        invalid_names = (
            "server-4-0123abcd",
            SUFFIXED_MEMBER_NAMES[1],
            SUFFIXED_MEMBER_NAMES[2],
        )
        set_etcd_member_names(baseline, observation, invalid_names)
        result = evaluate_gate(baseline, observation, SERVER_ORDER)
        self.assertFalse(check(result, "three-healthy-etcd-members").passed)

    def test_ran_marker_non_hex_or_wrong_length_suffix_fails(self) -> None:
        baseline, observation = passing_observation()
        invalid_names = (
            "server-1-1234567g",
            SUFFIXED_MEMBER_NAMES[1],
            SUFFIXED_MEMBER_NAMES[2],
        )
        set_etcd_member_names(baseline, observation, invalid_names)
        result = evaluate_gate(baseline, observation, SERVER_ORDER)
        self.assertFalse(check(result, "three-healthy-etcd-members").passed)

    def test_ran_marker_bare_names_with_bare_baseline_pass(self) -> None:
        baseline, observation = passing_observation()
        set_etcd_member_names(baseline, observation, EXPECTED_SERVERS)
        result = evaluate_gate(baseline, observation, SERVER_ORDER)
        self.assertTrue(check(result, "three-healthy-etcd-members").passed)

    def test_raw_modeled_output_is_scrubbed_by_registered_candidates(self) -> None:
        model = provisioned_model()
        old_token = current_server_token(model)
        new_token = pair_and_rotate(model)
        model["injections"]["raw_output"] = old_token
        for node in EXPECTED_NODES:
            restart_node(model, node, 30)
        observation = gate_observation(model)
        registry = TokenRegistry(registry_values(old_token, new_token))
        serialized = str(redact_value(observation, registry))
        self.assertNotIn(old_token, serialized)
        self.assertNotIn(normalize_token(old_token), serialized)


class PhaseEvidenceTests(unittest.TestCase):
    def test_fresh_phase_ledger_accepts_setup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            record = record_phase(
                Path(temporary),
                1,
                "SETUP",
                "2026-09-02T07:47:00.000Z",
                "2026-09-02T07:47:01.000Z",
                0,
            )
            self.assertEqual(record["phase"], "SETUP")

    def test_leftover_setup_ledger_rejects_setup_with_existing_message(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_path = Path(temporary)
            record_phase(
                run_path,
                1,
                "SETUP",
                "2026-09-02T07:02:00.000Z",
                "2026-09-02T07:02:01.000Z",
                0,
            )
            with self.assertRaisesRegex(
                TestAGuardError,
                "phase order violation: expected 'BREAK', observed 'SETUP'",
            ):
                record_phase(
                    run_path,
                    2,
                    "SETUP",
                    "2026-09-02T07:47:00.000Z",
                    "2026-09-02T07:47:01.000Z",
                    0,
                )

    def test_phase_order_sequence_and_duration_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_path = Path(temporary)
            first = record_phase(
                run_path,
                10,
                "SETUP",
                "2026-08-14T12:00:00.000Z",
                "2026-08-14T12:00:01.250Z",
                0,
            )
            second = record_phase(
                run_path,
                20,
                "BREAK",
                "2026-08-14T12:00:02.000Z",
                "2026-08-14T12:00:04.000Z",
                0,
            )
            self.assertEqual(first["duration_seconds"], 1.25)
            self.assertEqual(second["sequence"], 20)

    def test_phase_order_guard_can_fail(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            self.assertRaisesRegex(TestAGuardError, "phase order violation"),
        ):
            record_phase(
                Path(temporary),
                1,
                "BREAK",
                "2026-08-14T12:00:00.000Z",
                "2026-08-14T12:00:01.000Z",
                0,
            )


if __name__ == "__main__":
    unittest.main()
