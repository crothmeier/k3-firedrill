# Finding F-8 — infix-X mktemp templates are not portable to macOS

Status: FIXED in code with this commit (10 templates renamed); retained for
provenance and for the tracing hazard notes below
Classification: portability defect, macOS (BSD userland) seats only

## Statement

Ten `mktemp` templates of the form `firedrill-*.XXXXXX.json` placed the `X`
run mid-name. BSD `mktemp` (macOS) only substitutes trailing `X`s, so it
created files literally named `…XXXXXX.json`. That works exactly once per
namespace: the EXIT trap normally removes the file, but any death that skips
the trap (untrapped signal; SIGPIPE through a pipeline teardown was measured
2026-08-30) orphans it, and every subsequent invocation then fails at
startup with `mkstemp failed … File exists`. It also forbids concurrent
invocations sharing a TMPDIR. GNU `mktemp` substitutes infix runs and never
exhibits this.

## Fix

All ten templates renamed `NAME.XXXXXX.json` → `NAME.json.XXXXXX` (trailing
substitution, portable to both userlands). No consumer depends on the
extension position; paths are always passed explicitly. Recovery from a
poisoned TMPDIR: remove the literal `firedrill-*.XXXXXX*` files.

## Related hazards measured the same day (do not re-learn these)

- Never run this harness under external `bash -x`: `pve_guest_config_json`
  and peers capture command output with `2>&1`, so trace lines are captured
  into values and corrupt JSON parsing — the run fails on the instrumentation,
  not the code.
- `BASH_XTRACEFD` is ignored when imported from the environment; its special
  handling fires only on assignment inside the running shell. If tracing is
  ever needed, add a guarded in-script assignment; do not wrap from outside.
