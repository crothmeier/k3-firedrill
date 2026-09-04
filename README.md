# k3-firedrill

`k3-firedrill` is a failure-rehearsal harness for server-token rotation on a disposable,
three-server embedded-etcd K3s cluster. Its purpose is to make recovery claims reviewable:
commands, output, state observations, timings, and gate verdicts are retained as redacted
machine-readable evidence.

This checkout implements the `mock` lifecycle and the offline Test A, Test B, and Test C
execution bodies with evidence-derived gates. The `pve` driver implements lifecycle primitives,
the air-gapped guest interface, and the six real Test A hooks; Test B/C remain fail-closed at
exit 69. The `libvirt` driver remains a fail-closed stub, and `test-all` intentionally exits 69.
Passing an offline test makes no claim about real-hardware rotation or recovery. The PVE Test A
hooks have transport-stub coverage only and have never been executed against a cluster. Follow
`docs/GUEST_ARTIFACT_STAGING.md` and `docs/PVE_DRIVER_VERIFICATION.md` before first use.

## Why `./firedrill` is the entrypoint

The executable provides one place for strict mode, error and cleanup traps, configuration
selection, stable exit codes, confirmation handling, and driver loading. `make` is retained
only for the mandatory local quality gate; it is not the operator control surface.

## Safety boundary

Configuration is parsed as literal lowercase `key=value` data. It is never sourced or
evaluated as shell. Missing, duplicate, malformed, and placeholder values abort with the
variable's purpose.

Before every driver mutation—not merely during `preflight`—the harness:

1. probes the selected hypervisor's identity and requires an exact match with
   `expected_hypervisor_hostname`;
2. checks every configured hypervisor, gateway, guest IP, and guest hostname against the
   optional exact-match `firedrill.denylist`;
3. requires the guest's numeric allocation ID to be both inside `vmid_base..vmid_base+4`
   and present in the exact five-node inventory; and
4. for an existing guest, requires a driver-specific ownership marker matching the active
   `lab_id`.

The local state file is evidence, not authorization. An ID in state still cannot be mutated
without live identity and ownership checks. `destroy` additionally requires the exact active
lab ID through `--confirm` and retains the run evidence after deleting guests.

The committed addresses use RFC 5737 documentation space and `.invalid` hostnames. They are
not production examples and real drivers reject a `.invalid` hypervisor target.

## Configuration

Copy both examples before local use:

```sh
cp firedrill.conf.example firedrill.conf
cp firedrill.denylist.example firedrill.denylist
```

Every setting is explained in `firedrill.conf.example`. Common safety, allocation,
addressing, version, snapshot, and evidence settings are always required. SSH and
hypervisor-specific values are required only when their real driver is selected. PVE additionally
requires a local mode-0600 join-credential file and exact SHA-256 pins for the staged K3s binary,
K3s install script, and `etcdctl`; the committed placeholders deliberately reject real use.

The five planned nodes are fixed in this increment:

| Node | Allocation | CPU | Memory | Disk |
|---|---:|---:|---:|---:|
| server-1 | `vmid_base+0` | 2 | 4 GiB | 20 GiB |
| server-2 | `vmid_base+1` | 2 | 4 GiB | 20 GiB |
| server-3 | `vmid_base+2` | 2 | 4 GiB | 20 GiB |
| agent-1 | `vmid_base+3` | 2 | 2 GiB | 15 GiB |
| agent-2 | `vmid_base+4` | 2 | 2 GiB | 15 GiB |

## Offline mock workflow

The mandatory local gate uses no network, SSH client, hypervisor tool, cluster, or registry.
It requires Bash 3.2 or newer, Python 3.11 or newer, Ruff, and ShellCheck to already be
installed; the Makefile never downloads tooling:

```sh
make test
./firedrill preflight
./firedrill provision
./firedrill baseline
./firedrill test-a
./firedrill report
./firedrill rollback
./firedrill test-b
./firedrill report
./firedrill rollback
./firedrill test-c
./firedrill report
./firedrill rollback
```

`provision` prints the generated lab ID. Destruction requires that exact value:

```sh
./firedrill destroy --confirm fd-YYYYMMDDTHHMMSSz-abcdef
```

Re-running `provision` for an already provisioned or baselined active lab is a no-op.
An active lab with a different configuration is a hard error. Baseline capture is also a
no-op when it already exists.

## Evidence and state

`provision` creates a timestamped run beneath `run_dir` and updates `current.json`. Each run
contains:

```text
RUN/
├── manifest.json
├── state.json
├── driver/mock.json
├── evidence/
│   ├── commands.jsonl
│   ├── commands/*.stdout.log and *.stderr.log
│   ├── test-a/{phases.json,gate-observation.json,gate.json,gate-table.md}
│   ├── test-b/{setup.json,break.json,recovery.json,phases.json,
│   │           gate-observation.json,gate.json,gate-table.md}
│   └── test-c/{setup.json,break.json,triage.json,recovery.json,
│              recovery-finish.json,phases.json,gate-observation.json,
│              final-bootstrap-key.json,gate.json,gate-table.md}
├── baseline/
│   ├── ca.sha256
│   ├── cluster-state.json
│   └── snapshots.json
└── report.md
```

Command records contain ordered sequence numbers, timestamps, node, redacted argv, exit
status, stdout, and stderr. Full-format K3s tokens are replaced with a short prefix and a
SHA-256 reference before evidence is written. YAML token keys and token-bearing command or
environment syntax are redacted as backstops. The evidence writer also consumes the in-memory
JSON array in `FIREDRILL_ACTIVE_TOKENS_JSON`; literal and whitespace-normalized occurrences of
those known values are removed anywhere in argv, stdout, stderr, journals, or captured file
content. Console replay comes from the sanitized artifacts rather than the raw capture files.
Future token-handling code must keep this registry current, keep raw tokens out of state, and
pass only redacted references to the reporting layer.

## Planned real-hardware sequence

The PVE lifecycle and Test A sequence are implemented but the new guest and Test A paths
**have not been verified on real hardware**. Test B, Test C, and `test-all` are not runnable:

1. Prepare an isolated bridge and the reviewed Ubuntu cloud-init template on ZFS; stage the
   pinned offline set with `docs/GUEST_ARTIFACT_STAGING.md`.
2. Allocate five unused consecutive VMIDs and a disposable subnet.
3. Fill `firedrill.conf`, populate the denylist with forbidden production targets, and review
   the computed inventory.
4. Run `make test`, then `./firedrill preflight`.
5. Run `./firedrill provision`, verify the five guests, then `./firedrill baseline`.
6. After the lifecycle evidence is reviewed, follow the Test A walk in
   `docs/PVE_DRIVER_VERIFICATION.md`; stop on any abort point and do not improvise recovery.
7. Confirm that `test-b`, `test-c`, and `test-all` still exit 69 with `driver=pve`.
8. Attach the retained lifecycle and Test A evidence to the execution record.
9. After review, run `./firedrill destroy --confirm LAB_ID`.

Real Test B/C hooks still require a separate reviewed increment.

## Restart-order caveat

The lab default is `server-1,server-2,server-3`, deliberately exercising the cluster-init
server first while two other etcd members remain. This is a lab choice, not production
guidance. Production ordering also depends on the floating API VIP location and a mix of
bare-metal and virtualized control-plane hosts. This five-VM lab models neither factor and
cannot rehearse VIP failover during the roll. See `docs/OPEN_QUESTIONS.md`.

## Exit behavior

Configuration errors use exit 65, state errors 66, missing snapshots 67, driver/model errors
69, bounded-health timeout uses 70, Test B blast-radius violations use 71, and safety guard
failures use 78. All failures are loud; an unimplemented real-driver or failure-test path never
degrades into a mock success.
