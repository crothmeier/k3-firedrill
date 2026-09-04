from __future__ import annotations

import json
import traceback
import unittest
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import replace

from firedrill.bootstrap import (
    BOOTSTRAP_HASH_BITS,
    BootstrapBranch,
    BootstrapDiscriminatorResult,
    TokenNormalizationError,
    bootstrap_key_name,
    detect_bootstrap_era,
    normalize_token,
)
from firedrill.redact import TokenRegistry, token_reference
from firedrill.test_c_recovery import (
    PairedSnapshot,
    RecoveryContractError,
    RecoveryExecution,
    RecoveryForm,
    RecoveryHalted,
    RecoveryInvariantError,
    ResetAttemptError,
    ResetFlagCleanupError,
    ResetFlagObservation,
    TokenCandidate,
    apply_recovery_policy,
    assert_final_bootstrap_key,
    remove_reset_flag_explicitly,
)

OLD_SECRET = "old-secret"
NEW_SECRET = "new-secret"
OLD_TOKEN = f"K10{'a' * 64}::server:{OLD_SECRET}"
NEW_TOKEN = f"K10{'b' * 64}::server:{NEW_SECRET}"
OLD_KEY = "/bootstrap/5d865deae06f"
NEW_KEY = "/bootstrap/fc97bb52861f"
UNKNOWN_KEY = "/bootstrap/000000000000"
SNAPSHOT_PATH = "/var/lib/rancher/k3s/server/db/snapshots/pre-rotation"
SNAPSHOT_SHA256 = "f" * 64
RESET_FLAG_PATH = "/var/lib/rancher/k3s/server/db/reset-flag"


class MockRecoveryDriver:
    """In-memory Test C driver fixture; it cannot contact infrastructure."""

    def __init__(
        self,
        keys: Iterable[str],
        *,
        fail_reset: bool = False,
        flag_present: bool = False,
        k3s_running: bool = False,
    ) -> None:
        self.keys = tuple(keys)
        self.fail_reset = fail_reset
        self.flag_present = flag_present
        self.flag_mtime_ns = 100 if flag_present else None
        self.k3s_running = k3s_running
        self.events: list[str] = []
        self.reset_calls: list[dict[str, object]] = []
        self.remove_calls: list[str] = []

    def reset(self, *, token: str, restore_path: str | None) -> None:
        self.events.append("reset")
        self.reset_calls.append(
            {
                "explicit_token": bool(token),
                "token_reference": token_reference(token),
                "restore_path": restore_path,
            }
        )
        if self.fail_reset:
            self.flag_present = True
            self.flag_mtime_ns = 200
            raise RuntimeError(f"mock reset rejected secret {token}")

    def observe_keys(self) -> Iterable[str]:
        self.events.append("observe-keys")
        return self.keys

    def observe_flag(self, path: str) -> ResetFlagObservation:
        self.events.append("observe-flag")
        return ResetFlagObservation(path, self.flag_present, self.flag_mtime_ns)

    def process_running(self) -> bool:
        self.events.append("process-running")
        return self.k3s_running

    def remove_flag(self, path: str) -> None:
        self.events.append("remove-flag")
        self.remove_calls.append(path)
        self.flag_present = False
        self.flag_mtime_ns = None


class ForbiddenRecovery:
    """Fails a test immediately if a halt branch attempts recovery."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *, token: str, restore_path: str | None) -> None:
        self.calls += 1
        raise AssertionError(
            f"recovery must not be called with token={token!r}, restore_path={restore_path!r}"
        )


class RecordingRegistry(TokenRegistry):
    """Token registry that records ordering without exposing values to evidence."""

    def __init__(self, events: list[tuple[str, str]]) -> None:
        self.events = events
        super().__init__()

    def register(self, token: str) -> None:
        self.events.append(("register", token))
        super().register(token)


def assert_no_secrets(test: unittest.TestCase, records: list[dict[str, object]]) -> None:
    test.assertTrue(records, "expected emitted evidence before checking it for secrets")
    serialized = json.dumps(records, sort_keys=True)
    for secret in (OLD_TOKEN, NEW_TOKEN, OLD_SECRET, NEW_SECRET):
        test.assertNotIn(secret, serialized)


class TokenNormalizationTests(unittest.TestCase):
    def test_full_token_normalizes_to_secret(self) -> None:
        self.assertEqual(normalize_token(OLD_TOKEN), OLD_SECRET)

    def test_bare_secret_is_unchanged(self) -> None:
        self.assertEqual(normalize_token(OLD_SECRET), OLD_SECRET)

    def test_ca_hash_and_unusual_username_are_excluded(self) -> None:
        unusual = f"K10{'c' * 64}::bootstrap.user+lab@example:{OLD_SECRET}"
        different_ca = f"K10{'d' * 64}::another-user:{OLD_SECRET}"
        self.assertEqual(normalize_token(unusual), OLD_SECRET)
        self.assertEqual(bootstrap_key_name(unusual), OLD_KEY)
        self.assertEqual(bootstrap_key_name(different_ca), OLD_KEY)

    def test_ca_hash_field_is_not_validated_on_local_reset_path(self) -> None:
        malformed_ca = f"K10not-a-validated-ca-hash::server:{OLD_SECRET}"
        self.assertEqual(normalize_token(malformed_ca), OLD_SECRET)
        self.assertEqual(bootstrap_key_name(malformed_ca), OLD_KEY)

    def test_secret_retains_colons_after_username_separator(self) -> None:
        token = f"K10{'e' * 64}::odd-user:part-one:part-two"
        self.assertEqual(normalize_token(token), "part-one:part-two")

    def test_empty_username_is_discarded(self) -> None:
        token = f"K10{'e' * 64}:::{OLD_SECRET}"
        self.assertEqual(normalize_token(token), OLD_SECRET)

    def test_empty_normalized_secret_is_a_caller_error(self) -> None:
        invalid = ("", "   ", f"K10{'a' * 64}", f"K10{'a' * 64}::server:")
        for token in invalid:
            with self.subTest(token=token), self.assertRaises(TokenNormalizationError):
                normalize_token(token)

    def test_known_answer_uses_independent_literal(self) -> None:
        token = f"K10{'e' * 64}::server:known-answer-secret"
        self.assertEqual(bootstrap_key_name(token), "/bootstrap/4a3f6fb0a521")
        self.assertEqual(BOOTSTRAP_HASH_BITS, 48)


class DiscriminatorTests(unittest.TestCase):
    def detect(
        self,
        observed: Iterable[str],
        old: str = OLD_TOKEN,
        new: str = NEW_TOKEN,
    ) -> BootstrapDiscriminatorResult:
        return detect_bootstrap_era(observed, old, new, registry=TokenRegistry())

    def test_all_named_branches(self) -> None:
        cases = (
            ((OLD_KEY,), BootstrapBranch.OLD_ONLY),
            ((NEW_KEY,), BootstrapBranch.NEW_ONLY),
            ((NEW_KEY, OLD_KEY), BootstrapBranch.BOTH),
            ((), BootstrapBranch.ZERO),
            ((UNKNOWN_KEY,), BootstrapBranch.ANOMALOUS),
        )
        for observed, expected in cases:
            with self.subTest(expected=expected):
                result = self.detect(observed)
                self.assertEqual(result.branch, expected)
                self.assertEqual(result.observed_key_names, tuple(sorted(observed)))
                self.assertEqual(result.old_candidate_key_name, OLD_KEY)
                self.assertEqual(result.new_candidate_key_name, NEW_KEY)
                self.assertTrue(result.method)
                self.assertTrue(result.reason)
                assert_no_secrets(self, [result.to_evidence()])

    def test_required_anomalous_shapes(self) -> None:
        cases = (
            (UNKNOWN_KEY,),
            (OLD_KEY, NEW_KEY, UNKNOWN_KEY),
            (OLD_KEY, UNKNOWN_KEY),
        )
        for observed in cases:
            with self.subTest(observed=observed):
                self.assertEqual(self.detect(observed).branch, BootstrapBranch.ANOMALOUS)

    def test_duplicate_observation_is_anomalous(self) -> None:
        self.assertEqual(
            self.detect((OLD_KEY, OLD_KEY)).branch,
            BootstrapBranch.ANOMALOUS,
        )

    def test_candidate_derivation_collision_is_anomalous(self) -> None:
        old = f"K10{'c' * 64}::server:shared-secret"
        new = f"K10{'d' * 64}::unusual-user:shared-secret"
        key = "/bootstrap/d3046ecc8dd3"
        result = self.detect((key,), old, new)
        self.assertEqual(result.branch, BootstrapBranch.ANOMALOUS)
        self.assertIn("collision", result.reason)
        self.assertEqual(result.old_candidate_key_name, key)
        self.assertEqual(result.new_candidate_key_name, key)
        serialized = json.dumps(result.to_evidence(), sort_keys=True)
        for secret in (old, new, "shared-secret"):
            self.assertNotIn(secret, serialized)

    def test_normalization_error_is_not_a_branch(self) -> None:
        with self.assertRaises(TokenNormalizationError):
            self.detect((OLD_KEY,), "", NEW_TOKEN)


class RecoveryPolicyTests(unittest.TestCase):
    def apply(
        self,
        observed: Iterable[str],
        driver: MockRecoveryDriver,
        *,
        paired_snapshot: PairedSnapshot | None = None,
        old: str = OLD_TOKEN,
        new: str = NEW_TOKEN,
        evidence: list[dict[str, object]] | None = None,
        registry: TokenRegistry | None = None,
    ) -> tuple[RecoveryExecution, list[dict[str, object]]]:
        records = evidence if evidence is not None else []
        token_registry = registry if registry is not None else TokenRegistry()
        result = apply_recovery_policy(
            observed,
            old,
            new,
            paired_snapshot=paired_snapshot,
            reset=driver.reset,
            observe_bootstrap_keys=driver.observe_keys,
            observe_reset_flag=driver.observe_flag,
            reset_flag_path=RESET_FLAG_PATH,
            registry=token_registry,
            evidence=records.append,
        )
        return result, records

    def test_old_only_uses_token_paired_with_snapshot(self) -> None:
        driver = MockRecoveryDriver((OLD_KEY,))
        pair = PairedSnapshot(
            SNAPSHOT_PATH,
            SNAPSHOT_SHA256,
            TokenCandidate.OLD,
            token_reference(OLD_TOKEN),
        )
        execution, records = self.apply((OLD_KEY,), driver, paired_snapshot=pair)
        self.assertEqual(execution.decision.form, RecoveryForm.SNAPSHOT_RESTORE)
        self.assertEqual(execution.decision.selected_candidate, TokenCandidate.OLD)
        self.assertEqual(driver.reset_calls[0]["token_reference"], token_reference(OLD_TOKEN))
        self.assertEqual(driver.reset_calls[0]["restore_path"], SNAPSHOT_PATH)
        self.assertEqual(execution.decision.snapshot_sha256, SNAPSHOT_SHA256)
        self.assertTrue(driver.reset_calls[0]["explicit_token"])
        self.assertTrue(execution.recovery_complete)
        assert_no_secrets(self, records)

    def test_new_only_uses_membership_reset_without_restore(self) -> None:
        driver = MockRecoveryDriver((NEW_KEY,))
        execution, records = self.apply((NEW_KEY,), driver)
        self.assertEqual(execution.decision.form, RecoveryForm.MEMBERSHIP_ONLY)
        self.assertEqual(execution.decision.selected_candidate, TokenCandidate.NEW)
        self.assertEqual(driver.reset_calls[0]["token_reference"], token_reference(NEW_TOKEN))
        self.assertIsNone(driver.reset_calls[0]["restore_path"])
        self.assertTrue(driver.reset_calls[0]["explicit_token"])
        self.assertTrue(execution.recovery_complete)
        assert_no_secrets(self, records)

    def test_old_only_can_use_membership_reset_without_snapshot(self) -> None:
        driver = MockRecoveryDriver((OLD_KEY,))
        execution, _ = self.apply((OLD_KEY,), driver)
        self.assertEqual(execution.decision.form, RecoveryForm.MEMBERSHIP_ONLY)
        self.assertEqual(execution.decision.selected_candidate, TokenCandidate.OLD)
        self.assertIsNone(driver.reset_calls[0]["restore_path"])

    def test_new_only_can_use_snapshot_paired_with_new_token(self) -> None:
        driver = MockRecoveryDriver((NEW_KEY,))
        pair = PairedSnapshot(
            SNAPSHOT_PATH,
            SNAPSHOT_SHA256,
            TokenCandidate.NEW,
            token_reference(NEW_TOKEN),
        )
        execution, _ = self.apply((NEW_KEY,), driver, paired_snapshot=pair)
        self.assertEqual(execution.decision.form, RecoveryForm.SNAPSHOT_RESTORE)
        self.assertEqual(execution.decision.selected_candidate, TokenCandidate.NEW)
        self.assertEqual(driver.reset_calls[0]["restore_path"], SNAPSHOT_PATH)

    def test_both_without_snapshot_is_deterministic_and_incomplete(self) -> None:
        decisions = []
        for _ in range(2):
            driver = MockRecoveryDriver((NEW_KEY, OLD_KEY))
            execution, records = self.apply((OLD_KEY, NEW_KEY), driver)
            decisions.append(execution.decision.selected_candidate)
            self.assertEqual(execution.decision.form, RecoveryForm.MEMBERSHIP_ONLY)
            self.assertEqual(execution.decision.cleanup_key_name, OLD_KEY)
            self.assertTrue(execution.decision.cleanup_required)
            self.assertFalse(execution.recovery_complete)
            self.assertEqual(driver.remove_calls, [])
            self.assertIn(OLD_KEY, execution.post_reset_key_names)
            assert_no_secrets(self, records)
        self.assertEqual(decisions, [TokenCandidate.NEW, TokenCandidate.NEW])

    def test_both_with_snapshot_uses_its_pair_and_flags_other_key(self) -> None:
        driver = MockRecoveryDriver((OLD_KEY, NEW_KEY))
        pair = PairedSnapshot(
            SNAPSHOT_PATH,
            SNAPSHOT_SHA256,
            TokenCandidate.OLD,
            token_reference(OLD_TOKEN),
        )
        execution, _ = self.apply((OLD_KEY, NEW_KEY), driver, paired_snapshot=pair)
        self.assertEqual(execution.decision.form, RecoveryForm.SNAPSHOT_RESTORE)
        self.assertEqual(execution.decision.selected_candidate, TokenCandidate.OLD)
        self.assertEqual(execution.decision.cleanup_key_name, NEW_KEY)
        self.assertFalse(execution.recovery_complete)

    def test_both_fails_if_non_selected_key_does_not_survive(self) -> None:
        driver = MockRecoveryDriver((NEW_KEY,))
        with self.assertRaisesRegex(RecoveryInvariantError, "must preserve"):
            self.apply((OLD_KEY, NEW_KEY), driver)

    def test_snapshot_pair_mismatch_halts_before_reset(self) -> None:
        driver = MockRecoveryDriver((OLD_KEY,))
        pair = PairedSnapshot(
            SNAPSHOT_PATH,
            SNAPSHOT_SHA256,
            TokenCandidate.NEW,
            token_reference(NEW_TOKEN),
        )
        with self.assertRaises(RecoveryContractError):
            self.apply((OLD_KEY,), driver, paired_snapshot=pair)
        self.assertEqual(driver.reset_calls, [])

    def test_snapshot_candidate_label_must_match_its_reference(self) -> None:
        driver = MockRecoveryDriver((OLD_KEY,))
        contradictory = PairedSnapshot(
            SNAPSHOT_PATH,
            SNAPSHOT_SHA256,
            TokenCandidate.NEW,
            token_reference(OLD_TOKEN),
        )
        with self.assertRaises(RecoveryContractError):
            self.apply((OLD_KEY,), driver, paired_snapshot=contradictory)
        self.assertEqual(driver.reset_calls, [])

    def test_zero_and_anomalous_shapes_never_call_recovery(self) -> None:
        cases = (
            (),
            (UNKNOWN_KEY,),
            (OLD_KEY, UNKNOWN_KEY),
            (OLD_KEY, NEW_KEY, UNKNOWN_KEY),
        )
        for observed in cases:
            forbidden = ForbiddenRecovery()
            driver = MockRecoveryDriver(observed)
            records: list[dict[str, object]] = []
            with self.subTest(observed=observed), self.assertRaises(RecoveryHalted):
                apply_recovery_policy(
                    observed,
                    OLD_TOKEN,
                    NEW_TOKEN,
                    paired_snapshot=None,
                    reset=forbidden,
                    observe_bootstrap_keys=driver.observe_keys,
                    observe_reset_flag=driver.observe_flag,
                    reset_flag_path=RESET_FLAG_PATH,
                    registry=TokenRegistry(),
                    evidence=records.append,
                )
            self.assertEqual(forbidden.calls, 0)
            self.assertEqual(driver.events, [])
            assert_no_secrets(self, records)

    def test_collision_never_calls_recovery(self) -> None:
        old = f"K10{'c' * 64}::server:shared-secret"
        new = f"K10{'d' * 64}::other:shared-secret"
        key = "/bootstrap/d3046ecc8dd3"
        forbidden = ForbiddenRecovery()
        driver = MockRecoveryDriver((key,))
        records: list[dict[str, object]] = []
        with self.assertRaises(RecoveryHalted):
            apply_recovery_policy(
                (key,),
                old,
                new,
                paired_snapshot=None,
                reset=forbidden,
                observe_bootstrap_keys=driver.observe_keys,
                observe_reset_flag=driver.observe_flag,
                reset_flag_path=RESET_FLAG_PATH,
                registry=TokenRegistry(),
                evidence=records.append,
            )
        self.assertEqual(forbidden.calls, 0)
        self.assertTrue(records)
        serialized = json.dumps(records, sort_keys=True)
        for secret in (old, new, "shared-secret"):
            self.assertNotIn(secret, serialized)

    def test_raw_tokens_are_absent_from_every_branch_evidence(self) -> None:
        cases = (
            (OLD_KEY,),
            (NEW_KEY,),
            (OLD_KEY, NEW_KEY),
            (),
            (UNKNOWN_KEY,),
            (OLD_KEY, UNKNOWN_KEY),
            (OLD_KEY, NEW_KEY, UNKNOWN_KEY),
        )
        for observed in cases:
            driver = MockRecoveryDriver(observed)
            records: list[dict[str, object]] = []
            with suppress(RecoveryHalted):
                self.apply(observed, driver, evidence=records)
            events = {str(record["event"]) for record in records}
            self.assertTrue(
                {"bootstrap-discriminator", "test-c-recovery-decision"} <= events
            )
            if observed in {(OLD_KEY,), (NEW_KEY,), (OLD_KEY, NEW_KEY)}:
                self.assertTrue(
                    {
                        "reset-flag-observation",
                        "cluster-reset-succeeded",
                        "test-c-recovery-result",
                    }
                    <= events
                )
            assert_no_secrets(self, records)

    def test_candidates_registered_before_first_evidence(self) -> None:
        order: list[tuple[str, str]] = []
        registry = RecordingRegistry(order)
        records: list[dict[str, object]] = []

        def emit(record: dict[str, object]) -> None:
            order.append(("evidence", str(record["event"])))
            records.append(record)

        driver = MockRecoveryDriver((NEW_KEY,))
        apply_recovery_policy(
            (NEW_KEY,),
            OLD_TOKEN,
            NEW_TOKEN,
            paired_snapshot=None,
            reset=driver.reset,
            observe_bootstrap_keys=driver.observe_keys,
            observe_reset_flag=driver.observe_flag,
            reset_flag_path=RESET_FLAG_PATH,
            registry=registry,
            evidence=emit,
        )
        first_evidence = next(index for index, item in enumerate(order) if item[0] == "evidence")
        registered = {item[1] for item in order[:first_evidence] if item[0] == "register"}
        self.assertTrue({OLD_TOKEN, NEW_TOKEN, OLD_SECRET, NEW_SECRET} <= registered)
        self.assertTrue(records)

    def test_selected_token_mismatch_is_caught_before_reset(self) -> None:
        driver = MockRecoveryDriver((NEW_KEY,))

        def stale_discriminator(
            observed_key_names: Iterable[str],
            old_token_candidate: str,
            new_token_candidate: str,
            *,
            registry: TokenRegistry,
        ) -> BootstrapDiscriminatorResult:
            del observed_key_names, old_token_candidate, new_token_candidate
            return detect_bootstrap_era((NEW_KEY,), OLD_TOKEN, NEW_TOKEN, registry=registry)

        with self.assertRaises(RecoveryContractError):
            apply_recovery_policy(
                (NEW_KEY,),
                OLD_TOKEN,
                "different-new-secret",
                paired_snapshot=None,
                reset=driver.reset,
                observe_bootstrap_keys=driver.observe_keys,
                observe_reset_flag=driver.observe_flag,
                reset_flag_path=RESET_FLAG_PATH,
                registry=TokenRegistry(),
                evidence=lambda _: None,
                discriminator=stale_discriminator,
            )
        self.assertEqual(driver.reset_calls, [])

    def test_unsupported_discriminator_branch_halts_before_reset(self) -> None:
        driver = MockRecoveryDriver((NEW_KEY,))

        def unsupported_discriminator(
            observed_key_names: Iterable[str],
            old_token_candidate: str,
            new_token_candidate: str,
            *,
            registry: TokenRegistry,
        ) -> BootstrapDiscriminatorResult:
            result = detect_bootstrap_era(
                observed_key_names,
                old_token_candidate,
                new_token_candidate,
                registry=registry,
            )
            return replace(result, branch="UNSUPPORTED")

        with self.assertRaisesRegex(RecoveryContractError, "unsupported discriminator"):
            apply_recovery_policy(
                (NEW_KEY,),
                OLD_TOKEN,
                NEW_TOKEN,
                paired_snapshot=None,
                reset=driver.reset,
                observe_bootstrap_keys=driver.observe_keys,
                observe_reset_flag=driver.observe_flag,
                reset_flag_path=RESET_FLAG_PATH,
                registry=TokenRegistry(),
                evidence=lambda _: None,
                discriminator=unsupported_discriminator,
            )
        self.assertEqual(driver.reset_calls, [])

    def test_snapshot_requires_canonical_path_digest_and_candidate(self) -> None:
        invalid_pairs = (
            ("/", SNAPSHOT_SHA256, TokenCandidate.OLD),
            ("/tmp/../snapshot", SNAPSHOT_SHA256, TokenCandidate.OLD),
            (SNAPSHOT_PATH, "not-a-digest", TokenCandidate.OLD),
            (SNAPSHOT_PATH, SNAPSHOT_SHA256, "BOGUS"),
        )
        for path, digest, candidate in invalid_pairs:
            with (
                self.subTest(path=path, digest=digest, candidate=candidate),
                self.assertRaises(RecoveryContractError),
            ):
                PairedSnapshot(path, digest, candidate, token_reference(OLD_TOKEN))


class ResetFlagTests(unittest.TestCase):
    def test_reset_records_flag_before_and_after(self) -> None:
        driver = MockRecoveryDriver((NEW_KEY,))
        records: list[dict[str, object]] = []
        execution, _ = RecoveryPolicyTests().apply((NEW_KEY,), driver, evidence=records)
        self.assertEqual(driver.events[:3], ["observe-flag", "reset", "observe-flag"])
        self.assertFalse(execution.reset_flag_before.present)
        self.assertFalse(execution.reset_flag_after.present)
        phases = [
            record["phase"]
            for record in records
            if record["event"] == "reset-flag-observation"
        ]
        self.assertEqual(phases, ["before", "after"])

    def test_failed_reset_reports_stranded_flag_and_never_removes_it(self) -> None:
        driver = MockRecoveryDriver((NEW_KEY,), fail_reset=True)
        records: list[dict[str, object]] = []
        with self.assertRaises(ResetAttemptError) as raised:
            RecoveryPolicyTests().apply((NEW_KEY,), driver, evidence=records)
        self.assertFalse(raised.exception.before.present)
        self.assertIsNotNone(raised.exception.after)
        self.assertTrue(raised.exception.after and raised.exception.after.present)
        self.assertIn("retry would be refused", str(raised.exception))
        self.assertEqual(driver.remove_calls, [])
        self.assertEqual(driver.events, ["observe-flag", "reset", "observe-flag"])
        assert_no_secrets(self, records)
        self.assertNotIn(NEW_TOKEN, str(raised.exception))
        formatted = "".join(traceback.format_exception(raised.exception))
        self.assertNotIn(NEW_TOKEN, formatted)
        self.assertNotIn(NEW_SECRET, formatted)
        self.assertIsNone(raised.exception.__cause__)

    def test_existing_stranded_flag_refuses_retry_before_reset(self) -> None:
        driver = MockRecoveryDriver((NEW_KEY,), flag_present=True)
        with self.assertRaisesRegex(ResetAttemptError, "retry would be refused") as raised:
            RecoveryPolicyTests().apply((NEW_KEY,), driver)
        self.assertIsNotNone(raised.exception.after)
        self.assertTrue(raised.exception.after and raised.exception.after.present)
        self.assertEqual(driver.reset_calls, [])
        self.assertEqual(driver.events, ["observe-flag", "observe-flag"])

    def test_explicit_cleanup_refuses_while_k3s_is_running(self) -> None:
        driver = MockRecoveryDriver((NEW_KEY,), flag_present=True, k3s_running=True)
        with self.assertRaises(ResetFlagCleanupError):
            remove_reset_flag_explicitly(
                RESET_FLAG_PATH,
                observe_reset_flag=driver.observe_flag,
                k3s_process_running=driver.process_running,
                remove_reset_flag=driver.remove_flag,
                registry=TokenRegistry(),
                evidence=lambda _: None,
            )
        self.assertEqual(driver.remove_calls, [])
        self.assertEqual(driver.events, ["observe-flag", "process-running"])

    def test_explicit_cleanup_requires_boolean_stopped_proof(self) -> None:
        for process_state in (None, 0, ""):
            driver = MockRecoveryDriver((NEW_KEY,), flag_present=True)
            with (
                self.subTest(process_state=process_state),
                self.assertRaisesRegex(ResetFlagCleanupError, "boolean process-state proof"),
            ):
                remove_reset_flag_explicitly(
                    RESET_FLAG_PATH,
                    observe_reset_flag=driver.observe_flag,
                    k3s_process_running=lambda state=process_state: state,
                    remove_reset_flag=driver.remove_flag,
                    registry=TokenRegistry(),
                    evidence=lambda _: None,
                )
            self.assertEqual(driver.remove_calls, [])
            self.assertEqual(driver.events, ["observe-flag"])

    def test_explicit_cleanup_logs_and_verifies_exact_removal(self) -> None:
        driver = MockRecoveryDriver((NEW_KEY,), flag_present=True)
        records: list[dict[str, object]] = []
        result = remove_reset_flag_explicitly(
            RESET_FLAG_PATH,
            observe_reset_flag=driver.observe_flag,
            k3s_process_running=driver.process_running,
            remove_reset_flag=driver.remove_flag,
            registry=TokenRegistry(),
            evidence=records.append,
        )
        self.assertTrue(result.removed)
        self.assertEqual(driver.remove_calls, [RESET_FLAG_PATH])
        self.assertEqual(
            driver.events,
            ["observe-flag", "process-running", "remove-flag", "observe-flag"],
        )
        self.assertFalse(result.after.present)
        self.assertIn(RESET_FLAG_PATH, json.dumps(records))

    def test_explicit_cleanup_rejects_root_and_traversal_without_callbacks(self) -> None:
        for path in ("/", "/tmp/../reset-flag", "/tmp/not-the-reset-flag"):
            driver = MockRecoveryDriver((NEW_KEY,), flag_present=True)
            with self.subTest(path=path), self.assertRaises(RecoveryContractError):
                remove_reset_flag_explicitly(
                    path,
                    observe_reset_flag=driver.observe_flag,
                    k3s_process_running=driver.process_running,
                    remove_reset_flag=driver.remove_flag,
                    registry=TokenRegistry(),
                    evidence=lambda _: None,
                )
            self.assertEqual(driver.events, [])


class FinalBootstrapKeyGateTests(unittest.TestCase):
    def test_gate_matches_key_name_to_running_token(self) -> None:
        records: list[dict[str, object]] = []
        result = assert_final_bootstrap_key(
            (NEW_KEY,),
            NEW_TOKEN,
            registry=TokenRegistry(),
            evidence=records.append,
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.expected_key_name, NEW_KEY)
        assert_no_secrets(self, records)

    def test_gate_rejects_cardinality_without_name_match(self) -> None:
        with self.assertRaises(RecoveryInvariantError):
            assert_final_bootstrap_key(
                (OLD_KEY, NEW_KEY),
                NEW_TOKEN,
                registry=TokenRegistry(),
                evidence=lambda _: None,
            )


if __name__ == "__main__":
    unittest.main()
