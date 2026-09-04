# AGENTS.md — k3-firedrill standing rules for AI assistants

Audience: any AI assistant working in this repository — a dispatched offline
agent (Codex cloud), an interactive assistant with repo access (Claude,
GPT fat client on the operator's Linux seat), or a successor to either.
Authority: these rules restate operator doctrine ratified across dispatches
#1–#3 (2026-08-30) and standing session rulings. The operator may amend
them; an agent may not. Read `docs/PROJECT_STATE.md` before doing anything.

## What this project is

A fail-closed rehearsal harness for K3s failure drills (3-server
embedded-etcd + 2 agents) on disposable Proxmox guests. The point is the
discipline, not just the cluster: every mutation is guarded, every wait is
bounded, every failure exits distinctly, and evidence is recorded before
verdicts are drawn. Entry point `./firedrill`; gate `make test`
(shellcheck + ruff + Python unittests + negative probes).

## Universal rules — every agent, every mode

- Fail-closed is the product. An unimplemented real path never degrades
  into a mock success. Never weaken a guard to make something pass.
- Every guard ships with a negative probe proving it can fail. A guard
  compared against its own output is a defect.
- Raise objections and gaps as FINDINGS and stop; do not implement your
  own remedy without an operator ruling. Findings live in
  `docs/FINDING_*.md` (see F-2, F-5, F-8 for the format).
- Severability: deliver unblocked work items, report blocked ones as
  findings; a global stop is justified only if the first item is blocked.
- A ratification or status marker must REPLACE the instruction it
  satisfies, never sit beside it, and must carry a date.
- No secrets, raw tokens, real production hostnames, or private
  credentials anywhere in the tree or in evidence. Committed examples use
  RFC 5737 address space and `.invalid` names. Join tokens travel via
  root-owned mode-0600 files, never argv (one documented guest-side
  exception, D2, recorded in `docs/OPEN_QUESTIONS.md`).
- Frozen files: dispatch prompts carry a frozen list. The freeze binds
  agents, not the operator; unfreezing requires an explicit operator
  ruling recorded in a commit message (precedent: D1, `cf7214f`).
- Any change to the required-config set (`COMMON_REQUIRED` /
  `DRIVER_REQUIRED` in `py/firedrill/config.py`) MUST state a config
  migration note in its closeout: live `firedrill.conf` is gitignored and
  cannot receive new keys from a commit (finding F-5). `make config-check`
  reports the full gap.
- Never trace this harness with external `bash -x`, and never rely on
  `BASH_XTRACEFD` from the environment (finding F-8 notes). mktemp
  templates keep their `X` run trailing.

## Git and commit authority

- Agents do not commit or push. Commits are signed with a
  verify-required hardware credential held by the operator; print a
  commit block staging exact paths and stop.
- Never `git add -A`, `git add .`, or `git add -u`. Exact paths only.
- Read-only git (status, diff, log) is permitted for interactive
  assistants on the operator's seat; dispatched offline agents run no git
  at all and take repository state from plain file I/O.
- Work is UNCOMMITTED until the operator returns a hash and push output.
- Remote: `origin` = private-forge/k3-firedrill
  (single remote).

## Execution boundary

- Proposed commands are inert until the operator runs them. Distinguish
  read-only checks from mutations; never hide a mutation inside a
  validation block.
- Real-host mutations (lab-hv01, guests 7100–7104) happen only through
  the harness's guarded paths or by explicit operator hand-execution.
  `firedrill destroy --confirm` is the only sanctioned teardown.
- Dispatched offline agents: OFFLINE ONLY — no network, no SSH, no
  hypervisor tools; the PVE driver is exercised only through stubbed
  transport in unit tests. Open with a tooling probe (print every tool
  version the run will use); an unprobed tool needed mid-run is a
  finding, not a download. No subordinate agents, including read-only
  reconnaissance.

## Reporting standard for substantial work

State explicitly, three ways: which checks EXECUTED with exact output;
which could NOT be executed and why; and what remains UNPROVEN. Paste
gate output verbatim, never summarized. A file manifest with per-file
line counts accompanies any multi-file change. An acknowledgment without
pasted outputs is a failed run.

## 6. Stub and working-tree rules

**Stub-sample rule (in force 2026-09-02).** Any stub, mock, or fixture that models the behaviour, output shape, naming, or file surface of an external tool — PVE/`qm`, k3s, etcd/`etcdctl`, systemd, cloud-init, the guest OS — must carry, beside it in the same file, one **measured sample** from the real tool: the exact command, the host it ran on, the date, and the verbatim output or file content the stub reproduces (credentials redacted to prefix+digest per the evidence writer's convention). A stub without a sample is a defect, not a placeholder. Four stubs passed review with the modelled assumption wrong and were disproven on hardware on 2026-09-02: F-A03-1, F-TA-1, F-TA-4, F-TA-6. Each was cheap to measure and expensive to discover live.

**Working-tree rule.** Never run `./firedrill` against the lab while a Codex dispatch is in flight. Seat and lab share one working tree; a dispatch editing `lib/` under a live run corrupts both the run's evidence and the dispatch's diff.

## Key documents

- `docs/PROJECT_STATE.md` — current state, open queue, findings ledger.
- `docs/TEST_SPEC.md` — normative test contracts and pinned derivations.
- `docs/OPEN_QUESTIONS.md` — rulings and unresolved gaps; unresolved
  items are explicit and must not become silent defaults.
- `docs/GUEST_ARTIFACT_STAGING.md` — operator air-gap staging procedure.
- `docs/FINDING_*.md` — findings ledger entries.
- `docs/CODEX_PROMPT_*.md` — dispatch history; process rules originate in
  the 2026-08-30 PVE_DRIVER_AND_TESTB prompt and are inherited forward.
