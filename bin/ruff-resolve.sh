#!/usr/bin/env bash
# Resolve a ruff binary that matches the one CI runs, then exec it.
#
# CI lints via `qlty check`, which runs ruff from its own pinned tool cache
# (see the [[plugin]] name = "ruff" entry in .qlty/qlty.toml). There is no
# standalone ruff on PATH here, so `ruff check <file>` — which this repo's
# skills and agent prompts tell you to run — silently does not exist. Worse,
# `qlty check` from inside .claude/worktrees/ scans zero files and prints
# "✔ No issues", so the fallback looks clean rather than broken.
#
# Resolution order, most-authoritative first:
#   1. $RUFF_BIN, if the caller pinned one explicitly
#   2. qlty's cached ruff — the exact build CI uses
#   3. .venv/bin/ruff, then PATH — may differ from CI; warn on version drift
#
# Usage: bin/ruff-resolve.sh check src/
#        bin/ruff-resolve.sh --print   # show the resolved path and exit
set -euo pipefail

qlty_ruff() {
  # Layout is <cache>/ruff/<version>-<hash>/bin/ruff, so the binary sits at
  # depth 3. Newest cached build wins if several versions are present.
  find "${HOME}/.qlty/cache/tools/ruff" -maxdepth 3 -type f -name ruff -perm -u+x \
    2>/dev/null | sort -V | tail -1
}

resolve() {
  if [[ -n "${RUFF_BIN:-}" && -x "${RUFF_BIN}" ]]; then
    echo "${RUFF_BIN}"; return 0
  fi
  local cached; cached="$(qlty_ruff || true)"
  if [[ -n "${cached}" && -x "${cached}" ]]; then
    echo "${cached}"; return 0
  fi
  local repo_root; repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  if [[ -x "${repo_root}/.venv/bin/ruff" ]]; then
    echo "${repo_root}/.venv/bin/ruff"; return 0
  fi
  if command -v ruff >/dev/null 2>&1; then
    command -v ruff; return 0
  fi
  return 1
}

if ! RUFF="$(resolve)"; then
  cat >&2 <<'EOF'
ERROR: no ruff binary found.

CI lints through `qlty check`, which supplies its own pinned ruff. To get the
same binary locally, run any qlty check once so it populates the tool cache:

    ~/.qlty/bin/qlty check --no-cache src/core/paths.py

Then re-run this command. To use a specific build instead:

    RUFF_BIN=/path/to/ruff bin/ruff-resolve.sh check src/

Do NOT `pip install ruff` to work around this — an unpinned version drifts from
the one CI enforces, so local results stop predicting CI results.
EOF
  exit 127
fi

if [[ "${1:-}" == "--print" ]]; then
  echo "${RUFF}"
  "${RUFF}" --version
  exit 0
fi

exec "${RUFF}" "$@"
