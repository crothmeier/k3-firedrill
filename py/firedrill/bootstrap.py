"""K3s bootstrap-key derivation and Test C era discrimination."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from firedrill.redact import TokenRegistry, token_reference

BOOTSTRAP_PREFIX = "/bootstrap/"
BOOTSTRAP_HASH_HEX_LENGTH = 12
# Twelve hexadecimal characters expose 48 bits: 2**48 possible suffixes, with
# birthday collisions becoming plausible around 2**24 independently chosen secrets.
BOOTSTRAP_HASH_BITS = BOOTSTRAP_HASH_HEX_LENGTH * 4
DISCRIMINATOR_METHOD = "k3s-storage-key-sha256-normalized-secret-12hex"
K3S_VERSION_PIN = "v1.34.4+k3s1"
K3S_SOURCE_PIN = "c6017918a65c824ce8d321db15267c8a317cd39d"


class TokenNormalizationError(ValueError):
    """A candidate token cannot yield a non-empty K3s token secret."""


class BootstrapBranch(StrEnum):
    """Complete Test C discriminator state."""

    OLD_ONLY = "OLD_ONLY"
    NEW_ONLY = "NEW_ONLY"
    BOTH = "BOTH"
    ZERO = "ZERO"
    ANOMALOUS = "ANOMALOUS"


@dataclass(frozen=True)
class BootstrapDiscriminatorResult:
    """Secret-free structured result consumed by the recovery policy."""

    branch: BootstrapBranch
    observed_key_names: tuple[str, ...]
    old_candidate_key_name: str
    new_candidate_key_name: str
    old_token_reference: str
    new_token_reference: str
    method: str
    reason: str
    source_pin: str = K3S_SOURCE_PIN

    def to_evidence(self) -> dict[str, object]:
        """Return the stable, secret-free representation permitted in evidence."""
        return {
            "event": "bootstrap-discriminator",
            "branch": self.branch,
            "observed_key_names": list(self.observed_key_names),
            "old_candidate_key_name": self.old_candidate_key_name,
            "new_candidate_key_name": self.new_candidate_key_name,
            "old_token_reference": self.old_token_reference,
            "new_token_reference": self.new_token_reference,
            "method": self.method,
            "reason": self.reason,
            "source_pin": self.source_pin,
        }


def normalize_token(token: str) -> str:
    """Return the secret used by K3s bootstrap encryption.

    The local reset path recognizes a secure token by its ``K10`` prefix and
    separators, then discards both the CA-hash field and username. It does not
    validate the CA-hash field. A non-``K10`` value is a bare secret.
    """
    if not isinstance(token, str):
        raise TokenNormalizationError("candidate token must be a string")
    if not token.strip():
        raise TokenNormalizationError("candidate token must yield a non-empty secret")
    if not token.startswith("K10"):
        return token

    _, marker, credentials = token.partition("::")
    if not marker:
        raise TokenNormalizationError("K10 candidate is missing the credential separator")
    _, separator, secret = credentials.partition(":")
    if not separator:
        raise TokenNormalizationError("K10 candidate is missing the username separator")
    if not secret.strip():
        raise TokenNormalizationError("K10 candidate is missing a non-empty secret")
    return secret


def bootstrap_key_name(token: str) -> str:
    """Derive the exact bootstrap key path for a candidate token."""
    secret = normalize_token(token)
    suffix = hashlib.sha256(secret.encode()).hexdigest()[:BOOTSTRAP_HASH_HEX_LENGTH]
    return f"{BOOTSTRAP_PREFIX}{suffix}"


def register_candidate_tokens(
    registry: TokenRegistry,
    old_token_candidate: str,
    new_token_candidate: str,
) -> None:
    """Register raw candidates and normalized secrets before evidence is emitted."""
    old_secret = normalize_token(old_token_candidate)
    new_secret = normalize_token(new_token_candidate)
    registry.register(old_token_candidate)
    registry.register(old_secret)
    registry.register(new_token_candidate)
    registry.register(new_secret)


def _anomalous_reason(
    observed: tuple[str, ...],
    old_key: str,
    new_key: str,
) -> str:
    observed_set = set(observed)
    expected = {old_key, new_key}
    matching = sorted(observed_set & expected)
    unexpected = sorted(observed_set - expected)
    if len(observed) != len(observed_set):
        return "duplicate key observations are invalid for an observed key set"
    if len(observed_set) > 2:
        return (
            "more than two bootstrap keys were observed; "
            f"matching={matching!r}, unexpected={unexpected!r}"
        )
    if len(observed_set) == 2 and len(matching) == 1:
        return (
            "two bootstrap keys were observed but only one candidate matched; "
            f"matching={matching!r}, unexpected={unexpected!r}"
        )
    if unexpected:
        return f"bootstrap key names did not match either candidate: {unexpected!r}"
    return (
        "bootstrap key observation did not equal an allowed exact set; "
        f"observed={list(observed)!r}, expected={sorted(expected)!r}"
    )


def detect_bootstrap_era(
    observed_key_names: Iterable[str],
    old_token_candidate: str,
    new_token_candidate: str,
    *,
    registry: TokenRegistry,
) -> BootstrapDiscriminatorResult:
    """Classify exact observed key names without inspecting bootstrap payloads."""
    register_candidate_tokens(registry, old_token_candidate, new_token_candidate)
    old_key = bootstrap_key_name(old_token_candidate)
    new_key = bootstrap_key_name(new_token_candidate)
    old_reference = token_reference(old_token_candidate)
    new_reference = token_reference(new_token_candidate)

    observed_values = tuple(observed_key_names)
    if not all(isinstance(name, str) for name in observed_values):
        raise TypeError("observed bootstrap key names must all be strings")
    observed = tuple(sorted(observed_values))
    observed_set = set(observed)

    if old_key == new_key:
        branch = BootstrapBranch.ANOMALOUS
        reason = (
            "candidate derivation collision: OLD and NEW both derive "
            f"{old_key} in the {BOOTSTRAP_HASH_BITS}-bit key namespace"
        )
    elif len(observed) != len(observed_set):
        branch = BootstrapBranch.ANOMALOUS
        reason = _anomalous_reason(observed, old_key, new_key)
    elif not observed:
        branch = BootstrapBranch.ZERO
        reason = (
            "no bootstrap keys were observed; reset would otherwise create an empty lock "
            "using the supplied token"
        )
    elif observed_set == {old_key}:
        branch = BootstrapBranch.OLD_ONLY
        reason = "the sole bootstrap key matches the OLD candidate encryption secret"
    elif observed_set == {new_key}:
        branch = BootstrapBranch.NEW_ONLY
        reason = "the sole bootstrap key matches the NEW candidate encryption secret"
    elif observed_set == {old_key, new_key} and len(observed) == 2:
        branch = BootstrapBranch.BOTH
        reason = (
            "both candidate keys are present; this is a valid rotation transient or a "
            "persisted swallowed-delete outcome"
        )
    else:
        branch = BootstrapBranch.ANOMALOUS
        reason = _anomalous_reason(observed, old_key, new_key)

    return BootstrapDiscriminatorResult(
        branch=branch,
        observed_key_names=observed,
        old_candidate_key_name=old_key,
        new_candidate_key_name=new_key,
        old_token_reference=old_reference,
        new_token_reference=new_reference,
        method=DISCRIMINATOR_METHOD,
        reason=reason,
    )
