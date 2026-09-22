#!/usr/bin/env bash
# PreToolUse hook (matcher: Write) -- stop a read-only-contract agent from writing
# tracked source.
#
# Contract: exit 2 blocks the tool call and shows stderr to Claude. Exit 0 allows.
#
# WHY THIS EXISTS
# ---------------
# `.claude/agents/researcher.md` and `.claude/agents/Plan.md` both grant `Write` and
# then state, in prose, that the agent must only write run artifacts and never tracked
# source. PR #392 spent three review rounds refining that prose. Each round closed a
# hole and opened the next:
#
#   round 1  "writing a NEW file cannot destroy work"   -- false; Write overwrites
#   round 2  "never write a file that already exists"   -- stalls every retry, because
#                                                          a re-run stage meets its own
#                                                          partial output
#   round 3  "never write a path you found by exploring" -- a caller naming src/foo.py
#                                                          as an "output" was obeyed
#
# The lesson is not that round 4 needs better wording. Prose in a frontmatter file is
# read by a model that may or may not apply it; this hook is read by the harness, which
# always applies it. The prose stays as intent; this is the part with teeth.
#
# WHY A ROLE CHECK IS POSSIBLE AT ALL
# -----------------------------------
# The PreToolUse payload carries `agent_type` -- the spawning role name, e.g.
# "researcher". Verified by probe rather than assumed: a researcher subagent's Write
# arrived here with `agent_type: "researcher"`, alongside session_id, cwd, tool_name and
# tool_input. Without that field this hook could not distinguish a researcher's write
# from a code-writer's, and would have to be abandoned rather than guessed at.
#
# The main session has NO agent_type. That is the correct allow: the user driving the
# session directly is not a read-only-contract agent, and blocking them would make the
# repo unusable.
#
# SCOPE: THIS ENFORCES ONE OF THE TWO CONDITIONS, NOT BOTH
# --------------------------------------------------------
# The agent definitions state two conditions a path must satisfy:
#
#   1. the caller named this exact file as an output of this stage, AND
#   2. the path is a run artifact, not tracked source
#
# This hook enforces (2) only. It cannot enforce (1): a PreToolUse hook sees one tool
# call in isolation, with no access to the stage's `writes_to` list or the prompt that
# spawned the agent. Condition (1) remains advisory, and the agent definitions remain
# the place it is stated.
#
# That is a real limit, not a rounding error: a researcher can still overwrite another
# stage's artifact inside a shared workspace, and this hook will allow it. What it
# stops is the case that actually reached review three times -- a read-only-contract
# agent writing into src/, tests/, bin/, workflows/, or .claude/.
#
# Deliberately NOT a git query. `git ls-files <path>` would be a truer test of
# "tracked", but it forks a process on every Write, answers "no" for a new file inside
# src/ (exactly the case worth blocking), and behaves unpredictably when cwd is not a
# repo. A directory-prefix test is cruder, faster, and errs toward blocking.

set -u

# Fail CLOSED on a malformed payload, for the reason its sibling hooks document at
# length: a hook that cannot read its input does not know what it is approving, and
# the failure of the inspecting step must never read as approval.
PAYLOAD=$(cat)

if ! AGENT=$(jq -er '.agent_type // ""' <<< "$PAYLOAD" 2>/dev/null); then
  echo "Blocked: could not parse the PreToolUse payload (not JSON, or .agent_type unreadable)." >&2
  echo "Failing closed rather than allowing an uninspected write." >&2
  exit 2
fi

# A non-string agent_type is not a jq parse failure: {"agent_type": {}} exits 0 and
# prints "{}". Treating that as a role name would compare a literal "{}" against the
# role list, match nothing, and allow the write -- a spurious ALLOW through a door the
# parse check does not watch.
AGENT_TYPE=$(jq -r '.agent_type | type' <<< "$PAYLOAD" 2>/dev/null || echo "unknown")
case "$AGENT_TYPE" in
  string|null) ;;
  *)
    echo "Blocked: .agent_type is a $AGENT_TYPE, not a string." >&2
    echo "Failing closed rather than allowing a write from an unidentifiable caller." >&2
    exit 2
    ;;
esac

# Roles whose definition says they never modify source. Keep in sync with the
# `disallowedTools`/body contract in .claude/agents/<role>.md.
#
# Explore is included even though it cannot Write today (its frontmatter still
# disallows the tool). If that is ever relaxed the way researcher's and Plan's were,
# this list should already be right rather than needing to be remembered.
READONLY_ROLES=(
  "researcher"
  "Plan"
  "Explore"
  "reviewer"
  "critic"
  "fact-checker"
  "unit-validator"
  "cross-unit-validator"
  "haiku-reviewer"
)

# No agent_type means the main session, not a subagent. Allow.
if [ -z "$AGENT" ] || [ "$AGENT" = "null" ]; then
  exit 0
fi

IS_READONLY=0
for r in "${READONLY_ROLES[@]}"; do
  if [ "$AGENT" = "$r" ]; then
    IS_READONLY=1
    break
  fi
done

# A role with no read-only contract (code-writer, tester, ci-fixer, doc-writer,
# thread-fixer, workflow-author, …) is supposed to write source. Allow.
if [ "$IS_READONLY" -eq 0 ]; then
  exit 0
fi

# From here down the caller is a read-only-contract agent. Now the path matters, so
# apply the same fail-closed parsing its sibling hook uses for file_path.
if ! FILE=$(jq -er ".tool_input.file_path" <<< "$PAYLOAD" 2>/dev/null); then
  echo "Blocked: could not parse .tool_input.file_path for a $AGENT write." >&2
  echo "Failing closed rather than allowing an uninspected write." >&2
  exit 2
fi

FILE_TYPE=$(jq -r '.tool_input.file_path | type' <<< "$PAYLOAD" 2>/dev/null || echo "unknown")
if [ "$FILE_TYPE" != "string" ]; then
  echo "Blocked: .tool_input.file_path is a $FILE_TYPE, not a string." >&2
  echo "Failing closed rather than allowing a write the hook cannot read." >&2
  exit 2
fi

if [ -z "${FILE//[[:space:]]/}" ]; then
  echo "Blocked: .tool_input.file_path is empty." >&2
  echo "Failing closed rather than allowing an uninspected write." >&2
  exit 2
fi

# Resolve the path against the repo so relative and absolute spellings are judged
# identically. `src/mail/cli.py` and `/…/dancing-bear/src/mail/cli.py` are the same
# write and must not get different answers.
#
# REPO_ROOT is derived from this script's location, not from cwd: a subagent's cwd may
# be its own worktree, the main checkout, or somewhere else entirely, and reading the
# guarded prefixes relative to a moving cwd is how a guard ends up protecting the wrong
# tree. The script lives at <repo>/.claude/hooks/, so <repo> is two levels up.
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." 2>/dev/null && pwd) || REPO_ROOT=""

REL="$FILE"
case "$FILE" in
  /*)
    if [ -n "$REPO_ROOT" ] && [ "${FILE#"$REPO_ROOT"/}" != "$FILE" ]; then
      REL="${FILE#"$REPO_ROOT"/}"
    else
      # An absolute path outside this repo is not this repo's tracked source. The
      # scratchpad and /tmp artifacts land here, which is the intended allow.
      exit 0
    fi
    ;;
  ./*) REL="${FILE#./}" ;;
esac

# `..` can walk out of an artifact directory and back into source: a path like
# `outputs/../src/mail/cli.py` has no `src/` prefix as written but resolves into src/.
# Rather than normalize (textual normalization disagrees with the kernel when symlinks
# are involved -- see the Known gaps table in README.md), refuse the ambiguity.
case "$REL" in
  *..*)
    echo "Blocked: $AGENT may not write a path containing '..' ($FILE)." >&2
    echo "Such a path can resolve back into tracked source. Name the artifact directly." >&2
    exit 2
    ;;
esac

# Tracked source trees a read-only-contract agent must never write, even when a caller
# names one as an output. A prompt naming src/foo.py as a stage output is misconfigured,
# not authorization -- that is the exact case round 3 of #392 found.
SOURCE_PREFIXES=(
  "src/"
  "tests/"
  "bin/"
  "configs/"
  "workflows/"
  ".claude/"
  ".github/"
  "concerns/"
  "docs/"
  ".llm/"
)

for p in "${SOURCE_PREFIXES[@]}"; do
  if [ "${REL#"$p"}" != "$REL" ]; then
    echo "Blocked: the $AGENT role may not write tracked source ($FILE matches $p)." >&2
    echo "" >&2
    echo "This role's definition (.claude/agents/$AGENT.md) states it never modifies source." >&2
    echo "That holds even if the prompt named this path as an output -- a prompt naming a" >&2
    echo "source path as a stage artifact is misconfigured, not authorization." >&2
    echo "" >&2
    echo "Write your findings to a run artifact instead, and report what needs changing in" >&2
    echo "the source file rather than changing it. Implementing is another role's job." >&2
    exit 2
  fi
done

# Repo-root files that are build/lint/CI configuration rather than run artifacts.
# A read-only agent writing setup.cfg or the mypy baseline is the same category of
# mistake as writing src/, and none of them sit under a guarded directory prefix.
case "$REL" in
  Makefile|pyproject.toml|setup.cfg|setup.py|.coveragerc|.bandit|\
  typecheck-baseline.json|CLAUDE.md|README.md|.envrc|.gitignore)
    echo "Blocked: the $AGENT role may not write repo configuration ($FILE)." >&2
    echo "Report the change needed rather than making it." >&2
    exit 2
    ;;
esac

exit 0
