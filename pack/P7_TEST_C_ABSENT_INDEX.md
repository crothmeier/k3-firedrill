# P7 — Index proving Test (c) has not run

The rehearsal gate (P1, condition 1: "P0.6 PASS per runbook §0 — all boxes") has three tests. Two have run. This file collects, verbatim and dated, every place the record says the third has not.

| Test | What it rehearses | Status | Evidence |
|---|---|---|---|
| (a) | clean rotation with ordered rolling restart | **PASS 2026-09-02** | P3, note 2 |
| (b) | one server restarted on the stale credential; Branch B recovery incl. the timestamp-trap delete | **PASS 2026-09-04** | P4 |
| (c) | quorum loss — two servers restarted on the stale credential; Branch C recovery, plus sub-cases C.3 / C.4 | **NOT RUN** | below |

---

## Statements of absence (verbatim, dated)

**`EXEC_LOG_2026-09-04_P06_TEST_B.md` §5 "What this sitting did not do"** (Nexus @ `48b4fb6`, 2026-09-04):

> - Production rotation: **not touched**; remains operator-executed from runbook v1.7 with a second reader.
> - Test (c) / C.3 / C.4 / C.5: **not run** (operator-fatigue rule: recorded (b) + clean shutdown is a complete sitting).
> - Harness-native Test B hooks: **not implemented**; this was the manual annex path by design.

**`EXEC_LOG_2026-09-04_P06_LAB_READONLY_CAPTURE.md` §5** (Nexus @ `dbc0d51`, 2026-09-04 evening):

> **Not done tonight (by design, R6):** test (c) / C.3 / C.4 / rollback-#7 dry-run; FGT deny-log read for tonight's C5 probes; any in-guest mutation; harness use; production anything.

**`docs/PROJECT_STATE.md` open queue** (k3-firedrill @ `11748cc`; this file is in the mirror):

> 0. **Test (c) NOT RUN.**

**Runbook header, v1.8** (`RUNBOOK_K3S_TOKEN_ROTATION_v1.md` @ `1f40250`, 2026-09-04):

> NOT execution-ready: P0.1, P0.6 test (c), P0.7, P0.8, and the P0.9 token-surface ruling remain open.

---

## The baseline the pack stands on (acceptance record)

`EXEC_LOG_2026-09-04_P06_LAB_READONLY_CAPTURE.md` §5.1 (Nexus @ `1497c8b`) records the operator's decision that the rehearsal snapshot `p06-baseline` — whose old credential reached a terminal transcript on 2026-09-04 (F-TB-1, P4 §4) — is **accepted without re-minting**: the exposure is lab-scoped, the lab is a routed segment isolated from production at the firewall policy layer (re-measured from a guest on 2026-09-04, Block C5: 100 % loss to two production addresses), and re-minting would orphan every cross-reference to the key name `0a6c128f5dad` used throughout P3–P5. Reversal triggers are recorded there. Two bracketed fields (transcript diff date, `rm` date) were still open when this pack was cut.

---

## What "not run" means for the claims in this pack

- Nothing in P3–P5 depends on test (c). The clean rotation and the single-node failure-injection are complete, independently re-measured sittings.
- No claim of a rehearsed **quorum-loss recovery** is made anywhere in this pack or in the mirror's README. Branch C of the runbook is source-pinned but not hardware-exercised.
- Production rotation therefore remains deferred (P1). Test (c) is scheduled as its own sitting after this pack; its result will be a separate dated log.
