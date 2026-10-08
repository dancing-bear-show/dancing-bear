#!/usr/bin/env bash
# PreToolUse hook (matcher: Bash) -- refuse to open a PR for a commit the
# pre-Copilot concern swarm has not swept.
#
# Contract: exit 2 blocks the tool call and shows stderr to Claude. Exit 0 allows.
#
# THE EVIDENCE
# ------------
# `./bin/workflow sweep-record write|waive` leaves one JSON file per commit at
#   <git common dir>/dancing-bear/concern-sweeps/<head_sha>.json
# inside .git, shared by every worktree and never tracked. This hook reads that
# file directly. It must NOT call ./bin/workflow or import repo modules: hooks run
# with the session's environment, which may name a foreign checkout on PYTHONPATH.
#
# WHAT COUNTS AS OPENING A PR
# ---------------------------
#   gh pr create | gh pr new          (gh by basename; -R/--repo allowed before create)
#   gh api -X POST repos/O/R/pulls    (commit from its head= field)
#   ./bin/github pr create            (also bin/github, python3 -m github_assistant)
#   ./bin/pr-assistant                (creates a PR when none exists; allowed with
#                                      --no-create or --dry-run)
#   hub pull-request
# also inside a static `bash -c '...'` / `sh -c`, and after `VAR=1`, `env`,
# `command`, `builtin`, `exec`, `nohup`, `timeout 5` or `nice`.
#
# The commit checked is HEAD of the payload cwd (following a literal `cd`), or the
# tip of the branch named by --head. Anything that cannot be known before the shell
# runs -- an unbalanced quote, a `$VAR` program or --head, a `cd "$D"`, a --head
# that does not resolve locally -- fails CLOSED. So does any form the analyser does
# not fully model: `$(...)`/backticks that open a PR, `eval`, `env -S`, `bash -c "$X"`,
# `source`, a PR entry run by xargs/find/sudo, an unreadable `gh api graphql` body.
#
# KNOWN GAPS: command semantics no tokenizer can see -- a script file or Makefile
# target that runs gh pr create, `python3 -c` or any program that calls the GitHub
# API itself, curl to api.github.com, user-defined `gh alias` names, git aliases.
#
# COST: every Bash call pays one bash regex over the payload. Only a command whose
# JSON text contains "pr", "pull", "gh", "hub" or "api" (any case), a quote, a backslash, `$`, a
# backtick, a brace or a glob character reaches Python. The filter is load-bearing -- a command it passes is
# never analysed -- so it errs toward Python for anything that can hide a word.

set -u

PAYLOAD="$(cat)"

# Pull tool_input.command out of the JSON without a parser. Inside a JSON string
# every `"` is escaped as `\"`, so the literal `"command"` key cannot be forged by
# text in another field; the capture is still JSON-escaped, which is fine for a
# substring test. A \u escape could spell "pr" invisibly, so it falls through too.
_re='"command"[[:space:]]*:[[:space:]]*"(([^"\\]|\\.)*)"'
if [[ $PAYLOAD =~ $_re ]]; then
  _cmd=${BASH_REMATCH[1]}
  # Any `gh`, `hub` or `api` reaches Python too: `gh api graphql --input q.json`
  # names no PR word, yet its body can create one, and only the analyser can
  # tell an inspectable GraphQL call from one it must refuse.
  # A quote, backslash, `$`, backtick, brace or glob character can spell "pr"
  # without the substring (`gh p''r create`, `gh p\r create`, `gh $'\x70'r create`,
  # `gh p{r,} create`, `gh p? create`), so any of them reaches Python too. The
  # capture is JSON-escaped: a `"` in the command arrives as `\"`, so the
  # backslash test covers double quotes as well.
  case "$_cmd" in
    *[Pp][Rr]*|*[Pp][Uu][Ll][Ll]*|*[Gg][Hh]*|*[Hh][Uu][Bb]*|*[Aa][Pp][Ii]*|*\\*|*\'*|*\$*|*\`*|*\{*|*\**|*\?*|*\[*) ;;
    *) exit 0 ;;
  esac
elif [[ $PAYLOAD != *'"command"'* ]]; then
  exit 0  # not a Bash payload with a command at all
fi

# `python3 -I -S`, never bare python3: a foreign PYTHONPATH would otherwise run
# that tree's sitecustomize.py before the helper starts. The helper sits beside
# this script; if it is missing, fail closed rather than allow unchecked.
_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P)"
if [ ! -f "$_dir/_pr_create_targets.py" ]; then
  echo "Blocked: the PR-create analyser is missing ($_dir/_pr_create_targets.py)." >&2
  echo "It must sit beside require-concern-sweep.sh. Failing closed." >&2
  exit 2
fi

printf '%s' "$PAYLOAD" | python3 -I -S "$_dir/_pr_create_targets.py"
_rc=$?
if [ "$_rc" -eq 0 ]; then
  exit 0
fi
if [ "$_rc" -ne 2 ]; then
  echo "Blocked: the PR-create analyser did not complete (exit $_rc); failing closed." >&2
fi
exit 2
