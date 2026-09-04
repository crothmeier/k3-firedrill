#!/usr/bin/env bash
set -Eeuo pipefail

TEST_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export PYTHONPATH="$TEST_ROOT/py${PYTHONPATH:+:$PYTHONPATH}"

python3 -m unittest discover -s "$TEST_ROOT/tests" -p 'test_*.py'
python3 "$TEST_ROOT/tests/probes_test_b.py"
python3 "$TEST_ROOT/tests/probes_test_c.py"
"$TEST_ROOT/tests/test_shell_lint_coverage.sh"
"$TEST_ROOT/tests/test_mock_lifecycle.sh"
bash "$TEST_ROOT/tests/test_test_b_lifecycle.sh"
"$TEST_ROOT/tests/test_test_c_lifecycle.sh"
"$TEST_ROOT/tests/test_fail_closed.sh"
"$TEST_ROOT/tests/test_test_a_negative.sh"
bash "$TEST_ROOT/tests/test_evidence_exec_failure.sh"
bash "$TEST_ROOT/tests/test_pve_driver.sh"
