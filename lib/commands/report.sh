#!/usr/bin/env bash

command_report() {
    state_load_current
    "$FD_PYTHON" -m firedrill.report --run-path "$FD_RUN_PATH"
}

