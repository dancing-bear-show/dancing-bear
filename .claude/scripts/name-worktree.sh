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

NAME=$(python3 -c "
import random
with open('/usr/share/dict/words') as f:
    words = [w.strip() for w in f if w.strip().isalpha() and 4 <= len(w.strip()) <= 7 and w.strip().islower()]
print('-'.join(random.sample(words, 3)))
" 2>/dev/null)
[ -z "$NAME" ] && NAME="$NAME_IN"

# git-common-dir works from any worktree or the main repo and always points
# back to the shared .git, so this resolves the true repo root regardless of
# what directory the hook subprocess happens to be launched from.
COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null) || exit 1
REPO_ROOT=$(cd "$(dirname "$COMMON_DIR")" && pwd)
WPATH="$REPO_ROOT/.claude/worktrees/$NAME"

mkdir -p "$REPO_ROOT/.claude/worktrees"
git -C "$REPO_ROOT" worktree add -b "$NAME" "$WPATH" HEAD >/dev/null

echo "$WPATH"
