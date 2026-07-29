#!/bin/bash
# Rename auto-created worktree branch to 3 random nouns (e.g. "coral-panda-drift")
INPUT=$(cat)
WPATH=$(echo "$INPUT" | jq -r '.worktree_path // .path // empty' 2>/dev/null)

# No reliable path from the hook payload — do nothing rather than guess.
# Guessing (e.g. "newest worktree in `git worktree list`") risks renaming the
# branch of an unrelated, already-in-use worktree.
[ -z "$WPATH" ] && exit 0

NAME=$(python3 -c "
import random
with open('/usr/share/dict/words') as f:
    words = [w.strip() for w in f if w.strip().isalpha() and 4 <= len(w.strip()) <= 7 and w.strip().islower()]
print('-'.join(random.sample(words, 3)))
")

[ -z "$NAME" ] && echo "$WPATH" && exit 0

cd "$WPATH" || exit 1
CURRENT=$(git branch --show-current)

# WorktreeCreate can fire more than once against the same worktree directory
# (e.g. once per session resume). Without a persistent marker, the "is this
# fresh" check below re-evaluates clean-tree/0-ahead every time and renames
# an already-named worktree again on each firing. A marker file makes the
# rename a one-time, idempotent operation per worktree.
MARKER="$WPATH/.claude/.worktree-named"
if [ -f "$MARKER" ]; then
  echo "$WPATH"
  exit 0
fi

# Only rename a worktree that is genuinely fresh: no uncommitted changes and
# no commits yet ahead of the branch it was created from. A worktree with any
# real state (uncommitted edits or existing commits) is either mid-use by
# another session or already has meaningful history — renaming its branch
# out from under it is how a concurrent session's real work gets silently
# retargeted. Branch-name shape is NOT a reliable signal (a legitimately
# named branch like "milchy-schuss-topsail" is indistinguishable from an
# auto-generated one), so this checks actual worktree state instead.
# Only mark as named when a rename actually happens here — if the worktree
# is dirty or ahead on this firing (not yet fresh, or already renamed by a
# prior firing before the marker existed), leave it eligible for the next
# firing instead of permanently skipping it.
if [ -n "$CURRENT" ] && [[ "$CURRENT" != */* ]]; then
  if [ -z "$(git status --porcelain 2>/dev/null)" ]; then
    UPSTREAM=$(git rev-parse --abbrev-ref "$CURRENT@{upstream}" 2>/dev/null)
    AHEAD=1
    if [ -n "$UPSTREAM" ]; then
      AHEAD=$(git rev-list --count "${UPSTREAM}..HEAD" 2>/dev/null || echo 1)
    fi
    if [ "$AHEAD" = "0" ]; then
      git branch -m "$CURRENT" "$NAME"
      mkdir -p "$WPATH/.claude" && touch "$MARKER"
    fi
  fi
fi

echo "$WPATH"
