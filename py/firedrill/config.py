"""Parse and validate the deliberately non-executable firedrill config format."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import NoReturn

GUESTS: tuple[tuple[str, str, int, int, int], ...] = (
    ("server-1", "server", 2, 4096, 20),
    ("server-2", "server", 2, 4096, 20),
    ("server-3", "server", 2, 4096, 20),
    ("agent-1", "agent", 2, 2048, 15),
    ("agent-2", "agent", 2, 2048, 15),
)

COMMON_REQUIRED = (
    "driver",
    "hypervisor_host",
    "expected_hypervisor_hostname",
    "vmid_base",
    "network_bridge",
    "ip_cidr",
    "gateway",
    "ip_offsets",
    "k3s_version",
    "snapshot_name",
    "run_dir",
    "guest_name_prefix",
    "server_restart_order",
    "guest_access_timeout_seconds",
    "node_ready_timeout_seconds",
    "k3s_install_timeout_seconds",
    "cluster_capture_timeout_seconds",
    "test_b_target_server",
    "test_b_data_dir",
    "test_b_deletion_allowlist",
    "test_b_systemd_unit",
    "test_b_systemd_dropin_dirs",
    "test_b_environment_file",
    "test_b_default_sources",
    "test_b_config_file",
    "test_b_config_dropin_dir",
    "test_b_helper_roots",
    "test_b_owned_override_name",
    "test_b_recovery_timeout_seconds",
)
DRIVER_REQUIRED = {
    "mock": (),
    "pve": (
        "pve_host",
        "pve_node",
        "pve_storage",
        "template_vmid",
        "ssh_user",
        "ssh_key_path",
        "firedrill_op_config_path",
        "guest_join_file",
        "k3s_join_credential_file",
        "k3s_api_port",
        "k3s_binary_artifact_path",
        "k3s_binary_sha256",
        "k3s_install_script_artifact_path",
        "k3s_install_script_sha256",
        "etcdctl_artifact_path",
        "etcdctl_sha256",
        "k3s_installed_binary_path",
        "k3s_kubeconfig_path",
        "k3s_agent_kubeconfig_path",
        "k3s_server_ca_path",
        "k3s_server_token_path",
        "k3s_server_service_env_path",
        "k3s_agent_service_env_path",
        "k3s_server_systemd_unit",
        "k3s_agent_systemd_unit",
        "k3s_etcd_endpoint",
        "k3s_etcd_ca_path",
        "k3s_etcd_client_cert_path",
        "k3s_etcd_client_key_path",
        "k3s_etcd_snapshot_dir",
        "test_a_journal_line_limit",
    ),
    "libvirt": (
        "libvirt_host",
        "libvirt_template",
        "libvirt_storage_pool",
        "ssh_user",
        "ssh_key_path",
    ),
}
KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
SNAPSHOT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
PLACEHOLDERS = {"", "changeme", "replace_me", "replace-me", "todo", "unset"}


class ConfigError(ValueError):
    """A fail-closed configuration error."""


def fail(message: str) -> NoReturn:
    raise ConfigError(message)


def parse_config(path: Path) -> dict[str, str]:
    if not path.is_file():
        fail(f"configuration file not found: {path}; copy firedrill.conf.example first")
    values: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            fail(f"{path}:{line_number}: expected a lowercase key=value assignment")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not KEY_RE.fullmatch(key):
            fail(f"{path}:{line_number}: invalid configuration key {key!r}")
        if key in values:
            fail(f"{path}:{line_number}: duplicate configuration key {key!r}")
        if value[:1] in {'"', "'"} or value[-1:] in {'"', "'"}:
            fail(
                f"{path}:{line_number}: values are literal and must not be shell-quoted: {key}"
            )
        values[key] = value
    return values


def require(values: dict[str, str], key: str, purpose: str) -> str:
    if key not in values:
        fail(f"required variable {key} is unset; it is used for {purpose}")
    value = values[key].strip()
    if value.casefold() in PLACEHOLDERS or "<" in value or ">" in value:
        fail(f"required variable {key} is a placeholder; it is used for {purpose}")
    return value


def integer(value: str, key: str, minimum: int = 0) -> int:
    try:
        result = int(value, 10)
    except ValueError as error:
        raise ConfigError(f"{key} must be a base-10 integer, observed {value!r}") from error
    if result < minimum:
        fail(f"{key} must be at least {minimum}, observed {result}")
    return result


def exact_guest_path(value: str, key: str) -> str:
    """Require one literal, normalized absolute POSIX path with no pattern syntax."""
    if not value.startswith("/"):
        fail(f"{key} must be an absolute guest path")
    if any(character in value for character in "*?[]{}"):
        fail(f"{key} must not contain glob or pattern syntax")
    if not re.fullmatch(r"/[A-Za-z0-9._/-]+", value):
        fail(f"{key} contains unsupported guest-path characters")
    components = value.split("/")[1:]
    if not components or any(component in {"", ".", ".."} for component in components):
        fail(f"{key} must not contain empty, current, or parent path components")
    if str(PurePosixPath(value)) != value:
        fail(f"{key} must be a normalized absolute guest path")
    return value


def exact_guest_paths(value: str, key: str) -> list[str]:
    paths = [item.strip() for item in value.split(",")]
    if not paths or any(not item for item in paths):
        fail(f"{key} must contain one or more comma-separated absolute paths")
    result = [exact_guest_path(item, key) for item in paths]
    if len(set(result)) != len(result):
        fail(f"{key} must not contain duplicate paths")
    return result


def provision_identity(canonical: dict[str, object]) -> dict[str, object]:
    """Project canonical config onto the fields that define a provisioned lab."""
    values = canonical.get("values")
    if not isinstance(values, dict):
        fail("canonical configuration values must be a mapping")

    value_keys = (
        "driver",
        "pve_host",
        "pve_node",
        "pve_storage",
        "template_vmid",
        "pve_clone_mode",
        "pve_net_model",
        "pve_net_device",
        "pve_ipconfig_device",
        "pve_os_disk",
        "pve_guest_agent",
        "pve_cloud_init_user",
        "pve_cloud_init_sshkeys_path",
        "expected_hypervisor_hostname",
        "hypervisor_host",
        "network_bridge",
        "gateway",
        "guest_ssh_user",
        "guest_privilege_mode",
        "pve_privilege_mode",
        "ssh_user",
        "k3s_binary_artifact_path",
        "k3s_binary_sha256",
        "k3s_install_script_artifact_path",
        "k3s_install_script_sha256",
        "etcdctl_artifact_path",
        "etcdctl_sha256",
        "k3s_installed_binary_path",
        "k3s_kubeconfig_path",
        "k3s_agent_kubeconfig_path",
        "k3s_server_token_path",
        "k3s_server_service_env_path",
        "k3s_agent_service_env_path",
        "k3s_server_systemd_unit",
        "k3s_agent_systemd_unit",
        "k3s_etcd_snapshot_dir",
        "firedrill_op_config_path",
        "guest_join_file",
        "k3s_version",
    )
    # Seat-local config, denylist, run, SSH, and join-source paths do not bind a lab.
    # Every *_timeout_seconds value is an operator wait parameter, not provisioned identity.
    # snapshot_name, values.server_restart_order, and top-level restart_order are test parameters.
    # Every test_a_* value is a Test A execution parameter and is intentionally excluded.
    # The top-level test_b section and every test_b_* value are intentionally excluded.
    result: dict[str, object] = {
        "schema_version": canonical["schema_version"],
        "allowed_id_min": canonical["allowed_id_min"],
        "allowed_id_max": canonical["allowed_id_max"],
        "inventory": canonical["inventory"],
        "values": {key: values[key] for key in value_keys if key in values},
    }
    serialized = json.dumps(result, sort_keys=True, separators=(",", ":"))
    result["provision_identity_sha256"] = hashlib.sha256(serialized.encode()).hexdigest()
    return result


def validate(values: dict[str, str], config_path: Path) -> dict[str, object]:
    purposes = {
        "driver": "selecting the isolated hypervisor implementation",
        "hypervisor_host": "selecting the only hypervisor transport target",
        "expected_hypervisor_hostname": "the pre-mutation remote identity guard",
        "vmid_base": "the five-guest mutation allowlist",
        "network_bridge": "guest NIC attachment",
        "ip_cidr": "computing the disposable guest addresses",
        "gateway": "guest cloud-init routing",
        "ip_offsets": "assigning five unique guest addresses",
        "k3s_version": "pinning the rehearsed K3s release",
        "snapshot_name": "baseline snapshot creation and restore",
        "run_dir": "persistent state and review evidence",
        "guest_name_prefix": "the owned guest namespace",
        "server_restart_order": "the explicit rolling-restart order",
        "guest_access_timeout_seconds": "bounding initial SSH or mock guest access waits",
        "node_ready_timeout_seconds": "bounding K3s node-health waits",
        "k3s_install_timeout_seconds": "bounding each K3s installation command",
        "cluster_capture_timeout_seconds": "bounding each cluster-state observation",
        "test_b_target_server": "selecting exactly one disposable Test B server",
        "test_b_data_dir": "anchoring the reviewed Test B credential deletion allowlist",
        "test_b_deletion_allowlist": "the exact Test B credential deletion boundary",
        "test_b_systemd_unit": "enumerating the Test B systemd unit precedence surface",
        "test_b_systemd_dropin_dirs": "enumerating every configured systemd drop-in directory",
        "test_b_environment_file": "enumerating the K3s systemd environment source",
        "test_b_default_sources": "enumerating the K3s default and sysconfig sources",
        "test_b_config_file": "enumerating the main K3s configuration source",
        "test_b_config_dropin_dir": "enumerating the K3s config.yaml.d source",
        "test_b_helper_roots": "enumerating configured helper and rejoin script roots",
        "test_b_owned_override_name": "naming the harness-owned stale-token override",
        "test_b_recovery_timeout_seconds": "bounding Test B stop-to-all-Ready recovery",
    }
    for key in COMMON_REQUIRED:
        require(values, key, purposes[key])

    driver = values["driver"]
    if driver not in DRIVER_REQUIRED:
        fail(f"driver must be one of mock, pve, libvirt; observed {driver!r}")
    for key in DRIVER_REQUIRED[driver]:
        require(values, key, f"the selected {driver} driver")

    if driver != "mock" and values["hypervisor_host"].endswith(".invalid"):
        fail("hypervisor_host uses the documentation-only .invalid domain")
    if driver == "pve":
        if values["pve_host"] != values["hypervisor_host"]:
            fail("pve_host must exactly match hypervisor_host")
        if values["pve_node"] != values["expected_hypervisor_hostname"]:
            fail("pve_node must exactly match expected_hypervisor_hostname")
        for key in (
            "firedrill_op_config_path",
            "guest_join_file",
            "k3s_binary_artifact_path",
            "k3s_install_script_artifact_path",
            "etcdctl_artifact_path",
            "k3s_installed_binary_path",
            "k3s_kubeconfig_path",
            "k3s_agent_kubeconfig_path",
            "k3s_server_ca_path",
            "k3s_server_token_path",
            "k3s_server_service_env_path",
            "k3s_agent_service_env_path",
            "k3s_etcd_ca_path",
            "k3s_etcd_client_cert_path",
            "k3s_etcd_client_key_path",
            "k3s_etcd_snapshot_dir",
        ):
            exact_guest_path(values[key], key)
        for key in (
            "k3s_binary_sha256",
            "k3s_install_script_sha256",
            "etcdctl_sha256",
        ):
            if not re.fullmatch(r"[a-f0-9]{64}", values[key]):
                fail(f"{key} must be exactly 64 lowercase hexadecimal characters")
        api_port = integer(values["k3s_api_port"], "k3s_api_port", 1)
        if api_port > 65535:
            fail("k3s_api_port must be at most 65535")
        unit_pattern = r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}"
        if not re.fullmatch(unit_pattern, values["k3s_server_systemd_unit"]):
            fail("k3s_server_systemd_unit contains unsafe characters")
        if not re.fullmatch(unit_pattern, values["k3s_agent_systemd_unit"]):
            fail("k3s_agent_systemd_unit contains unsafe characters")
        if not re.fullmatch(r"https://127\.0\.0\.1:[0-9]+", values["k3s_etcd_endpoint"]):
            fail("k3s_etcd_endpoint must be one explicit HTTPS IPv4 loopback endpoint")
        integer(values["test_a_journal_line_limit"], "test_a_journal_line_limit", 1)
    if driver == "libvirt" and values["libvirt_host"] != values["hypervisor_host"]:
        fail("libvirt_host must exactly match hypervisor_host")

    base = integer(values["vmid_base"], "vmid_base", 1)
    if driver == "pve":
        template_vmid = integer(values["template_vmid"], "template_vmid", 1)
        if base <= template_vmid <= base + len(GUESTS) - 1:
            fail("template_vmid must be outside the five-guest VMID allocation window")
    prefix = values["guest_name_prefix"]
    if not NAME_RE.fullmatch(prefix):
        fail("guest_name_prefix must contain only lowercase letters, digits, and hyphens")
    if not SNAPSHOT_RE.fullmatch(values["snapshot_name"]):
        fail("snapshot_name contains unsafe characters")

    try:
        network = ipaddress.ip_network(values["ip_cidr"], strict=True)
        gateway = ipaddress.ip_address(values["gateway"])
    except ValueError as error:
        raise ConfigError(f"invalid ip_cidr or gateway: {error}") from error
    if gateway not in network or gateway in {network.network_address, network.broadcast_address}:
        fail("gateway must be a usable address inside ip_cidr")

    raw_offsets = [item.strip() for item in values["ip_offsets"].split(",")]
    if len(raw_offsets) != len(GUESTS):
        fail("ip_offsets must contain exactly five comma-separated offsets")
    offsets = [integer(item, "ip_offsets", 1) for item in raw_offsets]
    if len(set(offsets)) != len(offsets):
        fail("ip_offsets must contain five unique offsets")

    inventory: list[dict[str, object]] = []
    for index, ((short_name, role, vcpus, memory_mb, disk_gb), offset) in enumerate(
        zip(GUESTS, offsets, strict=True)
    ):
        try:
            address = network.network_address + offset
        except ValueError as error:
            raise ConfigError(f"ip offset {offset} is outside ip_cidr") from error
        reserved = {network.network_address, network.broadcast_address}
        if address not in network or address in reserved:
            fail(f"ip offset {offset} does not identify a usable address in ip_cidr")
        if address == gateway:
            fail(f"ip offset {offset} collides with gateway {gateway}")
        inventory.append(
            {
                "index": index,
                "id": base + index,
                "name": f"{prefix}-{short_name}",
                "short_name": short_name,
                "role": role,
                "vcpus": vcpus,
                "memory_mb": memory_mb,
                "disk_gb": disk_gb,
                "ip": str(address),
                "cidr": network.prefixlen,
            }
        )

    order = [item.strip() for item in values["server_restart_order"].split(",")]
    expected_order = {"server-1", "server-2", "server-3"}
    if len(order) != 3 or set(order) != expected_order:
        fail("server_restart_order must be an exact permutation of server-1,server-2,server-3")
    for key in (
        "guest_access_timeout_seconds",
        "node_ready_timeout_seconds",
        "k3s_install_timeout_seconds",
        "cluster_capture_timeout_seconds",
        "test_b_recovery_timeout_seconds",
    ):
        integer(values[key], key, 1)

    target_server = values["test_b_target_server"]
    if target_server not in {"server-1", "server-2", "server-3"}:
        fail("test_b_target_server must be exactly one of server-1,server-2,server-3")
    test_b_data_dir = exact_guest_path(values["test_b_data_dir"], "test_b_data_dir")
    deletion_allowlist = exact_guest_paths(
        values["test_b_deletion_allowlist"], "test_b_deletion_allowlist"
    )
    expected_deletions = [
        f"{test_b_data_dir}/server/cred/passwd",
        f"{test_b_data_dir}/server/token",
    ]
    if deletion_allowlist != expected_deletions:
        fail(
            "test_b_deletion_allowlist must contain exactly "
            "<test_b_data_dir>/server/cred/passwd,<test_b_data_dir>/server/token"
        )
    systemd_unit = exact_guest_path(values["test_b_systemd_unit"], "test_b_systemd_unit")
    dropin_dirs = exact_guest_paths(
        values["test_b_systemd_dropin_dirs"], "test_b_systemd_dropin_dirs"
    )
    environment_file = exact_guest_path(
        values["test_b_environment_file"], "test_b_environment_file"
    )
    default_sources = exact_guest_paths(
        values["test_b_default_sources"], "test_b_default_sources"
    )
    if len(default_sources) != 2:
        fail("test_b_default_sources must contain exactly /etc/default and /etc/sysconfig paths")
    config_file = exact_guest_path(values["test_b_config_file"], "test_b_config_file")
    config_dropin_dir = exact_guest_path(
        values["test_b_config_dropin_dir"], "test_b_config_dropin_dir"
    )
    helper_roots = exact_guest_paths(values["test_b_helper_roots"], "test_b_helper_roots")
    override_name = values["test_b_owned_override_name"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.conf", override_name):
        fail("test_b_owned_override_name must be one literal .conf basename")
    owned_override_path = f"{dropin_dirs[0]}/{override_name}"
    precedence_surfaces = [
        {"surface": "main-systemd-unit-execstart", "path": systemd_unit},
        *[
            {"surface": "systemd-drop-in-directory", "path": path}
            for path in dropin_dirs
        ],
        {"surface": "k3s-environment-file", "path": environment_file},
        *[
            {"surface": "default-or-sysconfig-source", "path": path}
            for path in default_sources
        ],
        {"surface": "main-k3s-config", "path": config_file},
        {"surface": "k3s-config-drop-in-directory", "path": config_dropin_dir},
        {"surface": "role-token-file", "path": expected_deletions[1]},
        *[
            {"surface": "helper-or-rejoin-root", "path": path}
            for path in helper_roots
        ],
    ]

    run_dir = Path(values["run_dir"]).expanduser()
    if not run_dir.is_absolute():
        run_dir = config_path.parent / run_dir
    run_dir = run_dir.resolve()
    denylist_path = config_path.parent / "firedrill.denylist"
    canonical_values = dict(values)
    canonical_values["run_dir"] = str(run_dir)
    if "ssh_key_path" in canonical_values:
        key_path = Path(canonical_values["ssh_key_path"]).expanduser()
        if not key_path.is_absolute():
            key_path = config_path.parent / key_path
        canonical_values["ssh_key_path"] = str(key_path.resolve())
    for key in (
        "ssh_known_hosts_path",
        "guest_ssh_key_path",
        "guest_ssh_known_hosts_path",
        "k3s_join_credential_file",
    ):
        if key not in canonical_values:
            continue
        local_path = Path(canonical_values[key]).expanduser()
        if not local_path.is_absolute():
            local_path = config_path.parent / local_path
        canonical_values[key] = str(local_path.resolve())

    result: dict[str, object] = {
        "schema_version": 1,
        "config_path": str(config_path.resolve()),
        "denylist_path": str(denylist_path.resolve()),
        "values": canonical_values,
        "inventory": inventory,
        "allowed_id_min": base,
        "allowed_id_max": base + len(GUESTS) - 1,
        "restart_order": order,
        "test_b": {
            "target_server": target_server,
            "data_dir": test_b_data_dir,
            "deletion_allowlist": deletion_allowlist,
            "owned_override_path": owned_override_path,
            "precedence_surfaces": precedence_surfaces,
            "recovery_timeout_seconds": integer(
                values["test_b_recovery_timeout_seconds"],
                "test_b_recovery_timeout_seconds",
                1,
            ),
        },
    }
    serialized = json.dumps(result, sort_keys=True, separators=(",", ":"))
    result["config_sha256"] = hashlib.sha256(serialized.encode()).hexdigest()
    result["provision_identity_sha256"] = provision_identity(result)[
        "provision_identity_sha256"
    ]
    return result


def get_path(data: object, dotted: str) -> object:
    current = data
    for component in dotted.split("."):
        if isinstance(current, dict):
            current = current[component]
        elif isinstance(current, list):
            current = current[int(component)]
        else:
            raise KeyError(dotted)
    return current


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--config", required=True, type=Path)
    validate_parser.add_argument("--output", required=True, type=Path)
    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("--canonical", required=True, type=Path)
    get_parser.add_argument("path")
    args = parser.parse_args()
    try:
        if args.command == "validate":
            result = validate(parse_config(args.config), args.config.resolve())
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            return 0
        data = json.loads(args.canonical.read_text(encoding="utf-8"))
        value = get_path(data, args.path)
        if isinstance(value, (dict, list)):
            print(json.dumps(value, separators=(",", ":")))
        elif isinstance(value, bool):
            print("true" if value else "false")
        else:
            print(value)
        return 0
    except (ConfigError, KeyError, OSError, json.JSONDecodeError) as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 65


if __name__ == "__main__":
    raise SystemExit(main())
