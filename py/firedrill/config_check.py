"""Report every missing or placeholder required key in one pass (finding F-5).

Unlike ``config.py validate``, which fails closed on the first defect, this
tool compares a live config against the authoritative required set and prints
the complete gap so a drifted deployment sees one report instead of N
sequential exit-65 preflights. It is read-only and performs no value
validation beyond presence and placeholder detection; ``validate`` remains
the only authority on whether a config is actually usable.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import (
    COMMON_REQUIRED,
    DRIVER_REQUIRED,
    PLACEHOLDERS,
    ConfigError,
    parse_config,
    validate,
)


def check(config_path: Path, example_path: Path | None) -> int:
    values = parse_config(config_path)
    example = parse_config(example_path) if example_path and example_path.is_file() else {}

    driver = values.get("driver", "")
    if driver not in DRIVER_REQUIRED:
        print(f"driver must be one of mock, pve, libvirt; observed {driver!r}", file=sys.stderr)
        return 65
    required = list(COMMON_REQUIRED) + list(DRIVER_REQUIRED[driver])

    missing = [key for key in required if key not in values]
    placeholder = [
        key
        for key in required
        if key in values
        and (
            values[key].strip().casefold() in PLACEHOLDERS
            or "<" in values[key]
            or ">" in values[key]
        )
    ]

    print(f"config:   {config_path} ({len(values)} keys)")
    print(f"driver:   {driver} ({len(required)} required keys)")
    if not missing and not placeholder:
        print("result:   COMPLETE - every required key is present and non-placeholder")
        try:
            canonical = validate(values, config_path.resolve())
        except ConfigError as error:
            print(f"config_sha256: unavailable ({error})")
            print(f"provision_identity_sha256: unavailable ({error})")
        else:
            print(f"config_sha256: {canonical['config_sha256']}")
            print(
                "provision_identity_sha256: "
                f"{canonical['provision_identity_sha256']}"
            )
        print("note:     run config.py validate for full value validation")
        return 0

    if missing:
        print(f"\nMISSING required keys ({len(missing)}):")
        for key in missing:
            hint = example.get(key, "")
            suffix = f"  example={hint}" if hint else "  (no example value)"
            print(f"  {key}{suffix}")
    if placeholder:
        print(f"\nPLACEHOLDER required keys ({len(placeholder)}):")
        for key in placeholder:
            print(f"  {key}={values[key]}")
    print("\nresult:   INCOMPLETE - fill the keys above, then run config.py validate")
    return 65


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="firedrill.conf", type=Path)
    parser.add_argument("--example", default="firedrill.conf.example", type=Path)
    args = parser.parse_args()
    try:
        return check(args.config, args.example)
    except (ConfigError, OSError) as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 65


if __name__ == "__main__":
    raise SystemExit(main())
