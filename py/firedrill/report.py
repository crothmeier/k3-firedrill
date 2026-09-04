"""Render the currently accumulated lifecycle and test evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def table_text(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-path", required=True, type=Path)
    args = parser.parse_args()
    state = json.loads((args.run_path / "state.json").read_text(encoding="utf-8"))
    baseline = state.get("baseline")
    lines = [
        "# K3s firedrill report",
        "",
        f"- Run: `{state['run_id']}`",
        f"- Driver: `{state['driver']}`",
        f"- K3s version: `{state['k3s_version']}`",
        f"- Lifecycle: `{state['lifecycle']}`",
        f"- Baseline captured: `{'yes' if baseline else 'no'}`",
        "",
        "## Failure-rehearsal results",
        "",
    ]
    tests = state.get("tests", {})
    test_a = tests.get("test-a") if isinstance(tests, dict) else None
    if not isinstance(test_a, dict):
        lines.extend(
            (
                "Test A has not been executed for this run.",
                "",
            )
        )
    else:
        lines.extend(
            (
                "| Test | Verdict | Started | Ended | Gate evidence |",
                "|---|---|---|---|---|",
                f"| A — clean rotation | **{test_a['verdict']}** | "
                f"`{test_a['started_at']}` | `{test_a['ended_at']}` | "
                f"`{test_a['gate_evidence_path']}` |",
                "",
                "### Test A phase timings",
                "",
                "| Phase | Verdict | Started | Ended | Duration (seconds) | Sequence |",
                "|---|---|---|---|---:|---:|",
            )
        )
        phase_path = args.run_path / str(test_a["phase_evidence_path"])
        phases = json.loads(phase_path.read_text(encoding="utf-8"))
        for phase in phases:
            lines.append(
                f"| `{phase['phase']}` | **{phase['verdict']}** | `{phase['started_at']}` | "
                f"`{phase['ended_at']}` | {phase['duration_seconds']:.3f} | "
                f"{phase['sequence']} |"
            )
        lines.extend(
            (
                "",
                "### Test A gate verdicts",
                "",
                "| Check | Verdict | Coverage set (file by file) | Expected | Observed |",
                "|---|---|---|---|---|",
            )
        )
        checks = test_a.get("checks", [])
        for check in checks:
            coverage = "<br>".join(f"`{item}`" for item in check["coverage"])
            lines.append(
                f"| `{check['check']}` | **{check['verdict']}** | {coverage} | "
                f"{table_text(check['expected'])} | {table_text(check['observed'])} |"
            )
        lines.extend(("", f"Overall Test A gate: **{test_a['verdict']}**", ""))

    test_b = tests.get("test-b") if isinstance(tests, dict) else None
    if not isinstance(test_b, dict):
        lines.extend(("Test B has not been executed for this run.", ""))
    else:
        details = test_b.get("details")
        detail_mapping = details if isinstance(details, dict) else {}
        recovery_path = args.run_path / "evidence" / "test-b" / "recovery.json"
        recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
        lines.extend(
            (
                "| Test | Verdict | Started | Ended | Gate evidence |",
                "|---|---|---|---|---|",
                f"| B — stale token in one systemd unit | **{test_b['verdict']}** | "
                f"`{test_b['started_at']}` | `{test_b['ended_at']}` | "
                f"`{test_b['gate_evidence_path']}` |",
                "",
                "### Test B break and recovery proof",
                "",
                "| Field | Evidence value |",
                "|---|---|",
                f"| Target server | `{table_text(detail_mapping.get('target_server'))}` |",
                "| Crash signature observed | "
                f"`{table_text(detail_mapping.get('crash_signature_observed'))}` |",
                f"| Bystanders | `{table_text(detail_mapping.get('bystander_servers'))}` |",
                "| Bystanders healthy | "
                f"`{table_text(detail_mapping.get('bystanders_healthy'))}` |",
                "| Quorum intact during BREAK | "
                f"`{table_text(detail_mapping.get('quorum_intact_during_break'))}` |",
                "| API served during BREAK | "
                f"`{table_text(detail_mapping.get('api_served_during_break'))}` |",
                "| Precedence entries enumerated | "
                f"`{table_text(detail_mapping.get('precedence_entries_enumerated'))}` |",
                "| Measured recovery duration (seconds) | "
                f"`{table_text(detail_mapping.get('recovery_duration_seconds'))}` |",
                "| Recovery timeout (seconds) | "
                f"`{table_text(detail_mapping.get('recovery_timeout_seconds'))}` |",
                "",
                "### Test B precedence enumeration",
                "",
                "| Surface | Path | Occurrences |",
                "|---|---|---:|",
            )
        )
        precedence = recovery.get("precedence_enumeration", [])
        for entry in precedence if isinstance(precedence, list) else []:
            if not isinstance(entry, dict):
                continue
            lines.append(
                f"| `{table_text(entry.get('surface'))}` | `{table_text(entry.get('path'))}` | "
                f"{table_text(entry.get('occurrence_count'))} |"
            )
        lines.extend(
            (
                "",
                "### Test B exact-path deletion records",
                "",
                "| Path | Before type | Owner | Mode | Mtime | Action | Exists after |",
                "|---|---|---|---|---|---|---|",
            )
        )
        deletions = recovery.get("deletion_records", [])
        for deletion in deletions if isinstance(deletions, list) else []:
            if not isinstance(deletion, dict):
                continue
            before = deletion.get("before")
            after = deletion.get("after")
            before_mapping = before if isinstance(before, dict) else {}
            after_mapping = after if isinstance(after, dict) else {}
            lines.append(
                f"| `{table_text(deletion.get('path'))}` | "
                f"`{table_text(before_mapping.get('type'))}` | "
                f"`{table_text(before_mapping.get('owner'))}` | "
                f"`{table_text(before_mapping.get('mode'))}` | "
                f"`{table_text(before_mapping.get('mtime'))}` | "
                f"`{table_text(deletion.get('action'))}` | "
                f"`{table_text(after_mapping.get('exists'))}` |"
            )
        lines.extend(
            (
                "",
                "### Test B phase timings",
                "",
                "| Phase | Verdict | Started | Ended | Duration (seconds) | Sequence |",
                "|---|---|---|---|---:|---:|",
            )
        )
        phase_path = args.run_path / str(test_b["phase_evidence_path"])
        phases = json.loads(phase_path.read_text(encoding="utf-8"))
        for phase in phases:
            lines.append(
                f"| `{phase['phase']}` | **{phase['verdict']}** | `{phase['started_at']}` | "
                f"`{phase['ended_at']}` | {phase['duration_seconds']:.3f} | "
                f"{phase['sequence']} |"
            )
        lines.extend(
            (
                "",
                "### Test B gate verdicts",
                "",
                "| Check | Verdict | Coverage set (file by file) | Expected | Observed |",
                "|---|---|---|---|---|",
            )
        )
        checks = test_b.get("checks", [])
        for check in checks:
            coverage = "<br>".join(f"`{item}`" for item in check["coverage"])
            lines.append(
                f"| `{check['check']}` | **{check['verdict']}** | {coverage} | "
                f"{table_text(check['expected'])} | {table_text(check['observed'])} |"
            )
        lines.extend(("", f"Overall Test B gate: **{test_b['verdict']}**", ""))

    test_c = tests.get("test-c") if isinstance(tests, dict) else None
    if not isinstance(test_c, dict):
        lines.extend(("Test C has not been executed for this run.", ""))
    else:
        details = test_c.get("details")
        detail_mapping = details if isinstance(details, dict) else {}
        lines.extend(
            (
                "| Test | Verdict | Started | Ended | Gate evidence |",
                "|---|---|---|---|---|",
                f"| C — quorum loss during the roll | **{test_c['verdict']}** | "
                f"`{test_c['started_at']}` | `{test_c['ended_at']}` | "
                f"`{test_c['gate_evidence_path']}` |",
                "",
                "### Test C structured triage and recovery",
                "",
                "| Field | Evidence value |",
                "|---|---|",
                f"| Triage branch | `{table_text(detail_mapping.get('triage_branch'))}` |",
                "| Discriminator method | "
                f"`{table_text(detail_mapping.get('discriminator_method'))}` |",
                f"| Source pin | `{table_text(detail_mapping.get('source_pin'))}` |",
                f"| Triage reason | {table_text(detail_mapping.get('triage_reason'))} |",
                "| Observed key names | "
                f"`{table_text(detail_mapping.get('observed_key_names'))}` |",
                "| Expected key names | "
                f"`{table_text(detail_mapping.get('expected_key_names'))}` |",
                "| Recovery form | "
                f"`{table_text(detail_mapping.get('recovery_form'))}` |",
                "| Selected redacted reference | "
                f"`{table_text(detail_mapping.get('selected_token_reference'))}` |",
                "| Cleanup required | "
                f"`{table_text(detail_mapping.get('cleanup_required'))}` |",
                "| Recovery attempted | "
                f"`{table_text(detail_mapping.get('recovery_attempted'))}` |",
                "",
                "### Test C phase timings",
                "",
                "| Phase | Verdict | Started | Ended | Duration (seconds) | Sequence |",
                "|---|---|---|---|---:|---:|",
            )
        )
        phase_path = args.run_path / str(test_c["phase_evidence_path"])
        phases = json.loads(phase_path.read_text(encoding="utf-8"))
        for phase in phases:
            lines.append(
                f"| `{phase['phase']}` | **{phase['verdict']}** | `{phase['started_at']}` | "
                f"`{phase['ended_at']}` | {phase['duration_seconds']:.3f} | "
                f"{phase['sequence']} |"
            )
        lines.extend(
            (
                "",
                "### Test C gate verdicts",
                "",
                "| Check | Verdict | Coverage set (file by file) | Expected | Observed |",
                "|---|---|---|---|---|",
            )
        )
        checks = test_c.get("checks", [])
        for check in checks:
            coverage = "<br>".join(f"`{item}`" for item in check["coverage"])
            lines.append(
                f"| `{check['check']}` | **{check['verdict']}** | {coverage} | "
                f"{table_text(check['expected'])} | {table_text(check['observed'])} |"
            )
        lines.extend(("", f"Overall Test C gate: **{test_c['verdict']}**", ""))

    lines.extend(
        (
            "`test-all` remains intentionally unimplemented and exits 69.",
            "",
            "A mock Test A PASS proves only the offline model, guards, evidence flow, and gate "
            "evaluation. It makes no claim about server-token rotation on real hardware.",
            "",
            "A mock Test B PASS proves only the offline stale-source model, exact-path guards, "
            "evidence flow, and gate evaluation. Its real-driver path remains unavailable.",
            "",
            "A mock Test C PASS proves only the offline observable contracts, frozen-policy "
            "wiring, redaction, and evidence-derived gates. It makes no claim about real "
            "snapshots, cluster reset, journals, quorum loss, or recovery on real hardware.",
            "",
        )
    )
    report_path = args.run_path / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
