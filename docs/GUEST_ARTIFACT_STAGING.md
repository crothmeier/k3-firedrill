# Template 9000 air-gap staging procedure

This procedure is an operator action. The harness never downloads artifacts, grants the lab
egress, or modifies template 9000. Perform it only from the reviewed repository checkout and an
authenticated, out-of-band copy of the pinned release artifacts.

## 1. Prepare and pin the staging set

On the trusted staging seat, collect exactly these four files:

| Source | Template path | Owner | Mode |
|---|---|---:|---:|
| repository `guest/firedrill-op` | `/usr/local/sbin/firedrill-op` | `0:0` | `0755` |
| pinned K3s binary | `/opt/firedrill/artifacts/k3s` | `0:0` | `0755` |
| pinned K3s install script | `/opt/firedrill/artifacts/install.sh` | `0:0` | `0755` |
| pinned `etcdctl` binary | `/opt/firedrill/artifacts/etcdctl` | `0:0` | `0755` |

Obtain the three artifact SHA-256 values from the operator-approved official manifests for the
exact staged files. Put those lowercase 64-hex values into `k3s_binary_sha256`,
`k3s_install_script_sha256`, and `etcdctl_sha256` in the uncommitted `firedrill.conf`. Do not put
the files, hashes from an unreviewed source, or any join credential in this repository.

Create a root-only transfer directory on the PVE host and copy the four already-obtained files
into it. This example uses `/root/firedrill-template-9000`; the transfer mechanism is site-owned
and is not part of the harness:

```sh
install -d -o 0 -g 0 -m 0700 /root/firedrill-template-9000
install -o 0 -g 0 -m 0755 guest/firedrill-op /root/firedrill-template-9000/firedrill-op
install -o 0 -g 0 -m 0755 K3S_BINARY /root/firedrill-template-9000/k3s
install -o 0 -g 0 -m 0755 K3S_INSTALL_SCRIPT /root/firedrill-template-9000/install.sh
install -o 0 -g 0 -m 0755 ETCDCTL_BINARY /root/firedrill-template-9000/etcdctl
```

Before touching the template, run `sha256sum` on the three transferred artifacts and compare
each complete digest, character for character, with the corresponding filled configuration
value. A missing value, placeholder, mismatch, or unexpected fourth artifact is a stop condition.

## 2. Customize the stopped template offline

Template 9000 must be stopped. Record `qm config 9000`, identify the configured OS-disk volume
from the exact `pve_os_disk` key, and resolve that volume with `pvesm path`. Do not guess a ZFS
device name and do not use a cloud-init volume.

```sh
qm status 9000
qm config 9000
pvesm path VOLUME_ID_FROM_THE_CONFIGURED_OS_DISK
```

The required status is `stopped`. Set `OS_DISK_PATH` below to the exact `pvesm path` result.
This procedure uses `virt-customize` against that offline disk. If `virt-customize` is absent,
cannot inspect the filesystem, or reports the disk in use, stop; no alternate mount or live-boot
procedure is authorized by this document.

```sh
virt-customize -a OS_DISK_PATH \
  --mkdir /opt/firedrill \
  --mkdir /opt/firedrill/artifacts \
  --mkdir /etc/firedrill \
  --copy-in /root/firedrill-template-9000/k3s:/opt/firedrill/artifacts \
  --copy-in /root/firedrill-template-9000/install.sh:/opt/firedrill/artifacts \
  --copy-in /root/firedrill-template-9000/etcdctl:/opt/firedrill/artifacts \
  --copy-in /root/firedrill-template-9000/firedrill-op:/usr/local/sbin \
  --chmod 0755:/opt/firedrill \
  --chmod 0755:/opt/firedrill/artifacts \
  --chmod 0700:/etc/firedrill \
  --chmod 0755:/opt/firedrill/artifacts/k3s \
  --chmod 0755:/opt/firedrill/artifacts/install.sh \
  --chmod 0755:/opt/firedrill/artifacts/etcdctl \
  --chmod 0755:/usr/local/sbin/firedrill-op \
  --chown 0:0:/opt/firedrill \
  --chown 0:0:/opt/firedrill/artifacts \
  --chown 0:0:/etc/firedrill \
  --chown 0:0:/opt/firedrill/artifacts/k3s \
  --chown 0:0:/opt/firedrill/artifacts/install.sh \
  --chown 0:0:/opt/firedrill/artifacts/etcdctl \
  --chown 0:0:/usr/local/sbin/firedrill-op
```

Do not stage `/etc/firedrill/op.env` or `/etc/firedrill/join.env`. During provisioning the
harness writes the per-node runtime file and the credential-bearing join file through
`driver_guest_put`; both arrive root-owned and mode `0600`, and the join file is removed only
after its node's install succeeds.

`virt-customize` runs an automatic side-operation that writes a machine ID into an empty
`/etc/machine-id`. A template's machine-id must stay empty or every clone shares one identity,
so restore it and verify zero bytes (measured 2026-08-30, finding F-6):

```sh
virt-customize -a OS_DISK_PATH --truncate /etc/machine-id
virt-cat -a OS_DISK_PATH /etc/machine-id | wc -c
```

The user-supplied `--truncate` runs after the automatic side-operations, so the end state is
empty even though the second invocation reports setting the machine ID again. On a PVE host
there is no libvirtd; if any virt tool errors on the libvirt socket, prefix it with
`LIBGUESTFS_BACKEND=direct`.

## 3. Verify the image before provisioning

Set the three shell variables to the filled configuration values, then run the following against
the same stopped OS disk. The command is read-only with respect to the guest filesystem.

```sh
K3S_SHA256=FILLED_k3s_binary_sha256
INSTALL_SHA256=FILLED_k3s_install_script_sha256
ETCDCTL_SHA256=FILLED_etcdctl_sha256

test "$(virt-cat -a OS_DISK_PATH /opt/firedrill/artifacts/k3s | sha256sum | awk '{print $1}')" = "$K3S_SHA256"
test "$(virt-cat -a OS_DISK_PATH /opt/firedrill/artifacts/install.sh | sha256sum | awk '{print $1}')" = "$INSTALL_SHA256"
test "$(virt-cat -a OS_DISK_PATH /opt/firedrill/artifacts/etcdctl | sha256sum | awk '{print $1}')" = "$ETCDCTL_SHA256"
cmp guest/firedrill-op <(virt-cat -a OS_DISK_PATH /usr/local/sbin/firedrill-op)
virt-ls -l -a OS_DISK_PATH /opt/firedrill/artifacts
virt-ls -l -a OS_DISK_PATH /usr/local/sbin/firedrill-op
virt-ls -l -a OS_DISK_PATH /etc | grep -E ' firedrill$'
```

Do not use `virt-ls -ld`: for virt-ls, `-d` means `--domain` and forces a libvirt connection
that does not exist on a PVE host (finding F-6). List the parent directory and read the
`firedrill` row instead; require `drwx------` owned `0 0`.

All four comparisons must return zero. The listings must show root ownership, artifact and
script mode `0755`, and `/etc/firedrill` mode `0700`. Re-run `qm config 9000` and require the
template flag and configured OS-disk key to remain unchanged. Only then run the repository's
offline gate and PVE preflight.

The harness independently re-hashes all three staged artifacts before every install and before
every observation that uses them. The operator verification does not weaken or replace that
runtime guard.
