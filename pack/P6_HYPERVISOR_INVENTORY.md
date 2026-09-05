# P6 — Hypervisor inventory: three control-plane VMs on one host

**Source:** Nexus (private records repo) `EXEC_LOG_2026-09-04_P06_LAB_READONLY_CAPTURE.md` @ `dbc0d51`, §3 Block C rows C1–C3 (read-only, 22:53–22:55Z, values copied from the frozen evidence file whose sha256 is given in P5).
**Substitutions:** the hypervisor's hostname is the mirror's alias **`lab-hv01`**; its management address `203.0.113.40` (RFC 5737); guest addresses `198.51.100.N`. Dropped from the quoted C1/C2 rows: the NVMe model/serial, guest MAC addresses, and the cloud-init `sshkeys` field. Nothing else edited.

---

## C1–C3 (verbatim, with the drops above)

> | ID | Check | Expected | Measured | PASS/FAIL |
> |---|---|---|---|---|
> | C1 | `pveversion -v` / `labtank` / `pvesm` | 9.2.5 · single nvme, 0/0/0 · `labtank-guests` active | `proxmox-ve: 9.2.0`, `pve-manager: 9.2.5`; `labtank` 476G / 9.11G alloc / ONLINE, single vdev `nvme-⟦model/serial dropped⟧`, 0/0/0; `labtank-guests` zfspool active 1.97 %, `local` dir active, `local-lvm` disabled; `/etc/pve/qemu-server/` 7100–7104.conf mtime Sep 4 07:25–07:26 EDT (= rollback #6, 11:25–11:26Z), 999/9000 Jul 29 | PASS |
> | C2 | `qm config` ×5 | `bridge=vmbr1`; `ipconfig0 ip=198.51.100.1N/24,gw=198.51.100.1`; `agent: 1`; 4096/20G ×3, 2048/15G ×2; names match | all five: `net0: virtio=⟦MAC dropped⟧,bridge=vmbr1`; `ipconfig0` `.10–.14/24, gw .1`; `agent: 1`; `cores: 2`; memory 4096/4096/4096/2048/2048; scsi0 20G/20G/20G/15G/15G on `labtank-guests`; names `k3fd-server-1..3`, `k3fd-agent-1..2`; `parent: p06-baseline` ×5; `description: firedrill-owner:fd-20260830t151047z-370455`; `ciuser: labops`, `cipassword` masked | PASS |
> | C3 | `qm listsnapshot` ×5 | `firedrill-baseline` (08-30) → `p06-baseline` (09-01 03:29Z) → `current`, parent/child on all five | 7100–7104: `firedrill-baseline` 2026-08-30 11:37:05/19/34/48, 11:38:02 → `p06-baseline` 2026-09-01 03:29:27/31/35/39/44 "P0.6 quiesced baseline 2026-09-01, zero k3s PIDs verified" → `current` | PASS |

Host identity from the same log's A1 row: `lab-hv01` · `pve-manager/9.2.5/20242970da7fbcef` · kernel `7.0.14-8-pve`.

---

## What this proves, and what it does not

**Measured (C1–C3):**
- One hypervisor host (`lab-hv01`, Proxmox VE 9.2.5, one kernel `7.0.14-8-pve`).
- One storage pool (`labtank`, ZFS, a single NVMe vdev; every guest's `scsi0` is on `labtank-guests`).
- Five guests 7100–7104 = `k3fd-server-1..3` (the three etcd/control-plane servers) and `k3fd-agent-1..2`, all on one bridge `vmbr1`, all with the same snapshot lineage.

So the "other two servers held quorum" observations in P3 and P4 were made **inside one failure domain**: one kernel, one storage pool, one host. Partition behaviour between servers was not, and could not be, exercised. This is a rehearsal of the *procedure* (rotation, the stale-credential crash, Branch B recovery) and of the tooling — not of the production topology and not of high availability.

**Asserted, not measured in this capture:**
- **One power domain.** The host is a single box; the capture did not inventory UPS or circuit. The claim follows from C1 (one physical host) but no power-side reading was taken.

**Correction to earlier project prose.** Earlier gate-review packets stated that this single-failure-domain limit was "written into the project's open-questions document". At the mirrored commit (`11748cc`) `docs/OPEN_QUESTIONS.md` contains **no** such line. The closest committed disclosure is its "VIP and host-type gap" section, quoted here verbatim (that file is not part of the public mirror):

> ## VIP and host-type gap
>
> The lab consists entirely of virtual machines and does not model the production floating API
> VIP or the mix of bare-metal and virtualized control-plane hosts. It cannot rehearse VIP
> failover during server restarts, and its default `server-1`-first order must not be copied into
> production. Production ordering needs a separate decision based on VIP placement, workload
> impact, and host type.

The single-failure-domain statement is made *here*, on the strength of C1–C3, and is owed to that document as a follow-up edit.
