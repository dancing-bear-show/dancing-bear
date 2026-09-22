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

# Emit the hook's JSON with pure shell — no Python.
#
# Starting a Python interpreter here would run code from the very checkout we
# are about to warn about: PYTHONPATH is still set at this point, and Python
# imports sitecustomize/usercustomize from its entries during startup.
# Demonstrated, not theorised — a sitecustomize.py planted on a foreign
# PYTHONPATH entry printed before the warning did.
#
# Clearing PYTHONPATH and passing -I -S would also close it, but the payload is
# one string in one field, so shell escaping is less machinery than hardening an
# interpreter we do not need. Escapes backslash, double-quote, and newline —
# Escapes backslash, double-quote, and the control characters that are illegal
# raw inside a JSON string (RFC 8259 §7: U+0000–U+001F must be escaped).
#
# Newline alone is not enough. A directory name may legally contain a tab or a
# carriage return on every filesystem this runs on, and such a path reaches
# emit() verbatim through ${foreign}. Verified by creating a real
# ".../we<TAB>ird/src" checkout: the old escaper emitted INVALID JSON, so the
# hook broke its own one-object contract on a path it was built to report.
emit() {
  local msg=$1
  msg=${msg//\\/\\\\}
  msg=${msg//\"/\\\"}
  msg=${msg//$'\n'/\\n}
  msg=${msg//$'\r'/\\r}
  msg=${msg//$'\t'/\\t}
  msg=${msg//$'\b'/\\b}
  msg=${msg//$'\f'/\\f}
  # Any remaining C0 control character has no short escape; drop it rather than
  # emit a byte that makes the whole object unparseable.
  msg=$(printf '%s' "$msg" | LC_ALL=C tr -d '\000-\010\013\016-\037')
  printf '{"systemMessage": "%s"}\n' "$msg"
}

# Sentinel-guarded like every other path capture here: `git rev-parse` prints
# the toplevel followed by a newline, and command substitution cannot tell that
# newline from one belonging to the path. Truncating here is the most damaging
# of the four sites — own_src is derived from cwd_root, so a stripped root makes
# own_src disagree with the correctly-resolved entry and the hook warns that our
# OWN src/ is a foreign checkout, on every session start.
cwd_root=$(git rev-parse --show-toplevel 2>/dev/null && printf '.') || exit 0
cwd_root=${cwd_root%.}
cwd_root=${cwd_root%$'\n'}
[ -n "$cwd_root" ] || exit 0

# No PYTHONPATH at all is fine: the editable install resolves correctly.
[ -n "${PYTHONPATH:-}" ] || exit 0

# Physical, to match the `pwd -P` resolution applied to each entry below.
# Comparing a physical entry against a logical own_src would fail to recognise
# our own src/ when the checkout itself sits behind a symlink, and we would warn
# about ourselves.
# Deliberately NOT sentinel-guarded, unlike cwd_root above and the split and
# expansions below. `pwd -P` can only lose a newline that is in the FINAL
# component, and the basename check below admits an entry only when that
# component is exactly `src` — a path ending in `src\n` has basename `src\n`
# and is skipped before own_src is ever compared. The two conditions are
# mutually exclusive, so a guard here would be unreachable and untestable.
# cwd_root's guard is what actually matters: own_src is derived from it, and a
# newline anywhere in a PARENT component does reach this line.
own_src=$(cd "$cwd_root/src" 2>/dev/null && pwd -P) || own_src="$cwd_root/src"
foreign=""
# Split on ':' ONLY. `IFS=':' read -r -a entries <<< "$PYTHONPATH"` looks
# equivalent but is not: `read` is line-oriented, so it stops at the first
# newline in the here-string. A checkout path legally containing a newline
# therefore lost that entry and everything after it — the truncation happened
# here, before the per-entry `pwd -P` ever ran. bin/_pathrepair.py splits on
# os.pathsep with no such limit, so the shell and Python layers disagreed about
# the same PYTHONPATH: ./bin/* got repaired while the user went unwarned.
# The trailing ':' makes the final entry terminated like the rest; `|| [ -n ]`
# then catches it when the input does not end in a separator.
entries=()
while IFS= read -r -d ':' entry || [ -n "$entry" ]; do
  entries+=("$entry")
done < <(printf '%s:' "$PYTHONPATH")
for entry in "${entries[@]}"; do
  [ -n "$entry" ] || continue
  # Canonicalize FIRST, then inspect. Testing the raw string would miss a
  # symlink such as `/tmp/current-src -> /other-checkout/src`: its basename is
  # `current-src`, so a name check on the unresolved path skips it. The router
  # resolves before testing and strips that entry, so checking the raw string
  # here would leave the two layers disagreeing — the import gets fixed for
  # ./bin/* while the user is never warned about their bare-python3 hazard.
  # `pwd -P` (physical), not bare `pwd`: bare pwd reports the LOGICAL path, so
  # cd'ing into a symlink returns the symlink's own path and the basename check
  # below still sees `current-src` rather than `src`.
  # The sentinel `.` survives command substitution's trailing-newline strip, so
  # a checkout whose physical path legally ends in a newline is not truncated
  # before the basename and marker checks below. Without it that path is
  # silently missed here while bin/_pathrepair.py handles it correctly, leaving
  # the shell and Python layers disagreeing about the same PYTHONPATH.
  # The sentinel must be appended by a SEPARATE command, not by
  # `printf '%s.' "$(pwd -P)"`: that inner substitution strips the newline
  # before printf ever sees it, which defeats the whole point.
  resolved=$(cd "$entry" 2>/dev/null && { pwd -P; printf '.'; }) || continue
  resolved=${resolved%.}       # drop the sentinel
  resolved=${resolved%$'\n'}   # drop the single newline `pwd -P` itself emits
  # Only care about entries that are a `src/` dir of some checkout of THIS
  # project. Unrelated PYTHONPATH entries are none of our business.
  # Parameter expansion, not `$(basename ...)`/`$(dirname ...)`: those are
  # command substitutions and strip trailing newlines all over again, which is
  # what defeated the sentinel above. `${x##*/}` and `${x%/*}` are pure string
  # operations and leave the path byte-exact.
  case "${resolved##*/}" in src) ;; *) continue ;; esac
  # The marker must identify THIS project, not merely "some Python project".
  # A sibling pyproject.toml alone is far too broad — most third-party checkouts
  # have one, so that would warn about paths we have no business touching and
  # train the reader to ignore the warning.
  proj="${resolved%/*}/pyproject.toml"
  [ -f "$proj" ] || continue
  grep -qE '^name *= *"personal-assistants"' "$proj" 2>/dev/null || continue
  [ "$resolved" = "$own_src" ] && continue
  foreign="$foreign $resolved"
done

[ -n "$foreign" ] || exit 0

emit "WARNING — PYTHONPATH points at another checkout of this repo:${foreign}
This checkout is $cwd_root. Python will import mail/resume/core from the OTHER
tree, so a bare 'python3 -c ...' or 'python3 -m unittest' reports behaviour from
source you are not editing — it exits 0 and looks like a pass.

Use 'make test' and './bin/<tool>' (both pin the path correctly). Before
concluding a change did not take effect, print where a module WOULD load from:

  python3 -I -S -c \"import importlib.util as u, os, sys; sys.path[:0] = os.environ.get('PYTHONPATH','').split(os.pathsep); s = u.find_spec('resume'); print(s.origin if s else 'not found')\"

That is deliberately not 'python3 -c \"import resume; print(resume.__file__)\"'.
Importing runs code from whichever checkout wins — the package's __init__, and
sitecustomize from the PYTHONPATH entry before that — which is the hazard this
warning is about. -I -S skips both, PYTHONPATH is re-applied explicitly so the
answer still reflects real resolution order, and find_spec locates the module
without executing it. To fix the shell itself, run: direnv allow ."
