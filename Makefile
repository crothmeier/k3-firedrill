.PHONY: test lint

SHELL := /bin/bash

SHELL_FILES := $(shell LC_ALL=C find . \
	\( -type d -path './.git' -prune \) -o \
	\( -type f \
		\( -name '*.sh' -o -exec awk \
			'NR == 1 { shell_file = ($$0 ~ /^\#![[:space:]]*([^[:space:]]*\/)?(env[[:space:]]+(-S[[:space:]]+)?)?(sh|bash|dash|ksh|zsh)([[:space:]]|$$)/); exit } \
			END { exit !shell_file }' {} \; \) -print \) \
	| LC_ALL=C sort)

test: lint
	PYTHONDONTWRITEBYTECODE=1 ./tests/run.sh

lint:
	@command -v shellcheck >/dev/null || { echo "shellcheck is required" >&2; exit 1; }
	@command -v ruff >/dev/null || { echo "ruff is required" >&2; exit 1; }
	@printf 'ShellCheck files (%s):\n' '$(words $(SHELL_FILES))'
	@printf '  %s\n' $(SHELL_FILES)
	shellcheck $(SHELL_FILES)
	ruff check py tests

.PHONY: print-shell-files
print-shell-files:
	@printf '%s\n' $(SHELL_FILES)

# Finding F-5: report ALL missing/placeholder required keys in one pass
# instead of one exit-65 preflight per key. Read-only; presence check only.
.PHONY: config-check
config-check:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=py python3 -m firedrill.config_check --config firedrill.conf --example firedrill.conf.example
