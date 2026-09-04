"""Append ordered, timestamped, redacted command evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from firedrill.redact import redact_text, redact_value, registry_from_environment


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-path", required=True, type=Path)
    parser.add_argument("--sequence", required=True, type=int)
    parser.add_argument("--label", required=True)
    parser.add_argument("--node", required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--ended-at", required=True)
    parser.add_argument("--exit-code", required=True, type=int)
    parser.add_argument("--stdout", required=True, type=Path)
    parser.add_argument("--stderr", required=True, type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    evidence_dir = args.run_path / "evidence"
    command_dir = evidence_dir / "commands"
    command_dir.mkdir(parents=True, exist_ok=True)
    sequence = f"{args.sequence:06d}"
    registry = registry_from_environment()
    stdout = redact_text(
        args.stdout.read_text(encoding="utf-8", errors="replace"), registry
    )
    stderr = redact_text(
        args.stderr.read_text(encoding="utf-8", errors="replace"), registry
    )
    stdout_name = f"{sequence}.stdout.log"
    stderr_name = f"{sequence}.stderr.log"
    (command_dir / stdout_name).write_text(stdout, encoding="utf-8")
    (command_dir / stderr_name).write_text(stderr, encoding="utf-8")
    raw_record = {
        "schema_version": 1,
        "sequence": args.sequence,
        "label": args.label,
        "node": args.node,
        "started_at": args.started_at,
        "ended_at": args.ended_at,
        "exit_code": args.exit_code,
        "command": redact_value(args.command),
        "stdout_path": f"commands/{stdout_name}",
        "stderr_path": f"commands/{stderr_name}",
        "stdout": stdout,
        "stderr": stderr,
    }
    record = redact_value(raw_record, registry)
    if not isinstance(record, dict):
        raise TypeError("redacted evidence record is not a mapping")
    with (evidence_dir / "commands.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
