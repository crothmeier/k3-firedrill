# Evidence pack — k3s server-token rotation rehearsal (2026-09-02 / 2026-09-04)

Assembled 2026-09-05 from committed, already-redacted execution logs and decision records. This pack exists so that a reader who was not in the room can check every sentence the project makes about its two hardware sittings. It is deliberately not a narrative; each file quotes its source verbatim under a provenance header, and says what the quoted evidence does *not* show.

**Assembly rule:** built from committed records only, never from terminal transcripts. The pack's assembler is not its reviewer; an independent adjudication follows and is filed separately.

## What the reader is checking

| Claim (as it appears on the project's summary page) | Where it is checkable | Limit stated in the pack |
|---|---|---|
| The production credential is unrotated under a dated, written, ratified deferral | P1 | Amendment v1.1 never ratified; not cited |
| On 2026-09-02 the runbook, executed as then written, reproduced the outage it exists to prevent; it was then revised | P3 note 1; P2 hunks 1–2 | The harness reproduced the *mechanism* and the runbook's two pinned strings; identity with any specific production incident is not claimed |
| Then a clean rotation passed with an ordered rolling restart | P3 note 2 | Two clean rotations that night (attempts 3, 4); the second is the harness-certified 7/7 |
| On 2026-09-04 a stale credential planted on one of three servers crash-looped that server while the other two held quorum | P4 b1, P4b | API-served observation from **one** surviving server; the third proven at the etcd layer + unit active; all inside one failure domain (P6) |
| Fixing the credential source alone was not enough | P4 b2 | five refusals on the correct token |
| Two specific on-disk files were newer than the datastore; deleting exactly those two recovered it in 45 seconds | P4 b3, §2, P4e | 45 s = `stop` at 11:21:58Z → `active` at 11:22:43Z, includes 35 s of operator steps; Ready ≤65 s is a polling bound |
| Every result was re-measured by hand, independently of the harness | P5 | Two passes; the second on a cold boot with the harness unused; evidence file sha256 pinned |
| Three control-plane VMs on one host | P6 | one host / kernel / storage pool measured; "one power domain" asserted; the open-questions file does not yet carry the line |
| Test (c) — quorum-loss recovery — has not run | P7 | rotation therefore not execution-ready |
| Four stubs modelled external tools wrongly and were disproven on hardware | P8 | samples exist beside exactly those four; `mock_model.py` not yet inventoried |

## Files

| # | File | Sources (repo · file · commit · section) | Substitutions applied |
|---|---|---|---|
| P1 | `P1_DEFERRAL_RECORD.md` | Nexus · `OPERATOR_DECISION_RECORD_2026-08-28_ROTATION_DEFERRAL_DRAFT.md` · `0cc503b` · Decision, conditions 1–3, Ratification | incident IDs → role; Basis section and conditions 4–5 omitted |
| P2 | `P2_RUNBOOK_BEFORE_AFTER.md` | Nexus · `RUNBOOK_K3S_TOKEN_ROTATION_v1.md` · `7cc7e99` → `a35f8a6` → `1f40250` · §1.6, §3, P0.9, §6 Branch B steps 2–3, §7 | production control-plane hostnames → `prod-cp-A/B/C`; incident IDs → role; one reviewer name → role; all marked ⟦ ⟧ |
| P3 | `P3_2026-09-02_SITTING_NOTES.md` | Nexus · `EXEC_LOG_2026-09-02_P06_TEST_A_FIRST_CONTACT.md` · `4bdf43a` · §2–§5; `EXEC_LOG_2026-09-02_P06_TEST_A_PASS.md` · `91a1f84` · §1–§3 | lab guest addresses → `198.51.100.N`; seat paths elided |
| P4 | `P4_2026-09-04_INJECTION_SITTING.md` | Nexus · `EXEC_LOG_2026-09-04_P06_TEST_B.md` · `48b4fb6` · §0.1, §1 b1–b3, §2, §4 (two rows) | none |
| P5 | `P5_FIVE_NODE_REMEASUREMENT.md` | Nexus · `EXEC_LOG_2026-09-04_P06_TEST_B.md` · `48b4fb6` · §1 b3 closure, §3; `EXEC_LOG_2026-09-04_P06_LAB_READONLY_CAPTURE.md` · `dbc0d51` · §2 Block B | none; evidence-file sha256 `40d6b4a1…35a2` reproduced in full (allowlisted) |
| P6 | `P6_HYPERVISOR_INVENTORY.md` | Nexus · `EXEC_LOG_2026-09-04_P06_LAB_READONLY_CAPTURE.md` · `dbc0d51` · §3 C1–C3, §1 A1; k3-firedrill · `docs/OPEN_QUESTIONS.md` · `11748cc` · "VIP and host-type gap" | hypervisor → `lab-hv01` / `203.0.113.40`, guests → `198.51.100.N`; NVMe model/serial, MACs, `sshkeys` dropped |
| P7 | `P7_TEST_C_ABSENT_INDEX.md` | Nexus · `EXEC_LOG_2026-09-04_P06_TEST_B.md` §5 · `48b4fb6`; `…_LAB_READONLY_CAPTURE.md` §5, §5.1 · `dbc0d51` / `1497c8b`; runbook header · `1f40250`; k3-firedrill · `docs/PROJECT_STATE.md` · `11748cc` | none |
| P8 | `P8_DISPROVED_STUBS.md` | k3-firedrill · `docs/STUB_INVENTORY_2026-09-04.md`, `docs/PROJECT_STATE.md`, `docs/FINDING_FTBC1_ETCD_MEMBER_NAMES.md`, `AGENTS.md` · `11748cc`; mirror `tests/test_pve_driver.sh` :168 :203 :554 :851 · `e2e1187` | hypervisor → `lab-hv01` in lifted inventory rows |

"Nexus" is the project's private records repository; its files are cited by name and commit so the owner can produce any of them on request. The public mirror (this repository) is k3-firedrill at `11748cc`, scrubbed; its cut record is in `.scrub/`.

## Substitution map (identical to the mirror's, plus two pack-only extensions)

| Original | In pack and mirror | Class |
|---|---|---|
| lab guest network (a private /24) | `198.51.100.N` | RFC 5737 TEST-NET-2 |
| lab hypervisor management address (private) | `203.0.113.40` | RFC 5737 TEST-NET-3 |
| lab hypervisor hostname | `lab-hv01` | generic |
| source forge URL | `private-forge/k3-firedrill` | generic |
| *(pack only)* production control-plane hostnames | `prod-cp-A`, `prod-cp-B`, `prod-cp-C` | generic; marked ⟦ ⟧ |
| *(pack only)* incident record identifiers | `⟦prior-rotation-incident⟧`; the origin exposure's record is not cited | role |

Everything already in `192.0.2.0/24` (TEST-NET-1) is fixture data and untouched. Kubernetes pod-network routes (`10.42.x`) are k3s defaults and untouched.

## Redaction gates run over this directory (2026-09-05)

1. identity grep — the private address prefixes, the operator's identifiers, the site's name, the lab hostname prefix, and the forge name (pattern held in the private repo's cut script) — must be 0.
2. `[a-f0-9]{64}` — must be 0 after subtracting the one allowlisted evidence-file sha256 (`40d6b4a1a6e0…35a2`, P5).
3. `K10[a-f0-9]+::` — must be 0.

Results are recorded in `pack/GATES_2026-09-05.txt` beside this file.

## Numbers a reader will cross-check

5 nodes (3 servers with embedded etcd + 2 agents), k3s `v1.34.4+k3s1` · etcd 3/3 · bootstrap key `0a6c128f5dad` at baseline · CA `744d6a1e…2798` · `server/token` whole-file digest `0b0ff4b8d018` ×3 at baseline · b3: 45 s to `active` (11:21:58Z → 11:22:43Z), Ready ≤65 s · six harness rollbacks, six PASS · 141 offline tests in the mirror · evidence sha256 `40d6b4a1…35a2`.

## Not in this pack

The terminal transcript of 2026-09-04 (contains a lab credential; never an input). The origin exposure's incident record. Production node inventories beyond the aliased surface table in P2 hunk 3. Any claim about test (c).
