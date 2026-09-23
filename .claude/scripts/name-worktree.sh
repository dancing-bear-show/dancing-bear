#!/bin/bash
# WorktreeCreate hook: this project uses hook-based worktree creation (see
# CLAUDE.md), which means the harness does NOT create the worktree itself —
# this hook must run `git worktree add`, choose the branch name (3 random
# nouns, e.g. "coral-panda-drift"), and print the resulting absolute
# directory path as the last line of stdout. The harness then chdir()s into
# whatever path this script prints.
set -euo pipefail

INPUT=$(cat)
NAME_IN=$(echo "$INPUT" | jq -r '.name // empty' 2>/dev/null)
[ -z "$NAME_IN" ] && exit 1

# -I -S: hook processes inherit the session's environment, so PYTHONPATH may
# name a foreign checkout here just as it can at SessionStart. Python imports
# sitecustomize/usercustomize from PYTHONPATH entries during startup, which
# would execute code from that checkout before this script does anything. -I
# ignores PYTHONPATH and the user site dir; -S skips site.py, which performs
# those imports. This snippet is stdlib-only, so isolation costs nothing.
# `|| true` is required, not defensive noise: `set -e` aborts the script at a
# command substitution that exits non-zero, so without it the fallback on the
# next line is dead code. /usr/share/dict/words ships on macOS but NOT on a
# stock Linux runner, so the generator genuinely fails there — and this hook
# then blocked worktree creation outright instead of falling back, which is what
# turned a red CI job into a mystery.
#
# The generator also falls back when the dict yields too few candidates to
# sample three from, rather than raising ValueError.
NAME=$(python3 -I -S -c "
import random
try:
    with open('/usr/share/dict/words') as f:
        words = [w.strip() for w in f if w.strip().isalpha() and 4 <= len(w.strip()) <= 7 and w.strip().islower()]
    print('-'.join(random.sample(words, 3)) if len(words) >= 3 else '')
except OSError:
    print('')
" 2>/dev/null || true)

# Sanitise whatever we fall back to: the caller's name reaches a git branch
# name, so spaces, slashes and leading dashes must not survive.
if [ -z "$NAME" ]; then
  NAME=$(printf '%s' "$NAME_IN" \
    | tr '[:upper:]' '[:lower:]' \
    | tr -c 'a-z0-9-' '-' \
    | sed -e 's/-\{2,\}/-/g' -e 's/^-*//' -e 's/-*$//' \
    | cut -c1-40)
fi
# Everything above can still yield an empty string (a name of only punctuation,
# say). Fall back to something always valid rather than asking git for "".
[ -z "$NAME" ] && NAME="worktree-$(date +%Y%m%d%H%M%S)"

# The generator's output is random, so collisions were effectively impossible.
# The fallback is DETERMINISTIC — the same caller name yields the same branch —
# so two worktrees from one name would collide with "a branch named X already
# exists". This cheap pre-check picks a plausible free name to try first, but
# it is only a first guess: the check-then-act gap between it and the actual
# `git worktree add` below is a real TOCTOU race under concurrent invocations
# (two overlapping calls can both observe the same name as free). Correctness
# does not depend on this loop — it exists only to make the common case not
# need a retry.
if git show-ref --verify --quiet "refs/heads/$NAME" 2>/dev/null; then
  base="$NAME"
  n=2
  while git show-ref --verify --quiet "refs/heads/$NAME" 2>/dev/null; do
    NAME="${base}-${n}"
    n=$((n + 1))
    [ "$n" -gt 99 ] && { NAME="${base}-$(date +%s)"; break; }
  done
fi

# git-common-dir works from any worktree or the main repo and always points
# back to the shared .git, so this resolves the true repo root regardless of
# what directory the hook subprocess happens to be launched from.
COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null) || exit 1
REPO_ROOT=$(cd "$(dirname "$COMMON_DIR")" && pwd)

mkdir -p "$REPO_ROOT/.claude/worktrees"

# `git worktree add -b` is the only atomic arbiter available here, so it — not
# the pre-check above — is what actually resolves the race: two concurrent
# invocations that both picked the same NAME will have exactly one `add`
# succeed and the other fail on the branch/path collision, and the loser
# retries with a fresh candidate. `|| true` on the add is required, not
# defensive noise: `set -e` would otherwise abort the whole script on the
# first collision, before the retry below ever runs — the same dead-code trap
# documented above for the name generator.
base="$NAME"
attempt=1
max_attempts=20
while :; do
  WPATH="$REPO_ROOT/.claude/worktrees/$NAME"
  if git -C "$REPO_ROOT" worktree add -b "$NAME" "$WPATH" HEAD >/dev/null 2>/dev/null; then
    break
  fi
  attempt=$((attempt + 1))
  if [ "$attempt" -gt "$max_attempts" ]; then
    # Unique by construction: timestamp + PID cannot collide with a prior
    # attempt from this or any other process.
    NAME="${base}-$(date +%s)-$$"
    WPATH="$REPO_ROOT/.claude/worktrees/$NAME"
    git -C "$REPO_ROOT" worktree add -b "$NAME" "$WPATH" HEAD >/dev/null
    break
  fi
  NAME="${base}-${attempt}-$$"
done

# Deliberately NOT running `direnv allow` here.
#
# It would fix a real problem: .envrc exports PYTHONPATH="$PWD/src", direnv only
# loads an .envrc it has been told to trust, and a worktree's .envrc is a
# distinct file from the main checkout's — so it starts untrusted, the shell
# keeps the PYTHONPATH it exported for whichever checkout it started in, and
# imports of mail/resume/core silently resolve to THAT tree.
#
# But .envrc is a TRACKED, branch-controlled file. Auto-approving it means any
# branch this hook creates a worktree for — including one from an untrusted PR —
# gets its .envrc trusted and executed on the next direnv load, before a human
# reads it. That is arbitrary shell execution from branch content, a worse
# problem than the one it solves.
#
# Handled without the trust grant instead:
#   - bin/_router.py strips foreign-checkout PYTHONPATH entries, so every
#     ./bin/* command resolves to this worktree regardless of direnv.
#   - The Makefile pins PYTHONPATH for make targets.
#   - .claude/scripts/check-pythonpath.sh warns at SessionStart when PYTHONPATH
#     names another checkout, and tells the user to run `direnv allow .`
#     themselves after reading the file.
if command -v direnv >/dev/null 2>&1 && [ -f "$WPATH/.envrc" ]; then
  echo "note: run 'direnv allow .' in $WPATH after reviewing its .envrc" >&2
fi

echo "$WPATH"
