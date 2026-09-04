from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from firedrill.config import ConfigError, parse_config, validate
from firedrill.config_check import check as config_check
from firedrill.safety import SafetyError, check_denylist, check_id

EXAMPLE = Path(__file__).parents[1] / "firedrill.conf.example"


class ConfigTests(unittest.TestCase):
    def test_example_is_valid_mock_configuration(self) -> None:
        result = validate(parse_config(EXAMPLE), EXAMPLE)
        self.assertEqual(result["allowed_id_max"], result["allowed_id_min"] + 4)
        self.assertEqual(len(result["inventory"]), 5)

    def test_config_check_prints_both_configuration_digests(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            status = config_check(EXAMPLE, EXAMPLE)
        lines = output.getvalue().splitlines()
        self.assertEqual(
            (
                status,
                sum(line.startswith("config_sha256: ") for line in lines),
                sum(line.startswith("provision_identity_sha256: ") for line in lines),
            ),
            (0, 1, 1),
        )

    def test_placeholder_is_rejected(self) -> None:
        values = parse_config(EXAMPLE)
        values["snapshot_name"] = "CHANGEME"
        with self.assertRaisesRegex(ConfigError, "snapshot_name is a placeholder"):
            validate(values, EXAMPLE)

    def test_exact_denylist_match_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "firedrill.conf"
            config_path.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
            config = validate(parse_config(config_path), config_path)
            Path(str(config["denylist_path"])).write_text("192.0.2.12\n", encoding="utf-8")
            with self.assertRaisesRegex(SafetyError, "server-3"):
                check_denylist(config)

    def test_id_outside_exact_allocation_is_rejected(self) -> None:
        config = validate(parse_config(EXAMPLE), EXAMPLE)
        with self.assertRaisesRegex(SafetyError, "outside configured range"):
            check_id(config, int(config["allowed_id_max"]) + 1)


if __name__ == "__main__":
    unittest.main()
