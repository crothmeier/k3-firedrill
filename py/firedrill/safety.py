"""Fail-closed inventory and denylist checks."""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
from pathlib import Path


class SafetyError(RuntimeError):
    """A safety invariant was not satisfied."""


def normalize(value: str) -> str:
    candidate = value.strip().rstrip(".")
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return candidate.casefold()


def configured_targets(config: dict[str, object]) -> dict[str, str]:
    values = config["values"]
    assert isinstance(values, dict)
    targets: dict[str, str] = {}
    for key in (
        "hypervisor_host",
        "expected_hypervisor_hostname",
        "pve_host",
        "pve_node",
        "libvirt_host",
        "gateway",
    ):
        value = values.get(key)
        if isinstance(value, str) and value:
            targets[key] = value
    inventory = config["inventory"]
    assert isinstance(inventory, list)
    for guest in inventory:
        assert isinstance(guest, dict)
        targets[f"guest:{guest['short_name']}:ip"] = str(guest["ip"])
        targets[f"guest:{guest['short_name']}:name"] = str(guest["name"])
    return targets


def check_denylist(config: dict[str, object]) -> None:
    denylist_path = Path(str(config["denylist_path"]))
    if not denylist_path.exists():
        return
    entries: dict[str, int] = {}
    for line_number, raw in enumerate(denylist_path.read_text(encoding="utf-8").splitlines(), 1):
        entry = raw.split("#", 1)[0].strip()
        if entry:
            entries[normalize(entry)] = line_number
    for label, target in configured_targets(config).items():
        normalized = normalize(target)
        if normalized in entries:
            raise SafetyError(
                f"denylist refused {label}={target!r}; matched {denylist_path}:"
                f"{entries[normalized]}"
            )


def check_id(config: dict[str, object], guest_id: int) -> None:
    minimum = int(config["allowed_id_min"])
    maximum = int(config["allowed_id_max"])
    inventory = config["inventory"]
    assert isinstance(inventory, list)
    planned = {int(guest["id"]) for guest in inventory if isinstance(guest, dict)}
    if not minimum <= guest_id <= maximum:
        raise SafetyError(
            f"guest id {guest_id} is outside configured range {minimum}..{maximum}"
        )
    if guest_id not in planned:
        raise SafetyError(f"guest id {guest_id} is not in the exact planned inventory")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--canonical", required=True, type=Path)
    parser.add_argument("--check-id", type=int)
    parser.add_argument("--check-denylist", action="store_true")
    args = parser.parse_args()
    try:
        config = json.loads(args.canonical.read_text(encoding="utf-8"))
        if args.check_denylist:
            check_denylist(config)
        if args.check_id is not None:
            check_id(config, args.check_id)
        return 0
    except (SafetyError, OSError, json.JSONDecodeError) as error:
        print(f"SAFETY ABORT: {error}", file=sys.stderr)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
