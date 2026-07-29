#!/bin/bash
# Rename auto-created worktree branch to 3 random nouns (e.g. "coral-panda-drift")
INPUT=$(cat)
WPATH=$(echo "$INPUT" | jq -r '.worktree_path // .path // empty' 2>/dev/null)

# Fallback: newest non-main worktree
if [ -z "$WPATH" ]; then
  MAIN=$(git rev-parse --show-toplevel 2>/dev/null)
  WPATH=$(git worktree list --porcelain | grep '^worktree ' | awk '{print $2}' | grep -v "^${MAIN}$" | tail -1)
fi

[ -z "$WPATH" ] && exit 1

NAME=$(python3 -c "
import random
with open('/usr/share/dict/words') as f:
    words = [w.strip() for w in f if w.strip().isalpha() and 4 <= len(w.strip()) <= 7 and w.strip().islower()]
print('-'.join(random.sample(words, 3)))
")

[ -z "$NAME" ] && echo "$WPATH" && exit 0

cd "$WPATH" && CURRENT=$(git branch --show-current) && [ -n "$CURRENT" ] && git branch -m "$CURRENT" "$NAME"

echo "$WPATH"
