#!/usr/bin/env bash
# Run shellcheck over every tracked bash/sh script, using the repo's .shellcheckrc.
#
# Why this exists: `qlty check` only lints files with a shell extension (.sh), so
# extensionless scripts (most of bin/, .githooks/) are skipped even though they have
# a bash shebang. Verified by probe: a defect in bin/zz-probe went unreported while
# the identical bin/zz-probe.sh was flagged. The file list is derived from shebangs,
# never hard-coded.
#
# Shellcheck binary: $SHELLCHECK_BIN, else the newest qlty-cached build, else PATH.
# Exit: 0 clean, 1 findings, 2 setup problem (no shellcheck, no git, no files).
set -euo pipefail

ROOT="$(CDPATH="" cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

resolve_shellcheck() {
  if [[ -n "${SHELLCHECK_BIN:-}" ]]; then
    printf '%s\n' "$SHELLCHECK_BIN"
    return 0
  fi
  local cached=("$HOME"/.qlty/cache/tools/shellcheck/*/shellcheck)
  if [[ -e "${cached[0]}" ]]; then
    printf '%s\n' "${cached[@]}" | sort -V | tail -n 1
    return 0
  fi
  command -v shellcheck || true
}

SC="$(resolve_shellcheck)"
if [[ -z "$SC" || ! -x "$SC" ]]; then
  echo "shellcheck-all: no shellcheck found (set SHELLCHECK_BIN, run a qlty check to" >&2
  echo "populate ~/.qlty/cache/tools/shellcheck, or install shellcheck on PATH)." >&2
  exit 2
fi

# Paths mirroring qlty's exclude_patterns that matter for tracked shell scripts.
is_excluded() {
  case "/$1" in
    */.venv/*|*/out/*|*/_out/*|*/backups/*|*/maker/*|*/_disasm/*) return 0 ;;
  esac
  return 1
}

is_shell() {
  local first=""
  [[ "$1" == *.sh ]] && return 0
  IFS= read -r first < "$1" 2>/dev/null || true
  [[ "$first" =~ ^#!.*[/[:space:]](ba)?sh([[:space:]]|$) ]]
}

files=()
while IFS= read -r -d '' f; do
  [[ -L "$f" || ! -f "$f" ]] && continue
  is_excluded "$f" && continue
  is_shell "$f" && files+=("$f")
done < <(git ls-files -z)

if [[ ${#files[@]} -eq 0 ]]; then
  echo "shellcheck-all: found no shell scripts; refusing to report a pass." >&2
  exit 2
fi

echo "shellcheck-all: ${#files[@]} files ($SC)" >&2
if "$SC" -f gcc "${files[@]}"; then
  echo "shellcheck-all: clean" >&2
else
  echo "shellcheck-all: findings above" >&2
  exit 1
fi
