# Finding F-5 — required-key additions cannot reach gitignored live configs

Status: OPEN (mitigation `make config-check` proposed alongside this doc)
Recorded: 2026-08-30
Discovered by: shakeout attempt 2026-08-30 (preflight/provision exit 65, `cluster_capture_timeout_seconds` unset)
Classification: structural process defect, not a code defect

## Statement

Dispatch #3 (`06ee682`) plus the D-A/D-B/D-C rulings added 26 keys to the
required set in `py/firedrill/config.py` (all `driver=pve` path). The example
config was updated correctly, but `firedrill.conf` is gitignored, so no commit
can deliver new required keys to an existing deployment. Every live config
written before the dispatch breaks silently and reveals the gap only one key
at a time, through sequential exit-65 fail-closed preflights.

## Evidence (measured 2026-08-30, HEAD `4345f55`)

- Live `firedrill.conf`: 53 keys. `firedrill.conf.example`: 79 keys.
- Missing: exactly 26, all REQUIRED for `driver=pve`, all example-backed;
  zero optional keys missing, zero live-only keys, zero required keys absent
  from the example.
- 4 of the 26 are deliberate operator blockers: `k3s_binary_sha256`,
  `k3s_install_script_sha256`, `etcdctl_sha256` (artifact pins,
  `GUEST_ARTIFACT_STAGING.md`), and `k3s_join_credential_file` (local 0600
  token file, D-B ruling).
- Merge proof: `firedrill.conf.merged-20260830` with the four blockers
  substituted by syntactically valid dummies validates exit 0; with the
  blockers left as CHANGEME it fails closed on placeholder rejection, not
  unset rejection.

## What worked

The config gate caught the drift before any host mutation, named the exact
variable and its purpose, and exited 65 cleanly. Fail-closed design behaved
as specified. The defect is process-level: no dispatch that adds a required
key carries a migration note, and nothing compares live config against the
authoritative required set.

## Mitigation

`make config-check` (added with this finding) validates `firedrill.conf`
against `py/firedrill/config.py`'s required set and reports ALL missing and
placeholder keys in one pass, converting N sequential preflight failures into
one report. Residual process rule for future dispatches: any change to
`COMMON_REQUIRED` or `DRIVER_REQUIRED` must state, in the dispatch closeout,
that existing deployments need a config migration.

## Closure condition

F-5 closes when (a) `config-check` is committed and (b) the next dispatch
that touches the required set demonstrably carries a migration note.
