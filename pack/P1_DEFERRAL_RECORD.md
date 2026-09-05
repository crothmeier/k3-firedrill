# P1 — Dated, authored risk-acceptance: production rotation deferred

**Source:** Nexus (private records repo) `OPERATOR_DECISION_RECORD_2026-08-28_ROTATION_DEFERRAL_DRAFT.md`, committed `0cc503b` (2026-08-28, SSH-signed by the operator). Sections lifted: Decision; Binding conditions 1–3; Ratification.
**Authorship:** drafted by the operator's advising assistant for signature; ratified by operator ruling 2026-08-28; the signature is the operator's signed commit of the file. A later amendment (v1.1, 2026-08-30) exists but was never ratified and is not cited here.
**Redactions:** incident record identifiers and the "Basis" section (which narrates the original exposure) are omitted. Conditions 4–5 (containment housekeeping, unrelated de-hardcode work) are omitted. Nothing else is altered.

---

## Decision (verbatim)

> Production rotation of the exposed K3s server token remains **DEFERRED behind the P0.6 scratch rehearsal**, and is **not** executed inside the 2026-08-28 → 09-03 window despite the lapse of all frontier-model subscriptions on 09-03.

## Binding conditions 1–3 (verbatim)

| # | Condition |
|---|---|
| 1 | Rotation executes only after P0.6 PASS per runbook §0 — all boxes, no compression. |
| 2 | **Review boundary:** 2026-10-15, or P0.6 PASS, whichever first. At the boundary: either book the P0.8 window or re-ratify deferral with reasons in a v2 of this record. |
| 3 | **Escalation triggers unchanged** (incident record): any unknown node, CSR, RBAC change, or foreign 6443 source → reclassify to probable compromise, rebuild from known-good per `RUNBOOK_K3S_ETCD_DR_v1`, rotation question mooted. |

## Ratification (verbatim)

> - [x] RATIFIED — operator ruling, 2026-08-28 (Cowork session; signature completes with the operator's signed commit)
> - [ ] REJECTED — rotation to be scheduled in-window; reasons: ____________

---

## What this establishes for the reader

- The production credential the runbook rotates was **still unrotated** on 2026-08-28 by a written, dated, ratified decision, and remains so at the time of this pack (2026-09-05) — P0.6 is not yet PASS in full (test (c) has not run; see P7).
- "P0.6" is the rehearsal gate this pack documents: test (a) clean rotation (P3), test (b) failure injection and recovery (P4), test (c) quorum-loss recovery (not run, P7).
- The review boundary is 2026-10-15.
