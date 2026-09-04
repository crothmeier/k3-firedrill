"""Evidence-safe secret redaction with an in-memory active-token registry."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable

SECURE_TOKEN_RE = re.compile(
    r"K10[a-fA-F0-9]{64}::(?:server|node|agent):[^\s'\"]+"
)
TOKEN_ARGUMENT_RE = re.compile(
    r"(?P<prefix>"
    r"(?:--(?:agent-|server-)?token(?:=|\s+))"
    r"|(?:K3S_(?:AGENT_|SERVER_)?TOKEN\s*=\s*)"
    r")"
    r"(?P<quote>['\"]?)(?P<token>[^\s'\"]+)(?P=quote)",
    re.IGNORECASE,
)
YAML_TOKEN_RE = re.compile(
    r"^(?P<prefix>[ \t]*(?P<key_quote>['\"]?)"
    r"(?:token|agent-token|server-token)(?P=key_quote)[ \t]*:[ \t]*)"
    r"(?P<value_quote>['\"]?)(?P<token>[^\s'\"#]+)(?P=value_quote)",
    re.IGNORECASE | re.MULTILINE,
)
ACTIVE_TOKENS_ENV = "FIREDRILL_ACTIVE_TOKENS_JSON"


def token_reference(token: str) -> str:
    digest = hashlib.sha256(token.encode()).hexdigest()
    visible_prefix = token[:8] if len(token) > 16 else token[:2]
    return f"<redacted-token prefix={visible_prefix} sha256={digest}>"


class TokenRegistry:
    """Known active tokens and normalized forms retained only in process memory."""

    def __init__(self, tokens: Iterable[str] = ()) -> None:
        self._variants: dict[str, str] = {}
        for token in tokens:
            self.register(token)

    def register(self, token: str) -> None:
        raw = token.strip()
        if not raw:
            raise ValueError("registered token must not be empty")
        unquoted = raw
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
            unquoted = raw[1:-1]
        normalized = "".join(unquoted.split())
        if not normalized:
            raise ValueError("registered token must contain non-whitespace characters")
        for variant in {raw, unquoted, normalized}:
            if variant:
                self._variants[variant] = normalized

    def redact(self, value: str) -> str:
        result = value
        ordered = sorted(self._variants.items(), key=lambda item: len(item[0]), reverse=True)
        for variant, normalized in ordered:
            result = result.replace(variant, token_reference(normalized))
        normalized_tokens = sorted(set(self._variants.values()), key=len, reverse=True)
        for token in normalized_tokens:
            if len(token) < 4:
                continue
            split_pattern = re.compile(r"\s*".join(re.escape(character) for character in token))
            result = split_pattern.sub(token_reference(token), result)
        return result


def registry_from_environment() -> TokenRegistry:
    serialized = os.environ.get(ACTIVE_TOKENS_ENV, "[]")
    try:
        values = json.loads(serialized)
    except json.JSONDecodeError as error:
        raise ValueError(f"{ACTIVE_TOKENS_ENV} must contain a JSON array") from error
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise ValueError(f"{ACTIVE_TOKENS_ENV} must contain a JSON array of strings")
    return TokenRegistry(values)


def _redact_match(match: re.Match[str]) -> str:
    return (
        f"{match.group('prefix')}{match.group('quote')}"
        f"{token_reference(match.group('token'))}{match.group('quote')}"
    )


def _redact_yaml_match(match: re.Match[str]) -> str:
    return (
        f"{match.group('prefix')}{match.group('value_quote')}"
        f"{token_reference(match.group('token'))}{match.group('value_quote')}"
    )


def redact_text(value: str, registry: TokenRegistry | None = None) -> str:
    redacted = YAML_TOKEN_RE.sub(_redact_yaml_match, value)
    redacted = TOKEN_ARGUMENT_RE.sub(_redact_match, redacted)
    redacted = SECURE_TOKEN_RE.sub(lambda match: token_reference(match.group(0)), redacted)
    if registry is not None:
        redacted = registry.redact(redacted)
    return redacted


def redact_value(value: object, registry: TokenRegistry | None = None) -> object:
    if isinstance(value, str):
        return redact_text(value, registry)
    if isinstance(value, list):
        return [redact_value(item, registry) for item in value]
    if isinstance(value, dict):
        return {key: redact_value(item, registry) for key, item in value.items()}
    return value
