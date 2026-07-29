#!/bin/bash
# WorktreeCreate hook: rename the harness's proposed branch name to 3 random
# nouns (e.g. "coral-panda-drift") and echo the chosen name back to stdout.
#
# The hook payload only ever contains `name` (the harness's proposed branch
# name) — never a filesystem path. The worktree directory doesn't exist yet
# at hook-fire time, so there is nothing on disk to `cd` into or inspect.
# The harness takes whatever this script prints on stdout as the branch/dir
# name for the worktree it is about to create.
INPUT=$(cat)
NAME_IN=$(echo "$INPUT" | jq -r '.name // empty' 2>/dev/null)

# No name in the payload — nothing to rename, let the harness use its default.
[ -z "$NAME_IN" ] && exit 0

NAME=$(python3 -c "
import random
with open('/usr/share/dict/words') as f:
    words = [w.strip() for w in f if w.strip().isalpha() and 4 <= len(w.strip()) <= 7 and w.strip().islower()]
print('-'.join(random.sample(words, 3)))
" 2>/dev/null)

[ -z "$NAME" ] && echo "$NAME_IN" && exit 0

echo "$NAME"
