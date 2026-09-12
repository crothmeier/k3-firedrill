# Failure-rehearsal test specification

This document is the reviewer-facing intent. Test A, Test B, and Test C are implemented for the
offline `mock` driver. PVE lifecycle primitives and the six PVE Test A hooks are implemented;
the PVE Test A path is transport-stub tested but unproven on hardware. PVE Test B/C, every
libvirt test path, and `test-all` remain fail-closed. Passing an offline test proves only its
modeled or command-construction contracts, guards, evidence, and gate logic. Real token rotation,
artifact and credential paths, journals, and convergence remain unproven until an operator run.

Every test begins by proving that the cluster matches the captured baseline: five expected
nodes Ready, three expected etcd members healthy, exactly one bootstrap key, unchanged CA
hash, matching normalized join credential references, matching inventory/config identity,
and all five hypervisor baseline snapshots present. Failure of any prerequisite aborts the
test; tests never run on one another's wreckage.

Every SETUP, BREAK, RECOVER, and GATE phase records ordered commands and output, Ready and
etcd health, bootstrap key names only, CA hash, server journal windows, and phase timing.
Raw tokens must never enter evidence. A token is represented by format classification, a
short prefix, and a SHA-256 digest.

## Test A — clean rotation

### Setup

Capture an etcd snapshot on every server and record each snapshot path beside the SHA-256
reference for its current server token. Reject an unpaired snapshot. Generate or obtain the
new server token, then positively require full server-token format matching
`^K10[a-f0-9]{64}::server:` before invoking rotation. An agent token or short token aborts.
The PVE hook supplies token values to guest-side mutation shells over stdin, records only token
references, and refuses rotation until all three snapshot pairs exist.

### Break

There is no injected fault. Rotate to the validated full-format server token. Restart servers
one at a time in configured order, waiting within a fixed timeout for each server and its etcd
member to become healthy before touching the next. Restart both agents after the servers.

The lab default starts with `server-1`, the cluster-init node. This deliberately differs from
production ordering. The lab has neither the production floating API VIP placement nor its
mix of bare-metal and virtualized control-plane hosts, so it cannot validate VIP failover or
establish the correct production restart order.

On PVE, each restart first updates the configured role-appropriate credential file, refreshes
the non-secret split SHA-256 node labels used for cluster observation, and then performs one
bounded service restart and health wait. The configured credential and kubeconfig path defaults
remain unverified until the first pristine-node walk.

### Recovery

No special recovery is expected. Failure during the clean sequence ends the test and leaves
rollback as an operator action; the harness must not improvise.

### Gate

Pass only if every server journal contains zero bootstrap-decryption failures, etcd contains
exactly one bootstrap key, all nodes expose the same normalized join-credential digest through
their role-appropriate token path, all five nodes are Ready, the CA hash is unchanged, and all
three etcd members are healthy.

## Test B — stale token in one systemd unit

### Setup

Perform Test A's snapshot/token pairing, full server-token format assertion, and rotation,
without rolling every node. Retain both old and new token references outside evidence.

### Break

On exactly one configured server, install an owned systemd override whose `ExecStart` includes
the old token as `--token=`. Restart only that server and require a bootstrap-data decryption
failure/crash-loop signature. Positively prove the two untouched servers remain healthy, etcd
quorum remains, and the API is served. Loss of quorum is a distinct immediate failure because
it means Test B no longer represents its intended blast radius.

### Recovery

Start the recovery clock, stop K3s only on the failed server, and do not mutate etcd or restart
the healthy servers. Enumerate the full precedence surface and report every occurrence:

- main systemd unit `ExecStart`;
- every systemd drop-in directory;
- the K3s environment file;
- `/etc/default` and `/etc/sysconfig` K3s sources;
- the main K3s config and its `config.yaml.d` directory;
- the role-appropriate on-disk token file; and
- configured helper/rejoin script roots.

Token and credential deletion uses a separately reviewed exact-path allowlist. For each path,
record type, existence, owner, mode, and mtime before deletion. Reject symlinks, directories,
globs, path traversal, or any discovered path not exactly on that allowlist. Correct the stale
source, remove only allowed local credential/token files, reload systemd, start the failed
server, and wait within a fixed timeout for cluster health. Stop the clock when all nodes are
Ready.

### Gate

Pass only if the failed server rejoins, exactly one bootstrap key exists, normalized join
credentials match on all nodes, the post-recovery journal window contains neither “different
token” nor “newer than datastore”, all five nodes are Ready, the CA hash is unchanged, and all
three etcd members are healthy. Record stop-to-all-Ready recovery duration as a measured value.

## Test C — quorum loss during the roll

### Setup

Capture a known-good pre-rotation etcd snapshot and pair its exact path and digest with the old
token reference. Capture the baseline CA hash. Validate the proposed new token, register both raw
candidate values and their normalized secrets with the in-memory redaction registry, and retain
only redacted token references in evidence. A token that cannot normalize to a non-empty secret is
a caller error and aborts before mutation.

Derive and record both expected bootstrap key names before rotation. If the two candidates derive
the same key name, classify the observation `ANOMALOUS` and halt. A post-rotation snapshot is an
eligible recovery source only when its exact path, digest, and token reference were explicitly
paired before the failure; snapshot presence alone never selects it. Recovery input nominates
either one exact paired snapshot or none. An unselected pool of multiple snapshot pairs is not a
valid recovery input.

### Break

Force exactly two servers to start with the stale old token, producing quorum loss. Preserve
the third server's current datastore until triage is complete. The offline mock execution body
models and records these SETUP and BREAK observable contracts; real SETUP and BREAK operations
remain unimplemented.

### Pinned bootstrap-key derivation

This contract is pinned to K3s `v1.34.4+k3s1`, commit
`c6017918a65c824ce8d321db15267c8a317cd39d`, with embedded etcd
`k3s-io/etcd@server/v3.6.7-k3s1`, commit
`9f7f2c9540f1211570c2f23fd0baafc1d537662d`. The defining K3s sources are
`pkg/cluster/encrypt.go:storageKey:17-21` and
`pkg/util/token.go:NormalizeToken:41-49, ShortHash:67-70`.

The derivation is:

```text
key_path = "/bootstrap/" + hex( sha256( normalize(secret) ) )[:12]
```

Hex output is lowercase. For a full token of the form
`K10<64 hex chars>::<username>:<secret>`, normalization discards the complete `K10` CA-hash
segment and the username and retains only the secret. A bare secret is unchanged. The CA-hash
segment is neither hash input nor validated by the local reset path.

Twelve hexadecimal characters provide a 48-bit namespace: `2^48` possible suffixes, with a
birthday collision scale of approximately `2^24` independently chosen secrets. Candidate-key
equality is therefore `ANOMALOUS`, never evidence that the candidates represent the same era.

### Encryption era and payload era

The key name identifies the **encryption era**: the secret that encrypts the stored value and
therefore the token usable for bootstrap selection. It does not identify the **payload era**:
whether the encrypted value contains pre-rotation or post-rotation bootstrap content.

Rotation is non-atomic and has this observable sequence:

```text
A6: Create(new_key) containing the OLD payload, re-encrypted under the new secret
A7: Delete(old_key) in a separate transaction; its error is swallowed
A9: Update(new_key) with the NEW payload
```

The normal key-count trajectory is one old key, then two keys, then one new key; it never passes
through zero. `BOTH` is a normal transient and can persist after an A7 deletion error. From A6
until A9, both keys carry the old payload under different encryption. If execution reaches A9
after a swallowed A7 error, only the new-key payload is updated while the old key survives. In
either case, selecting one key does not remove the other and key names alone do not identify
payload contents. There is no newest-key rule.

### Triage interface and decision table

Triage must call one swappable discriminator and consume only its structured result:

```text
detect_bootstrap_era(
  observed_bootstrap_key_names,
  old_token_candidate,
  new_token_candidate
) -> {
  branch: OLD_ONLY | NEW_ONLY | BOTH | ZERO | ANOMALOUS,
  observed_key_names: [...exact non-secret key paths...],
  old_candidate_key_name: string,
  new_candidate_key_name: string,
  old_token_reference: redacted-token-reference,
  new_token_reference: redacted-token-reference,
  method: string,
  source_pin: string,
  reason: string
}
```

The triage layer may switch on `branch` but may not reinterpret observations, guess from
cardinality, or select a fallback. The exact states and actions are:

| Branch | Exact observation | Required action |
| --- | --- | --- |
| `OLD_ONLY` | `{old_key}` | Recover with the old candidate. |
| `NEW_ONLY` | `{new_key}` | Recover with the new candidate. |
| `BOTH` | `{old_key, new_key}` | Recover with either candidate according to the deterministic rule below, then prove the non-selected key survived and flag that exact key for cleanup. Recovery remains incomplete while both keys exist. |
| `ZERO` | Empty set | Halt with an unmistakable failure and perform no recovery mutation. The underlying reset would otherwise fabricate an empty lock and apparent era from the supplied token. |
| `ANOMALOUS` | Any other set, including an unmatched key, more than two keys, two keys with only one candidate match, duplicate observations, or a candidate derivation collision | Halt with no recovery mutation and report observed and expected names. |

For `BOTH`, the single snapshot pair explicitly nominated for use deterministically selects its
paired candidate. Supplying more than one pair is a caller error. Without a nominated snapshot,
the policy deterministically selects `NEW`, the intended rotation credential, and flags the old
key for cleanup. The reason and selected redacted reference are evidence.

### Recovery

The recovery form is selected solely by whether an eligible paired snapshot is being used, not
by the discriminator branch:

- **Form 1 — snapshot restore:** invoke cluster reset with the exact paired restore path and the
  secret paired with that snapshot.
- **Form 2 — membership only:** invoke cluster reset without any restore path and with the secret
  matching the selected surviving key. Preserve the survivor's locally committed data and reset
  membership to that one member.

Both forms must supply the selected token through an explicit `--token` argument. Omission,
token-file input, configuration/on-disk fallback, and retry with the other candidate are forbidden.
The recovery API requires a non-empty explicit token and has no token-file or fallback form. A
snapshot form additionally requires that its stored redacted token reference match the selected
candidate before mutation.

After a successful reset from `BOTH`, observe the key set before any key cleanup and assert that
the non-selected expected key still exists. Record it as `cleanup_required`; do not declare
recovery complete. Cleanup must delete only that exact orphan after separate authorization and
then capture the before/after key-name sets. No automatic newest-key selection is permitted.

After a permitted reset, remove only the exact local etcd data directory on each of the other two
servers, then restart them so they rejoin and resynchronize. These execution-body operations are
modeled only as observable contracts by the offline mock; their real implementations remain
outside the current increment.

### Reset-flag trap

A reset writes its reset flag under the configured etcd data directory before the forced
single-member start. The harness records the flag's exact path, presence, and nanosecond mtime
immediately before and after every reset attempt. A failed reset that leaves the flag present must
report that stranded path and mtime explicitly and state that a retry would be refused. A reset
attempt beginning with an existing flag is refused before mutation.

Normal recovery never removes this flag. `remove_reset_flag_explicitly` is a separate operation:
it requires an exact non-glob path, proves that no K3s process is running, records the path and
mtime, removes only that path, and verifies absence afterward.

### Gate

Pass only if exactly one bootstrap key survives and its full name equals the derived key path for
the explicit token the recovered cluster is demonstrably running with. The runtime credential
must be observed or independently verified; the intended selection is insufficient. For an
initial `BOTH`, evidence must additionally prove the non-selected key survived reset and explicit
orphan cleanup removed it. No reset flag may remain stranded.

Normalized join-credential digests must match across all nodes, post-recovery journals must
contain neither “different token” nor “newer than datastore”, the CA certificate hash must exactly
match baseline, all five nodes must be Ready, and all three etcd members must be healthy.

Any Test C failure is reported as the run's primary finding. The report must name the triage
branch, discriminator method, source pin and reason, observed and expected key names, selected
redacted token reference, recovery form, whether recovery was attempted, reset-flag observations,
required cleanup, key cardinality, and every failed assertion. `ZERO`, `ANOMALOUS`, a stranded
reset flag, or multiple final bootstrap keys can never be labeled a flake or partial pass.
