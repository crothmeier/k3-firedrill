# P8 — Four test doubles that modelled an external tool wrongly, disproven on hardware

Before the first hardware run the harness had passed its own offline suite (133 tests, 30 files under ShellCheck, at `f2a1f90`). Four of those tests encoded an assumption about an external tool — the hypervisor, k3s, etcd — that was wrong. Each was cheap to measure and expensive to discover live. They are listed as findings, with the file positions of the stub, the finding, and the measured sample that now sits beside the stub in the public mirror.

**Sources:**
- `docs/STUB_INVENTORY_2026-09-04.md` (k3-firedrill @ `11748cc`, produced in the `a905062` increment; **not** in the mirror — rows lifted here by hand, hypervisor hostname aliased `lab-hv01`).
- `docs/PROJECT_STATE.md` findings ledger (k3-firedrill @ `11748cc`; **in** the mirror).
- `docs/FINDING_FTBC1_ETCD_MEMBER_NAMES.md` (in the mirror).
- `tests/test_pve_driver.sh` measured-sample comments at lines 168, 203, 554, 851 (in the mirror; lines refer to the mirror at `e2e1187`, identical numbering to `11748cc`).
- `AGENTS.md` stub-sample rule (in the mirror).

---

## The four

### 1. F-A03-1 — the hypervisor does not refuse a disk-only rollback on a running guest; it stops the guest itself

| | |
|---|---|
| Stub | `lib/drivers/pve.sh:801-856` — rollback policy assumed a stopped guest was a precondition PVE would enforce; the harness had no stop/start beat around `qm rollback`. |
| Disproven | 2026-09-02, first harness rollback: PVE 9.2.5 accepted `qm rollback` on running guests, stopped each one, rolled the disk back, and left it stopped. |
| Ledger row (PROJECT_STATE, verbatim) | "F-A03-1 rollback path has no guest stop/start beat — CLOSED ON HARDWARE 2026-09-02 (`632336c`; A0.3 rerun 06:05:46–06:09:06Z, evidence rows 59–79 all exit 0: 5× graceful shutdown, 5× rollback, 5× start servers-then-agents, 1× SSH-gated capture; `PASS: baseline restored and cluster health verified`, EXIT=0 […])" |
| Sample beside the stub | `tests/test_pve_driver.sh:554` — exact recorded argv for five `qm rollback` calls, per-guest timestamps and exit codes, PVE task-log shape, post-run power state, and the observation line: "PVE 9.2.5 did not refuse the disk-only rollback on running guests. It stopped each guest itself, rolled the disk back, and left it stopped." |
| Fix | `632336c` — rollback now stops all five guests gracefully, rolls back, starts servers then agents, waits for SSH, captures. Proven across six rollbacks (P3, P5). |

### 2. F-TA-1 — `k3s token generate` does not produce a server token

| | |
|---|---|
| Stub | `lib/drivers/pve.sh:950-997` (and the fixture at `tests/test_pve_driver.sh:851-860`) — the proposal hook minted the new credential with `k3s token generate`, assumed to emit a full `K10<ca>::server:<secret>` string. |
| Disproven | 2026-09-02, read-only probe on server-1 before firing: `rc=0 len=23 k10_server_full=0 dots=1`; `k3s token --help` describes the output as a "bootstrap token" (kubeadm-style, 23 characters, one dot). The runbook's §1.5 already forbade it. |
| Ledger row (PROJECT_STATE, verbatim fragment) | "MEASURED on server-1: `k3s token generate` emits a 23-char kubeadm-style bootstrap token (`--help`: "Generate and print a bootstrap token"), not `K10<ca>::server:<secret>`; runbook §1.5 says so explicitly." |
| Sample beside the stub | `tests/test_pve_driver.sh:851` — reconstructed command, host, date, the four measured shape values, and the `--help` wording. |
| Fix | `1181b50` — the hook reads the current full token, preserves its CA hash and user part, and mints only a fresh 48-hex secret on the seat. Proven on hardware 07:01Z the same night (P3, note 1: "same CA prefix, different secret"). |

### 3. F-TA-4 — `server/token` is an output of the configured token source, not an input

| | |
|---|---|
| Stub | `lib/drivers/pve.sh:1127-1181`, `:1261-1280`, `:1341-1393`, `:1467-1492` (token-state fixtures at `tests/test_pve_driver.sh:203-261`, `:937-964`) — the harness modelled "write the new token into `/var/lib/rancher/k3s/server/token` and restart" as sufficient for a peer server. |
| Disproven | 2026-09-02 attempt 1 (P3, note 1): k3s regenerated `server/token` from `K3S_TOKEN=` in `k3s.service.env` at start (mtime 07:02:28Z, OLD content), and server-2 crash-looped on the runbook's two pinned strings. This is the mechanism of the prior production rotation outage, reproduced on the first real rotation. |
| Ledger row (PROJECT_STATE, verbatim fragment) | "Hardware measured that k3s regenerates `server/token` from `K3S_TOKEN=` in `k3s.service.env`; the stale env value caused the runbook-pinned crash sequence on server-2. The repair factors the existing fail-closed env editor once and uses it for servers and agents, then compares a guest-computed full-token digest with the expected digest after every server restart." |
| Sample beside the stub | `tests/test_pve_driver.sh:203` — two dated observations on server-2: the 2026-09-02 post-crash state (`server/token` mtime vs content digest, NRestarts=38, both journal lines verbatim) and the 2026-09-04 fresh-boot read (unit `EnvironmentFile=`, no `--token` in ExecStart, env-file size/mode/mtime, both allowlist files' size/mtime). |
| Fix | `4fda3de` — server path edits the env-file surface like the agent path already did, and gates each restart on `server/token` regenerating to the expected digest. Proven on attempts 3 and 4 (P3, note 2). Runbook v1.7 followed from the same evidence (P2, hunks 1–3). |

### 4. F-TA-6 / F-TBC-1 — embedded-etcd member names carry an 8-hex suffix

| | |
|---|---|
| Stub | `tests/test_pve_driver.sh:168-201` and the Test B/C fixtures (`tests/test_guest_firedrill_op.sh:217-248`, `tests/test_test_a.py:37-119`, `:334-467`) — the cluster-state fixtures hard-coded bare member names `server-1/2/3`, and all three evaluators compared observed names to that bare set. |
| Disproven | 2026-09-02 attempt 3 gate: real members are `server-1-d1dfa965`, `server-2-3ee0262b`, `server-3-9b17da5b`; the otherwise-clean rotation failed 6/7 on `three-healthy-etcd-members` alone. |
| Finding document (verbatim) | "The shared mock emits k3s-style embedded-etcd member names of the form `server-N-<8hex>`, stable per lab id, as required by the F-TA-6 dispatch. Before this repair, the Test B and Test C `three-healthy-etcd-members` evaluators still required the observed name set to equal the bare `EXPECTED_SERVERS` set. Their passing mock worlds therefore failed the full repository gate even though all three members were present and healthy." — `docs/FINDING_FTBC1_ETCD_MEMBER_NAMES.md` |
| Sample beside the stub | `tests/test_pve_driver.sh:168` — reconstructed `etcdctl member list` command, host, two dates, the three measured member names with `IS LEARNER false`, and the gate mapping accepted at `e4b9fbe`. |
| Fix | `e4b9fbe` — one evaluator in `py/firedrill/etcd_members.py`: exact three-member continuity against the baseline set, all healthy, one-to-one mapping accepting bare names or lowercase 8-hex suffixes; used by Test A, B, and C. Attempt 4 passed 7/7 with `unmapped_names=[]` (P3, note 2). |

---

## The rule that came out of it

`AGENTS.md` (in the mirror), in force 2026-09-02, verbatim:

> **Stub-sample rule (in force 2026-09-02).** Any stub, mock, or fixture that models the behaviour, output shape, naming, or file surface of an external tool — PVE/`qm`, k3s, etcd/`etcdctl`, systemd, cloud-init, the guest OS — must carry, beside it in the same file, one **measured sample** from the real tool: the exact command, the host it ran on, the date, and the verbatim output or file content the stub reproduces (credentials redacted to prefix+digest per the evidence writer's convention). A stub without a sample is a defect, not a placeholder. Four stubs passed review with the modelled assumption wrong and were disproven on hardware on 2026-09-02: F-A03-1, F-TA-1, F-TA-4, F-TA-6. Each was cheap to measure and expensive to discover live.

## Disclosed limits

- **Scope of the retroactive samples.** The stub inventory covers `lib/drivers/mock.sh`, `lib/drivers/pve.sh`, and every file under `tests/`: 96 rows. Exactly the four disproven assumptions above carry a measured sample today. The inventory's own closing note: "The four retroactive measured samples are deliberately limited to the four hardware-disproven assumptions named in the dispatch." The remaining external-tool rows are marked `NO-SAMPLE` (with the read-only command that would produce one) or `AMBIGUOUS` (harness interface carrying external semantics).
- **`py/firedrill/mock_model.py` was not inventoried.** The inventory's first row says so ("External semantics live in `py/firedrill/mock_model.py`, outside this file"); that module holds the mock lifecycle's model of PVE, k3s and etcd state and is scheduled for its own inventory pass. It is why no sentence in this pack or in the README claims the harness is a self-proving closed loop: the 2026-09-02 and 2026-09-04 results were re-measured by hand, independently of the harness (P5), and that hand measurement is what the claims rest on.
- Two later findings from the 2026-09-04 sitting (F-TB-1 two token forms, F-TB-3 self-armed timestamp trap) are hardware observations, not stub disproofs; their `NO-SAMPLE` rows in the inventory are out of scope for this list and are recorded in P4 and P2.
