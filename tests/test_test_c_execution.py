from __future__ import annotations

import copy
import hashlib
import json
import unittest
from contextlib import suppress
from dataclasses import replace

from firedrill.bootstrap import BootstrapBranch, bootstrap_key_name
from firedrill.mock_model import (
    cluster_state,
    current_server_token,
    datastore_sha256,
    empty_model,
    new_guest,
    proposed_server_token,
)
from firedrill.redact import TokenRegistry, redact_value, token_reference
from firedrill.test_a import EXPECTED_NODES
from firedrill.test_c import evaluate_gate
from firedrill.test_c_model import (
    RESET_FLAG_PATH,
    MockBootstrapDiscriminator,
    MockRecoveryProtocols,
    ModeledEtcdSnapshot,
    TestCModelError,
    break_test_c,
    finish_recovery,
    gate_observation,
    nominated_snapshot,
    observed_running_token,
    prepare_test_c,
    record_recovery_execution,
    resolve_nominated_snapshot,
    set_preexisting_reset_flag,
    snapshot_catalog,
)
from firedrill.test_c_recovery import (
    RecoveryAction,
    RecoveryHalted,
    RecoveryInvariantError,
    ResetAttemptError,
    apply_recovery_policy,
    assert_final_bootstrap_key,
    select_recovery,
)


def fixture() -> tuple[dict[str, object], dict[str, object], str, str]:
    lab_id = "fd-test-c-execution"
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
                "k3s_running": True,
                "etcd_healthy": role == "server",
                "join_credential_sha256": model["cluster"]["join_credential_sha256"],
                "running_token_reference": model["cluster"]["server_token_reference"],
                "journal": [f"k3s {role} installed and Ready"],
            }
        )
        if role == "server":
            item["datastore_revision"] = 1
            item["datastore_sha256"] = datastore_sha256(lab_id, node, 1)
        model["guests"][str(spec["id"])] = item
    baseline = cluster_state(model)
    return model, baseline, current_server_token(model), proposed_server_token(model)


def apply_reset(
    model: dict[str, object], old_token: str, new_token: str
) -> tuple[object, list[dict[str, object]]]:
    registry = TokenRegistry()
    observed = tuple(model["cluster"]["bootstrap_keys"])
    discriminator = MockBootstrapDiscriminator(model)
    triage = discriminator(observed, old_token, new_token, registry=registry)
    decision = select_recovery(triage, paired_snapshot=nominated_snapshot(model))
    if decision.action is RecoveryAction.RECOVER:
        model["cluster"]["test_c"]["triage_branch"] = triage.branch
    records: list[dict[str, object]] = []
    protocols = MockRecoveryProtocols(model, old_token, new_token)
    execution = apply_recovery_policy(
        observed,
        old_token,
        new_token,
        paired_snapshot=nominated_snapshot(model),
        reset=protocols.reset,
        observe_bootstrap_keys=protocols.observe_bootstrap_keys,
        observe_reset_flag=protocols.observe_reset_flag,
        reset_flag_path=RESET_FLAG_PATH,
        registry=registry,
        evidence=records.append,
        discriminator=MockBootstrapDiscriminator(model),
    )
    assert execution.decision.to_evidence() == decision.to_evidence()
    record_recovery_execution(model, execution.to_evidence())
    return execution, records


def recover_and_gate(
    branch: BootstrapBranch = BootstrapBranch.NEW_ONLY,
    *,
    recovery_form: str = "membership",
    injections: dict[str, object] | None = None,
    stranded_after_finish: bool = False,
) -> tuple[object, dict[str, object], dict[str, object], dict[str, object]]:
    model, baseline, old_token, new_token = fixture()
    prepare_test_c(model, old_token, new_token, recovery_form)
    if injections:
        model["injections"]["test_c"].update(copy.deepcopy(injections))
    break_test_c(model, branch)
    execution, _ = apply_reset(model, old_token, new_token)
    finish_recovery(
        model,
        authorize_orphan_cleanup=branch is BootstrapBranch.BOTH,
        timeout_seconds=30,
    )
    if stranded_after_finish:
        set_preexisting_reset_flag(model, 1_700_000_000_999_999_999)
    observation = gate_observation(model)
    runtime = observed_running_token(model)
    final_records: list[dict[str, object]] = []
    with suppress(RecoveryInvariantError):
        assert_final_bootstrap_key(
            observation["bootstrap_keys"],
            runtime,
            registry=TokenRegistry(),
            evidence=final_records.append,
        )
    final = next(
        record for record in final_records if record["event"] == "bootstrap-key-final-gate"
    )
    triage = {
        "branch": execution.decision.branch,
        "method": "independent-test-discriminator",
        "source_pin": "unit-fixture",
        "reason": "unit fixture structured decision",
        "observed_key_names": list(execution.post_reset_key_names),
        "expected_key_names": [
            model["cluster"]["test_c"]["old_candidate_key_name"],
            model["cluster"]["test_c"]["new_candidate_key_name"],
        ],
        "preserved_datastore_unchanged": True,
    }
    gate = evaluate_gate(baseline, observation, final, triage)
    return gate, model, observation, baseline


class SnapshotAndBreakModelTests(unittest.TestCase):
    def test_snapshot_form_records_exact_digest_and_redacted_pair(self) -> None:
        model, _, old_token, new_token = fixture()
        record = prepare_test_c(model, old_token, new_token, "snapshot")
        pair = nominated_snapshot(model)
        self.assertIsNotNone(pair)
        self.assertEqual(pair.restore_path, record["paired_snapshot"]["path"])
        self.assertRegex(pair.snapshot_sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(pair.token_reference, token_reference(old_token))
        serialized = json.dumps(model, sort_keys=True)
        self.assertNotIn(old_token, serialized)
        self.assertNotIn(new_token, serialized)

    def test_membership_form_nominates_no_snapshot(self) -> None:
        model, _, old_token, new_token = fixture()
        prepare_test_c(model, old_token, new_token, "membership")
        self.assertIsNone(nominated_snapshot(model))
        self.assertEqual(len(snapshot_catalog(model)), 1)

    def test_multiple_nominations_are_rejected_without_mutating_catalog(self) -> None:
        model, _, old_token, new_token = fixture()
        prepare_test_c(model, old_token, new_token, "snapshot")
        first = snapshot_catalog(model)[0]
        second = replace(first, path=first.path.replace("server-3", "server-2"))
        original = copy.deepcopy(model)
        with self.assertRaisesRegex(TestCModelError, "more than one nominated"):
            resolve_nominated_snapshot((first, second), (first.path, second.path))
        self.assertEqual(model, original)

    def test_unpaired_snapshot_is_ineligible_before_mutation(self) -> None:
        unpaired = ModeledEtcdSnapshot(
            path="/var/lib/rancher/k3s/server/db/snapshots/unpaired.db",
            snapshot_sha256=hashlib.sha256(b"unpaired").hexdigest(),
            token_candidate=None,
            token_reference=None,
            paired=False,
        )
        with self.assertRaisesRegex(TestCModelError, "unpaired snapshot is ineligible"):
            resolve_nominated_snapshot((unpaired,), (unpaired.path,))

    def test_break_models_exact_stale_pair_quorum_loss_and_preservation(self) -> None:
        model, _, old_token, new_token = fixture()
        prepare_test_c(model, old_token, new_token, "membership")
        record = break_test_c(model, BootstrapBranch.BOTH)
        self.assertEqual(record["stale_token_servers_up"], ["server-1", "server-2"])
        self.assertTrue(record["quorum_lost"])
        self.assertEqual(record["healthy_etcd_members"], [])
        self.assertTrue(record["preserved_datastore_unchanged"])
        self.assertEqual(len(record["observed_bootstrap_key_names"]), 2)

    def test_model_presents_all_five_structured_branches(self) -> None:
        for branch in BootstrapBranch:
            with self.subTest(branch=branch):
                model, _, old_token, new_token = fixture()
                prepare_test_c(model, old_token, new_token, "membership")
                break_test_c(model, branch)
                observed = tuple(model["cluster"]["bootstrap_keys"])
                result = MockBootstrapDiscriminator(model)(
                    observed,
                    old_token,
                    new_token,
                    registry=TokenRegistry(),
                )
                self.assertEqual(result.branch, branch)


class RecoveryAdapterNegativeTests(unittest.TestCase):
    def test_zero_halts_with_no_recovery_mutation(self) -> None:
        model, _, old_token, new_token = fixture()
        prepare_test_c(model, old_token, new_token, "membership")
        break_test_c(model, BootstrapBranch.ZERO)
        before = copy.deepcopy(model)
        with self.assertRaisesRegex(RecoveryHalted, "ZERO"):
            apply_reset(model, old_token, new_token)
        self.assertEqual(model, before)
        self.assertEqual(model["cluster"]["test_c"]["reset_attempts"], 0)

    def test_three_key_anomalous_halts_and_reports_observed_and_expected_names(self) -> None:
        model, _, old_token, new_token = fixture()
        prepare_test_c(model, old_token, new_token, "membership")
        old_key = bootstrap_key_name(old_token)
        new_key = bootstrap_key_name(new_token)
        third = "/bootstrap/ffffffffffff"
        model["injections"]["test_c"]["anomalous_key_names"] = [old_key, new_key, third]
        break_test_c(model, BootstrapBranch.ANOMALOUS)
        records: list[dict[str, object]] = []
        registry = TokenRegistry()
        protocols = MockRecoveryProtocols(model, old_token, new_token)
        with self.assertRaises(RecoveryHalted) as raised:
            apply_recovery_policy(
                tuple(model["cluster"]["bootstrap_keys"]),
                old_token,
                new_token,
                paired_snapshot=None,
                reset=protocols.reset,
                observe_bootstrap_keys=protocols.observe_bootstrap_keys,
                observe_reset_flag=protocols.observe_reset_flag,
                reset_flag_path=RESET_FLAG_PATH,
                registry=registry,
                evidence=records.append,
                discriminator=MockBootstrapDiscriminator(model),
            )
        reason = str(raised.exception)
        self.assertIn(third, reason)
        self.assertIn(old_key, reason)
        self.assertIn(new_key, reason)
        self.assertEqual(model["cluster"]["test_c"]["reset_attempts"], 0)

    def test_derivation_collision_is_anomalous_and_never_resets(self) -> None:
        model, _, normal_old, normal_new = fixture()
        prepare_test_c(model, normal_old, normal_new, "membership")
        shared = hashlib.sha256(b"test-c-collision-secret").hexdigest()
        old_token = f"K10{hashlib.sha256(b'collision-old-ca').hexdigest()}::server:{shared}"
        new_token = f"K10{hashlib.sha256(b'collision-new-ca').hexdigest()}::server:{shared}"
        key = bootstrap_key_name(old_token)
        model["cluster"]["bootstrap_keys"] = [key]
        protocols = MockRecoveryProtocols(model, old_token, new_token)
        with self.assertRaisesRegex(RecoveryHalted, "collision") as raised:
            apply_recovery_policy(
                (key,),
                old_token,
                new_token,
                paired_snapshot=None,
                reset=protocols.reset,
                observe_bootstrap_keys=protocols.observe_bootstrap_keys,
                observe_reset_flag=protocols.observe_reset_flag,
                reset_flag_path=RESET_FLAG_PATH,
                registry=TokenRegistry(),
                evidence=lambda _: None,
                discriminator=MockBootstrapDiscriminator(model),
            )
        self.assertIn(key, str(raised.exception))
        self.assertEqual(model["cluster"]["test_c"]["reset_attempts"], 0)

    def test_preexisting_flag_refuses_before_reset_with_exact_path_and_mtime(self) -> None:
        model, _, old_token, new_token = fixture()
        prepare_test_c(model, old_token, new_token, "membership")
        break_test_c(model, BootstrapBranch.NEW_ONLY)
        mtime_ns = 1_700_000_000_111_222_333
        set_preexisting_reset_flag(model, mtime_ns)
        with self.assertRaises(ResetAttemptError) as raised:
            apply_reset(model, old_token, new_token)
        self.assertEqual(raised.exception.before.path, RESET_FLAG_PATH)
        self.assertEqual(raised.exception.before.mtime_ns, mtime_ns)
        self.assertEqual(model["cluster"]["test_c"]["reset_attempts"], 0)

    def test_failed_reset_reports_stranded_exact_flag_and_mtime(self) -> None:
        model, _, old_token, new_token = fixture()
        prepare_test_c(model, old_token, new_token, "membership")
        break_test_c(model, BootstrapBranch.NEW_ONLY)
        mtime_ns = 1_700_000_000_444_555_666
        model["injections"]["test_c"].update(
            {"reset_failure": True, "reset_flag_mtime_ns": mtime_ns}
        )
        with self.assertRaises(ResetAttemptError) as raised:
            apply_reset(model, old_token, new_token)
        self.assertIsNotNone(raised.exception.after)
        self.assertEqual(raised.exception.after.path, RESET_FLAG_PATH)
        self.assertEqual(raised.exception.after.mtime_ns, mtime_ns)
        self.assertIn("retry would be refused", str(raised.exception))

    def test_both_orphan_vanishing_during_reset_fails_invariant(self) -> None:
        model, _, old_token, new_token = fixture()
        prepare_test_c(model, old_token, new_token, "membership")
        model["injections"]["test_c"]["orphan_vanish_during_reset"] = True
        break_test_c(model, BootstrapBranch.BOTH)
        with self.assertRaisesRegex(RecoveryInvariantError, "must preserve"):
            apply_reset(model, old_token, new_token)
        self.assertEqual(model["cluster"]["test_c"]["reset_attempts"], 1)

    def test_both_requires_separate_cleanup_authorization(self) -> None:
        model, _, old_token, new_token = fixture()
        prepare_test_c(model, old_token, new_token, "membership")
        break_test_c(model, BootstrapBranch.BOTH)
        execution, _ = apply_reset(model, old_token, new_token)
        before = copy.deepcopy(model["cluster"]["bootstrap_keys"])
        with self.assertRaisesRegex(TestCModelError, "authorization is absent"):
            finish_recovery(
                model,
                authorize_orphan_cleanup=False,
                timeout_seconds=30,
            )
        self.assertFalse(execution.recovery_complete)
        self.assertEqual(model["cluster"]["bootstrap_keys"], before)


class GateEvaluationTests(unittest.TestCase):
    def test_both_cleanup_path_passes_only_after_survival_and_explicit_removal(self) -> None:
        gate, _, observation, _ = recover_and_gate(BootstrapBranch.BOTH)
        self.assertEqual(gate.verdict, "PASS")
        cleanup = observation["orphan_cleanup"]
        self.assertTrue(cleanup["authorized"])
        self.assertEqual(len(cleanup["before_key_names"]), 2)
        self.assertEqual(len(cleanup["after_key_names"]), 1)
        self.assertTrue(all(check.passed for check in gate.checks))

    def test_snapshot_and_membership_forms_are_both_exercisable(self) -> None:
        snapshot_gate, _, snapshot_observation, _ = recover_and_gate(
            BootstrapBranch.OLD_ONLY,
            recovery_form="snapshot",
        )
        membership_gate, _, membership_observation, _ = recover_and_gate(
            BootstrapBranch.NEW_ONLY,
            recovery_form="membership",
        )
        self.assertEqual(snapshot_gate.verdict, "PASS")
        self.assertEqual(membership_gate.verdict, "PASS")
        self.assertEqual(
            snapshot_observation["recovery_execution"]["decision"]["form"],
            "SNAPSHOT_RESTORE",
        )
        self.assertEqual(
            membership_observation["recovery_execution"]["decision"]["form"],
            "MEMBERSHIP_ONLY",
        )

    def test_runtime_credential_mismatch_fails_frozen_final_key_gate(self) -> None:
        gate, _, _, _ = recover_and_gate(
            injections={"runtime_candidate_override": "OLD"},
        )
        checks = {check.name: check for check in gate.checks}
        self.assertEqual(gate.verdict, "FAIL")
        self.assertFalse(checks["final-key-matches-observed-runtime-credential"].passed)

    def test_injected_different_token_journal_line_fails_gate(self) -> None:
        gate, _, _, _ = recover_and_gate(
            injections={
                "post_recovery_journal_lines": {
                    "server-2": ["k3s rejected a different token during post-recovery start"]
                }
            }
        )
        checks = {check.name: check for check in gate.checks}
        self.assertFalse(checks["clean-post-recovery-server-journals"].passed)

    def test_each_remaining_modeled_gate_can_fail_independently(self) -> None:
        cases = (
            (
                {"join_credential_mismatch_node": "agent-2"},
                False,
                "matching-normalized-join-credential-digests",
            ),
            ({"ca_hash_changed": True}, False, "ca-hash-unchanged"),
            ({"not_ready_node": "agent-1"}, False, "five-ready-nodes"),
            ({"unhealthy_member": "server-1"}, False, "three-healthy-etcd-members"),
            ({}, True, "no-stranded-reset-flag"),
        )
        for injections, stranded, expected_check in cases:
            with self.subTest(expected_check=expected_check):
                gate, _, _, _ = recover_and_gate(
                    injections=injections,
                    stranded_after_finish=stranded,
                )
                checks = {check.name: check for check in gate.checks}
                self.assertEqual(gate.verdict, "FAIL")
                self.assertFalse(checks[expected_check].passed)

    def test_raw_token_planted_in_modeled_output_is_redacted_before_evidence(self) -> None:
        model, _, old_token, new_token = fixture()
        prepare_test_c(model, old_token, new_token, "membership")
        model["injections"]["raw_output"] = old_token
        break_test_c(model, BootstrapBranch.NEW_ONLY)
        apply_reset(model, old_token, new_token)
        finish_recovery(
            model,
            authorize_orphan_cleanup=False,
            timeout_seconds=30,
        )
        raw_observation = gate_observation(model)
        registry = TokenRegistry((old_token, new_token))
        registry.register(old_token.split(":")[-1])
        registry.register(new_token.split(":")[-1])
        sanitized = redact_value(raw_observation, registry)
        serialized = json.dumps(sanitized, sort_keys=True)
        self.assertNotIn(old_token, serialized)
        self.assertNotIn(new_token, serialized)
        self.assertIn("<redacted-token ", serialized)


if __name__ == "__main__":
    unittest.main()
