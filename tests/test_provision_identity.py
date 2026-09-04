from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import firedrill.config as config_module
from firedrill.config import parse_config, provision_identity, validate
from firedrill.state import StateError, atomic_json, begin

EXAMPLE = Path(__file__).parents[1] / "firedrill.conf.example"


def canonical(
    overrides: dict[str, str] | None = None,
    config_path: Path = EXAMPLE,
) -> dict[str, object]:
    values = parse_config(EXAMPLE)
    values.update(overrides or {})
    return validate(values, config_path)


class ProvisionIdentityDigestTests(unittest.TestCase):
    def assert_test_parameter_only(
        self, before: dict[str, object], after: dict[str, object]
    ) -> None:
        self.assertEqual(
            (
                before["config_sha256"] != after["config_sha256"],
                before["provision_identity_sha256"]
                == after["provision_identity_sha256"],
            ),
            (True, True),
        )

    def assert_provisioning_change(
        self, before: dict[str, object], after: dict[str, object]
    ) -> None:
        self.assertEqual(
            (
                before["config_sha256"] != after["config_sha256"],
                before["provision_identity_sha256"]
                != after["provision_identity_sha256"],
            ),
            (True, True),
        )

    def test_ran_marker_snapshot_name_changes_only_full_config_digest(self) -> None:
        self.assert_test_parameter_only(
            canonical(), canonical({"snapshot_name": "post-provision-baseline"})
        )

    def test_ran_marker_server_restart_order_changes_only_full_config_digest(self) -> None:
        self.assert_test_parameter_only(
            canonical(),
            canonical({"server_restart_order": "server-2,server-3,server-1"}),
        )

    def test_ran_marker_run_dir_changes_only_full_config_digest(self) -> None:
        self.assert_test_parameter_only(
            canonical(), canonical({"run_dir": "./alternate-runs"})
        )

    def test_ran_marker_config_path_changes_only_full_config_digest(self) -> None:
        self.assert_test_parameter_only(
            canonical(), canonical(config_path=EXAMPLE.parent / "alternate.conf")
        )

    def test_ran_marker_ssh_key_path_changes_only_full_config_digest(self) -> None:
        self.assert_test_parameter_only(
            canonical(), canonical({"ssh_key_path": "./keys/alternate"})
        )

    def test_ran_marker_cluster_capture_timeout_changes_only_full_config_digest(self) -> None:
        self.assert_test_parameter_only(
            canonical(), canonical({"cluster_capture_timeout_seconds": "121"})
        )

    def test_ran_marker_test_a_journal_limit_changes_only_full_config_digest(self) -> None:
        self.assert_test_parameter_only(
            canonical(), canonical({"test_a_journal_line_limit": "1001"})
        )

    def test_ran_marker_template_vmid_changes_both_digests(self) -> None:
        self.assert_provisioning_change(canonical(), canonical({"template_vmid": "9001"}))

    def test_ran_marker_k3s_binary_sha256_changes_both_digests(self) -> None:
        self.assert_provisioning_change(
            canonical(), canonical({"k3s_binary_sha256": "a" * 64})
        )

    def test_ran_marker_pve_storage_changes_both_digests(self) -> None:
        self.assert_provisioning_change(
            canonical(), canonical({"pve_storage": "alternate-storage"})
        )

    def test_ran_marker_network_bridge_changes_both_digests(self) -> None:
        self.assert_provisioning_change(
            canonical(), canonical({"network_bridge": "vmbr-alternate"})
        )

    def test_ran_marker_inventory_ip_changes_both_digests(self) -> None:
        self.assert_provisioning_change(
            canonical(), canonical({"ip_offsets": "20,21,22,23,24"})
        )

    def test_ran_marker_inventory_disk_gb_changes_both_digests(self) -> None:
        guests = list(config_module.GUESTS)
        first = guests[0]
        guests[0] = (*first[:-1], first[-1] + 1)
        with patch.object(config_module, "GUESTS", tuple(guests)):
            changed = canonical()
        self.assert_provisioning_change(canonical(), changed)

    def test_config_sha256_preserves_the_pre_identity_hash_surface(self) -> None:
        result = canonical()
        serialized_config = dict(result)
        serialized_config.pop("config_sha256")
        serialized_config.pop("provision_identity_sha256")
        expected = hashlib.sha256(
            json.dumps(
                serialized_config, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        self.assertEqual(result["config_sha256"], expected)

    def test_manifest_projection_recomputes_the_canonical_identity(self) -> None:
        result = canonical()
        legacy = dict(result)
        legacy.pop("provision_identity_sha256")
        self.assertEqual(
            provision_identity(legacy)["provision_identity_sha256"],
            result["provision_identity_sha256"],
        )


class StateProvisionIdentityTests(unittest.TestCase):
    def write_config(
        self,
        root: Path,
        overrides: dict[str, str] | None = None,
        name: str = "canonical.json",
    ) -> tuple[Path, dict[str, object]]:
        values = {"run_dir": str(root / "runs")}
        values.update(overrides or {})
        result = canonical(values, root / "firedrill.conf")
        path = root / name
        atomic_json(path, result)
        return path, result

    def test_new_state_writes_both_configuration_digests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path, config = self.write_config(root)
            created = begin(config_path)
            state = json.loads(
                (Path(str(created["run_path"])) / "state.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                (
                    state["config_sha256"],
                    state["provision_identity_sha256"],
                ),
                (
                    config["config_sha256"],
                    config["provision_identity_sha256"],
                ),
            )

    def test_legacy_state_recomputes_manifest_identity_for_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path, original = self.write_config(root)
            created = begin(config_path)
            run_path = Path(str(created["run_path"]))

            state = json.loads((run_path / "state.json").read_text(encoding="utf-8"))
            state.pop("provision_identity_sha256")
            atomic_json(run_path / "state.json", state)
            manifest = json.loads(
                (run_path / "manifest.json").read_text(encoding="utf-8")
            )
            manifest["config"].pop("provision_identity_sha256")
            atomic_json(run_path / "manifest.json", manifest)

            resumed_path, changed = self.write_config(
                root,
                {
                    "snapshot_name": "post-provision-baseline",
                    "server_restart_order": "server-2,server-3,server-1",
                },
                "resumed.json",
            )
            resumed = begin(resumed_path)
            self.assertEqual(
                (
                    resumed["created"],
                    resumed["lab_id"],
                    original["provision_identity_sha256"]
                    == changed["provision_identity_sha256"],
                ),
                (False, created["lab_id"], True),
            )

    def test_new_state_allows_test_parameter_changes_on_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path, _ = self.write_config(root)
            created = begin(config_path)
            resumed_path, _ = self.write_config(
                root,
                {
                    "snapshot_name": "post-provision-baseline",
                    "server_restart_order": "server-2,server-3,server-1",
                },
                "resumed.json",
            )
            resumed = begin(resumed_path)
            self.assertEqual(
                (resumed["created"], resumed["lab_id"]),
                (False, created["lab_id"]),
            )

    def test_new_state_rejects_provisioning_drift_on_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path, _ = self.write_config(root)
            begin(config_path)
            drift_path, _ = self.write_config(
                root, {"template_vmid": "9001"}, "drift.json"
            )

            with self.assertRaisesRegex(StateError, "different configuration"):
                begin(drift_path)

    def test_legacy_state_manifest_recompute_rejects_provisioning_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path, _ = self.write_config(root)
            created = begin(config_path)
            run_path = Path(str(created["run_path"]))

            state = json.loads((run_path / "state.json").read_text(encoding="utf-8"))
            state.pop("provision_identity_sha256")
            atomic_json(run_path / "state.json", state)
            drift_path, _ = self.write_config(
                root, {"template_vmid": "9001"}, "drift.json"
            )

            with self.assertRaisesRegex(StateError, "different configuration"):
                begin(drift_path)


if __name__ == "__main__":
    unittest.main()
