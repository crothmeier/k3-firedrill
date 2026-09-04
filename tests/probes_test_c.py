"""Executable negative probes for the offline Test C increment."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from firedrill.bootstrap import BootstrapBranch, bootstrap_key_name, normalize_token
from firedrill.redact import ACTIVE_TOKENS_ENV, TokenRegistry
from firedrill.test_c_model import (
    RESET_FLAG_PATH,
    MockBootstrapDiscriminator,
    MockRecoveryProtocols,
    ModeledEtcdSnapshot,
    TestCModelError,
    break_test_c,
    finish_recovery,
    gate_observation,
    prepare_test_c,
    resolve_nominated_snapshot,
    set_preexisting_reset_flag,
    snapshot_catalog,
)
from firedrill.test_c_recovery import (
    RecoveryHalted,
    RecoveryInvariantError,
    ResetAttemptError,
    apply_recovery_policy,
)
from test_test_c_execution import apply_reset, fixture, recover_and_gate


def emit(label: str, reason: str) -> None:
    print(f"NEGATIVE PROBE {label}: EXPECTED FAILURE — {reason}")


def probe_zero() -> None:
    model, _, old_token, new_token = fixture()
    prepare_test_c(model, old_token, new_token, "membership")
    break_test_c(model, BootstrapBranch.ZERO)
    before = copy.deepcopy(model)
    try:
        apply_reset(model, old_token, new_token)
    except RecoveryHalted as error:
        assert model == before
        assert model["cluster"]["test_c"]["reset_attempts"] == 0
        emit("zero-no-mutation", str(error))
        return
    raise AssertionError("ZERO probe unexpectedly permitted recovery")


def probe_three_key_anomalous() -> None:
    model, _, old_token, new_token = fixture()
    prepare_test_c(model, old_token, new_token, "membership")
    expected = [bootstrap_key_name(old_token), bootstrap_key_name(new_token)]
    third = "/bootstrap/ffffffffffff"
    observed = [*expected, third]
    model["injections"]["test_c"]["anomalous_key_names"] = observed
    break_test_c(model, BootstrapBranch.ANOMALOUS)
    protocols = MockRecoveryProtocols(model, old_token, new_token)
    try:
        apply_recovery_policy(
            tuple(model["cluster"]["bootstrap_keys"]),
            old_token,
            new_token,
            paired_snapshot=None,
            reset=protocols.reset,
            observe_bootstrap_keys=protocols.observe_bootstrap_keys,
            observe_reset_flag=protocols.observe_reset_flag,
            reset_flag_path=RESET_FLAG_PATH,
            registry=TokenRegistry(),
            evidence=lambda _: None,
            discriminator=MockBootstrapDiscriminator(model),
        )
    except RecoveryHalted as error:
        reason = str(error)
        assert all(name in reason for name in observed)
        assert model["cluster"]["test_c"]["reset_attempts"] == 0
        emit("anomalous-three-key-set", reason)
        return
    raise AssertionError("three-key ANOMALOUS probe unexpectedly permitted recovery")


def probe_collision() -> None:
    model, _, normal_old, normal_new = fixture()
    prepare_test_c(model, normal_old, normal_new, "membership")
    shared = hashlib.sha256(b"negative-collision-secret").hexdigest()
    old_token = f"K10{hashlib.sha256(b'negative-old-ca').hexdigest()}::server:{shared}"
    new_token = f"K10{hashlib.sha256(b'negative-new-ca').hexdigest()}::server:{shared}"
    key = bootstrap_key_name(old_token)
    model["cluster"]["bootstrap_keys"] = [key]
    protocols = MockRecoveryProtocols(model, old_token, new_token)
    try:
        apply_recovery_policy(
            (key,),
            old_token,
            new_token,
            paired_snapshot=None,
            reset=protocols.reset,
            observe_bootstrap_keys=protocols.observe_bootstrap_keys,
            observe_reset_flag=protocols.observe_reset_flag,
            reset_flag_path=RESET_FLAG_PATH,
            registry=TokenRegistry(),
            evidence=lambda _: None,
            discriminator=MockBootstrapDiscriminator(model),
        )
    except RecoveryHalted as error:
        reason = str(error)
        assert "collision" in reason and key in reason
        assert model["cluster"]["test_c"]["reset_attempts"] == 0
        emit("anomalous-derivation-collision", reason)
        return
    raise AssertionError("derivation collision probe unexpectedly permitted recovery")


def probe_snapshot_guards() -> None:
    model, _, old_token, new_token = fixture()
    prepare_test_c(model, old_token, new_token, "snapshot")
    first = snapshot_catalog(model)[0]
    second = replace(first, path=first.path.replace("server-3", "server-2"))
    try:
        resolve_nominated_snapshot((first, second), (first.path, second.path))
    except TestCModelError as error:
        emit("multiple-nominated-snapshots", str(error))
    else:
        raise AssertionError("multiple snapshot nomination unexpectedly succeeded")

    unpaired = ModeledEtcdSnapshot(
        path="/var/lib/rancher/k3s/server/db/snapshots/unpaired-negative.db",
        snapshot_sha256=hashlib.sha256(b"negative-unpaired").hexdigest(),
        token_candidate=None,
        token_reference=None,
        paired=False,
    )
    try:
        resolve_nominated_snapshot((unpaired,), (unpaired.path,))
    except TestCModelError as error:
        emit("unpaired-snapshot-ineligible", str(error))
        return
    raise AssertionError("unpaired snapshot unexpectedly became eligible")


def probe_reset_flags() -> None:
    model, _, old_token, new_token = fixture()
    prepare_test_c(model, old_token, new_token, "membership")
    break_test_c(model, BootstrapBranch.NEW_ONLY)
    before_mtime = 1_700_000_000_101_202_303
    set_preexisting_reset_flag(model, before_mtime)
    try:
        apply_reset(model, old_token, new_token)
    except ResetAttemptError as error:
        assert error.before.path == RESET_FLAG_PATH
        assert error.before.mtime_ns == before_mtime
        assert model["cluster"]["test_c"]["reset_attempts"] == 0
        emit("preexisting-reset-flag", str(error))
    else:
        raise AssertionError("pre-existing reset flag unexpectedly allowed reset")

    model, _, old_token, new_token = fixture()
    prepare_test_c(model, old_token, new_token, "membership")
    break_test_c(model, BootstrapBranch.NEW_ONLY)
    stranded_mtime = 1_700_000_000_404_505_606
    model["injections"]["test_c"].update(
        {"reset_failure": True, "reset_flag_mtime_ns": stranded_mtime}
    )
    try:
        apply_reset(model, old_token, new_token)
    except ResetAttemptError as error:
        assert error.after is not None
        assert error.after.path == RESET_FLAG_PATH
        assert error.after.mtime_ns == stranded_mtime
        emit("failed-reset-stranded-flag", str(error))
        return
    raise AssertionError("failed-reset probe did not strand its modeled flag")


def probe_both_orphan_vanishes() -> None:
    model, _, old_token, new_token = fixture()
    prepare_test_c(model, old_token, new_token, "membership")
    model["injections"]["test_c"]["orphan_vanish_during_reset"] = True
    break_test_c(model, BootstrapBranch.BOTH)
    try:
        apply_reset(model, old_token, new_token)
    except RecoveryInvariantError as error:
        emit("both-orphan-vanished-during-reset", str(error))
        return
    raise AssertionError("BOTH orphan-vanish probe unexpectedly passed")


def probe_cleanup_authorization() -> None:
    model, _, old_token, new_token = fixture()
    prepare_test_c(model, old_token, new_token, "membership")
    break_test_c(model, BootstrapBranch.BOTH)
    apply_reset(model, old_token, new_token)
    before = copy.deepcopy(model["cluster"]["bootstrap_keys"])
    try:
        finish_recovery(
            model,
            authorize_orphan_cleanup=False,
            timeout_seconds=30,
        )
    except TestCModelError as error:
        assert model["cluster"]["bootstrap_keys"] == before
        emit("both-cleanup-without-authorization", str(error))
        return
    raise AssertionError("BOTH cleanup unexpectedly ran without authorization")


def probe_gate_failures() -> None:
    gate, _, _, _ = recover_and_gate(injections={"runtime_candidate_override": "OLD"})
    runtime_check = next(
        check
        for check in gate.checks
        if check.name == "final-key-matches-observed-runtime-credential"
    )
    assert gate.verdict == "FAIL" and not runtime_check.passed
    emit("runtime-credential-mismatch", runtime_check.observed)

    gate, _, _, _ = recover_and_gate(
        injections={
            "post_recovery_journal_lines": {
                "server-2": ["k3s observed a different token after recovery"]
            }
        }
    )
    journal_check = next(
        check for check in gate.checks if check.name == "clean-post-recovery-server-journals"
    )
    assert gate.verdict == "FAIL" and not journal_check.passed
    emit("different-token-journal-line", journal_check.observed)


def probe_raw_modeled_output() -> None:
    model, _, old_token, new_token = fixture()
    prepare_test_c(model, old_token, new_token, "membership")
    model["injections"]["raw_output"] = old_token
    break_test_c(model, BootstrapBranch.NEW_ONLY)
    apply_reset(model, old_token, new_token)
    finish_recovery(model, authorize_orphan_cleanup=False, timeout_seconds=30)
    raw = json.dumps(gate_observation(model), sort_keys=True)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        stdout_path = root / "stdout"
        stderr_path = root / "stderr"
        run_path = root / "run"
        stdout_path.write_text(raw, encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        environment = os.environ.copy()
        environment[ACTIVE_TOKENS_ENV] = json.dumps(
            [old_token, new_token, normalize_token(old_token), normalize_token(new_token)]
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "firedrill.evidence",
                "--run-path",
                str(run_path),
                "--sequence",
                "1",
                "--label",
                "test-c-planted-modeled-output",
                "--node",
                "test-c",
                "--started-at",
                "2026-08-14T00:00:00Z",
                "--ended-at",
                "2026-08-14T00:00:01Z",
                "--exit-code",
                "0",
                "--stdout",
                str(stdout_path),
                "--stderr",
                str(stderr_path),
                "--",
                "modeled-output",
                old_token,
            ],
            check=True,
            env=environment,
        )
        artifacts = [path for path in (run_path / "evidence").rglob("*") if path.is_file()]
        for artifact in artifacts:
            content = artifact.read_text(encoding="utf-8")
            assert old_token not in content
            assert new_token not in content
            assert normalize_token(old_token) not in content
            assert normalize_token(new_token) not in content
        emit(
            "raw-token-planted-in-modeled-output",
            f"raw candidate absent from {len(artifacts)} evidence artifacts",
        )


def main() -> int:
    probe_zero()
    probe_three_key_anomalous()
    probe_collision()
    probe_snapshot_guards()
    probe_reset_flags()
    probe_both_orphan_vanishes()
    probe_cleanup_authorization()
    probe_gate_failures()
    probe_raw_modeled_output()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
