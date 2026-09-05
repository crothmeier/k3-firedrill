# P2 — Runbook before / after: the text the 2026-09-02 first attempt executed, and what replaced it

**Source:** Nexus (private records repo) `RUNBOOK_K3S_TOKEN_ROTATION_v1.md` at three commits:
- **v1.6 — `7cc7e99`** (2026-08-15): the text in force when the harness executed the rotation on 2026-09-02 attempt 1 (P3).
- **v1.7 — `a35f8a6`** (2026-09-02): the revision written from that attempt's evidence (F-TA-4).
- **v1.8 — `1f40250`** (2026-09-04): the revision written from the 2026-09-04 injection sitting (F-TB-1, F-TB-3; P4).

**Full-diff provenance (run in the records repo):**
```
git diff 7cc7e99 a35f8a6 -- RUNBOOK_K3S_TOKEN_ROTATION_v1.md     # 76 insertions, 35 deletions
git diff a35f8a6 1f40250 -- RUNBOOK_K3S_TOKEN_ROTATION_v1.md     # 9 insertions, 5 deletions
```
This file reproduces the hunks that matter to the claims: §1.6 (pre-staging recipe), §3 (per-node gates), P0.9 (one-surface ruling), §6 Branch B (recovery steps), §7 (failure-string register). Diff markers are the original `-`/`+`. Text inside ⟦double brackets⟧ is a pack substitution: production control-plane hostnames are aliased `prod-cp-A/B/C`, incident record identifiers are replaced by their role, and one external reviewer's name is replaced by its role. Nothing else is edited.

---

## Hunk 1 — §1.6 pre-staging (v1.6 → v1.7)

```diff
-**1.6 Pre-stage the new token everywhere — DO NOT restart anything.** Render (via Ansible from `vault_k3s_token`) into exactly one drop-in on all 7 nodes + fix the helper script. K3s reads the token only at process start, so pre-staging is safe.
+**1.6 Pre-stage the new token into the RULED surface only — DO NOT restart anything.** [rewritten v1.7 — F-TA-4] K3s reads the token only at process start, so pre-staging is safe. Write the new token **in place into the one surface ruled per node in §1.1**, and nowhere else. Do NOT add a `config.yaml.d` drop-in to a node whose ruled surface is something else — that is the two-surfaces-disagree shape that crash-looped server-2 on 2026-09-02. The v1.6 recipe (drop-in on all 7 + `sed` the env file) is WITHDRAWN: on a `--token=`-unit node it adds a losing surface, on a `config.yaml` node it adds a second one.
 ```
-install -d -m 755 /etc/rancher/k3s/config.yaml.d
-printf 'token: "%s"\n' "$NEW_TOKEN" > /etc/rancher/k3s/config.yaml.d/90-token-rotation.yaml
-sed -i "s|^K3S_TOKEN=.*|K3S_TOKEN=$NEW_TOKEN|" /etc/systemd/system/k3s.service.env 2>/dev/null || true
+# per node, ONE of the following, matching the §1.1 ruling — via Ansible render from vault_k3s_server_token / vault_k3s_agent_token where the surface is a render target:
+#   env-file surface:      sed -i "s|^K3S_TOKEN=.*|K3S_TOKEN=$NEW_TOKEN|" /etc/systemd/system/$U.service.env      # exactly one line must match
+#   config.yaml surface:   edit the existing 'token:' line in /etc/rancher/k3s/config.yaml (or the ruled config.yaml.d file)
+#   unit --token= surface: edit that ExecStart argument in place (daemon-reload happens at §3); this is the ⟦prior-rotation-incident⟧ shape — acceptable only because it is the measured winning surface today; migrating it is B1, not this runbook
+# then prove the write landed and is alone (names/counts only):
+grep -cE "^K3S_TOKEN=" /etc/systemd/system/$U.service.env 2>/dev/null     # 1 on env-file nodes, 0 elsewhere
+grep -lE '^(token|token-file):' /etc/rancher/k3s/config.yaml /etc/rancher/k3s/config.yaml.d/*.yaml 2>/dev/null   # exactly the ruled file, or nothing
 ```
-`[unverified]` — pre-staging as a hard prerequisite is a derived control (both DRs); K3s doesn't document it. It is the core anti-⟦prior-rotation-incident⟧ move. Do NOT `daemon-reload`+restart yet.
+Pre-staging as a hard prerequisite is a derived control (both DRs; K3s doesn't document it) — now **hardware-supported**: after the F-TA-4 fix (`4fda3de`, env-file surface) the harness pre-staged the env file, restarted in order, and produced clean rotations on 2026-09-02 (attempt 3 verified clean; attempt 4 the 7/7 PASS); before the fix, the same harness writing `server/token` reproduced the ⟦prior-rotation-incident⟧ failure. Do NOT `daemon-reload`+restart yet.
```

**Why it mattered:** the v1.6 recipe assumed one uniform token source across all nodes and wrote a second one. On the rehearsal cluster (install-script provisioning, `K3S_TOKEN=` in `k3s.service.env`) the harness's own hook — modelled on the same assumption — wrote the new token to `server/token`, a file k3s regenerates from the env value at start. Server-2 restarted on the old credential and crash-looped (P3).

## Hunk 2 — §3 per-node gates: before restart and after restart (v1.6 → v1.7)

```diff
-# (ii) new secret present in the WINNING config source (not merely present somewhere):
-grep -RIn '<NEW_SECRET>' /etc/rancher/k3s/config.yaml.d/ /etc/systemd/system/k3s*.service.env
-#      NOTE: config.yaml.d/ is last-value-wins by alphabetical filename. Confirm no LATER-sorting
-#      drop-in re-declares token: with a different/absent value that would override 90-token-rotation.yaml.
-# (iii) on-disk token file secret == new secret:
-awk -F'::' '{print $2}' $DATA_DIR/server/token
+# (ii) new secret present in THIS NODE'S RULED SURFACE (§1.1 table) and in no other surface — count, don't read:
+grep -RIl '<NEW_SECRET>' /etc/rancher/k3s/ /etc/systemd/system/*k3s*.service /etc/systemd/system/*k3s*.service.d/ /etc/systemd/system/k3s*.service.env 2>/dev/null | tee /dev/stderr | wc -l
+#      expect exactly ONE file, and it is the ruled surface. Two files = two surfaces = STOP (P0.9).
+#      If the ruled surface is config.yaml.d: it is last-value-wins by filename — confirm no later-sorting file declares token:.
+# (iii) [changed v1.7] record, do not gate on, the token file:
+awk -F'::' '{print $2}' $DATA_DIR/server/token | sha256sum | cut -c1-12      # digest only
+#      On S1 this is already NEW (rotate wrote it). On S2/S3 it is still OLD and MUST NOT be edited —
+#      k3s regenerates it from the configured surface at start (F-TA-4, measured). It becomes a gate AFTER restart, below.
 ```
-Gate — (i) empty, (i-b) all referenced files clean, (ii) new secret is the winning value, (iii) matches. **Only then:**
+Gate — (i) empty, (i-b) all referenced files clean, (ii) exactly one file and it is the ruled surface. **Only then:**
 ```
 systemctl daemon-reload
-systemctl restart k3s
-```
-
-**Post-restart gate (before the next server):**
-```
-journalctl -u k3s -n 50 --no-pager | grep -Ei 'bootstrap|fatal'   # expect NO "encrypted with different token"
+RESTART_AT=$(date -u +%FT%TZ); systemctl restart k3s
+```
+
+**Post-restart gate (before the next server)** [regeneration check added v1.7 — F-TA-4]:
+```
+# (a) regeneration: k3s rewrote server/token from the configured surface — its secret must now be NEW.
+#     If it is OLD, the ruled surface was wrong or lost to another surface; the node is on the stale token whether or not it has crashed yet.
+awk -F'::' '{print $2}' $DATA_DIR/server/token | sha256sum | cut -c1-12     # == digest of <NEW_SECRET>
+stat -c '%y' $DATA_DIR/server/token                                          # S2/S3: mtime >= $RESTART_AT (file was OLD, so a rewrite is expected — measured: peer file mtime = start time). S1: already NEW from §2, mtime may predate the restart; whether k3s rewrites an already-matching file is UNVERIFIED — gate S1 on content only
+awk -F'::' '{print $2}' $DATA_DIR/server/token | sha256sum | cut -c1-12 \
+  | diff - <(ssh S1 "awk -F'::' '{print \$2}' $DATA_DIR/server/token | sha256sum | cut -c1-12")   # identical to S1 (attempt-4 evidence: identical ×3)
+# (b) no stale-token signature since the restart:
+journalctl -u k3s --since "$RESTART_AT" --no-pager | grep -c 'encrypted with different token'   # 0
+journalctl -u k3s --since "$RESTART_AT" --no-pager | grep -c 'newer than datastore'             # 0
+systemctl show -p NRestarts --value k3s                                                         # 0 since this restart
+# (c) cluster:
 kubectl get nodes                                                  # this node Ready
 ETCDCTL_API=3 etcdctl endpoint health --cluster --cacert ... --cert ... --key ...   # 3/3
 kubectl -n kube-system get lease plndr-cp-lock -o jsonpath='{.spec.holderIdentity}'; echo
 ```
-- Crash-loop with `bootstrap data already found and encrypted with different token` → **Branch B immediately; restart no further node.**
-- `... newer than datastore and could cause a cluster outage` → different failure; **Branch B (newer-than-datastore variant).**
+Gate: (a) digest == NEW and == S1, mtime after restart; (b) all three zero; (c) Ready, 3/3, lease holder known. **Do not touch the next server until all three hold.**
+- Crash-loop with `bootstrap data already found and encrypted with different token` (→ then `cred/passwd newer than datastore`, ~5 s cadence; observed live 2026-09-02, NRestarts=38 in 4 min) → **Branch B immediately; restart no further node.**
+- `... newer than datastore and could cause a cluster outage` alone → different failure; **Branch B (newer-than-datastore variant).**
+- (a) OLD but no crash yet → the node has not reached bootstrap select; treat as Branch B now, do not wait for it.
```

**Why it mattered:** v1.6's pre-restart gate (iii) demanded that `server/token` already equal the new secret *before* restarting a peer. That is unsatisfiable by design — rotation never writes peers' files, and k3s regenerates the file from the configured surface at start. v1.7 demotes (iii) to record-only and moves the regeneration check to *after* the restart, where it is measurable.

## Hunk 3 — P0.9, the one-surface ruling (added v1.7; extended v1.8)

Added at `a35f8a6`:

```diff
+| P0.9 | **Token-surface ruling [added v1.7, from F-TA-4].** §1.1 inventory executed on all 7 nodes inside the window; for each node, exactly ONE surface ruled as the one this rotation writes, recorded in the change's exec log as a node → surface table; no second surface may hold any token value after §1.6. **No surface migration in flight:** B1 (⟦prod-cp-A⟧/⟦prod-cp-B⟧ `--token=` → `config.yaml.d` drop-in, PARKED 2026-08-29 after Phase 1) must be either COMPLETE on both nodes or NOT STARTED — a node with a `--token=` unit line AND a drop-in has two surfaces and is not rotation-eligible. The ruled surface is whatever is measured as winning on the day; this runbook does not migrate surfaces. | F-TA-4 (hardware, 2026-09-02) | ⬜ open — last measured surfaces: ⟦prod-cp-A⟧ `k3s.service` ExecStart `--token=` (08-29, env file size 0, no drop-ins); ⟦prod-cp-B⟧ `k3s.service` ExecStart `--token=` (07-10 sweep, not re-measured); ⟦prod-cp-C⟧ `/etc/rancher/k3s/config.yaml` `token:` (07-10); agents `k3s-agent.service.env` `K3S_TOKEN=` (07-10). All four are HISTORICAL until re-measured in-window. |
```

Extended at `1f40250` (inserted into the same row, after "…does not migrate surfaces."):

```diff
+**Two on-disk token forms [added v1.8, F-TB-1, measured 2026-09-04]:** a configured surface may hold the token in either form — the **bare secret** (measured: the lab's `k3s.service.env` holds `K3S_TOKEN='<64-hex>'`) or the **full `K10<ca>::server:<secret>` string** (measured: `server/token`, and the production `--token=` / `config.yaml` surfaces per the 07-10 sweep). Same credential, different bytes, different digests. The §1.1 table therefore records the **form** beside the surface for every node; every digest comparison in §3/§4/§5 is like-with-like (secret part vs secret part — `${TOKEN##*:}` — or whole file vs the same file on a peer), never env value vs token file; and terminal redaction covers both forms — `[a-f0-9]{64}` **and** `::server:[a-f0-9]*` — because `systemctl show -p ExecStart`, drop-in echoes, and `environ` reads print the bare form (the 09-04 sitting leaked the lab's OLD secret to a transcript through a `::server:`-only regex).
```

**What this says about production:** the three production control-plane nodes were last measured with *three different* token surfaces (unit argument, unit argument, config file), and the agents with a fourth (env file). Those measurements are dated July/August 2026 and are marked HISTORICAL until re-measured inside the change window. This is why the rehearsal cluster — env-file surface on every node — proves the *procedure*, not the production topology.

## Hunk 4 — §6 Branch B, steps 2–3 (v1.6 → v1.7 → v1.8)

Step 2 at `a35f8a6`:

```diff
-2. Re-run the §3 (expanded) verify gates; find + fix the stale token source (systemd unit `--token=` / env / config / drop-in / **helper script** — ⟦prior-rotation-incident⟧'s exact origin).
+2. Re-run the §3 (expanded) verify gates; find + fix the stale token source (systemd unit `--token=` / env / config / drop-in / **helper script** — ⟦prior-rotation-incident⟧'s exact origin). [v1.7] Check for the F-TA-4 shape specifically: the NEW value was written somewhere k3s does not read (`server/token`, or a drop-in on a node whose winning surface is the unit or the env file) while the ruled surface still holds OLD — `server/token` content OLD with an mtime at the restart time is the fingerprint (measured 2026-09-02). Fix the ruled surface; delete any second surface you added.
```

Step 3 at `1f40250` (the step the 2026-09-04 sitting exercised — P4c/P4d):

```diff
-3. **`[⟦external-review⟧ correction — the timestamp trap this branch originally missed]`** Fixing the token source alone can still fatal with **"newer than datastore and could cause a cluster outage"** if any on-disk file retained a newer mtime from the partial restart. **Explicitly delete** `$DATA_DIR/server/cred/passwd` **and** `$DATA_DIR/server/token` (and any file flagged newer in triage step 3) so they re-derive from the healthy quorum's datastore. This is **safe and does NOT cascade** — it forces this node to pull current bootstrap data (incl. preserved CA) from etcd; other nodes untouched, quorum intact. Without this delete, the trap remains.
+3. **`[⟦external-review⟧ correction — the timestamp trap this branch originally missed]`** Fixing the token source alone can still fatal with **"newer than datastore and could cause a cluster outage"** if any on-disk file retained a newer mtime from the partial restart. **[v1.8 — F-TB-3, measured 2026-09-04: assume it did.]** The failed node's *own* wrong-token start is what arms the trap: the first attempt reconciles `cred/passwd` and `server/token` from the datastore *before* it fails the token check, so both files carry an mtime later than the rotation write by the time you reach this step (measured: rewritten at +0.8 s / +3.4 s into the first crash-loop attempt; five refusals on the correct token after the source fix, cleared only by the delete). Treat this step as **unconditional** in Branch B — do not skip it on a clean-looking triage step 3, and do not "try a restart first". **Explicitly delete** `$DATA_DIR/server/cred/passwd` **and** `$DATA_DIR/server/token` (and any file flagged newer in triage step 3) so they re-derive from the healthy quorum's datastore. This is **safe and does NOT cascade** — it forces this node to pull current bootstrap data (incl. preserved CA) from etcd; other nodes untouched, quorum intact. Without this delete, the trap remains.
```

## Hunk 5 — §7 register: the pinned strings, and the two "observed live" paragraphs

The register rows the sittings matched (unchanged text, present since v1.5):

| Row | Register string (verbatim) |
|---|---|
| 3 — stale token at bootstrap | `Shutdown request received: failed to save bootstrap data: bootstrap data already found and encrypted with different token` |
| 5 — disk newer than datastore | `<path>[, <path>...] newer than datastore and could cause a cluster outage. Remove the file(s) from disk and restart to be recreated from datastore.` |

Added at `a35f8a6`:

```diff
+**Observed live 2026-09-02 (lab, server-2, `v1.34.4+k3s1`):** rows 3 and 5 of this table, verbatim, in that order — `Shutdown request received: failed to save bootstrap data: bootstrap data already found and encrypted with different token` at 07:02:29Z, then the `cred/passwd newer than datastore …` fatal at 07:02:34Z and every ~5 s after (`EXEC_LOG_2026-09-02_P06_TEST_A_FIRST_CONTACT.md` §3). The surviving server logged `Failed to retrieve HTTP bootstrap data from datastore; falling back to disk for <peer>… etcdserver: key not found` while the stale peer asked with the old key. The register is no longer source-only.
```

Added at `1f40250`:

```diff
+**Observed live 2026-09-04 (lab, server-2, `v1.34.4+k3s1`, `EXEC_LOG_2026-09-04_P06_TEST_B.md` §1 b1 / §2) — the wrong-token start arms the "newer than datastore" trap by itself (F-TB-3).** Sequence within the first crash-loop attempt, ordered by journal and file mtimes against the rotation's datastore write at 11:18:31Z: `Reconciling bootstrap data between datastore and disk` → `cred/passwd will be updated from the datastore.` → `Updating bootstrap data on disk from datastore` → `cred/passwd` rewritten (mtime 11:19:30.848Z) and `server/token` rewritten (11:19:33.386Z) → row 3 (`encrypted with different token`) → exit. Every later attempt in the same loop (from +9 s) logged row 5 instead, with `cred/passwd` as the named path; after the source was fixed and the override removed, five consecutive starts on the correct token still logged row 5, and only the two-path delete cleared it (recovery `active` in 10 s, `server/token` regenerated with the rotating server's digest). Consequences for the register: (i) row 5 is the *steady-state* signature of a stale-token server, row 3 appears once — a `grep -c` for row 3 alone under-counts a crash loop, so §3/§6 gates count both; (ii) row 5's full text at this tag matches the table verbatim (`… newer than datastore and could cause a cluster outage. Remove the file(s) from disk and restart to be recreated from datastore.`); (iii) the disk-reconcile-before-token-check ordering is **UNVERIFIED at source** — measured once by mtimes; the candidate pin is the call order inside `pkg/cluster/bootstrap.go:Bootstrap` / `ReconcileBootstrapData` relative to the token-select failure, not yet read. The "not a token condition" paragraph below stands: the trap is armed by the byte-and-mtime comparison, which the stale start satisfies as a side effect.
```

---

## Status line at each version (header, verbatim fragment)

- v1.6: "NOT execution-ready: ⟦prior-rotation-incident⟧ preconditions + scratch rehearsal (incl. the Branch-C test) REQUIRED before any run."
- v1.7: "NOT execution-ready: P0.1, P0.6 tests (b)/(c), P0.7, P0.8, and the new P0.9 token-surface ruling remain open."
- v1.8: "NOT execution-ready: P0.1, P0.6 test (c), P0.7, P0.8, and the P0.9 token-surface ruling remain open."

The runbook has never been marked execution-ready. No procedure step in §1–§5 changed between v1.7 and v1.8; v1.8 added notes and made Branch B step 3 unconditional.
