#!/bin/bash
# SessionStart hook: warn when PYTHONPATH points at a DIFFERENT checkout of this
# repo than the one we are working in.
#
# Why this exists. `.envrc` exports PYTHONPATH="$PWD/src", and direnv loads the
# `.envrc` belonging to whichever checkout the shell started in. Start a shell
# in the main checkout, move into `.claude/worktrees/<wt>`, and PYTHONPATH still
# names the MAIN `src/` — the worktree's `.envrc` is a different file and is not
# on direnv's allow list. A PYTHONPATH entry also outranks the editable
# install's `.pth`, so even the worktree's own `.venv` interpreter imports
# `mail`/`resume`/`core` from the other tree.
#
# The failure is silent and looks exactly like success: a command runs, exits 0,
# and reports behaviour from source you are not editing; a test suite passes
# against unmodified code. It cost three separate misdiagnoses in one session
# before anyone noticed the cause.
#
# Two other layers handle the mechanics — `bin/_router.py` strips foreign
# entries so every `./bin/*` command is correct, and the Makefile pins
# PYTHONPATH for `make test`. Neither covers an ad-hoc `python3 -c`, which is
# what this warning is for. Print, never block: a wrong PYTHONPATH is a
# correctness hazard, not a reason to refuse to start.
set -uo pipefail

emit() { python3 -c 'import json,sys; print(json.dumps({"systemMessage": sys.argv[1]}))' "$1"; }

cwd_root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
[ -n "$cwd_root" ] || exit 0

# No PYTHONPATH at all is fine: the editable install resolves correctly.
[ -n "${PYTHONPATH:-}" ] || exit 0

own_src="$cwd_root/src"
foreign=""
IFS=':' read -r -a entries <<< "$PYTHONPATH"
for entry in "${entries[@]}"; do
  [ -n "$entry" ] || continue
  # Only care about entries that are a `src/` dir of some checkout of THIS
  # project (a sibling pyproject.toml). Unrelated PYTHONPATH entries are none
  # of our business.
  case "$(basename "$entry")" in src) ;; *) continue ;; esac
  [ -f "$(dirname "$entry")/pyproject.toml" ] || continue
  resolved=$(cd "$entry" 2>/dev/null && pwd) || continue
  [ "$resolved" = "$own_src" ] && continue
  foreign="$foreign $resolved"
done

[ -n "$foreign" ] || exit 0

emit "WARNING — PYTHONPATH points at another checkout of this repo:${foreign}
This checkout is $cwd_root. Python will import mail/resume/core from the OTHER
tree, so a bare 'python3 -c ...' or 'python3 -m unittest' reports behaviour from
source you are not editing — it exits 0 and looks like a pass.

Use 'make test' and './bin/<tool>' (both pin the path correctly). Before
concluding a change did not take effect, print where the module actually loaded
from: python3 -c \"import resume; print(resume.__file__)\". To fix the shell
itself, run: direnv allow ."
