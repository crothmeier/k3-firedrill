# P4 — 2026-09-04: deliberate stale-credential injection on one server, and recovery

**Source:** Nexus (private records repo) `EXEC_LOG_2026-09-04_P06_TEST_B.md` @ `48b4fb6` (wording of §5 later adjusted at `1f40250`; nothing quoted here changed). Sections lifted: §0.1 (setup), §1 b1/b2/b3, §2 (timestamp-trap beat), §4 (findings table, two rows).
**Substitutions:** none needed in the quoted sections (node names are already generic; addresses do not appear). The injected node's alias throughout is **`server-2`**, the same name P3 uses. Elisions are marked `[…]`.
**Setting:** same five-VM rehearsal cluster as P3, restored to snapshot `p06-baseline` before the sitting. Manual procedure (the harness's Test B hooks are deliberately fail-closed; this was run by hand from the runbook's annex). Every command ran in the operator's terminal and was pasted back; no production system touched.

The five items a reader asked for are marked **P4a–P4e** in the margin.

---

## §0.1 Setup — capture/mint, reconnaissance, rotate on server-1 only (verbatim)

> - **A2 (srv-1, 11:17:17Z):** OLD copied to `/root/p06-OLD-token.txt` (141 B, 0600); NEW minted per runbook §1.5 (`K10<ca>::server:<openssl rand -hex 24>`) to `/root/p06-NEW-token.txt` (124 B, 0600). **WS-7 old key `0a6c128f5dad`** (= live bootstrap key ✓), old digest `0b0ff4b8d018`. **WS-8 new key `2af7b510f61e`**, new file digest `353165aec15b`. CA hash prefix `744d6a` ✓.
> - **srv-2 reconnaissance (11:17:28Z, read-only):** `systemctl cat k3s` — `EnvironmentFile=-/etc/systemd/system/k3s.service.env`, multi-line install.sh `ExecStart` (`server`, `--node-name server-2`, two `--node-label firedrill.internal/join-sha256-*`), **no token in ExecStart**; env file 113 B, 0600, mtime 2026-08-30 15:31, exactly one `K3S_TOKEN=` line; no `k3s.service.d`; no `/etc/rancher/k3s/config.yaml.d`. Allowlist paths, both regular files: `cred/passwd` 175 B mtime **2026-08-30 15:30:55Z**; `server/token` 141 B mtime **2026-09-04 11:12:52Z** (regenerated at this boot — F-TA-4 behaviour re-observed).
> - **Ruling (operator, by non-objection to the stated default):** stage NEW into srv-2's `k3s.service.env` **before** b1, so the OLD-token override is the single stale surface and its removal in b2 is exactly parent §4's "fix the token source to NEW". […]
> - **Rotate (srv-1, 11:18:31Z […]):** `k3s token rotate --token <OLD> --new-token <NEW>` → `Token rotated, restart k3s nodes with new token`, exit 0. `/bootstrap` → exactly `/bootstrap/2af7b510f61e` (WS-8 gate PASS). srv-1 `server/token` digest now `91112ccfab36`; srv-1 `active`; 5/5 Ready. No other node rolled.
> - **NEW carried to srv-2** via seat pipe (`ssh srv-1 cat | ssh srv-2 cat >`), digest on srv-2 `353165aec15b` ✓.

**Reading note.** The datastore's rotation write is at **11:18:31Z**; every "newer than" comparison below is against that instant. The injection method is a systemd drop-in forcing the OLD token onto server-2's command line — the "hardcoded token in a unit" shape the runbook names as the prior incident's origin.

---

## §1 b1 — induce + blast radius (server-2) · 11:19:29Z → 11:19:55Z (verbatim)

> - OLD captured from srv-2's own env file (`sed -n 's/^K3S_TOKEN=//p'`) → digest `d21421511cdf` — **differs from `server/token`'s `0b0ff4b8d018` because the env surface holds the bare 64-hex secret (single-quoted) while `server/token` holds the `K10<ca>::server:<secret>` form**; same credential, two on-disk forms (§4 F-TB-1 note).
> - NEW staged into env: 1 `K3S_TOKEN=` line, value digest `353165aec15b`, 0600 root:root, harness env-edit pattern.
> - Drop-in `/etc/systemd/system/k3s.service.d/90-p06-testb.conf` (0600): `ExecStart=` reset, then the verbatim multi-line ExecStart with `'--token' '<OLD>'` appended. `systemctl show -p ExecStart` confirmed argv `… --token <OLD>`.
> - `systemctl daemon-reload && systemctl restart --no-block k3s` at **11:19:30Z**; after 25 s: `is-active` **activating**, `NRestarts 4`.
> - **Signature count: 1.** Observed verbatim (11:19:33Z, pid 1894): **⟵ P4a**
>   `level=error msg="Shutdown request received: failed to save bootstrap data: bootstrap data already found and encrypted with different token"`
> - Subsequent attempts (11:19:39 / :44 / :50, pids 1936/1954/1972) logged instead:
>   `level=fatal msg="/var/lib/rancher/k3s/server/cred/passwd newer than datastore and could cause a cluster outage. Remove the file(s) from disk and restart to be recreated from datastore."`
>   — the timestamp trap fired **inside b1's crash loop**, before b2. Cause, MEASURED by mtimes: attempt 1 logged `Reconciling bootstrap data between datastore and disk` → `cred/passwd will be updated from the datastore.` → `Updating bootstrap data on disk from datastore` at 11:19:30 and rewrote `cred/passwd` (mtime 11:19:30.848Z) and `server/token` (11:19:33.386Z), both later than the 11:18:31Z rotation write, then died on the token check. Why k3s reconciles disk from datastore before failing the token check is UNVERIFIED at source level.
> - **Blast radius (from srv-1, 11:20:13Z):** srv-1 `active`; etcd `.10 true 9.0 ms`, `.12 true 8.4 ms`, `.11 false context deadline exceeded` (`connection refused`); `/bootstrap` one key `2af7b510f61e`; API served from srv-1: agent-1/2, server-1/3 Ready, **server-2 NotReady only**. Quorum held. **Stop condition not fired.** **⟵ P4b**
>
> **b1 verdict: PASS** (signature ≥1, blast radius exactly one server).

### P4b — what the observer evidence does and does not show

Measured, from server-1 at 11:20:13Z, while server-2 was in its crash loop: server-1's k3s unit `active`; etcd endpoint health `true` for server-1 and server-3, `connection refused` for server-2; the Kubernetes API **answered a node listing from server-1** showing four nodes Ready and server-2 NotReady.

**Limit, stated plainly:** the API-served observation is from **one** surviving server (server-1). Server-3's API was not called directly during the crash window; its health during that window rests on its etcd endpoint answering `true` from server-1 and on its unit being `active` at the sitting's closure (§1 b3 per-node closure, 11:23–11:24Z). "The other two kept serving" is therefore: one server proven serving the API, one proven healthy at the datastore layer and running, quorum 2/3 held. The pack does not upgrade this.

---

## §1 b2 — remove override, source already NEW, start with allowlist files present · 11:21:28Z → 11:21:58Z (verbatim)

> - `systemctl stop k3s` → `inactive` 11:21:28Z. Drop-in removed, `daemon-reload`; `k3s.service.d` empty; `systemctl show -p ExecStart` contains `--token` **0** times (override gone). Env value digest `353165aec15b` (NEW).
> - `systemctl start --no-block k3s` at **11:21:28Z**, allowlist files present. After 30 s: `is-active` **activating**, `NRestarts 25` (cumulative).
> - Counts since start: `different token` **0**; `newer than datastore` **5**. Observed verbatim (11:21:29 / :35 / :41 / :47 / :53, pids 2443–2515): **⟵ P4c**
>   `level=fatal msg="/var/lib/rancher/k3s/server/cred/passwd newer than datastore and could cause a cluster outage. Remove the file(s) from disk and restart to be recreated from datastore."`
> - `systemctl stop k3s` → `inactive` **11:21:58Z** (stop-to-Ready clock starts here).
>
> **b2 outcome: trap MANIFESTED** (recorded; see §2).

**Reading note.** This is the "fixing the credential source alone was not enough" evidence: the wrong-token override is gone, the configured source holds the NEW token, and five consecutive starts still refuse — with the correct credential — because two on-disk files are newer than the datastore.

---

## §1 b3 — exact two-path delete + recover · 11:22:33Z → 11:23:03Z (verbatim)

> | Exact path | `ls -l` before | Removal | `ls -l` after | Recreated after start |
> |---|---|---|---|---|
> | `/var/lib/rancher/k3s/server/cred/passwd` | `-rw------- root root 175 Sep 4 11:19` | `rm` exit 0 | `No such file or directory` | `-rw------- root root 143 Sep 4 11:18` (mtime = datastore's rotation write → restored **from** datastore) |
> | `/var/lib/rancher/k3s/server/token` | `-rw------- root root 141 Sep 4 11:19` | `rm` exit 0 | `No such file or directory` | `-rw------- root root 125 Sep 4 11:22`, digest **`91112ccfab36`** = srv-1's post-rotate digest |
>
> Regular-file/no-symlink guard checked before each `rm`; no other `rm` of any kind. **⟵ P4d**
>
> - `systemctl start --no-block k3s` at **11:22:33Z** → `active` after **10 s** (11:22:43Z), `NRestarts 0`.
> - Post-recovery journal (since 11:22:33Z): `different token` **0**, `newer than datastore` **0**; `Managed etcd cluster bootstrap already complete and initialized` → `Reconciling bootstrap data between datastore and disk` → `Updating bootstrap data on disk from datastore` → etcd `restarting local member` `8734d8433dfa652d`, commit-index 104777.
> - From srv-1: server-2 **Ready at first poll, 11:23:03Z**; 5/5 Ready; etcd 3/3 `true` (7.0 / 8.7 / 12.2 ms); `/bootstrap` one key `2af7b510f61e`; CA `744d6a1e…` unchanged.
> - **Stop-to-Ready: 11:21:58Z → `active` 11:22:43Z = 45 s; Ready confirmed ≤65 s (11:23:03Z, first poll — true Ready time is at or before this).** **⟵ P4e**
> - Per-node closure (11:23–11:24Z): srv-1/2 `k3s=active` digest `91112ccfab36`; **srv-3 `active` digest `0b0ff4b8d018`** — un-restarted server still serving on its in-memory credential (the WS-5 mechanism, observed on the third server); agent-1/2 `k3s-agent=active`; `different token` 0 ×5, `newer than datastore` 0 ×5, agent `not authorized` since 11:18Z 0 ×2.
>
> **b3 verdict: PASS.**

### P4e — where the 45 seconds comes from

The interval is **from the `systemctl stop` that ended b2 (`inactive` at 11:21:58Z) to the unit reporting `active` after the delete-and-start (11:22:43Z)**: 45 s wall-clock from journal/`systemctl` timestamps. It includes the 35 s the operator spent running the `ls`/guard/`rm` steps between 11:21:58Z and 11:22:33Z; the start itself took 10 s. Cluster-level Ready for server-2 was confirmed at the first poll, 11:23:03Z (≤65 s) — a polling upper bound, not a measurement of when Ready was reached.

---

## §2 Timestamp-trap beat — recorded, not assumed (verbatim) **⟵ P4d**

> Comparison boundary: the datastore bootstrap write at rotation, **11:18:31Z**.
>
> | Path | mtime before b1 restart | mtime after b1 crash loop | Post-rotation mtime retained into b2? |
> |---|---|---|---|
> | `/var/lib/rancher/k3s/server/cred/passwd` | 2026-08-30 15:30:55Z | **2026-09-04 11:19:30.848Z** | yes → newer than datastore |
> | `/var/lib/rancher/k3s/server/token` | 2026-09-04 11:12:52Z | **2026-09-04 11:19:33.386Z** | yes (k3s named only `cred/passwd` in the fatal) |
>
> **Conditional verdict: MANIFESTED** — five verbatim `newer than datastore` fatals in b2 with the correct (NEW) token and no override; cleared by b3's two-path delete and nothing else. […]

---

## §4 Findings from this sitting that bear on the claims (verbatim rows)

| ID | Symptom | Class | How caught | Fix | Proven? |
|---|---|---|---|---|---|
| F-TB-1 | Redaction regex (`::server:[a-f0-9]*`) assumed the `K10…` form; the env surface holds the bare 64-hex secret, so the drop-in echo and `systemctl show` printed the lab OLD secret to the terminal | credential discipline (advisor error) | read on paste | broader regex `[a-f0-9]{64}` used from b2 on; **two on-disk token forms** (env = bare secret, `server/token` = K10 form) is a runbook v1.7 §P0.9 note owed | regex proven b2/b3; note not yet written |
| F-TB-3 | Trap fired inside b1's crash loop: attempt 1 with the wrong token reconciled `cred/passwd`/`server/token` from datastore before failing, making them newer than the rotation write | k3s behaviour, mechanism UNVERIFIED at source | b1 journal + mtimes | none needed; document in runbook §7 (the trap can be armed by the stale node's *own* failed start) | measured once |

Both were folded into runbook v1.8 (P2, hunks 3–5). F-TB-1 is disclosed here because it is why this pack is assembled from the redacted log and never from the terminal transcript: the transcript contains the rehearsal cluster's old credential. That credential is lab-scoped; it has never been a production value.
