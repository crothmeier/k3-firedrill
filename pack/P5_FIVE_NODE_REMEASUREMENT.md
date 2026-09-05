# P5 — Independent five-node hand-remeasurement

Two passes, neither produced by the harness:

1. **2026-09-04 11:24–11:28Z, after the injection sitting** — the post-recovery closure and the post-rollback re-verification (`EXEC_LOG_2026-09-04_P06_TEST_B.md` §1 b3 closure and §3, Nexus @ `48b4fb6`).
2. **2026-09-04 22:52–22:57Z, a separate read-only sitting** with the lab freshly booted from `p06-baseline` and the harness not used at all (`EXEC_LOG_2026-09-04_P06_LAB_READONLY_CAPTURE.md` §2 Block B, Nexus @ `dbc0d51`). Every value in that pass was captured into one evidence file through a redaction filter and frozen:
   `evidence/MEASURED_2026-09-04_P06_LAB_READONLY_CAPTURE.log` — 403 lines, 17,936 B, sha256 **`40d6b4a1a6e0598ceaba01dc35c684bc56658e3b5ecaf484c86a7b4e120d35a2`** (held on the operator's seat with a `.sha256` sidecar; the hash is recorded in the committed log).

**Substitutions:** none in the quoted sections. Node addresses appear only as `.10–.14` suffixes.
**Digests, not values:** every credential-derived figure below is a 12-character prefix of a sha256 (`sha256 | cut -c1-12`). The bootstrap key *name* `0a6c128f5dad` is the pre-rotation credential's key. The cluster CA fingerprint is pinned as `744d6a1e…2798`. Presence and equality are what the checklist proves; no value is recoverable from this file.

---

## Checklist a reader asked for, and where each row is measured

| Item | Pass 1 (11:23–11:28Z, post-recovery / post-rollback) | Pass 2 (22:53Z, cold boot from baseline, no harness) |
|---|---|---|
| Node state, all five | 5/5 Ready at 11:23:03Z; 5/5 Ready at 11:28:12Z after rollback | 5/5 `Ready` `v1.34.4+k3s1`, names `server-1/2/3` (`control-plane,etcd`), `agent-1/2` |
| Datastore health | etcd 3/3 `true` (7.0 / 8.7 / 12.2 ms); after rollback 3/3 (7.2 / 9.0 / 11.5 ms) | etcd endpoint health 3/3 `true` (8.4 / 11.9 / 12.0 ms) |
| Bootstrap-key presence (not value) | exactly one key `2af7b510f61e` post-recovery; exactly `0a6c128f5dad` after rollback | `/bootstrap/0a6c128f5dad` only |
| CA fingerprint | `744d6a1e…` unchanged; `744d6a1e6e8cdd1f…2798` after rollback | `ca_sha256=744d6a1e...2798` |
| Per-server credential digests (not values) | srv-1/2 `91112ccfab36` (rotated), srv-3 `0b0ff4b8d018` (un-restarted, still serving on in-memory credential); after rollback `0b0ff4b8d018` ×3 | whole-file `0b0ff4b8d018` ×3; secret-part digest equal across all five nodes (`0a6c128f5dad`) |
| Both failure-string counts, all five | `different token` 0 ×5, `newer than datastore` 0 ×5, agent `not authorized` 0 ×2 (since 11:18Z); after rollback `different token` 0 ×5 | `different_token=0 newer_than_datastore=0` on each server; `not_authorized=0` on each agent |
| Disk-level rollback proof | `/root/p06-OLD-token.txt` and `/root/p06-NEW-token.txt` absent on srv-1 (both postdate the snapshot); srv-2 drop-in absent | `server/token` mtimes 14–17 s after each guest's boot (regenerated at start, F-TA-4 behaviour); `cred/passwd` 175 B 2026-08-30 on all three |

---

## Pass 1 — `EXEC_LOG_2026-09-04_P06_TEST_B.md` §3 (verbatim)

> - Harness invocation: `script -q ~/rb_<ts>.log ./firedrill rollback; echo "EXIT=$?"` at `ba90be8`, ~11:24–11:27Z […].
> - Output shape: 5× `QEMU Guest Agent is not running … guest-ping … timeout` (expected) · 5× `pve-stop-mode=graceful-shutdown` · 5× rollback waits · 5× `generating cloud-init ISO` · `pve wait: attempt 1/120` (SSH gate) · **`PASS: baseline restored and cluster health verified` · `EXIT=0`**. No `FATAL:`, no `guard:`, no `timeout`.
> - Independent re-verify **11:28:12Z** (guest uptime 1 min): 5/5 Ready; srv-1/2/3 `k3s=active`, agent-1/2 `k3s-agent=active` (e5 pairing); etcd 3/3 `true` (7.2 / 9.0 / 11.5 ms); `/bootstrap` exactly `0a6c128f5dad`; CA `744d6a1e6e8cdd1f…2798`; server token digest `0b0ff4b8d018` ×3; `different token` this boot 0 ×5.
> - Disk-level proof: `/root/p06-OLD-token.txt` and `/root/p06-NEW-token.txt` on srv-1 **absent** (both postdate the snapshot). srv-2 `k3s.service.d` absent — the probe printed `dropin=1` on all five because it counted the `ls: cannot access` line; the agents (which never had a drop-in) show the identical value, so the reading is *absent*, but the probe shape was wrong (advisor error; a check whose silence and failure look alike — §5 rule 3).
>
> **Rollback verdict: PASS — sixth harness rollback, sixth PASS, independently verified. Lab at `p06-baseline`.**

(The rollback itself is a harness command; the *re-verification* at 11:28:12Z is the hand pass. The `dropin=1` probe-shape error is left in as recorded.)

## Pass 2 — `EXEC_LOG_2026-09-04_P06_LAB_READONLY_CAPTURE.md` §2 Block B (verbatim)

> B1 (server-1, 22:53:37Z): five nodes `Ready` `v1.34.4+k3s1`, node names `server-1/2/3` (`control-plane,etcd`) and `agent-1/2`, INTERNAL-IPs `.10–.14`, OS `Ubuntu 24.04.4 LTS`, kernel `6.8.0-136-generic`, containerd `2.1.5-k3s1`, AGE 5d7h. etcd endpoint health 3/3 `true` (8.4 / 11.9 / 12.0 ms). `/bootstrap/0a6c128f5dad` only. `ca_sha256=744d6a1e...2798`.
>
> | Node | `is-active` / NRestarts | env file (`ls`) | `k3s_token_lines` | `env_secret_digest` | `tokenfile_secret_digest` | `tokenfile_whole_digest` | `server/token` | `cred/passwd` | counts |
> |---|---|---|---|---|---|---|---|---|---|
> | server-1 `.10` | active / 0 | `k3s.service.env` **77 B** 0600 Aug 30 15:30; no `k3s.service.d`, `config.yaml`, `config.yaml.d` | 1 | `0a6c128f5dad` | `0a6c128f5dad` | `0b0ff4b8d018` | 141 B 22:48:33Z (this boot) | 175 B 2026-08-30 15:30:55Z | `different_token=0 newer_than_datastore=0` |
> | server-2 `.11` | active / 0 | `k3s.service.env` 113 B 0600 Aug 30 15:31; same absences | 1 | `0a6c128f5dad` | `0a6c128f5dad` | `0b0ff4b8d018` | 141 B 22:48:35Z | 175 B 2026-08-30 15:30:55Z | 0 / 0 |
> | server-3 `.12` | active / 0 | `k3s.service.env` 113 B 0600 Aug 30 15:32; same absences | 1 | `0a6c128f5dad` | `0a6c128f5dad` | `0b0ff4b8d018` | 141 B 22:48:41Z | 175 B 2026-08-30 15:30:55Z | 0 / 0 |
> | agent-1 `.13` | active / 0 | **`k3s-agent.service.env`** 113 B 0600 Aug 30 15:33; no `k3s-agent.service.d`; `/etc/rancher/k3s` absent | 1 | `0a6c128f5dad` | — | — | — | — | `not_authorized=0` |
> | agent-2 `.14` | active / 0 | `k3s-agent.service.env` 113 B 0600 Aug 30 15:34; same absences | 1 | `0a6c128f5dad` | — | — | — | — | `not_authorized=0` |
>
> | ID | Check | Expected | PASS/FAIL |
> |---|---|---|---|
> | B1 | nodes / etcd / bootstrap / CA | 5/5 `v1.34.4+k3s1`; 3/3; `0a6c128f5dad` only; `744d6a1e...2798` | PASS |
> | B2–B4 | single surface per server | one `K3S_TOKEN=` line in `k3s.service.env`; no drop-in, no `config.yaml(.d)` | PASS ×3 |
> | B2–B4 | two forms, like-with-like | env secret == token-file secret on each server; equal across servers | PASS ×3 |
> | B2–B4 | whole-file digest | `0b0ff4b8d018` ×3 | PASS |
> | B2–B4 | allowlist file shape | `cred/passwd` 175 B 08-30; `server/token` 141 B this boot (F-TA-4, not a finding) | PASS ×3 |
> | B2–B4 | journal counts this boot | 0 / 0 | PASS ×3 |
> | B5–B6 | agents | `not_authorized=0`; env secret digest equals servers' | PASS ×2 |
> | B5–B6 | agent env-file name | UNVERIFIED on the sheet | **now VERIFIED: `/etc/systemd/system/k3s-agent.service.env`** |
>
> Data, not findings: (i) the shared secret's 12-char digest equals the bootstrap key name `0a6c128f5dad` — expected, k3s derives the key from the token; (ii) server-1's env file is 77 B against 113 B elsewhere — consistent with the init server carrying no `K3S_URL=` line (contents not read; UNVERIFIED-benign); (iii) `server/token` mtimes 22:48:33–41Z are 14–17 s after each guest's boot.

**Reading note.** Pass 2 measures the baseline the pack stands on, eighteen hours after the injection sitting, from a fresh boot of the same snapshot: every server on one token surface, one credential in two on-disk forms with matching secret digests, zero failure strings, bootstrap key and CA as pinned. That the pre-rotation credential is back (`0a6c128f5dad`) is the point — the rollback restored the datastore era, not only the disks.
