#!/usr/bin/env bash

command_preflight() {
    driver_load
    driver_preflight
    printf 'PASS: configuration, driver, identity, denylist, allocation, and template checks passed\n'
}

