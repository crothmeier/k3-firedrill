#!/usr/bin/env bash

config_prepare() {
    local config_path=$1
    FD_CANONICAL_CONFIG=$(mktemp "${TMPDIR:-/tmp}/firedrill-config.json.XXXXXX")
    FD_TEMP_FILES+=("$FD_CANONICAL_CONFIG")
    "$FD_PYTHON" -m firedrill.config validate \
        --config "$config_path" \
        --output "$FD_CANONICAL_CONFIG"
}

config_get() {
    "$FD_PYTHON" -m firedrill.config get --canonical "$FD_CANONICAL_CONFIG" "$1"
}

config_inventory_count() {
    config_get inventory | "$FD_PYTHON" -c 'import json,sys; print(len(json.load(sys.stdin)))'
}

config_inventory_field() {
    local index=$1
    local field=$2
    config_get "inventory.${index}.${field}"
}

