# P3 — 2026-09-02: first-attempt failure signature, then the clean rotation

Two dated notes from one night. They are kept separate on purpose: attempt 1 (07:01Z) failed and reproduced the crash the runbook exists to prevent; attempt 4 (09:00Z) passed cleanly. Attempts 2 and 3 are cited by name only.

**Sources (Nexus, the private records repo):**
- `EXEC_LOG_2026-09-02_P06_TEST_A_FIRST_CONTACT.md` @ `4bdf43a` — §2 (invocation), §3 (lab state before rollback), §4 (F-TA-4), §5 (rollback).
- `EXEC_LOG_2026-09-02_P06_TEST_A_PASS.md` @ `91a1f84` — §1 (attempt 4 milestones), §2 (independent verification), §3 (rollback #5).

**Substitutions:** guest addresses → `198.51.100.N` (the mirror's map). Seat paths omitted. Nothing else edited; elisions are marked `[…]`.

**Setting (from both logs' headers):** rehearsal cluster of five VMs on one hypervisor — `server-1/2/3` (embedded etcd, control plane) and `agent-1/2`, k3s `v1.34.4+k3s1`. Operator-executed from a seat shell; every command output was pasted back before the next step. No production host, VM, or credential touched at any point.

---

## Note 1 — Attempt 1, 07:01–07:07Z: FAIL at BREAK, crash mechanism reproduced

### §2 Invocation and output (verbatim)

> ```
> script -q ~/testa_20260902T030124.log ./firedrill test-a; echo "EXIT=$?"
> ```
> Verbatim, 3554 B:
>
> - `PASS: full server-token format asserted before mutation` ×2 (old and proposed).
> - **SETUP** (35.6 s, `sequence 86`, PASS): `provision-identity-and-inventory` PASS (`provision_identity_match=true, inventory_match=true`) · `cluster-matches-baseline` PASS · `all-baseline-snapshots-present` PASS · token-format assertion with references `old prefix=K10744d6 sha256=18aec9fc…` / `new prefix=K10744d6 sha256=53e38bb7…` (**same CA prefix, different secret — §1.5 construction confirmed on hardware**) · three k3s etcd snapshots labelled by the old token reference (`server-1` 07:01:59Z, `server-2` 07:02:04Z, `server-3` 07:02:10Z; sha256s recorded).
> - **BREAK**: `server-token-rotated` at 07:02:14–07:02:21Z on server-1 (`sequence 87`), `bootstrap_keys: ["/bootstrap/bd77ff8013c8"]` — **exactly one key, the new one; `/bootstrap/0a6c128f5dad` was replaced, not added to.** `configured_server_restart_order: ["server-2","server-3","server-1"]`.
> - Then nothing. `EXIT=1`. No restart event, no BREAK phase record, no gate, no `pve Test A guard:` line, no `firedrill: command failed` line. Log mtime 03:02 EDT → the process ended within ~40 s of the rotation.
>
> Evidence ledger: rows 80–87 written (capture, prerequisites, format assertion, 3× snapshot-pair, SETUP phase, token-rotate). **No row 88.**

### §3 Lab state measured before rollback (07:05–07:07Z, read-only) (verbatim)

> | Node | k3s | Detail |
> |---|---|---|
> | server-1 (.10) | `active`, NRestarts=0 | `server/token` mtime 07:02:15Z, content NEW (`f2f38d8e…`); journal: repeated `Failed to retrieve HTTP bootstrap data from datastore; falling back to disk for 198.51.100.11:… etcdserver: key not found` — server-2 asking with the old key |
> | server-2 (.11) | **`activating`, NRestarts=38, NotReady, etcd endpoint refused** | `server/token` mtime 07:02:28Z but content OLD (`0b0ff4b8…`, identical to untouched server-3); `k3s.service.env` unchanged since 08-30, exactly one `K3S_TOKEN=` line; no `/etc/rancher/k3s/config.yaml.d`; `ExecStart` sources that env file |
> | server-3 (.12) | `active`, NRestarts=0 | untouched: token file mtime = boot (06:08:54Z), content OLD |
> | agents | Ready | untouched |
> | etcd | **2/3** (quorate) | .11 `connection refused` |
> | `/bootstrap` | one key `bd77ff8013c8` | |
>
> server-2 journal, verbatim, no token values:
> ```
> 07:02:29Z level=error msg="Shutdown request received: failed to save bootstrap data: bootstrap data already found and encrypted with different token"
> 07:02:34Z level=fatal msg="/var/lib/rancher/k3s/server/cred/passwd newer than datastore and could cause a cluster outage. Remove the file(s) from disk and restart to be recreated from datastore."
>    … the same fatal every ~5 s thereafter (38 restarts by 07:06Z)
> ```
> Both lines are source-pinned register strings in runbook v1.6 (§4 crash signature; §5/Test B `newer than datastore` trap). Journals for all three servers preserved on the seat […] (803/727/449 lines; local only, never committed).

### §4 Finding F-TA-4 (verbatim)

> **F-TA-4 — server credential written to the wrong surface (procedure/hook defect, hardware-proven).** `pve_test_a_write_node_credential` handles servers by rewriting `/var/lib/rancher/k3s/server/token`. On this install (`install.sh` with `K3S_TOKEN=…`), the server's runtime token is `K3S_TOKEN=` in `/etc/systemd/system/k3s.service.env`; k3s regenerates `server/token` from it at startup — which is exactly what the 07:02:28Z mtime with old content shows. The agent path edits the env file's `K3S_TOKEN=` and is correct; the server path must do the same (or a `config.yaml.d` drop-in per runbook §1.6, but that leaves two surfaces disagreeing — the env edit is the consistent choice). Consequence: server-2 restarted with the stale token → `encrypted with different token` → `cred/passwd newer than datastore` crash loop. **This is the SEV-2 mechanism, reproduced on the first real rotation, with the exact strings the runbook pinned from source.** It is also Test B's BREAK state, reached from Test A.

### §5 Rollback from wreckage (verbatim)

> `script -q ~/rb2_*.log ./firedrill rollback` at `f2a1f90`: five `pve-stop-mode=graceful-shutdown` (server-2's crash-looping unit stopped cleanly under ACPI), five rollbacks, servers-then-agents start, `pve wait: attempt 1/120` SSH gate, `PASS: baseline restored and cluster health verified`, EXIT=0. Independent re-verification (07:21:18Z, uptime 9 min, `StrictHostKeyChecking=yes`): 5/5 `Ready`, k3s `active` on all three servers, etcd 3/3 (7–11 ms), **WS-1 `/bootstrap/0a6c128f5dad` restored** (the rotated key `bd77ff8013c8` is gone — the datastore era was rolled back, not only the disks), **WS-2 `744d6a1e…2798` unchanged**, server token digest `0b0ff4b8d018` identical on servers 1/2/3 (the pre-rotation token). **Rollback from wreckage: MEASURED PASS.**

**Reading note.** The harness executed the runbook's v1.6 assumption faithfully and reproduced the failure; it did not "fail closed" against a wrong procedure. The two register strings appeared in the runbook's predicted order. The other two servers stayed `active` with etcd 2/3 quorate; the API was not separately probed during this attempt's crash window (that observation was made deliberately on 2026-09-04 — see P4b).

---

## Note 2 — Attempt 4, 09:00:21–09:02:29Z: clean rotation with ordered rolling restart, 7/7

Between the two notes: harness fix `4fda3de` (write the env-file surface, add the regeneration check), attempt 2 (07:47Z, stopped before rotation by a ledger-archival defect, F-TA-5), attempt 3 (08:16Z, rotation and all five restarts clean and independently verified; harness gate 6/7 because the etcd member-name evaluator compared suffixed names to bare names, F-TA-6). Each attempt was followed by a rollback to `p06-baseline`.

### §1 Attempt 4 — verbatim milestones

> - `test-a: archived prior attempt evidence to evidence/test-a.attempts/20260902T081649Z/` (attempt 3 preserved; attempt 1 already at `…T070135Z/`)
> - SETUP PASS 35.8 s (`sequence 183`): `provision-identity-and-inventory` PASS · `cluster-matches-baseline` PASS · `all-baseline-snapshots-present` PASS · references `old prefix=K10744d6 sha256=18aec9fc…` / `new prefix=K10744d6 sha256=dd4330ca…` · three token-labelled etcd snapshots 09:00:44–09:00:55Z.
> - `server-token-rotated`: `bootstrap_keys: ["/bootstrap/36e19983d14e"]`, order `["server-2","server-3","server-1"]`.
> - BREAK PASS 84.3 s (`sequence 190`): `server-2` 10 s · `server-3` 12 s · **`server-1` 10 s (hold-out, last)** · `agent-1` 5 s · `agent-2` 6 s — all `healthy`, bound 300 s.
> - GATE PASS 7.7 s (`sequence 193`): all seven checks PASS, including `three-healthy-etcd-members` with `mapping=['server-1←server-1-d1dfa965','server-2←server-2-3ee0262b','server-3←server-3-9b17da5b'], unmapped_names=[]`.
> - `PASS: Test A clean server-token rotation satisfied every evidence gate` · **EXIT=0**.

### §2 Independent verification (post-run, pre-rollback) (verbatim)

> 5/5 Ready · etcd endpoint health 3/3 (9.9–13.7 ms) · `/bootstrap` exactly one key `36e19983d14e` · CA `744d6a1e6e8cdd1f…` unchanged · **server token digest `e7402d1eb20f` identical on servers 1/2/3** · `different token` journal lines since 09:00Z: **0, 0, 0, 0, 0** · two archived attempts on the seat, live ledger belongs to attempt 4.

### §3 Rollback #5 (verbatim)

> `rb5` at `e4b9fbe` (~05:15 EDT): five graceful stops, five rollbacks, servers-then-agents, SSH gate, `PASS: baseline restored and cluster health verified`, EXIT=0. Verified: `/bootstrap/0a6c128f5dad`, 5/5 Ready, server token digest `0b0ff4b8d018`. **Lab at `p06-baseline` at close of sitting. Five harness rollbacks tonight, five PASS, each independently verified.**

**Reading note.** "Ordered rolling restart" means: the server that ran `k3s token rotate` (`server-1`) was restarted last, after the two peers had each come back healthy on the new token. The night produced two clean end-to-end rotations (attempts 3 and 4); the second is the one the harness gate certified 7/7.
