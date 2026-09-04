# Finding F-TBC-1 — Test B/C gates reject hardware-shaped etcd member names

Status: FIX IMPLEMENTED, STUB-PROVEN 2026-09-02 (UNCOMMITTED)
Ruling: RATIFIED 2026-09-02 — CR; repair folded into the F-TA-6 increment
Classification: evaluator and stub-model fidelity defect

## Statement

The shared mock emits k3s-style embedded-etcd member names of the form
`server-N-<8hex>`, stable per lab id, as required by the F-TA-6 dispatch.
Before this repair, the Test B and Test C `three-healthy-etcd-members`
evaluators still required the observed name set to equal the bare
`EXPECTED_SERVERS` set. Their passing mock worlds therefore failed the full
repository gate even though all three members were present and healthy.

CR ruled the repair into scope on 2026-09-02. The complete check logic now
lives once in `py/firedrill/etcd_members.py`: exact three-member continuity
against the baseline set, every observed member healthy, and a one-to-one
mapping to the expected servers accepting either bare names or lowercase
8-hex k3s suffixes. Test A, Test B, and Test C call that helper and retain
their existing check ids.

## Evidence (measured 2026-09-02, base HEAD `cde7643` plus uncommitted F-TA-6)

`make test` passed ShellCheck over 30 files and Ruff, then ran 141 Python
tests and failed exactly three passing-world assertions:

- `test_test_b.TestBGateTests.test_passing_world_satisfies_every_evidence_gate`
- `test_test_c_execution.GateEvaluationTests.test_both_cleanup_path_passes_only_after_survival_and_explicit_removal`
- `test_test_c_execution.GateEvaluationTests.test_snapshot_and_membership_forms_are_both_exercisable`

Focused pre-fix evaluation showed that the only failed check in each result was
`three-healthy-etcd-members`. Test B observed
`server-1-c3226f26`, `server-2-9143d299`, and `server-3-651da8e9`;
Test C observed `server-1-743019e7`, `server-2-fb65b7b3`, and
`server-3-af1813e4`.

## Repair proof (measured 2026-09-02)

- The focused A/B/C evaluator run passed all 25 tests, including the three
  passing-world tests that failed before the ruling.
- `make test` exited 0: ShellCheck covered all 30 discovered shell files,
  Ruff passed, all 141 Python tests passed, the Test A two-attempt lifecycle
  passed, Test B's lifecycle passed, both Test C recovery-form lifecycles
  passed, and the remaining negative and PVE transport-stub suites completed.
- Source inspection finds the member mapping implementation only in
  `py/firedrill/etcd_members.py`; each evaluator has one call site.
- A fresh two-file `/tmp` copy of attempt 3's baseline and Test A observation
  re-adjudicated 7/7 PASS through the final shared helper.
- The required config-key set did not change; no F-5 migration is required.

## Proof boundary

This is stub/offline proof for Test B and Test C. Their PVE failure-test hooks
remain deliberately unimplemented and fail closed, so this change makes no
claim of Test B or Test C hardware execution. Attempt 3's 7/7 result remains
an offline re-adjudication of saved Test A hardware evidence, not a new run.
