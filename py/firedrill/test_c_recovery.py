"""Offline Test C triage, recovery selection, and reset safety policy."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Protocol

from firedrill.bootstrap import (
    BootstrapBranch,
    BootstrapDiscriminatorResult,
    bootstrap_key_name,
    detect_bootstrap_era,
    normalize_token,
    register_candidate_tokens,
)
from firedrill.redact import TokenRegistry, redact_text, redact_value, token_reference


class RecoveryPolicyError(RuntimeError):
    """Base class for a fail-closed Test C recovery-policy error."""


class RecoveryHalted(RecoveryPolicyError):
    """The discriminator requires a no-mutation halt."""


class RecoveryContractError(RecoveryPolicyError):
    """Recovery inputs violate an explicit safety contract."""


class ResetAttemptError(RecoveryPolicyError):
    """A reset was refused or failed, with flag observations retained."""

    def __init__(
        self,
        message: str,
        before: ResetFlagObservation,
        after: ResetFlagObservation | None,
    ) -> None:
        super().__init__(message)
        self.before = before
        self.after = after


class RecoveryInvariantError(RecoveryPolicyError):
    """A required post-reset bootstrap-key invariant failed."""


class ResetFlagCleanupError(RecoveryPolicyError):
    """Explicit reset-flag cleanup failed its process or removal guard."""


class TokenCandidate(StrEnum):
    """Candidate identity without carrying its raw token."""

    OLD = "OLD"
    NEW = "NEW"


class RecoveryAction(StrEnum):
    """Whether the policy permits a reset mutation."""

    RECOVER = "RECOVER"
    HALT = "HALT"


class RecoveryForm(StrEnum):
    """The two distinct cluster-reset forms."""

    SNAPSHOT_RESTORE = "SNAPSHOT_RESTORE"
    MEMBERSHIP_ONLY = "MEMBERSHIP_ONLY"


def _validate_exact_path(path: str, purpose: str) -> None:
    if not path or not path.startswith("/"):
        raise RecoveryContractError(f"{purpose} must be a non-empty absolute path")
    if path == "/" or "//" in path or any(
        ord(character) < 32 or ord(character) == 127 for character in path
    ):
        raise RecoveryContractError(f"{purpose} must be a canonical non-root path")
    if any(character in path for character in "*?[]"):
        raise RecoveryContractError(f"{purpose} must be exact and contain no glob syntax")
    parsed = PurePosixPath(path)
    if ".." in parsed.parts or str(parsed) != path:
        raise RecoveryContractError(f"{purpose} must not contain traversal or normalization")


def _validate_reset_flag_path(path: str) -> None:
    _validate_exact_path(path, "reset flag path")
    if PurePosixPath(path).name != "reset-flag":
        raise RecoveryContractError("reset flag path must name the exact reset-flag file")


@dataclass(frozen=True)
class PairedSnapshot:
    """Secret-free proof that a restore path is paired to one candidate."""

    restore_path: str
    snapshot_sha256: str
    token_candidate: TokenCandidate
    token_reference: str

    def __post_init__(self) -> None:
        _validate_exact_path(self.restore_path, "paired snapshot restore path")
        if not isinstance(self.token_candidate, TokenCandidate):
            raise RecoveryContractError("paired snapshot has an unsupported token candidate")
        if re.fullmatch(r"[0-9a-f]{64}", self.snapshot_sha256) is None:
            raise RecoveryContractError(
                "paired snapshot must carry a lowercase SHA-256 digest"
            )
        if not self.token_reference.startswith("<redacted-token "):
            raise RecoveryContractError("paired snapshot must carry a redacted token reference")


@dataclass(frozen=True)
class RecoveryDecision:
    """Secret-free triage decision; the reset executor receives raw tokens separately."""

    action: RecoveryAction
    branch: BootstrapBranch
    form: RecoveryForm | None
    selected_candidate: TokenCandidate | None
    selected_key_name: str | None
    selected_token_reference: str | None
    restore_path: str | None
    snapshot_sha256: str | None
    explicit_token_required: bool
    cleanup_key_name: str | None
    cleanup_required: bool
    reason: str

    def to_evidence(self) -> dict[str, object]:
        """Return the stable, secret-free decision record."""
        return {
            "event": "test-c-recovery-decision",
            "action": self.action,
            "branch": self.branch,
            "form": self.form,
            "selected_candidate": self.selected_candidate,
            "selected_key_name": self.selected_key_name,
            "selected_token_reference": self.selected_token_reference,
            "restore_path": self.restore_path,
            "snapshot_sha256": self.snapshot_sha256,
            "token_argument": "explicit" if self.explicit_token_required else None,
            "cleanup_key_name": self.cleanup_key_name,
            "cleanup_required": self.cleanup_required,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ResetFlagObservation:
    """Presence and nanosecond mtime for the configured reset flag."""

    path: str
    present: bool
    mtime_ns: int | None

    def __post_init__(self) -> None:
        _validate_reset_flag_path(self.path)
        if not isinstance(self.present, bool):
            raise RecoveryContractError("reset flag presence must be boolean")
        if self.present and self.mtime_ns is None:
            raise RecoveryContractError("present reset flag observation must include mtime_ns")
        if self.mtime_ns is not None and (
            not isinstance(self.mtime_ns, int) or isinstance(self.mtime_ns, bool)
        ):
            raise RecoveryContractError("reset flag mtime_ns must be an integer")
        if not self.present and self.mtime_ns is not None:
            raise RecoveryContractError("absent reset flag observation cannot include mtime_ns")

    def to_evidence(self, phase: str) -> dict[str, object]:
        """Return one before/after observation record."""
        return {
            "event": "reset-flag-observation",
            "phase": phase,
            "path": self.path,
            "present": self.present,
            "mtime_ns": self.mtime_ns,
        }


@dataclass(frozen=True)
class RecoveryExecution:
    """Secret-free result of one permitted, injected reset operation."""

    decision: RecoveryDecision
    reset_flag_before: ResetFlagObservation
    reset_flag_after: ResetFlagObservation
    post_reset_key_names: tuple[str, ...]
    recovery_complete: bool
    reason: str

    def to_evidence(self) -> dict[str, object]:
        """Return the stable, secret-free execution record."""
        return {
            "event": "test-c-recovery-result",
            "decision": self.decision.to_evidence(),
            "reset_flag_before": self.reset_flag_before.to_evidence("before"),
            "reset_flag_after": self.reset_flag_after.to_evidence("after"),
            "post_reset_key_names": list(self.post_reset_key_names),
            "recovery_complete": self.recovery_complete,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ResetFlagCleanupResult:
    """Result of the separately invoked reset-flag removal operation."""

    path: str
    removed: bool
    before: ResetFlagObservation
    after: ResetFlagObservation
    reason: str

    def to_evidence(self) -> dict[str, object]:
        """Return the stable cleanup record."""
        return {
            "event": "reset-flag-explicit-cleanup",
            "path": self.path,
            "removed": self.removed,
            "before": self.before.to_evidence("cleanup-before"),
            "after": self.after.to_evidence("cleanup-after"),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class BootstrapKeyGateResult:
    """Final exact-name gate for the cluster's verified runtime token."""

    expected_key_name: str
    observed_key_names: tuple[str, ...]
    token_reference: str
    passed: bool
    reason: str

    def to_evidence(self) -> dict[str, object]:
        """Return the stable final-gate record."""
        return {
            "event": "bootstrap-key-final-gate",
            "expected_key_name": self.expected_key_name,
            "observed_key_names": list(self.observed_key_names),
            "token_reference": self.token_reference,
            "passed": self.passed,
            "reason": self.reason,
        }


class BootstrapDiscriminator(Protocol):
    """Swappable discriminator boundary; triage accepts only its result."""

    def __call__(
        self,
        observed_key_names: Iterable[str],
        old_token_candidate: str,
        new_token_candidate: str,
        *,
        registry: TokenRegistry,
    ) -> BootstrapDiscriminatorResult: ...


class ResetFunction(Protocol):
    """Injected reset operation with an unavoidable explicit token argument."""

    def __call__(self, *, token: str, restore_path: str | None) -> None: ...


class ResetFlagObserver(Protocol):
    """Injected reset-flag stat operation."""

    def __call__(self, path: str) -> ResetFlagObservation: ...


class BootstrapKeyObserver(Protocol):
    """Injected exact bootstrap-key enumeration operation."""

    def __call__(self) -> Iterable[str]: ...


EvidenceSink = Callable[[dict[str, object]], None]


def _candidate_fields(
    result: BootstrapDiscriminatorResult,
    candidate: TokenCandidate,
) -> tuple[str, str]:
    if candidate is TokenCandidate.OLD:
        return result.old_candidate_key_name, result.old_token_reference
    if candidate is TokenCandidate.NEW:
        return result.new_candidate_key_name, result.new_token_reference
    raise RecoveryContractError("unsupported selected token candidate")


def select_recovery(
    result: BootstrapDiscriminatorResult,
    *,
    paired_snapshot: PairedSnapshot | None,
) -> RecoveryDecision:
    """Select recovery solely from a discriminator result and snapshot pairing."""
    if not isinstance(result.branch, BootstrapBranch):
        raise RecoveryContractError(
            "unsupported discriminator branch; recovery halted before mutation"
        )
    if result.branch is BootstrapBranch.ZERO:
        return RecoveryDecision(
            action=RecoveryAction.HALT,
            branch=result.branch,
            form=None,
            selected_candidate=None,
            selected_key_name=None,
            selected_token_reference=None,
            restore_path=None,
            snapshot_sha256=None,
            explicit_token_required=False,
            cleanup_key_name=None,
            cleanup_required=False,
            reason=(
                "DANGER: ZERO bootstrap keys; HALT with no recovery mutation because "
                "cluster reset would accept the supplied token and fabricate a bootstrap era"
            ),
        )
    if result.branch is BootstrapBranch.ANOMALOUS:
        return RecoveryDecision(
            action=RecoveryAction.HALT,
            branch=result.branch,
            form=None,
            selected_candidate=None,
            selected_key_name=None,
            selected_token_reference=None,
            restore_path=None,
            snapshot_sha256=None,
            explicit_token_required=False,
            cleanup_key_name=None,
            cleanup_required=False,
            reason=(
                "ANOMALOUS bootstrap keys; HALT with no recovery mutation; "
                f"observed={list(result.observed_key_names)!r}, expected="
                f"{[result.old_candidate_key_name, result.new_candidate_key_name]!r}; "
                f"{result.reason}"
            ),
        )

    form = (
        RecoveryForm.SNAPSHOT_RESTORE
        if paired_snapshot is not None
        else RecoveryForm.MEMBERSHIP_ONLY
    )
    if result.branch is BootstrapBranch.OLD_ONLY:
        selected = TokenCandidate.OLD
    elif result.branch is BootstrapBranch.NEW_ONLY:
        selected = TokenCandidate.NEW
    elif paired_snapshot is not None:
        selected = paired_snapshot.token_candidate
    else:
        selected = TokenCandidate.NEW

    selected_key, selected_reference = _candidate_fields(result, selected)
    if paired_snapshot is not None:
        if paired_snapshot.token_candidate is not selected:
            raise RecoveryContractError(
                "snapshot candidate label does not match the selected candidate"
            )
        if paired_snapshot.token_reference != selected_reference:
            raise RecoveryContractError(
                "snapshot token reference does not match the selected candidate"
            )
        restore_path = paired_snapshot.restore_path
        snapshot_sha256 = paired_snapshot.snapshot_sha256
        selection_reason = (
            f"{selected} selected because the requested restore path is explicitly paired "
            "with that candidate"
        )
    else:
        restore_path = None
        snapshot_sha256 = None
        if result.branch is BootstrapBranch.BOTH:
            selection_reason = (
                "NEW selected deterministically for BOTH without a paired snapshot because it "
                "is the intended rotation credential; OLD remains flagged for cleanup"
            )
        else:
            selection_reason = f"{selected} is the sole candidate matching the surviving key"

    cleanup_key = None
    cleanup_required = result.branch is BootstrapBranch.BOTH
    if cleanup_required:
        cleanup_key = (
            result.new_candidate_key_name
            if selected is TokenCandidate.OLD
            else result.old_candidate_key_name
        )

    return RecoveryDecision(
        action=RecoveryAction.RECOVER,
        branch=result.branch,
        form=form,
        selected_candidate=selected,
        selected_key_name=selected_key,
        selected_token_reference=selected_reference,
        restore_path=restore_path,
        snapshot_sha256=snapshot_sha256,
        explicit_token_required=True,
        cleanup_key_name=cleanup_key,
        cleanup_required=cleanup_required,
        reason=selection_reason,
    )


def _emit(record: dict[str, object], registry: TokenRegistry, sink: EvidenceSink) -> None:
    sanitized = redact_value(record, registry)
    if not isinstance(sanitized, dict):
        raise TypeError("sanitized Test C evidence record is not a mapping")
    sink(sanitized)


def _assert_result_matches_candidates(
    result: BootstrapDiscriminatorResult,
    old_token: str,
    new_token: str,
) -> None:
    expected = (
        bootstrap_key_name(old_token),
        bootstrap_key_name(new_token),
        token_reference(old_token),
        token_reference(new_token),
    )
    observed = (
        result.old_candidate_key_name,
        result.new_candidate_key_name,
        result.old_token_reference,
        result.new_token_reference,
    )
    if observed != expected:
        raise RecoveryContractError(
            "discriminator result does not belong to the supplied candidate tokens"
        )


def _observe_flag(
    observer: ResetFlagObserver,
    path: str,
) -> ResetFlagObservation:
    observation = observer(path)
    if observation.path != path:
        raise RecoveryContractError("reset-flag observer returned a different path")
    return observation


def _observe_keys(observer: BootstrapKeyObserver) -> tuple[str, ...]:
    values = tuple(observer())
    if not all(isinstance(name, str) for name in values):
        raise RecoveryContractError("bootstrap-key observer returned a non-string name")
    if len(values) != len(set(values)):
        raise RecoveryInvariantError("bootstrap-key observer returned duplicate names")
    return tuple(sorted(values))


def _selected_raw_token(
    decision: RecoveryDecision,
    old_token: str,
    new_token: str,
) -> str:
    if not decision.explicit_token_required or decision.selected_candidate is None:
        raise RecoveryContractError(
            "cluster reset requires a selected, explicit token argument; fallback is forbidden"
        )
    selected = old_token if decision.selected_candidate is TokenCandidate.OLD else new_token
    normalize_token(selected)
    if token_reference(selected) != decision.selected_token_reference:
        raise RecoveryContractError("selected explicit token does not match its recorded reference")
    if bootstrap_key_name(selected) != decision.selected_key_name:
        raise RecoveryContractError("selected explicit token does not match its bootstrap key")
    return selected


def apply_recovery_policy(
    observed_key_names: Iterable[str],
    old_token: str,
    new_token: str,
    *,
    paired_snapshot: PairedSnapshot | None,
    reset: ResetFunction,
    observe_bootstrap_keys: BootstrapKeyObserver,
    observe_reset_flag: ResetFlagObserver,
    reset_flag_path: str,
    registry: TokenRegistry,
    evidence: EvidenceSink,
    discriminator: BootstrapDiscriminator = detect_bootstrap_era,
) -> RecoveryExecution:
    """Discriminate, select, and run one injected reset under fail-closed policy."""
    register_candidate_tokens(registry, old_token, new_token)
    result = discriminator(
        observed_key_names,
        old_token,
        new_token,
        registry=registry,
    )
    _assert_result_matches_candidates(result, old_token, new_token)
    _emit(result.to_evidence(), registry, evidence)
    decision = select_recovery(result, paired_snapshot=paired_snapshot)
    _emit(decision.to_evidence(), registry, evidence)
    if decision.action is RecoveryAction.HALT:
        raise RecoveryHalted(decision.reason)

    selected_token = _selected_raw_token(decision, old_token, new_token)
    _validate_reset_flag_path(reset_flag_path)
    before = _observe_flag(observe_reset_flag, reset_flag_path)
    _emit(before.to_evidence("before"), registry, evidence)
    if before.present:
        after = _observe_flag(observe_reset_flag, reset_flag_path)
        _emit(after.to_evidence("after"), registry, evidence)
        reason = (
            "cluster reset refused before mutation: a reset flag is already present at "
            f"{before.path} with mtime_ns={before.mtime_ns}; retry would be refused"
        )
        _emit({"event": "cluster-reset-refused", "reason": reason}, registry, evidence)
        raise ResetAttemptError(reason, before, after)

    reset_error: Exception | None = None
    try:
        # The backend API requires this keyword. There is no token-file or fallback form.
        reset(token=selected_token, restore_path=decision.restore_path)
    except Exception as error:  # noqa: BLE001 - backend failure becomes structured evidence
        reset_error = error

    after = _observe_flag(observe_reset_flag, reset_flag_path)
    _emit(after.to_evidence("after"), registry, evidence)
    if reset_error is not None:
        safe_detail = redact_text(str(reset_error), registry) or type(reset_error).__name__
        if after.present:
            reason = (
                f"cluster reset failed: {safe_detail}; reset flag stranded at {after.path} "
                f"with mtime_ns={after.mtime_ns}; retry would be refused"
            )
        else:
            reason = f"cluster reset failed without a stranded reset flag: {safe_detail}"
        _emit({"event": "cluster-reset-failed", "reason": reason}, registry, evidence)
        raise ResetAttemptError(reason, before, after) from None

    _emit(
        {
            "event": "cluster-reset-succeeded",
            "form": decision.form,
            "selected_token_reference": decision.selected_token_reference,
            "restore_path": decision.restore_path,
        },
        registry,
        evidence,
    )
    post_reset_keys = _observe_keys(observe_bootstrap_keys)
    post_reset_set = set(post_reset_keys)
    if decision.branch is BootstrapBranch.BOTH:
        expected = {result.old_candidate_key_name, result.new_candidate_key_name}
        if post_reset_set != expected:
            raise RecoveryInvariantError(
                "BOTH reset must preserve the selected and non-selected keys before cleanup; "
                f"observed={list(post_reset_keys)!r}, expected={sorted(expected)!r}"
            )
        complete = False
        reason = (
            f"reset succeeded, but recovery is incomplete: non-selected key "
            f"{decision.cleanup_key_name} survived and requires explicit cleanup"
        )
    else:
        expected_key = decision.selected_key_name
        if post_reset_keys != (expected_key,):
            raise RecoveryInvariantError(
                "post-reset key set does not equal the selected token's key; "
                f"observed={list(post_reset_keys)!r}, expected={[expected_key]!r}"
            )
        complete = True
        reason = "reset succeeded and the sole bootstrap key matches the selected token"

    execution = RecoveryExecution(
        decision=decision,
        reset_flag_before=before,
        reset_flag_after=after,
        post_reset_key_names=post_reset_keys,
        recovery_complete=complete,
        reason=reason,
    )
    _emit(execution.to_evidence(), registry, evidence)
    return execution


def assert_final_bootstrap_key(
    observed_key_names: Iterable[str],
    observed_running_token: str,
    *,
    registry: TokenRegistry,
    evidence: EvidenceSink,
) -> BootstrapKeyGateResult:
    """Require one surviving key whose name derives from the verified runtime token."""
    secret = normalize_token(observed_running_token)
    registry.register(observed_running_token)
    registry.register(secret)
    expected = bootstrap_key_name(observed_running_token)
    observed_values = tuple(observed_key_names)
    if not all(isinstance(name, str) for name in observed_values):
        raise RecoveryContractError("final bootstrap key observations must all be strings")
    observed = tuple(sorted(observed_values))
    passed = observed == (expected,)
    reason = (
        "the sole bootstrap key matches the cluster's verified runtime token"
        if passed
        else (
            "final bootstrap key mismatch; "
            f"observed={list(observed)!r}, expected={[expected]!r}"
        )
    )
    result = BootstrapKeyGateResult(
        expected_key_name=expected,
        observed_key_names=observed,
        token_reference=token_reference(observed_running_token),
        passed=passed,
        reason=reason,
    )
    _emit(result.to_evidence(), registry, evidence)
    if not passed:
        raise RecoveryInvariantError(reason)
    return result


def remove_reset_flag_explicitly(
    reset_flag_path: str,
    *,
    observe_reset_flag: ResetFlagObserver,
    k3s_process_running: Callable[[], bool],
    remove_reset_flag: Callable[[str], None],
    registry: TokenRegistry,
    evidence: EvidenceSink,
) -> ResetFlagCleanupResult:
    """Perform separately named, guarded reset-flag cleanup; never called implicitly."""
    _validate_reset_flag_path(reset_flag_path)
    before = _observe_flag(observe_reset_flag, reset_flag_path)
    process_running = k3s_process_running()
    _emit(
        {
            "event": "reset-flag-cleanup-preflight",
            "path": reset_flag_path,
            "present": before.present,
            "mtime_ns": before.mtime_ns,
            "k3s_process_running": process_running,
        },
        registry,
        evidence,
    )
    if not isinstance(process_running, bool):
        raise ResetFlagCleanupError(
            "refusing explicit reset-flag cleanup without a boolean process-state proof"
        )
    if process_running:
        raise ResetFlagCleanupError(
            "refusing explicit reset-flag cleanup while a k3s process is running"
        )

    if not before.present:
        result = ResetFlagCleanupResult(
            path=reset_flag_path,
            removed=False,
            before=before,
            after=before,
            reason="reset flag was already absent; nothing was removed",
        )
        _emit(result.to_evidence(), registry, evidence)
        return result

    remove_reset_flag(reset_flag_path)
    after = _observe_flag(observe_reset_flag, reset_flag_path)
    if after.present:
        raise ResetFlagCleanupError(
            f"explicit reset-flag cleanup did not remove exact path {reset_flag_path}"
        )
    result = ResetFlagCleanupResult(
        path=reset_flag_path,
        removed=True,
        before=before,
        after=after,
        reason=f"removed exact reset-flag path {reset_flag_path} after proving k3s stopped",
    )
    _emit(result.to_evidence(), registry, evidence)
    return result
