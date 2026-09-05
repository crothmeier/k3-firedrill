# k3-firedrill

I built this harness to rehearse one specific production change before I made it: rotating the shared server token on a three-server, embedded-etcd k3s cluster. A previous rotation on that cluster had caused an outage, and I had written a runbook to prevent a repeat. I did not trust the runbook until it had been executed against something disposable. This repository is the disposable thing, and the record of what happened when I did.

## What it rehearses, and why

A k3s server keeps working on its old token in memory indefinitely. The crash only comes at restart: if a server starts with a token that no longer matches what etcd was re-encrypted with, it refuses to come up — `bootstrap data already found and encrypted with different token` — and then, on every retry, refuses for a second reason: two files on its disk are now newer than the datastore's record of them, and k3s will not overwrite them (`newer than datastore and could cause a cluster outage`). Fixing the token source does not clear the second condition. Only deleting those two files does. That two-stage trap is what the runbook had to get right, and what the harness exists to reproduce on purpose.

The lab is five VMs on one hypervisor host: three servers (embedded etcd) and two agents, restored to a snapshot baseline between attempts. It rehearses the procedure and the tooling. It does not rehearse the production topology — one host, one kernel, one storage pool — so nothing here is evidence of high availability.

## What happened

On 2026-09-02 the first hardware run executed my runbook's assumptions as then written and reproduced the outage the runbook exists to prevent: the harness wrote the new token into the file k3s regenerates at start, one server came back on the stale credential, and both register strings appeared in the predicted order while the other two servers kept quorum. I revised the runbook that day. Later the same night the clean rotation passed with an ordered rolling restart — the server that ran the rotate command restarted last — and every gate was re-measured by hand. On 2026-09-04 I planted a stale token on one server deliberately, watched it crash-loop while the other two held quorum and the API kept answering from the surviving server I was measuring from, confirmed that fixing the token source alone left five consecutive refusals, deleted exactly the two files, and had the server back in service in 45 seconds. Six harness rollbacks restored the baseline six times, including once from a crash-looping control plane.

The production credential is still unrotated, under a dated, written deferral I authored. The clean-rotation and single-node failure-injection tests passed; the quorum-loss test is next. Nothing about this is complete.

## Architecture

`./firedrill` is the single entrypoint (strict mode, traps, stable exit codes: 65 config, 66 state, 67 snapshot, 69 driver/unimplemented, 70 health timeout, 71 blast radius, 78 safety). Lifecycle verbs — `preflight`, `provision`, `baseline`, `test-a`, `test-b`, `test-c`, `rollback`, `report`, `destroy` — call a **driver interface** (`lib/drivers/`): a `mock` driver backed by a state model for offline runs, and a `pve` driver that talks to the hypervisor and guests over one replaceable SSH transport. Every mutation passes **fail-closed guards** first: exact hypervisor identity, a denylist of forbidden targets, a five-VMID allocation window, and a per-guest ownership marker. Every command is written to an **evidence ledger** (`commands.jsonl` plus per-command stdout/stderr, phase records, and gate observations) through a redaction layer that replaces token values with prefix-plus-digest before anything touches disk. Real Test B/C hooks are deliberately unimplemented and exit 69; those sittings were run by hand from the runbook's annex, which is how they belong until the hooks are reviewed. The **transport-stub tests** (`tests/`, 141 offline tests plus shell lint over 30 files) exercise command construction, guards, redaction, and gate logic without a network.

## The design lesson

Four of those offline tests encoded a wrong assumption about an external tool, and all four passed review: the hypervisor's rollback semantics (it stops a running guest itself), what `k3s token generate` emits (a bootstrap token, not a server token), where k3s reads its server token from (`server/token` is an output, not an input), and how embedded-etcd members are named (with an 8-hex suffix). Each was cheap to measure and expensive to discover live. The rule that came out of it, now in `AGENTS.md`: any stub that models an external tool's behaviour carries one measured sample beside it — command, host, date, verbatim output. The four are documented in `pack/P8_DISPROVED_STUBS.md`; the samples sit next to the stubs in `tests/test_pve_driver.sh`.

## Numbers

5 nodes · 2 clean rotations on 2026-09-02 (the second harness-certified 7/7) · 1 deliberate failure injection and recovery on 2026-09-04 · 6 rollbacks, 6 passed · 141 offline tests · 9 findings from the 09-02 night, 4 more from 09-04, 20 finding IDs in `docs/PROJECT_STATE.md` overall · quorum-loss test: 0 runs.

## Reading the evidence

`pack/` holds the evidence pack: the deferral record, the runbook before and after as diff hunks, both sittings' logs, the five-node hand-remeasurement, the hypervisor inventory, the index of what has not run, and the four disproved stubs — each file headed with its source and commit. Start at `pack/PACK_INDEX.md`. `docs/PROJECT_STATE.md` is the harness's own state record; `docs/FINDING_*.md` are the standalone finding writeups.

This repository is a curated snapshot of the working repo at commit `11748cc`, scrubbed of lab identity (addresses replaced with RFC 5737 space, hostnames aliased; cut record in `.scrub/`). Beyond the planned file list it also carries `pyproject.toml`, `.gitignore`, and `firedrill.denylist.example`, because without them the test suite cannot run here. Dispatch prompts, seat-migration notes, and handoffs are not included.

---
*Harness increments were produced by an AI coding agent (Codex) to my specification, under my dispatch and acceptance review; I wrote the runbook it tested and the revisions to it.*
