from __future__ import annotations

import unittest

from firedrill.redact import TokenRegistry, redact_text

SERVER_TOKEN = f"K10{'a' * 64}::server:server-secret"
AGENT_TOKEN = f"K10{'b' * 64}::node:agent-secret"
BARE_TOKEN = "c4f18d392aa44c9dbac02f77e13d5142"


class RedactionTests(unittest.TestCase):
    def assert_redacted(self, raw: str, text: str, registry: TokenRegistry | None = None) -> str:
        output = redact_text(text, registry)
        self.assertNotIn(raw, output)
        return output

    def test_full_server_token_in_prose(self) -> None:
        self.assert_redacted(SERVER_TOKEN, f"server accepted {SERVER_TOKEN} during startup")

    def test_full_agent_token(self) -> None:
        self.assert_redacted(AGENT_TOKEN, f"agent-token is {AGENT_TOKEN}")

    def test_command_and_environment_forms(self) -> None:
        for text in (f"--token={SERVER_TOKEN}", f"K3S_TOKEN={SERVER_TOKEN}"):
            with self.subTest(text=text):
                self.assert_redacted(SERVER_TOKEN, text)

    def test_yaml_token_keys_quoted_and_unquoted(self) -> None:
        cases = (
            ("token: short-config-token", "short-config-token"),
            ('token: "quoted-config-token"', "quoted-config-token"),
            ("agent-token: 'agent-config-token'", "agent-config-token"),
            ('"server-token"   :   "server-config-token"', "server-config-token"),
        )
        for text, raw in cases:
            with self.subTest(text=text):
                self.assert_redacted(raw, text)

    def test_registered_bare_token_in_journal_line(self) -> None:
        registry = TokenRegistry([BARE_TOKEN])
        self.assert_redacted(
            BARE_TOKEN,
            f"bootstrap decrypt failed using credential {BARE_TOKEN}",
            registry,
        )

    def test_registered_token_split_across_multiline_capture(self) -> None:
        registry = TokenRegistry([BARE_TOKEN])
        midpoint = len(BARE_TOKEN) // 2
        first_half = BARE_TOKEN[:midpoint]
        second_half = BARE_TOKEN[midpoint:]
        output = redact_text(f"token fragment: {first_half}\n{second_half}", registry)
        self.assertNotIn(BARE_TOKEN, output)
        self.assertNotIn(first_half, output)
        self.assertNotIn(second_half, output)


if __name__ == "__main__":
    unittest.main()
