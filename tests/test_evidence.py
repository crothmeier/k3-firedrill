from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from firedrill.redact import ACTIVE_TOKENS_ENV

SERVER_TOKEN = f"K10{'d' * 64}::server:evidence-secret"
AGENT_TOKEN = f"K10{'e' * 64}::node:evidence-agent-secret"
BARE_TOKEN = "9e55bf27364940278c69763e55745d20"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class EvidenceTests(unittest.TestCase):
    def test_failing_nested_transport_is_recorded_before_error_trap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_path = Path(temporary) / "run"
            script = r"""
set -Eeuo pipefail
FD_PYTHON=$3
FD_TEMP_FILES=()
FD_EVIDENCE_SEQUENCE=0
FD_RUN_PATH=$2
on_error() {
    local status=$?
    local line=${BASH_LINENO[0]:-unknown}
    printf 'firedrill: command failed at line %s with exit status %s\n' \
        "$line" "$status" >&2
    exit "$status"
}
trap on_error ERR
source "$1/lib/evidence.sh"
transport() {
    printf 'injected guest transport failure\n' >&2
    "$BASH" -c 'exit 255'
}
evidence_exec pve-guest-exec server-1 transport
"""
            result = subprocess.run(
                [
                    "/bin/bash",
                    "-c",
                    script,
                    "evidence-failure-test",
                    str(REPOSITORY_ROOT),
                    str(run_path),
                    sys.executable,
                ],
                cwd=REPOSITORY_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 255)
            self.assertIn("injected guest transport failure", result.stderr)
            self.assertIn("with exit status 255", result.stderr)
            records = [
                json.loads(line)
                for line in (run_path / "evidence" / "commands.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["label"], "pve-guest-exec")
            self.assertEqual(records[0]["node"], "server-1")
            self.assertEqual(records[0]["exit_code"], 255)

    def test_every_written_artifact_is_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_path = root / "run"
            stdout_path = root / "stdout"
            stderr_path = root / "stderr"
            stdout_path.write_text(
                f"journal has {BARE_TOKEN} and {AGENT_TOKEN}\n", encoding="utf-8"
            )
            stderr_path.write_text(f"token: {SERVER_TOKEN}\n", encoding="utf-8")
            environment = os.environ.copy()
            environment[ACTIVE_TOKENS_ENV] = json.dumps([BARE_TOKEN, SERVER_TOKEN, AGENT_TOKEN])
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "firedrill.evidence",
                    "--run-path",
                    str(run_path),
                    "--sequence",
                    "1",
                    "--label",
                    "file-content-capture",
                    "--node",
                    "server-1",
                    "--started-at",
                    "2026-07-20T00:00:00Z",
                    "--ended-at",
                    "2026-07-20T00:00:01Z",
                    "--exit-code",
                    "1",
                    "--stdout",
                    str(stdout_path),
                    "--stderr",
                    str(stderr_path),
                    "--",
                    "k3s",
                    f"--token={SERVER_TOKEN}",
                ],
                check=True,
                env=environment,
            )
            artifacts = [
                path
                for path in (run_path / "evidence").rglob("*")
                if path.is_file()
            ]
            self.assertGreaterEqual(len(artifacts), 3)
            for artifact in artifacts:
                content = artifact.read_text(encoding="utf-8")
                for raw in (BARE_TOKEN, SERVER_TOKEN, AGENT_TOKEN):
                    self.assertNotIn(raw, content, artifact)


if __name__ == "__main__":
    unittest.main()
