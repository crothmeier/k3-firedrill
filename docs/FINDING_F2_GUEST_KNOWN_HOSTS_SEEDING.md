# Finding F-2 — guest host-key trust must be seeded by the operator

Status: CONFIRMED 2026-08-30, MITIGATED for run fd-20260830t151047z-370455;
procedure below is the standing mitigation until a design change is ruled
Classification: undocumented operator prerequisite (not a code defect)

## Statement

The guest SSH transport uses `StrictHostKeyChecking=yes` against
`guest_ssh_known_hosts_path`, and nothing in the harness ever populates that
file — `ssh-keyscan` appears nowhere in the codebase. Each clone generates
fresh host keys at first boot, which happens mid-provision, so as shipped
`driver_impl_guest_wait_access` can never succeed: it retries to the
`guest_access_timeout_seconds` bound and exits 70.

Measured 2026-08-30: empty known-hosts file, probe exit 255
("Host key verification failed"), keyscan of the booted guest returning a
valid ed25519 key.

## Why this is not fixed in code

Automating trust-on-first-use inside the harness would silently accept
whatever host answers on the guest IP. Refusing to do that is correct
fail-closed design. The defect is that the resulting operator obligation was
documented nowhere and cannot be satisfied per-guest mid-provision without
racing the access timeout.

## Standing operator procedure

Trust ruling: appending keyscan output is TOFU over the lab L2. Running the
commands is the ruling; it is scoped to the five disposable guests.

1. Run `provision` once. It will create all five guests, start the first,
   and (without seeding) wait on guest access.
2. Start the remaining guests manually so their host keys exist
   (`already-running` is a supported resume state):
   `qm start 7101 7102 7103 7104` on the PVE host, then wait ~90s.
3. Harvest all five keys from the harness seat:

   ```sh
   for ip in <five guest IPs>; do
       ssh-keyscan -t ed25519 "$ip" >> <guest_ssh_known_hosts_path>
   done
   ```

4. Verify five entries and a working transport, then rerun `provision`;
   every wait_access then passes on sight.

Snapshot interaction: guest host keys are baked into the `firedrill-baseline`
snapshots, so rollback does NOT invalidate the seeded file. Destroying and
reprovisioning generates new keys — remove the old entries and reseed.

## Open design option (unruled)

A `firedrill seed-trust` helper that performs steps 2–3 under explicit
operator confirmation would remove the manual race without weakening the
fail-closed default. PROPOSED only; requires an operator ruling and a
dispatch.
