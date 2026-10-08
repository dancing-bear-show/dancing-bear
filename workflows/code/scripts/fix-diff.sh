#!/usr/bin/env bash
# Print the working-tree diff of every path listed in a file, one per line,
# untracked files included -- without touching the index.
#
#   bash workflows/code/scripts/fix-diff.sh <paths-file> > out.patch
#
# Used by review-fix-threads' sweep-fix-regressions and resweep-regressions.
# `git diff HEAD` alone omits untracked files, and a fixer's new test file
# stays untracked until commit-and-push stages it, so a tracked path is
# diffed against HEAD and an untracked one against /dev/null. No `git add`
# (not even `-N`): both callers are read-only stages.
#
# Paths are read from the file, never from the command line, so no path is
# ever typed into shell text. Exit 0 once every path is diffed; 2 on a usage
# error; any git failure (e.g. a listed path that does not exist) exits
# non-zero and the caller must treat the patch as incomplete.
set -euo pipefail

if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
  echo "usage: fix-diff.sh <paths-file>" >&2
  exit 2
fi

while IFS= read -r path || [ -n "$path" ]; do
  [ -n "$path" ] || continue
  if git ls-files --error-unmatch -- "$path" >/dev/null 2>&1; then
    git diff HEAD -- "$path"
  else
    # --no-index exits 1 both when the files differ (the expected case) and
    # when it cannot read the path, so check the path exists first.
    if [ ! -f "$path" ]; then
      echo "fix-diff.sh: a listed untracked path is not a regular file" >&2
      exit 1
    fi
    rc=0
    git diff --no-index -- /dev/null "$path" || rc=$?
    [ "$rc" -le 1 ] || exit "$rc"
  fi
done < "$1"
