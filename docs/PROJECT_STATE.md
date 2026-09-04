# PROJECT_STATE — k3-firedrill

Snapshot date: 2026-09-04, HEAD `ba90be8` — **TEST (a) PASSED on
lab-hv01 at `e4b9fbe` (attempt 4, 09:00–09:02Z, 7/7, EXIT=0,
independently verified).** F-TA-6/F-TBC-1 is included in the measured HEAD.
Authority: Claude (Fable 5.1) primary 2026-09-04; Codex executor available
to 2026-09-17, per-item dispatch.
Owner: this file is the successor-agnostic state of record for any
assistant picking up the project without conversation history. Update it
at every significant checkpoint; a stale copy is worse than none — trust
live command output and `git log` over anything here that has aged.

## Hardware-proven facts (all measured 2026-08-30)

- Full chain preflight → provision → baseline PASSED on lab-hv01
  (PVE 9.2.5, 203.0.113.40, storage `labtank-guests`, bridge `vmbr1`).
- First real cluster: K3s v1.34.4+k3s1, guests 7100–7102 servers
  (embedded etcd) + 7103–7104 agents at 198.51.100.10–.14, air-gapped
  install from staged artifacts ("Skipping k3s download and verify" on
  all five nodes). Five `firedrill-baseline` snapshots captured;
  lifecycle = `baseline`, run `fd-20260830t151047z-370455`, state under
  the harness seat's `runs/` (currently the operator's Mac mini).
- A0 disk-resize path proven: template 3.5G → 20G servers / 15G agents.
- Resume semantics proven: `already-present` / `already-running`
  fast-paths across two aborted and one successful provision run, with
  no double mutation.
- Template 9000 staged per `docs/GUEST_ARTIFACT_STAGING.md`: firedrill-op
  + k3s + install.sh + etcdctl, sha256-verified at every hop; machine-id
  restored to empty after the virt-customize side-op.

## Artifact pins (operator-approved 2026-08-30)

- k3s v1.34.4+k3s1 binary: `94404b82…36db504` (official manifest value).
- install.sh (tag-pinned source): `40b487f0…ee9816e` (operator-computed).
- etcdctl upstream v3.6.7: `a14e39a2…18d7fef` (operator-computed from
  SHA256SUMS-verified tarball; version ratified-by-execution — the k3s
  release embeds `k3s-io/etcd@server/v3.6.7-k3s1`).

## Findings ledger

- F-2 guest known-hosts seeding — CONFIRMED + MITIGATED; procedure in
  `docs/FINDING_F2_GUEST_KNOWN_HOSTS_SEEDING.md`; `seed-trust` helper
  PROPOSED, unruled.
- F-3 clone disk < spec — CLOSED (A0, proven on hardware).
- F-4 silent wait loops — CLOSED (attempt counters).
- F-5 gitignored conf can't receive required keys — code leg CLOSED
  (`make config-check`, `3dccb7a`); process leg OPEN: the next dispatch
  touching the required set must carry a migration note.
- F-6 staging-doc defects (machine-id side-op, `virt-ls -ld` misparse) —
  CLOSED in `docs/GUEST_ARTIFACT_STAGING.md` (`a81f386`).
- F-8 BSD-mktemp infix-X templates — CLOSED in code
  (`docs/FINDING_F8_MKTEMP_PORTABILITY.md`); its tracing-hazard notes
  remain standing guidance.
- F-A03-1 rollback path has no guest stop/start beat — CLOSED ON
  HARDWARE 2026-09-02 (`632336c`; A0.3 rerun 06:05:46–06:09:06Z, evidence
  rows 59–79 all exit 0: 5× graceful shutdown, 5× rollback, 5× start
  servers-then-agents, 1× SSH-gated capture; `PASS: baseline restored
  and cluster health verified`, EXIT=0; all four §2 facts re-verified
  independently — Nexus `EXEC_LOG_2026-09-02_P06_A0_3_ROLLBACK.md` §5.2).
  History of the fix: The operator ratified the driver
  layer after implementation began on the documented blank-means-driver
  default (CR, 2026-09-02): PVE prepare/finish hooks reuse
  `driver_impl_guest_stop`/`pve_stop_approved` and
  `driver_impl_guest_start`, while `command_rollback` owns the cross-guest
  phases (validate all snapshots; stop all five; roll back all five;
  start all servers, then all agents; wait for server-1 SSH; capture).
  `driver_impl_snapshot_restore` now refuses a running guest before
  `qm rollback`. The existing configured `pve_operation_timeout_seconds`
  bounds graceful shutdown, so the required config-key set did not change.
- F-A03-2 silent non-zero exit — ROOT CAUSE FIXED, COMMITTED `632336c`;
  mechanism independently reproduced by Claude in an isolated bash 5.1
  probe (ERR trap fires inside the redirected function under `set +e`;
  `if`-condition form suppresses it) and the new test measured to FAIL
  against `42c6f85:lib/evidence.sh` and PASS after. Not bash-3.2-specific.
  Original wording of the finding:
  UNCOMMITTED 2026-09-02. `evidence_exec` used `set +e` before invoking
  the recorded command, but in Bash `set +e` disables errexit, not the
  `ERR` trap; with `set -E`, the trap remained inherited through the PVE
  guest-transport function chain. When external `ssh` returned 255,
  `on_error` ran inside the command whose stderr was redirected to the
  temporary evidence file and called `exit 255`, terminating the harness
  before the Python evidence writer or stderr replay. The fix invokes the
  recorded command as an `if` condition, one of Bash's defined contexts
  that suppresses both errexit and `ERR` through the nested call, captures
  its status, writes and replays the evidence, then returns 255 so the
  outer `on_error` line is visible. A child-process transport stub proved
  the pre-fix no-line/no-row signature and the post-fix line-plus-row
  contract.
- F-A03-3 evidence for 2026-09-02 appended to run
  `fd-20260830t151047z-370455` (08-30 manifest). Design or defect unruled.
- F-TA-1 Test A proposal hook uses the wrong primitive — FIX IMPLEMENTED,
  STUB-PROVEN (UNCOMMITTED 2026-09-02). Dispatch
  `docs/CODEX_PROMPT_2026-09-02_TESTA_TOKEN_MINT_1_5.md` was RATIFIED
  2026-09-02. MEASURED on server-1: `k3s token generate` emits a 23-char
  kubeadm-style bootstrap token (`--help`: "Generate and print a
  bootstrap token"), not `K10<ca>::server:<secret>`; runbook §1.5 says so
  explicitly. `driver_impl_test_a_propose_server_token` now reads and
  validates the current full server token through the same bounded raw
  transport as the read hook, preserves its CA hash and user part, and
  mints only a fresh 48-hex secret with Python `secrets` on the seat. The
  fabricated different-CA proposal stub and guest `token generate` branch
  are removed. Focused transport-stub tests and `make test` pass; token
  construction and rotation **PROVEN ON HARDWARE 2026-09-02 07:01Z** —
  see the later F-TA-1 proof entry below. COMMITTED `1181b50` 2026-09-02.
- F-TA-2 test-a SETUP identity check binds test parameters — FIX
  IMPLEMENTED, STUB-PROVEN (UNCOMMITTED 2026-09-02),
  dispatch `docs/CODEX_PROMPT_2026-09-02_TESTA_PROVISION_IDENTITY.md`
  RATIFIED 2026-09-02. `config_sha256` covers the whole canonical config;
  `baseline_prerequisites` asserts it equals the provisioned digest
  (`06c05b28…`). The live conf differs in exactly two operator-ruled
  fields — `snapshot_name` (LP-8) and `server_restart_order` (WS-5) —
  PROVEN by normalizing them back and reproducing `06c05b28…` exactly. So
  `test-a` would exit at SETUP before any mutation, and neither field can
  be reverted. Same digest also binds absolute seat paths, so a seat
  migration would fail identity on an unchanged lab. Implemented fix: a
  `provision_identity_sha256` over an explicit inclusion list, compared
  against re-projected `manifest.json#/config` with no run-state rewrite.
  The legacy live manifest and current config re-project to the same
  `e8e2170d…70d733` digest. Unit tests, mock lifecycle acceptance, the
  identity-drift negative probe, and the full offline gate pass. Hardware
  proof **PROVEN ON HARDWARE 2026-09-02 07:01Z** — see the dated F-TA-2
  entry immediately below.
  COMMITTED `f2a1f90`; **PROVEN ON HARDWARE 2026-09-02 07:01Z** — test-a
  SETUP `provision-identity-and-inventory` PASS against the legacy run.
- F-TA-1 also PROVEN ON HARDWARE 07:01Z: old/new references share the
  `K10744d6…` CA prefix; rotation converged; `/bootstrap` replaced
  `0a6c128f5dad` with exactly one new key `bd77ff8013c8`.
- F-TA-4 Test A server credential written to the wrong surface — FIX
  IMPLEMENTED, STUB-PROVEN (UNCOMMITTED 2026-09-02), dispatch (A) in
  `docs/CODEX_PROMPT_2026-09-02_TESTA_SERVER_ENV_AND_SHELL_DEATH.md`.
  Hardware measured that k3s regenerates `server/token` from
  `K3S_TOKEN=` in `k3s.service.env`; the stale env value caused the
  runbook-pinned crash sequence on server-2. The repair factors the
  existing fail-closed env editor once and uses it for servers and agents,
  then compares a guest-computed full-token digest with the expected digest
  after every server restart. The transport fixture keeps server-2/3's
  token stale until both the env edit and restart occur. Zero/two
  `K3S_TOKEN=` lines and failed regeneration independently exit 69. Nexus
  incident evidence remains in
  `EXEC_LOG_2026-09-02_P06_TEST_A_FIRST_CONTACT.md`; repair **PROVEN ON
  HARDWARE 2026-09-02 08:17–08:19Z** — see the later F-TA-4 proof entry
  below.
- F-TA-3 harness died silently inside the restart phase — FIX IMPLEMENTED,
  STUB-PROVEN (UNCOMMITTED 2026-09-02), dispatch (B) in the same prompt.
  `evidence_exec` now publishes a global in-flight marker immediately
  around the redirected command and leaves its temp files out of
  `FD_TEMP_FILES` until normal evidence writing completes. The startup
  path saves original stderr on fd 7. If EXIT observes the marker,
  cleanup emits the FATAL line and replays captured stderr to fd 7, writes
  a `-shell-death` evidence row, then removes the temp files and preserves
  a non-zero process status. Bash 3.2 with the inherited ERR trap can
  report status 0 for a fatal nounset expansion; the in-flight condition
  fail-closed normalizes only that impossible success status to 1. Both
  nounset and direct `exit 3` child probes pass. The first-contact root
  cause remains UNVERIFIED; the next operator run will surface it through
  this mechanism if it recurs. F-TA-3/F-TA-4 COMMITTED `4fda3de`.
- F-TA-5 Test A evidence not attempt-scoped — FIX IMPLEMENTED,
  STUB-PROVEN (UNCOMMITTED 2026-09-02), dispatch
  `docs/CODEX_PROMPT_2026-09-02_TESTA_ATTEMPT_EVIDENCE.md` RATIFIED
  2026-09-02. Attempt 2 (07:47Z, `4fda3de`) ran SETUP fully, then
  `record-phase SETUP` failed `phase order violation: expected 'BREAK',
  observed 'SETUP'` (exit 69, before rotation): attempt 1's
  `evidence/test-a/phases.json` survived the hypervisor rollback on the
  seat, and neither rollback nor test start archived it. `command_test_a`
  now archives prior `evidence/test-a/` to
  `evidence/test-a.attempts/<earliest-started-at>/` before driver loading,
  records `test-a-attempt-archived` on node `test-a`, moves any live
  result to timestamp-keyed `tests_history`, and clears the live result.
  Existing archive/history keys receive a numeric suffix; nothing is
  overwritten. `record_phase`, evaluation, and rollback logic are
  unchanged. The (B) FATAL path did not fire — an ordinary guarded
  failure, reported correctly. COMMITTED `ef6d921`; **PROVEN ON HARDWARE
  08:16Z** — attempt 3 archived attempt 1's ledger to
  `evidence/test-a.attempts/20260902T070135Z/` and ran clean.
- F-TA-4 PROVEN ON HARDWARE 08:17–08:19Z: three servers rolled to the
  new token via the env-file edit with the regeneration check passing
  on each; zero `different token` journal lines on all five nodes.
- F-TA-6 gate check `three-healthy-etcd-members` compared k3s's
  suffixed etcd member names (`server-1-d1dfa965` …) to bare node names
  — FIX IMPLEMENTED, STUB-PROVEN (UNCOMMITTED 2026-09-02), dispatch
  `docs/CODEX_PROMPT_2026-09-02_TESTA_ETCD_MEMBER_NAMES.md` RATIFIED
  2026-09-02. One shared evaluator now requires exact continuity with the
  three baselined member names, all healthy, and a one-to-one mapping to
  the expected servers; bare names and lowercase 8-hex k3s suffixes are
  the only accepted forms. Test A, Test B, and Test C call that helper,
  and the mock emits stable hardware-shaped names. Six focused ran-marker
  cases and all three mock lifecycles pass. A fresh `/tmp`
  copy of attempt 3's baseline and gate observation re-adjudicated 7/7
  PASS. This is a **re-adjudication of attempt 3 hardware evidence**, not
  a new hardware run or a harness-native PASS at the corrected revision.
  Fourth stub-modelled naming/behaviour assumption disproven tonight.
- F-TBC-1 Test B and Test C retained the same bare-name etcd comparison —
  FIX IMPLEMENTED, STUB-PROVEN (UNCOMMITTED 2026-09-02),
  `docs/FINDING_FTBC1_ETCD_MEMBER_NAMES.md`. CR RATIFIED the repair into
  this increment on 2026-09-02. The corrected check is factored once in
  `py/firedrill/etcd_members.py` and used by all three evaluators without
  changing check ids. The previously failing Test B/Test C passing-world
  cases now pass; full `make test` exits 0 through every shell lifecycle.
- F-TB-1 — two on-disk token forms: `K3S_TOKEN=` in `k3s.service.env`
  holds the bare 64-hex secret; `server/token` holds the
  `K10<ca>::server:<secret>` form. Same credential, two digests. Redaction
  regex must cover both (`[a-f0-9]{64}` and `::server:[a-f0-9]*`).
- F-TB-2 — manual annex A4 b2 omits the parent §4 clause "fix the token
  source to NEW"; ruled procedure is to stage NEW into the stale node's
  source before b1.
- F-TB-3 — a wrong-token start rewrites `cred/passwd` and `server/token`
  from the datastore before failing the token check, so the stale node's
  own failed start arms the timestamp trap by itself; recovery deletes both
  files even after the source is fixed. Mechanism UNVERIFIED at k3s source
  level; measured once by mtimes.
- F-TB-4 — PVE "Bulk start" reported OK and started nothing (05:04:45 EDT
  09-04, all five guests still stopped at 11:11Z); repeat of the 09-01
  finding, reproduced ×2. Standing rule: individual `qm start`.

## F-TA-6 / F-TBC-1 repair closeout evidence (UNCOMMITTED 2026-09-02)

Executed offline on the Mac mini, with no network, SSH, hypervisor command,
real-cluster mutation, or write under `runs/`:

- The new suffixed-name positive test failed against the pre-fix evaluator;
  the other 14 focused Test A gate tests passed in that fail-first run.
- After the repair, all 15 focused Test A gate tests passed. The six new
  cases cover matching suffixed names, a missing member, a fourth member,
  an unexpected server prefix, a non-hex suffix, and bare-name compatibility.
- The Test A mock lifecycle completed twice and passed end to end with stable
  k3s-style member names. Test B's lifecycle and both Test C recovery-form
  lifecycles also passed through the same shared member check.
- A fresh scratch tree under `/tmp` contained copies of only
  `baseline/cluster-state.json` and
  `evidence/test-a/gate-observation.json` from attempt 3. The evaluator
  wrote its output only into that scratch tree and returned 7/7 PASS,
  including mappings `server-1←server-1-d1dfa965`,
  `server-2←server-2-3ee0262b`, and
  `server-3←server-3-9b17da5b`. This was a re-adjudication of attempt 3's
  saved hardware evidence, not a new hardware run.
- The pre-ruling `make test` failure exposed F-TBC-1: only the Test B/Test C
  `three-healthy-etcd-members` rows failed in three passing-world tests.
  After CR ratified the shared repair, `make test` exited 0: ShellCheck
  covered all 30 discovered shell files, Ruff passed, all 141 Python tests
  passed, every shell lifecycle ran, all negative probes passed, and the
  PVE transport-stub suite completed without network access.
- The required config-key set is unchanged; no F-5 migration is required.

Exact new ran-markers:

```text
test_ran_marker_suffixed_names_matching_baseline_pass
test_ran_marker_missing_baselined_member_fails
test_ran_marker_fourth_member_fails
test_ran_marker_unexpected_server_prefix_fails
test_ran_marker_non_hex_or_wrong_length_suffix_fails
test_ran_marker_bare_names_with_bare_baseline_pass
```

Could not execute: a new operator-coordinated real `./firedrill test-a` run
at the corrected revision. Unproven: a harness-native 7/7 PASS on the real
five-node PVE lab. The saved observation's 7/7 result is explicitly limited
to offline re-adjudication.

## F-TA-5 repair closeout evidence (UNCOMMITTED 2026-09-02)

Executed offline on the Mac mini, with no network, SSH, hypervisor command,
or real-cluster mutation:

- Focused Test A unit coverage passed: a fresh ledger accepts `SETUP`, and
  a leftover `[SETUP]` ledger rejects another `SETUP` with the observed
  phase-order message unchanged.
- The mock lifecycle completed Test A, rolled the mock lab back, then
  completed a second Test A without manual run-directory cleanup. The
  first three-phase ledger, gate, and state result were preserved under
  one timestamp key; the second attempt reached its own `GATE`.
- The collision negative probe preserved an existing archive and selected
  the `-2` suffix for the new archive and state-history key.
- `make test` exited 0: ShellCheck covered all 30 discovered shell files,
  Ruff passed, 135 Python tests passed, both mock lifecycles and all
  negative probes passed, and the PVE transport-stub suite completed
  without network access.
- The required config-key set is unchanged; no F-5 migration is required.

Exact new ran-markers:

```text
PASS: test-a re-attempt archived prior evidence and started a clean phase ledger
NEGATIVE PROBE test-a-attempt-archive-collision: suffix applied, no overwrite
```

Could not execute: the operator-coordinated real `./firedrill test-a`
attempt 3. Unproven: attempt archival followed by token rotation and gate
completion on the real five-node PVE lab. Hardware proof belongs to that
operator run and is not claimed by this dispatch.

## F-TA-1 repair closeout evidence (UNCOMMITTED 2026-09-02)

Executed offline on the Mac mini, with no network, SSH, hypervisor command,
or real-cluster mutation:

- `bash tests/test_pve_driver.sh` exited 0.
- `make test` exited 0: ShellCheck covered all 30 discovered shell files,
  Ruff passed, 110 Python tests passed, and all shell suites completed.
- The required config-key set is unchanged; no F-5 migration is required.

Exact new ran-markers:

```text
NEGATIVE PROBE pve-test-a-propose-token-read-failure: expected failure exit=73
PASS: PVE Test A proposal preserves the CA hash and user part and mints a fresh 48-hex secret (runbook 1.5)
PASS: PVE Test A proposal never invokes k3s token generate
NEGATIVE PROBE pve-test-a-propose-from-malformed-current: expected failure exit=69
NEGATIVE PROBE pve-test-a-propose-same-token: expected failure exit=69
```

Could not execute: the operator-coordinated real `./firedrill test-a` run.
Unproven: proposal and rotation behavior on K3s v1.34.4+k3s1 and the real
five-node PVE lab. Hardware proof belongs to that operator run and is not
claimed by this dispatch.

## F-TA-2 repair closeout evidence (UNCOMMITTED 2026-09-02)

Executed offline on the Mac mini, with no network, SSH, hypervisor command,
or real-cluster mutation:

- The legacy run manifest and current live config independently re-projected
  to `e8e2170d8d83a21cc7596b96c7b3384635291d9d3dd65a61746826466270d733`.
- `make config-check` reported `pve (60 required keys)`, `COMPLETE`, and both
  the full-config and provision-identity digests.
- `make test` exited 0: ShellCheck covered all 30 discovered shell files,
  Ruff passed, 133 Python tests passed, and every shell suite completed.
- The required config-key set is unchanged; no F-5 migration is required.
- No existing `state.json` or `manifest.json` was rewritten.

Exact new ran-markers:

```text
PASS: test-a SETUP accepts post-provision snapshot_name and restart-order changes under provision identity
NEGATIVE PROBE test-a-provision-identity-drift: expected failure exit=69
```

Could not execute: the operator-coordinated real `./firedrill test-a` run.
Unproven: manifest-projected identity and clean token rotation on the real
five-node PVE lab. Hardware proof is the operator's `./firedrill test-a` run
and is not claimed by this dispatch.

## F-TA-4 and F-TA-3 repair closeout evidence (UNCOMMITTED 2026-09-02)

Executed offline on the Mac mini, with no network, SSH, hypervisor command,
or real-cluster mutation:

- Before the F-TA-3 change, `bash tests/test_evidence_exec_failure.sh`
  exited 0 and printed only the existing exit-255 PASS marker; neither new
  shell-death marker existed.
- The focused post-change evidence suite and PVE transport-stub suite exited
  0 with all five new markers below.
- `make test` exited 0: ShellCheck covered all 30 discovered shell files,
  Ruff passed, 133 Python tests passed, both mock lifecycles and all negative
  probes passed, and the PVE transport-stub suite completed without network
  access.
- The required config-key set is unchanged; no F-5 migration is required.

Exact new ran-markers:

```text
PASS: PVE Test A server restart edits K3S_TOKEN in the server env file and verifies server/token regenerated
NEGATIVE PROBE pve-test-a-server-env-token-count: expected failure exit=69
NEGATIVE PROBE pve-test-a-server-token-not-regenerated: expected failure exit=69
PASS: shell death inside evidence_exec emitted FATAL line, replayed stderr, and wrote an evidence row (unbound variable)
PASS: shell death inside evidence_exec emitted FATAL line, replayed stderr, and wrote an evidence row (exit builtin)
```

Could not execute: the operator-coordinated real `./firedrill test-a` run.
Unproven: server env-file editing, post-restart token regeneration, and
shell-death capture on the real five-node PVE lab. Hardware proof remains the
operator's next `./firedrill test-a` run and is not claimed by this dispatch.

## F-A03 repair closeout evidence (UNCOMMITTED 2026-09-02)

Executed offline on the Mac mini, with no SSH or hypervisor command:

- The pre-fix external transport stub exited 255 with empty visible output
  and no evidence row. The pre-fix rollback negative probe reported
  `exit=0 expected=69`, proving a running guest still reached the old
  restore path.
- Post-fix `make test` passed ShellCheck over all 30 discovered shell
  files, Ruff, 110 Python tests, both mock lifecycles, all negative probes,
  the exit-255 child-process probe, and the PVE transport-stub suite.
- `make config-check` reported `pve (60 required keys)` and `COMPLETE`.
  The required config-key set is unchanged; no F-5 migration is required.

Exact new ran-markers:

```text
PASS: PVE guest-exec exit 255 emitted stderr failure and an evidence row
PASS: PVE restore stopped a running guest before qm rollback and started it afterwards
PASS: PVE restore recorded already-stopped without issuing qm shutdown
PASS: rollback phased all stops, rollbacks, server starts, agent starts, SSH wait, and capture
```

Could not execute: an operator-coordinated live rollback or post-fix A0.3
rerun. Unproven: the new phase hooks, evidence behavior, ordering, SSH wait,
and final health verdict on lab-hv01/PVE 9.2.5. All new behavioral proof is
stub/offline only until that gate runs.

## Open queue (operator rulings in bold)

0. CLOSED 2026-09-02 — increment committed `632336c`, A0.3 PASSED on
   lab-hv01 through the harness. Rollback anchor is MEASURED at the
   harness layer; the leg used between tests is the leg that was proven.
0. **TEST (a) CLOSED — PASS.** Attempt 4 at `e4b9fbe`, 2026-09-02
   09:00:21–09:02:29Z: SETUP 35.8 s, rotation to `/bootstrap/36e19983d14e`,
   restarts server-2 10 s / server-3 12 s / server-1 10 s (hold-out) /
   agent-1 5 s / agent-2 6 s all healthy, GATE 7/7,
   `PASS: Test A clean server-token rotation satisfied every evidence
   gate`, EXIT=0. Independent: 5/5, 3/3, one key, CA unchanged, three
   identical new token digests, zero decryption failures on five nodes.
   Nexus `EXEC_LOG_2026-09-02_P06_TEST_A_PASS.md`. Operator ruled the
   fourth attempt over accepting the offline re-adjudication of attempt 3
   (which was also 7/7). Next harness work: **AGENTS.md rule** — any stub
   that models an external tool's behaviour or naming carries one measured
   sample beside it (four such assumptions disproven on hardware tonight:
   F-A03-1, F-TA-1, F-TA-4, F-TA-6). Test B/C real hooks remain exit 69
   by design; their bodies are manual-annex sittings.
0. **TEST (b) PASS 2026-09-04.** Manual annex §A4 on the `lab-hv01`
   rehearsal cluster 7100–7104, 11:18:31–11:23:03Z. b1: signature
   `bootstrap data already found and encrypted with different token` ×1 on
   server-2, blast radius exactly one server (etcd 2/3, quorum held). b2:
   timestamp trap **MANIFESTED** — `cred/passwd newer than datastore and
   could cause a cluster outage. Remove the file(s) from disk and restart
   to be recreated from datastore.` ×5 with the correct token and no
   override. b3: two-path delete
   (`/var/lib/rancher/k3s/server/cred/passwd`,
   `/var/lib/rancher/k3s/server/token`) → `active` in 45 s, Ready ≤65 s.
   **Six harness rollbacks, six PASS** (rollback #6 verified independently
   11:28:12Z). Findings: F-TB-1, F-TB-2, F-TB-3, F-TB-4. Source: Nexus
   `EXEC_LOG_2026-09-04_P06_TEST_B.md` at `48b4fb6`.
0. **Test (c) NOT RUN.**
1. History — **Test (a) attempt 3 (08:16Z, `ef6d921`): SUBSTANTIVELY PASSED** —
   rotation, five ordered healthy restarts (hold-out server-1 last, 16 s),
   zero decryption failures, one new key, CA unchanged, all verified
   independently on the lab; harness gate 6/7 on F-TA-6 only. Nexus
   `EXEC_LOG_2026-09-02_P06_TEST_A_ATTEMPTS_2_3.md`. History: attempt 2
   (07:47Z) stopped at the SETUP phase record (F-TA-5), before rotation.
   Attempt 1 (07:01Z) FAILED at
   BREAK: SETUP and rotation passed, server-2 restarted on the stale
   token (F-TA-4), harness died silently (F-TA-3), rollback restored
   `p06-baseline`. Everything upstream of the server restart is now
   hardware-proven.
   **WS-5 RULED 2026-09-02 (CR): hold-out = `server-1`.** Mechanism: the
   hold-out is the LAST name in `server_restart_order`; live gitignored
   conf now reads `server-2,server-3,server-1` (config-check COMPLETE).
   D2 measured 2026-09-01: `--new-token` has no file/
   stdin/env channel on the pinned release; correction APPLIED at ba90be8,
   2026-09-02 (`docs/OPEN_QUESTIONS.md:104`).
2. **qemu-guest-agent in template 9000** — currently configured-but-not-
   installed, so snapshots are crash-consistent, not fs-frozen.
3. **Laptop commit authority** — SK signing key is Mac-bound; a Linux
   seat either works uncommitted or commits unsigned. Unruled.
4. Seat migration to the Ubuntu laptop — `docs/SEAT_MIGRATION_UBUNTU.md`;
   gated on one routing measurement (its §1).
5. Real test-b / test-c hook bodies — fail-closed at exit 69 by design;
   need a future dispatch after test-a experience.
6. Exec-log evidence for the Lazarus Labs records repo (Nexus) covering
   the 2026-08-30 provisioning day.

## Lab power state

**CURRENT 2026-09-04 ~11:30Z: five guests 7100–7104 at `p06-baseline`;
`lab-hv01` powered off.**

**2026-09-02 ~05:10 EDT: fifth harness rollback (`rb5`, post test-a
PASS) — result recorded in Nexus `EXEC_LOG_2026-09-02_P06_TEST_A_PASS.md`
§3. Five rollbacks tonight, five PASS: healthy lab (`632336c`), wrecked
control plane (`f2a1f90`), benign snapshot litter (`ef6d921`), rotated
cluster ×2 (`ef6d921`, `e4b9fbe`); each independently re-verified to
WS-1/WS-2. The restore path is the proven between-test mechanism.**
**2026-09-02 03:10 EDT: second harness rollback PASS at `f2a1f90` from a
wrecked cluster (server-2 crash-looping, etcd 2/3); verified 07:21Z.**
**MEASURED 2026-09-02 02:09 EDT: guests 7100–7104 RUNNING at
`p06-baseline`, restored entirely by `./firedrill rollback` at `632336c`
(graceful stop → rollback → servers-then-agents start → SSH wait →
capture) — 5/5 Ready, etcd 3/3, `/bootstrap/0a6c128f5dad`, CA sha256
`744d6a1e…2798`, guest host keys intact under strict checking. The
harness rollback is the proven between-test restore path. Each rollback
regenerates cloud-init ISOs and takes ~3m20s wall-clock.**
Snapshot tree on all five: `firedrill-baseline` → `p06-baseline` →
`current`; `firedrill-baseline` is the parent, so deleting it is a
merge, not a free delete. `snapshot_name=p06-baseline` lives only in
the gitignored Mac-mini `firedrill.conf` — that value exists in no
commit; a seat change silently retargets rollback to the 08-30
live-cluster snapshots, which LP-8 rejects.

Safe shutdown: `qm shutdown` 7104→7100 (ACPI; no guest agent), verify
all stopped, then power off the host. Restart: 7100–7102 together first
(etcd quorum), then agents; the harness treats `already-running` as
normal. Never tear down with anything but `firedrill destroy --confirm`.
Destroy-and-reprovision invalidates the seeded guest host keys (F-2) and
the baseline snapshots.
