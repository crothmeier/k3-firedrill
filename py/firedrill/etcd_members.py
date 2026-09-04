"""Shared embedded-etcd member continuity gate."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class EtcdMemberEvaluation:
    """Evidence-ready result for the shared three-member gate check."""

    passed: bool
    expected: str
    observed: str
    coverage: tuple[str, ...]


def _mapping_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _member_mapping(
    member_names: list[str], expected_servers: tuple[str, ...]
) -> tuple[dict[str, str], list[str]]:
    mapping: dict[str, str] = {}
    unmapped_names: list[str] = []
    for name in member_names:
        matching_servers = [
            server
            for server in expected_servers
            if name == server
            or (
                name.startswith(f"{server}-")
                and re.fullmatch(r"[0-9a-f]{8}", name.removeprefix(f"{server}-"))
            )
        ]
        if len(matching_servers) != 1 or matching_servers[0] in mapping:
            unmapped_names.append(name)
            continue
        mapping[matching_servers[0]] = name
    return mapping, unmapped_names


def evaluate_three_healthy_etcd_members(
    baseline: Mapping[str, object],
    observation: Mapping[str, object],
    expected_servers: tuple[str, ...],
    observation_coverage: str,
) -> EtcdMemberEvaluation:
    """Require exact baseline continuity and one healthy member per server."""
    raw_baseline_members = baseline.get("etcd_members")
    baseline_members = _mapping_list(raw_baseline_members)
    baseline_names = [
        name
        for member in baseline_members
        if isinstance((name := member.get("name")), str)
    ]
    raw_members = observation.get("etcd_members")
    members = _mapping_list(raw_members)
    member_names = [
        name for member in members if isinstance((name := member.get("name")), str)
    ]
    healthy_names = sorted(
        name
        for member in members
        if member.get("healthy") is True
        and isinstance((name := member.get("name")), str)
    )
    member_mapping, unmapped_names = _member_mapping(member_names, expected_servers)
    mapping_observation = [
        f"{server}\u2190{member_mapping[server]}"
        for server in expected_servers
        if server in member_mapping
    ]
    passed = (
        len(expected_servers) == 3
        and len(set(expected_servers)) == 3
        and isinstance(raw_baseline_members, list)
        and len(raw_baseline_members) == 3
        and len(baseline_members) == 3
        and len(baseline_names) == 3
        and len(set(baseline_names)) == 3
        and isinstance(raw_members, list)
        and len(raw_members) == 3
        and len(members) == 3
        and len(member_names) == 3
        and len(set(member_names)) == 3
        and set(member_names) == set(baseline_names)
        and len(healthy_names) == 3
        and not unmapped_names
        and set(member_mapping) == set(expected_servers)
    )
    return EtcdMemberEvaluation(
        passed=passed,
        expected="the exact three baselined etcd members, one per server, all healthy",
        observed=(
            f"baseline_names={sorted(baseline_names)!r}, "
            f"healthy_count={len(healthy_names)}, mapping={mapping_observation!r}, "
            f"unmapped_names={unmapped_names!r}"
        ),
        coverage=(
            "baseline/cluster-state.json#/etcd_members",
            observation_coverage,
        ),
    )
