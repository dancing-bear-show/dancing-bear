#!/usr/bin/env bash
# PreToolUse hook (matcher: Write|Edit|Bash) -- stop a read-only-contract agent
# from modifying tracked source.
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
# SCOPE: WHAT THIS DOES AND DOES NOT ENFORCE
# ------------------------------------------
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
# stage's artifact inside a shared workspace, and this hook will allow it.
#
# THE TWO TOOL PATHS ARE NOT EQUALLY STRONG. Say so rather than claiming "enforced".
#
#   Write/Edit -- STRONG. `.tool_input.file_path` is a single string the harness hands
#     us. There is no grammar to approximate: the path we judge is the path that gets
#     written. If it resolves under a guarded prefix, the call is blocked, full stop.
#
#   Bash -- WEAK, and structurally so. Added because the Write-only version was
#     trivially bypassable (`echo x > src/mail/cli.py` never reached this hook), which
#     review caught. But it works by scanning a COMMAND STRING for operands that look
#     like guarded paths, and block-destructive-bash.sh's header documents four rounds
#     of adversarial review finding 68 holes in exactly that approach. Everything it
#     says applies here verbatim: `> src${IFS}/x.py`, a path in a variable, a quote-
#     concatenated filename, `python3 -c "open(...)"` with a computed name -- all reach
#     the shell. Fixing them individually means writing a bash parser.
#
# So: the Bash branch raises the cost of an accidental source edit from zero to
# noticeable. It does not make the boundary unbypassable, and nothing here should be
# read as saying it does. The strong guarantee is on Write/Edit only.
#
# Both branches are still worth having. An agent that reflexively runs
# `sed -i` on a file it was reading is the realistic failure, not an agent
# deliberately assembling a path from $IFS to evade a hook.
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

# From here down the caller is a read-only-contract agent.

# REPO_ROOT is derived from this script's location, not from cwd: a subagent's cwd may
# be its own worktree, the main checkout, or somewhere else entirely, and reading the
# guarded prefixes relative to a moving cwd is how a guard ends up protecting the wrong
# tree. The script lives at <repo>/.claude/hooks/, so <repo> is two levels up.
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." 2>/dev/null && pwd) || REPO_ROOT=""

# Tracked trees a read-only-contract agent must never modify, even when a caller names
# one as an output. A prompt naming src/foo.py as a stage output is misconfigured, not
# authorization -- that is the exact case round 3 of #392 found.
#
# Stored WITHOUT a trailing slash, and matched both as the bare directory AND as a
# prefix of its contents. The earlier version stored "src/" and tested prefixes only,
# so `rm -rf src/` was blocked while `rm -rf src` -- one character shorter, and the
# spelling that actually removes the tree -- was allowed. A guard that refuses the
# careful spelling and permits the destructive one is worse than no guard, because it
# reads as protection. The suite now pins both spellings for every entry.
#
# `config` and `.qlty` are here because they are tracked configuration this repo really
# has: config/filters_unified.example.yaml and .qlty/qlty.toml. Listing only `configs/`
# missed both, so a read-only role could rewrite the lint configuration that judges its
# own branch. Verified with `git ls-files config/ .qlty/`, not assumed.
SOURCE_TREES=(
  "src"
  "tests"
  "bin"
  "config"
  "configs"
  "workflows"
  ".claude"
  ".github"
  ".qlty"
  "concerns"
  "docs"
  ".llm"
)

# Repo-root files. Derived from the path SHAPE, not enumerated.
#
# This was a hand-maintained list of 11 names, and a hand-maintained list of tracked
# files is guaranteed to drift: `git ls-files` reports 20 files at the repo root, so
# nine were unguarded -- including AGENTS.md, COPILOT.md and GEMINI.md. That last group
# is the sharp one: a read-only agent rewriting AGENTS.md changes the instructions
# LATER agents consume, which is a more durable compromise than editing one source
# file. Review found it; enumerating harder would only have postponed the next miss.
#
# The rule: a repo-relative token with no `/` that names a file WHICH EXISTS at the
# repo root is guarded. Derived from the filesystem at call time, so adding a root file
# guards it automatically and nothing has to be remembered.
#
# "No slash" ALONE is not enough, and the first version of this made that mistake:
# it refused `rm -rf srcfoo`, the bare word `1` from `2>&1`, and an unexpanded `$P`,
# all of which are slashless and none of which are repo-root files. The existence test
# is what separates a real root file from any other bare word. Caught by the suite's
# ALLOW half.
#
# Deliberately not `git ls-files`: it forks a process per call, answers "no" for a NEW
# root file (a case worth blocking), and misbehaves when cwd is not a repo. A `-e` test
# against REPO_ROOT costs nothing and does not depend on the index. The tradeoff is
# that a *new* root file is not guarded until it exists -- acceptable, because creating
# one is itself the write we would want to catch, and the SOURCE_TREES rules already
# cover everything under a directory.
_is_repo_root_file() { # _is_repo_root_file <repo-relative-path> -> 0 if yes
  case "$1" in
    */*|"") return 1 ;;   # has a directory component, or is empty
  esac
  [ -n "$REPO_ROOT" ] && [ -e "$REPO_ROOT/$1" ]
}

# classify_path <path> -> prints "guarded:<reason>" or "ok"; never exits.
#
# Shared by the Write/Edit and Bash branches so the two cannot drift into disagreeing
# about what counts as source. A path one tool refuses and the other permits is the
# same shape of hole as a pair of guards disagreeing about what a template is.
classify_path() {
  # Two statements, not `local p="$1" rel="$p"`. In a single `local`, bash expands the
  # later initialiser before the earlier assignment is visible, so `rel="$p"` read an
  # unset `p` and `set -u` aborted the function -- which, because the abort happened
  # inside a command substitution, surfaced as an empty verdict and an ALLOW. A guard
  # that fails open when its own helper dies is the exact shape this file exists to
  # avoid; caught by the suite, not by reading.
  local p="$1"
  local rel="$p"

  # Collapse `/./` segments before anything else looks at the path. `a/./b` and `a/b`
  # name the same file, and every guarded-prefix test below is textual, so a single
  # inserted `/./` walked straight past it: `<repo>/./src/mail/cli.py` reduced to
  # `./src/mail/cli.py`, which does not start with `src/`. Both the Write branch and
  # the redirect branch were bypassable that way. Review found it; the suite pins it.
  #
  # Looped rather than one substitution because the collapse happens in stages --
  # a single pass over `a/././b` leaves `a/./b`, which still defeats the prefix test.
  # Each iteration strictly shortens the string, so this terminates.
  # Repeated separators collapse first: `a//b` and `a/b` name the same file, and
  # `<repo>//src/mail/cli.py` left `rel=/src/mail/cli.py` after the REPO_ROOT prefix
  # came off -- a leading slash, matching no guarded prefix. Same class as the `/./`
  # bug below, one variant over, and found the same way. Order matters: collapsing
  # separators first turns `a//./b` into `a/./b`, which the next loop then handles.
  while [ "$p" != "${p//\/\//\/}" ]; do
    p="${p//\/\//\/}"
  done
  while [ "$p" != "${p//\/.\//\/}" ]; do
    p="${p//\/.\//\/}"
  done
  # The leading `./` form has no slash in front of it to match the rule above.
  while [ "${p#./}" != "$p" ]; do
    p="${p#./}"
  done
  rel="$p"

  case "$p" in
    /*)
      if [ -n "$REPO_ROOT" ] && [ "${p#"$REPO_ROOT"/}" != "$p" ]; then
        rel="${p#"$REPO_ROOT"/}"
        # The repo-relative remainder can itself begin `./` once the prefix comes off.
        while [ "${rel#./}" != "$rel" ]; do
          rel="${rel#./}"
        done
      else
        # An absolute path outside this repo is not this repo's tracked source. The
        # scratchpad and /tmp artifacts land here, which is the intended allow.
        printf 'ok'
        return
      fi
      ;;
  esac

  # `..` can walk out of an artifact directory and back into source: a path like
  # `outputs/../src/mail/cli.py` has no `src/` prefix as written but resolves into
  # src/. Rather than normalize (textual normalization disagrees with the kernel when
  # symlinks are involved -- see the Known gaps table in README.md), refuse it.
  case "$rel" in
    *..*) printf "guarded:a path containing '..', which can resolve back into source"; return ;;
  esac

  # Strip a trailing slash so `src/` and `src` reach the same comparison. Without
  # this the bare-directory arm below would miss the `src/` spelling.
  local bare="${rel%/}"

  local q
  for q in "${SOURCE_TREES[@]}"; do
    # Two arms, and BOTH are needed. The prefix arm alone was the `rm -rf src` hole:
    # `src/mail/cli.py` starts with `src/`, but the token `src` does not, so the
    # command that removes the whole tree was the one that got through.
    if [ "$bare" = "$q" ]; then
      printf 'guarded:the tracked directory %s itself' "$q"
      return
    fi
    if [ "${rel#"$q"/}" != "$rel" ]; then
      printf 'guarded:tracked source (under %s/)' "$q"
      return
    fi
  done
  if _is_repo_root_file "$bare"; then
    printf 'guarded:a file at the repo root (%s) -- tracked content, not an artifact' "$bare"
    return
  fi
  printf 'ok'
}

TOOL=$(jq -r '.tool_name // ""' <<< "$PAYLOAD" 2>/dev/null || echo "")

# ---------------------------------------------------------------------------
# Bash branch -- weak by construction; see the SCOPE note above.
# ---------------------------------------------------------------------------
if [ "$TOOL" = "Bash" ]; then
  if ! CMD=$(jq -er '.tool_input.command' <<< "$PAYLOAD" 2>/dev/null); then
    echo "Blocked: could not parse .tool_input.command for a $AGENT Bash call." >&2
    echo "Failing closed rather than allowing an uninspected command." >&2
    exit 2
  fi
  CMD_TYPE=$(jq -r '.tool_input.command | type' <<< "$PAYLOAD" 2>/dev/null || echo "unknown")
  if [ "$CMD_TYPE" != "string" ]; then
    echo "Blocked: .tool_input.command is a $CMD_TYPE, not a string." >&2
    echo "Failing closed rather than allowing a command the hook cannot read." >&2
    exit 2
  fi
  if [ -z "${CMD//[[:space:]]/}" ]; then
    echo "Blocked: .tool_input.command is empty." >&2
    echo "Failing closed rather than allowing an uninspected command." >&2
    exit 2
  fi

  # WHY THIS IS NOT A BARE OPERAND SCAN.
  #
  # block-destructive-bash.sh scans every operand regardless of command word, and says
  # at length why. That is right for ITS question ("does this command touch a
  # credential file at all?"), because reading a secret is as bad as writing one.
  #
  # It is wrong here, and the first version of this branch got it wrong: the question
  # is "does this command MODIFY source?", and a read does not. Scanning every operand
  # blocked `cat src/mail/cli.py`, `grep -rn AppMeta src/`, `rg --files src/` and
  # `./bin/workflow list` -- reading and running the repo is the researcher's entire
  # job, so that version made the role useless. Caught by the suite's ALLOW half, which
  # is why both halves are asserted.
  #
  # So a token is judged only where it is a WRITE TARGET:
  #   * the operand of an output redirect (`> path`, `>> path`, `>| path`, `>& path`), or
  #   * an operand of a command word that is unambiguously mutating.
  #
  # The command-word list is the weak part and is knowingly incomplete -- see the SCOPE
  # note at the top. `/bin/sed` is handled by matching on the basename, but a mutating
  # tool nobody listed still passes. That is the documented limit, not an oversight.

  # 1. Redirect targets. Normalise every output-redirect spelling to a `>` marker plus
  #    the token, so the target is identifiable whatever the operator and spacing.
  #
  #    `>&` MUST be rewritten before the generic `>` arm. Left to the generic arm,
  #    `echo x >&src/mail/cli.py` becomes `> &src/mail/cli.py` -- the token still
  #    carries a leading `&`, so classify_path judges "&src/mail/cli.py", matches
  #    nothing, and the write goes through. Review found that live; the suite pins it.
  #    (`>&1` and friends are digits, not paths, so they classify as ok and cost
  #    nothing.)
  redir=${CMD//>>/ >}
  redir=${redir//>|/ >}
  redir=${redir//>&/ >}
  redir=${redir//>/ > }
  targets=""
  prev=""
  for tok in $redir; do
    if [ "$prev" = ">" ]; then
      targets="$targets $tok"
    fi
    prev="$tok"
  done

  # 2. WRITE DESTINATIONS of mutating command words -- not every operand.
  #
  #    Treating every operand as a target contradicted this branch's own
  #    write-target-only design, and blocked ordinary reads: `cp src/mail/cli.py
  #    /tmp/copy.py` (a normal way to produce an artifact) and `sed -n '1,5p'
  #    src/mail/cli.py` (prints, writes nothing) were both refused. Review caught it.
  #
  #    So the commands split into three shapes:
  #      * LAST-ARG writers (cp, mv, install, ln) -- only the final operand is the
  #        destination; everything before it is a source being read.
  #      * ALL-ARG writers (rm, rmdir, truncate, touch, shred, unlink, chmod, chown,
  #        patch, tee) -- every operand is acted on.
  #      * CONDITIONAL writers (sed, dd) -- sed rewrites only with -i; dd writes only
  #        to its of= operand. Without those, they read.
  #
  #    Split on separators so each segment is judged against its own leading command
  #    word -- `cat a.py && sed -i '' b.py` must not let the harmless first half
  #    vouch for the second.
  segs=${CMD//&&/;}
  segs=${segs//||/;}
  segs=${segs//|/;}
  IFS=';' read -ra _segments <<< "$segs"
  for seg in "${_segments[@]}"; do
    # shellcheck disable=SC2086
    set -- $seg
    [ "$#" -gt 0 ] || continue
    word=${1##*/}          # /bin/sed -> sed
    word=${word#\\}        # \sed     -> sed
    case "$word" in
      rm|rmdir|truncate|install|touch|shred|unlink|chmod|chown|patch|tee)
        # install is here as well as below: with -d it creates directories from every
        # operand, so treating only the last as a destination would miss the rest.
        shift
        targets="$targets $*"
        ;;
      cp|ln)
        # Only the final operand is written. `cp a b c dir/` writes into dir/ alone,
        # and the earlier operands are sources being READ -- blocking those is what
        # made `cp src/mail/cli.py /tmp/copy.py` fail.
        shift
        [ "$#" -gt 0 ] || continue
        for _ in $(seq 1 $(( $# - 1 ))); do shift; done
        targets="$targets $1"
        ;;
      mv)
        # mv is NOT like cp: it REMOVES the source. `mv src /tmp/elsewhere` destroys
        # the tree just as surely as `rm -rf src`, so both ends are write targets.
        shift
        targets="$targets $*"
        ;;
      sed)
        # Rewrites in place only with -i. Without it, sed reads and prints.
        case " $* " in
          *" -i "*|*" -i."*|*" --in-place"*|*" -i'"*|*' -i"'*)
            shift
            targets="$targets $*"
            ;;
        esac
        ;;
      dd)
        # Writes only to of=; if= is the input.
        for a in "$@"; do
          case "$a" in
            of=*) targets="$targets ${a#of=}" ;;
          esac
        done
        ;;
    esac
  done

  # Strip quoting so `"src/x.py"` and `'src/x.py'` are seen as the path they contain.
  targets=${targets//\"/ }
  targets=${targets//\'/ }

  for tok in $targets; do
    case "$tok" in
      ""|-*) continue ;;   # empty, or a flag rather than a path
    esac
    verdict=$(classify_path "$tok")
    # An empty verdict means classify_path died rather than decided (see the note in
    # that function). Refuse instead of reading the silence as approval.
    if [ -z "$verdict" ]; then
      echo "Blocked: path classification failed for token '$tok' in a $AGENT command." >&2
      echo "Failing closed rather than allowing an unclassified operand." >&2
      exit 2
    fi
    if [ "${verdict#guarded:}" != "$verdict" ]; then
      echo "Blocked: the $AGENT role may not modify tracked source via Bash." >&2
      echo "  command references: $tok" >&2
      echo "  reason: ${verdict#guarded:}" >&2
      echo "" >&2
      echo "This role's definition (.claude/agents/$AGENT.md) states it never modifies" >&2
      echo "source, and forbids routing around that with sed -i, > redirects, or patch." >&2
      echo "Report what needs changing instead; implementing is another role's job." >&2
      echo "" >&2
      echo "Reading these files is fine -- this only blocks commands naming them as" >&2
      echo "operands. If you only meant to read one, use the Read tool." >&2
      exit 2
    fi
  done
  exit 0
fi

# ---------------------------------------------------------------------------
# Write/Edit branch -- the strong one.
# ---------------------------------------------------------------------------
# Apply the same fail-closed parsing its sibling hook uses for file_path.
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

# Judge the path with the same function the Bash branch uses, so the two tools cannot
# drift into disagreeing about what counts as source.
VERDICT=$(classify_path "$FILE")
# Same fail-closed check as the Bash branch: an empty verdict is a dead helper, not
# an approval.
if [ -z "$VERDICT" ]; then
  echo "Blocked: path classification failed for '$FILE' ($AGENT write)." >&2
  echo "Failing closed rather than allowing an unclassified write." >&2
  exit 2
fi
if [ "${VERDICT#guarded:}" != "$VERDICT" ]; then
  echo "Blocked: the $AGENT role may not write tracked source." >&2
  echo "  path:   $FILE" >&2
  echo "  reason: ${VERDICT#guarded:}" >&2
  echo "" >&2
  echo "This role's definition (.claude/agents/$AGENT.md) states it never modifies" >&2
  echo "source. That holds even if the prompt named this path as an output -- a prompt" >&2
  echo "naming a source path as a stage artifact is misconfigured, not authorization." >&2
  echo "" >&2
  echo "Write your findings to a run artifact instead, and report what needs changing in" >&2
  echo "the source file rather than changing it. Implementing is another role's job." >&2
  exit 2
fi

exit 0
