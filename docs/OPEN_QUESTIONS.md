# Open questions and rehearsal gaps

Unresolved items remain explicit and must not be converted into silent defaults. Resolved research
is retained with its source pin so the implementation cannot silently regress it.

## Resolved — bootstrap-era discriminator

Resolved for K3s `v1.34.4+k3s1` at commit
`c6017918a65c824ce8d321db15267c8a317cd39d`, with embedded etcd
`k3s-io/etcd@server/v3.6.7-k3s1` at commit
`9f7f2c9540f1211570c2f23fd0baafc1d537662d`. The pinned K3s implementation derives
`/bootstrap/` plus the first 12 lowercase hexadecimal characters of SHA-256 over the normalized
token secret (`pkg/cluster/encrypt.go:storageKey:17-21` and
`pkg/util/token.go:NormalizeToken:41-49, ShortHash:67-70`). Full-token normalization discards the
CA hash and username; a bare secret is unchanged. The 12-character suffix is a 48-bit namespace,
so a candidate collision is `ANOMALOUS`.

The verified A6/A7/A9 write sequence distinguishes encryption era from payload era, permits a
normal or persisted two-key state, and never normally passes through zero. Test C now classifies
`OLD_ONLY`, `NEW_ONLY`, `BOTH`, and `ZERO`, with all other observations `ANOMALOUS`; it halts before
mutation on `ZERO` or `ANOMALOUS`. The normative decision, recovery-form, reset-flag, orphan
cleanup, and final exact-key-name rules are recorded in `TEST_SPEC.md`.

## VIP and host-type gap

The lab consists entirely of virtual machines and does not model the production floating API
VIP or the mix of bare-metal and virtualized control-plane hosts. It cannot rehearse VIP
failover during server restarts, and its default `server-1`-first order must not be copied into
production. Production ordering needs a separate decision based on VIP placement, workload
impact, and host type.

## Single failure domain

All three control-plane servers (7100–7102) and both agents (7103–7104) run on one hypervisor
host, `lab-hv01`. Measured 2026-09-04 22:53–22:55Z, read-only, Nexus
`EXEC_LOG_2026-09-04_P06_LAB_READONLY_CAPTURE.md` §3 rows C1–C3 (evidence file sha256 pinned
there): one host (Proxmox VE 9.2.5), one kernel (`7.0.14-8-pve`), one storage pool (`labtank`,
ZFS, a single NVMe vdev; every guest's `scsi0` is on `labtank-guests`), one bridge (`vmbr1`),
one shared snapshot lineage (`firedrill-baseline` → `p06-baseline`). One power domain is
ASSERTED from the host being a single machine; it has not been inventoried (no PDU or feed
record exists in this repo).

Consequences, stated so they are not silently upgraded elsewhere:

- "The other two held quorum" (Test (b), 2026-09-04) is quorum inside one failure domain. It is
  not evidence of partition tolerance, host loss, or storage loss. Network partition between
  servers cannot be exercised on this lab as built — the servers share a bridge on one kernel.
- Nothing in this lab is high-availability evidence. It rehearses the rotation procedure and
  the tooling on a topology that is deliberately smaller than production.
- Test (c) (quorum loss and snapshot recovery) is a separate, not-yet-run sitting and does not
  change this bound when it runs; it exercises recovery inside the same domain.

This section was owed to this file by the published evidence pack (P6, "the open-questions
file does not yet carry the line"). The pack's own text is not edited by this addition; the
public mirror follows on the next curated cut only.

## Exact Test B deletion allowlist

Originally open: the exact credential/token paths can vary with K3s release, role, packaging,
and configured data directory, so the recovery body could not safely infer a deletion set.

Source half resolved for this increment from runbook v1.6 section 6 Branch B, confirmed by two
independent audits: with `test_b_data_dir=/var/lib/rancher/k3s`, the exact configured allowlist is
`/var/lib/rancher/k3s/server/cred/passwd` and `/var/lib/rancher/k3s/server/token`. The mock Test B
body enforces those literal paths and rejects symlinks, directories, globs, traversal, and
off-list discoveries.

Still open: a pristine provisioned real node at the pinned K3s release must independently prove
both paths, their types, and whether packaging or configuration adds any source. Until that node
half is resolved, every real Test B hook remains fail-closed. No broad `find -delete` or recursive
removal is acceptable.

## Real-driver assumptions

- PVE identity resolved by measurement on 2026-08-30: the canonical command is `hostname`, its
  required exact output is the configured short hostname, and no normalization is permitted.
  The transport-stub suite proves mismatch rejection; first real-host execution remains open.
- PVE snapshot capability check is specified in two stages. Preflight requires the configured
  storage API object to report exact type `zfspool`; the first-contact lifecycle shakeout then
  creates, observes, restores, and observes a named snapshot on every owned guest. Stub tests
  cover command shape and convergence logic, but actual ZFS/PVE snapshot behavior is unproven.
  Libvirt snapshot behavior remains open and out of this increment.
- Cloud-init template conventions for disk bus, agent availability, SSH keys, and static
  networking remain site-specific. The PVE driver now consumes explicit configuration and
  verifies the converged VM config, but the values and real template behavior remain open.
- The secure known-hosts bootstrap procedure and noninteractive privilege boundary for the
  dedicated PVE and guest SSH accounts are not yet defined. Both account/key/known-hosts sets and
  `direct`, `sudo-n`, or `doas-n` privilege modes are explicit configuration and fail closed.
- K3s installation may require pre-staged binaries/images in an isolated lab. The harness must
  eventually choose between an explicit air-gap artifact directory and permitted lab egress;
  it must never silently download an unpinned artifact. **RESOLVED 2026-08-30 in favour of
  air-gap staging — see "Resolved — guest artifact delivery, credential handoff, and cluster
  observation" below. This bullet is retained for provenance and is no longer the authority.**

## Resolved — guest artifact delivery, credential handoff, and cluster observation

Operator decisions D-A, D-B, and D-C, ruled 2026-08-30 (CR). Codex dispatch #2
(`CODEX_PROMPT_2026-08-31_REAL_TEST_HOOKS_TESTA.md`, ratified `8b1e4be`) correctly returned
findings with zero edits because these three inputs did not exist. They are now settled and
Groups A and B are unblocked.

**D-A — artifact delivery is AIR-GAP STAGING, not lab egress.** Every artifact `firedrill-op`
needs is staged into template 9000 ahead of time and is never fetched at install time. The lab
subnet gains no egress permission as part of this work. Rationale: the lab's isolation is
measured and committed evidence (Nexus `42eecc4`), and perforating it for convenience would
retire the property the rehearsal environment exists to demonstrate; staging also removes
network variance from bounded convergence waits, and template 9000 must be modified for
`firedrill-op` regardless, so the marginal cost is near zero.

The staged set is the K3s binary, the K3s install script, and `etcdctl`, each pinned by SHA-256.
The hashes are **configuration, not code**: the operator supplies them from the official K3s
release checksum manifest for the pinned release `v1.34.4+k3s1`, and the harness verifies every
artifact before use and fails closed on any mismatch or absence. An unpinned or unverifiable
artifact is a hard failure, never a warning. Staging into the template is an OPERATOR act
performed from a documented procedure; the harness verifies staging, it does not perform it.

**D-B — the join credential and server endpoint reach the guest as a FILE, never as arguments.**
Before `install-k3s` runs, the driver writes a join file to the guest through the existing
`guest_put` primitive: mode `0600`, root-owned, path configurable with default
`/etc/firedrill/join.env`, carrying the server endpoint and the join token. `firedrill-op` reads
its endpoint and credential from that file. Passing either as an argv element is prohibited.
Rationale: this is not a preference but the existing contract that increment `54be94f` already
enforces — raw values live only in guest files and transient shell variables inside `guest_exec`,
and everything crossing the evidence boundary goes through the redaction registry. Process
arguments are visible to every user on the guest and would breach that boundary directly. The
join file is removed after a successful install; its contents never enter evidence, and any
reference to it in evidence goes through the redaction registry as a token reference.

**D2 — raw NEW token in guest-side argv at the final `k3s token rotate --new-token` exec.**
**Status: MEASURED 2026-09-01 (A0.2, `EXEC_LOG_2026-09-01_P06_A0_BASELINE.md` §2) — exception CONFIRMED, forced by upstream. Prior wording ("not a property of the procedure") RETRACTED.**
On `v1.34.4+k3s1 (c6017918)`, `k3s token rotate --help` documents env channels for `--data-dir`, `--kubeconfig`, `--token [$K3S_TOKEN]` and `--server`, and **none for `--new-token`** — no file, stdin, or env variant. The new token therefore transits argv (`/proc/<pid>/cmdline`, world-readable 0444; `environ` is 0400) for the lifetime of the `k3s token rotate` process, on the initiator only. This is a property of the upstream CLI at this release and applies to every caller — this harness, the manual annex, and a production run from `RUNBOOK_K3S_TOKEN_ROTATION_v1.md` — not a lab-only concession.
Harness posture (unchanged, no defect): the seat never places the token on argv; the guest receives it over stdin into a variable and only the final `exec` exposes it (`pve.sh:1129-1134`). The OLD token is never passed — read from the data dir as root.
UNVERIFIED: whether the `token rotate` subcommand scrubs its own argv the way `k3s server` does (measured 2026-08-29 on a production control-plane node, private change record: 0 `--token=` fields live). Assume it does not.
Runbook carries the risk with its bounded window and controls: `RUNBOOK_K3S_TOKEN_ROTATION_v1.md` v1.7 §2. Retire D2 when a release adds a `--new-token-file` or stdin channel; re-measure `--help` at every k3s bump.

**D-C — `etcdctl` is part of the same pinned, staged artifact set.** It is required, not
optional: bootstrap keys live under `/bootstrap/` in the K3s datastore and are unreachable
through the Kubernetes API, so neither key enumeration nor per-member etcd health can be
satisfied by `kubectl`. Node readiness needs nothing extra, since K3s ships `kubectl`.

The observation commands and their credential paths are explicit configuration with documented
defaults. **The defaults are UNVERIFIED until a pristine provisioned node at the pinned release
confirms them** — the same standing rule as the Test B deletion allowlist above. In particular
the server and agent kubeconfig paths, role credential paths, K3s etcd client certificate and key
paths, and their permissions must be read off a real node rather than assumed. The implemented
`capture-cluster-state` emits exactly the JSON shape `cluster_assert_healthy_file` consumes
(`nodes`, `all_nodes_ready`, `etcd_members`, `all_etcd_members_healthy`, `bootstrap_keys`,
`ca_sha256`), derived from the mock model rather than invented; its real-cluster observations are
still unverified.

Implementation status, 2026-08-30: D-A, D-B, and D-C are implemented and covered by offline
fixture and transport-stub tests. The operator procedure in `GUEST_ARTIFACT_STAGING.md` remains
the only authorized staging path; the harness does not modify template 9000. Operator-supplied
hashes and the local mode-0600 join-credential source intentionally remain fail-closed
placeholders in the PVE example.

## Timing and evidence assumptions

The laptop supplies evidence timestamps, while guest journal timestamps come from guest clocks.
Preflight should eventually measure/report clock skew so phase windows are reviewable. Timeout
values also need calibration on the real PVE host, while remaining bounded and configurable.

## Current increment boundary

The mock lifecycle and Test A/Test B/Test C execution bodies are implemented. The PVE driver now
implements lifecycle primitives, the air-gapped guest install/observation interface, and all six
real Test A hooks. Those paths have fixture or transport-stub coverage but no real-host execution.
PVE Test A may proceed past driver validation; PVE Test B and Test C remain fail-closed at exit 69,
as do every libvirt Test A/B/C hook, and `test-all` remains deliberately absent at exit 69.
Passing an offline test proves only command construction, bounded convergence, guards, persistence,
redaction, structured-policy wiring, and evidence-derived gate logic. It makes no claim that K3s
installation, server-token rotation, snapshot pairing, restart convergence, datastore observation,
or recovery works on real hardware. In particular, the configured guest paths and permissions,
real Test B credential deletion, real snapshots and rollback, cloud-init, guest SSH, real cluster
reset, real journald observations, and real quorum loss remain unproven.
