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

# REPO_ROOT: the project whose source this guard protects.
#
# $CLAUDE_PROJECT_DIR FIRST, script location as the fallback.
#
# Deriving it only from the script's location silently disarms the documented global
# install. Copy this file to ~/.claude/hooks (which README.md tells people to do) and
# "two levels up" becomes $HOME: an absolute payload naming real project source no
# longer starts with REPO_ROOT, so the prefix strip does not apply, the path is judged
# as outside the repo, and it is ALLOWED. Verified by simulating the install --
# `<repo>/src/mail/cli.py` blocked by the repo-local copy and allowed by the global
# one. Relative paths still blocked in both, which makes it worse: the guard looks
# alive right up until someone passes an absolute path.
#
# Not cwd, in either branch: a subagent's cwd may be its own worktree, the main
# checkout, or somewhere else entirely, and reading the guarded prefixes relative to a
# moving cwd is how a guard ends up protecting the wrong tree.
# `pwd -P`, not `pwd`, in BOTH branches.
#
# A logical root and a physical path do not compare equal. The symlink check below
# canonicalises candidate parents with `pwd -P`, so if CLAUDE_PROJECT_DIR is itself a
# symlink -- or the payload simply spells the checkout physically -- a path physically
# inside the repo failed the textual `REPO_ROOT/` test, `_real` was compared against
# the logical spelling, and the strong Write/Edit check returned ok. Two halves of the
# same file disagreeing about what the root is.
if [ -n "${CLAUDE_PROJECT_DIR:-}" ] && [ -d "${CLAUDE_PROJECT_DIR}" ]; then
  REPO_ROOT=$(cd -P "$CLAUDE_PROJECT_DIR" 2>/dev/null && pwd -P) || REPO_ROOT=""
else
  # Repo-local install: the script lives at <repo>/.claude/hooks/, so <repo> is two
  # levels up. Correct when the hook ships inside the checkout it guards.
  REPO_ROOT=$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." 2>/dev/null && pwd -P) || REPO_ROOT=""
fi

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
# The list below is a FALLBACK, not the primary rule.
#
# Enumerating tracked directories drifts, exactly as enumerating tracked root files
# did. That list was derived from a property last round and this one was left
# hand-maintained, so it drifted the same way within the same function: `templates/`
# and `signatures_assets/` were both tracked and both unguarded. Review found the
# first; auditing every top-level tracked directory found the second.
#
# So the primary rule is now derived: a top-level directory that EXISTS under
# REPO_ROOT is tracked repo content and is guarded. Artifacts do not live at the top
# level -- they go to a workspace, /tmp, or a named output directory, which resolve
# outside the repo or sit deeper than one segment. Adding a directory to the repo
# guards it with nothing to remember.
#
# The explicit list stays as a floor for the case where REPO_ROOT could not be
# resolved (an unset CLAUDE_PROJECT_DIR on a global install), so the guard degrades to
# "still blocks the obvious trees" rather than to nothing.
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
  "templates"
  "signatures_assets"
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
# root file, and misbehaves when cwd is not a repo.
#
# THE EXISTENCE TEST IS TOOL-DEPENDENT, and treating it as universal was a regression
# I introduced. The old comment here called "a new root file is not guarded until it
# exists" an acceptable tradeoff, on the reasoning that creating one is itself the
# write we would catch. That is circular: the create IS the write, and it was allowed.
# `Write new.py` put new source at the repo root, contradicting the README's claim
# that every repo-root file is guarded.
#
# The two tools ask different questions, so they get different answers:
#
#   Write/Edit -- `file_path` is a real path the harness is about to write. A
#     slashless path IS a repo-root file whether or not it exists yet, so existence
#     must not be required. STRICT=1.
#   Bash -- operands are bare words that may be anything: `rm -rf srcfoo`, the `1`
#     from `2>&1`, an unexpanded `$P`. Requiring existence is what stops those being
#     refused as root files. STRICT=0.
#
# That split is the whole fix: the over-blocking the existence test was added to
# prevent is a Bash-side problem, and it was costing the Write side its guarantee.
_is_repo_root_file() { # _is_repo_root_file <repo-relative-path> [strict] -> 0 if yes
  case "$1" in
    */*|"") return 1 ;;   # has a directory component, or is empty
  esac
  [ -n "$REPO_ROOT" ] || return 1
  if [ "${2:-0}" = "1" ]; then
    # STRICT (Write/Edit): `file_path` is a path the harness is about to write, not a
    # shell word. A leading dash is then part of the FILENAME -- `-probe.py` is a legal
    # repo-root file, and skipping it as a flag allowed a read-only agent to create new
    # source at the root. The dash filter belongs to the Bash side alone.
    return 0
  fi
  # Non-strict (Bash): operands really can be flags, and a dash-led one is never a
  # filename we should refuse.
  case "$1" in -*) return 1 ;; esac
  [ -e "$REPO_ROOT/$1" ]
}

# classify_path <path> -> prints "guarded:<reason>" or "ok"; never exits.
#
# Shared by the Write/Edit and Bash branches so the two cannot drift into disagreeing
# about what counts as source. A path one tool refuses and the other permits is the
# same shape of hole as a pair of guards disagreeing about what a template is.
# _option_values <args...> -> the VALUES glued onto options, as separate tokens.
#
# `--directory=src` and `-tsrc` are each ONE token starting with `-`, so the `-*` flag
# filter downstream discarded them -- and the destination went with them. Both forms are
# unglued here so the path survives as its own operand.
#
# Both spellings are emitted for every caller in the mutator group rather than for the
# one command review named: `patch --directory=src` was the reported case, but rounds
# 10, 12 and 13 each found the same shape in a different command (cp, install, mv,
# patch, ln), which is what fixing instances instead of the class costs.
_option_values() {
  local a
  for a in "$@"; do
    case "$a" in
      --*=*) printf '%s ' "${a#*=}" ;;
      --*) ;;
      -[tdDo]?*) printf '%s ' "${a#-?}" ;;   # -tsrc, -dsrc, -osrc
    esac
  done
}

# _attached_opt_value <letter> <args...> -> prints the value of an ATTACHED short
# option, e.g. `-tsrc` for letter `t`.
#
# coreutils accepts `install -tsrc file` and `ln -tsrc file` as well as the
# separated `-t src`. The separated form was parsed and the attached one fell
# through the `-*` flag filter, taking the destination with it. `ln -tsrc` was worse
# than a miss: the cluster contains an `s`, so it also read as `-s` and switched the
# arm to symlink semantics.
_attached_opt_value() {
  local letter="$1" a
  shift
  for a in "$@"; do
    case "$a" in
      --*) ;;                                  # long option, not a cluster
      -"$letter"?*) printf '%s' "${a#-"$letter"}"; return ;;
    esac
  done
}

# _cluster_flags <cluster> <value-taking letters...> -> the flag letters in a short
# option cluster, stopping at the first letter that takes an ATTACHED value.
#
# `-tsrc` is `-t` plus the directory `src`, not a cluster of -t -s -r -c. Scanning the
# raw token for a letter therefore reads the VALUE as flags: `ln -tsrc /tmp/x` looked
# symbolic because `src` contains an `s`, and symbolic ln treats its source operand as
# a harmless read -- so a hard link into a tracked path was allowed. Same shape would
# hit `install -tdir` on the `-d` test.
_cluster_flags() {
  local cluster="$1" rest out="" c v
  shift
  rest="$cluster"
  while [ -n "$rest" ]; do
    c=${rest%"${rest#?}"}          # first character
    out="$out$c"
    for v in "$@"; do
      [ "$c" = "$v" ] && { printf '%s' "$out"; return; }
    done
    rest=${rest#?}
  done
  printf '%s' "$out"
}

# _drop_opt_values <args...> -> the operands, with the VALUE of any separated
# value-taking short option removed.
#
# `truncate -s 0 /tmp/log` puts the size `0` in the operand list, indistinguishable by
# position from a filename. Harmless while operands were classified non-strictly (no
# repo-root file is named `0`), and an over-block the moment they are judged strictly.
# Same shape as `2>&1`'s descriptor, handled at normalisation for the same reason.
#
# Only the separated spelling needs this: `-s0` is one token that the `-*` filter
# already drops, and `--size=0` is unglued by _option_values into a value that
# classifies as ok.
_drop_opt_values() {
  local a skip=0 out=""
  for a in "$@"; do
    if [ "$skip" -eq 1 ]; then skip=0; continue; fi
    case "$a" in
      -s|-c|-n|-m|-o|--size|--bytes|--lines|--mode|--output) skip=1 ;;
    esac
    out="$out $a"
  done
  printf '%s' "$out"
}

# _target_dir <args...> -> prints the -t/--target-directory VALUE, or nothing.
#
# Covers all three spellings coreutils accepts, because cp, install, ln and mv each
# handled a different subset and each was wrong in its own way:
#   --target-directory=src          one token, discarded by the `-*` filter downstream
#   -t src / --target-directory src value is the NEXT token
#   -tsrc                           attached short option, which read as a flag and vanished
#
# The separated form's old inline version tested
# `[ "$_prev" = "-t" ] || [ "$_prev" = "--target-directory" ] && _tdir="$a"` with no
# grouping, and its `*)` branch matched `-t` itself -- so `-t` became its own target.
# One helper, so a fix lands on every caller rather than on the single command review
# happened to name. Four separate rounds found this same bug in cp, install, mv and
# patch before it was written down as one shape.
_target_dir() {
  local a prev="" v
  for a in "$@"; do
    case "$a" in
      --target-directory=*) printf '%s' "${a#--target-directory=}"; return ;;
    esac
  done
  v=$(_attached_opt_value t "$@")
  if [ -n "$v" ]; then printf '%s' "$v"; return; fi
  for a in "$@"; do
    if [ "$prev" = "-t" ] || [ "$prev" = "--target-directory" ]; then
      printf '%s' "$a"; return
    fi
    prev="$a"
  done
}

# _last_operand <args...> -> prints the final non-flag operand, or nothing.
#
# Replaces an inline `set -- $(...); for _ in $(seq 1 $(( $# - 1 ))); do shift; done;
# printf $1` that CRASHED under `set -u` whenever every argument was a flag: `$#`
# was 0, so `$1` was unbound and the hook exited 1. Exit 1 is neither block (2) nor
# allow (0) -- _harness.sh documents that a hook dying this way was historically
# reported as ALLOW, which makes a crash worse than a wrong decision. Found by
# review as `install -tsrc /tmp/evil.py`.
_last_operand() {
  local a last=""
  for a in "$@"; do
    case "$a" in -*) ;; *) last="$a" ;; esac
  done
  printf '%s' "$last"
}

classify_path() {
  # Two statements, not `local p="$1" rel="$p"`. In a single `local`, bash expands the
  # later initialiser before the earlier assignment is visible, so `rel="$p"` read an
  # unset `p` and `set -u` aborted the function -- which, because the abort happened
  # inside a command substitution, surfaced as an empty verdict and an ALLOW. A guard
  # that fails open when its own helper dies is the exact shape this file exists to
  # avoid; caught by the suite, not by reading.
  local p="$1"
  local base="${2:-}"
  # strict=1 when the caller hands us a real path (Write/Edit), 0 when it hands us a
  # bare shell word (Bash). See _is_repo_root_file for why the two differ.
  local strict="${3:-0}"
  local rel="$p"

  # A RELATIVE path is relative to the caller's cwd, not to the repo root.
  #
  # Treating every relative path as repo-root-relative broke the one guarantee this
  # file calls strong: an agent whose cwd is <repo>/src writes `mail/cli.py`, which
  # has no `src/` prefix, so classify_path returned ok and the write went through.
  # Same for `cli.py` from <repo>/src/mail. The PreToolUse payload carries `cwd` --
  # it was in the very probe that established `agent_type` exists -- and this never
  # used it.
  #
  # Passed in by the caller rather than read here, because the two branches differ:
  # Write/Edit gets the payload cwd (exact, and the strong guarantee depends on it),
  # while the Bash branch passes nothing. A shell command can `cd` before it writes,
  # so any cwd the hook resolves against there would be a guess -- and a guess that
  # ALLOWS is worse than the documented best-effort the Bash branch already is.
  if [ -n "$base" ]; then
    case "$p" in
      /*) ;;                      # already absolute
      *)  p="$base/$p" ;;
    esac
    rel="$p"
  fi

  # A RELATIVE path with a symlinked component: resolve it against REPO_ROOT for the
  # symlink check alone.
  #
  # The Bash branch passes no base on purpose -- a command can `cd` first, so a guessed
  # cwd could make a textual prefix test refuse a path that lands elsewhere. That
  # argument does not extend to RESOLUTION, and coupling the two through one `base`
  # parameter let `echo x > analysis/srclink/mail/cli.py` through while the identical
  # Write was blocked. Resolving can only find MORE guarded paths: if the link exists
  # relative to the repo root it is a real link in this repo, and if the command cd's
  # elsewhere the lookup finds nothing and the textual rules below still apply.
  #
  # Recursion rather than a second prefix test: re-listing the tracked trees here would
  # be a copy that drifts, which is the exact failure the repo-root file list showed
  # (11 of 20 names stale). Bounded by construction -- the recursive call is made with
  # an ABSOLUTE path, which cannot re-enter this branch.
  # Not gated on `strict`: strictness decides whether a NEW repo-root file counts,
  # which is a separate question from where a symlinked component lands. Gating on it
  # silently disabled this the moment redirect targets became strict in the same round
  # -- `echo x > analysis/srclink/...` is both a strict target AND a relative path, and
  # the two fixes cancelled out until a trace showed the branch was never entered.
  if [ -z "$base" ] && [ -n "$REPO_ROOT" ]; then
    case "$p" in
      /*) ;;
      *)
        local _relparent _relcanon _relverdict
        _relparent=$(dirname "$REPO_ROOT/$p")
        if [ -d "$_relparent" ]; then
          _relcanon=$(cd -P "$_relparent" 2>/dev/null && pwd -P) || _relcanon=""
          # Only when resolution actually MOVED the path does this add anything; an
          # ordinary relative path resolves to itself and is left to the rules below.
          if [ -n "$_relcanon" ] && [ "$_relcanon" != "$(dirname "$REPO_ROOT/$p")" ]; then
            _relverdict=$(classify_path "$_relcanon/$(basename "$p")" "" 0)
            if [ "${_relverdict#guarded:}" != "$_relverdict" ]; then
              printf '%s' "$_relverdict"
              return
            fi
          fi
        fi
        ;;
    esac
  fi

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

  # A path that NORMALISED AWAY TO NOTHING names the current directory, which for a
  # relative path is the repo root. `./` and `././` both reduce to "" here, and an
  # empty string then matched no root check and no SOURCE_TREES prefix, so it
  # returned ok -- `rm -rf ./` from the checkout deleted the tree through this hook.
  #
  # `.` and `./` and `` are the same directory; the bare `.` spelling was already
  # blocked because it survives normalisation as a token, which is what made this
  # inconsistent rather than merely open: two spellings of one path disagreed.
  if [ -z "$p" ] || [ "$p" = "." ]; then
    printf 'guarded:the current directory, which for a relative path is the repo root'
    return
  fi

  rel="$p"

  case "$p" in
    /*)
      # `..` in an ABSOLUTE path, before any containment test.
      #
      # The containment test below is textual: it asks whether the path starts with
      # `REPO_ROOT/`. A path that re-enters this checkout through a parent segment --
      # `<parent>/other/../<repo-name>/src/mail/cli.py` -- does not, so it took the
      # "outside this repo" branch and returned ok, never reaching the `*..*` refusal
      # further down. Both Write/Edit and Bash redirects could modify source that way,
      # including `rm -rf <parent>/other/../<repo>/src`.
      #
      # Refused rather than resolved, for the reason the relative `..` rule already
      # gives: textual normalisation disagrees with the kernel when symlinks are
      # involved, and resolving against the live filesystem reintroduces the
      # empty-result hole that rule was written to avoid. An absolute path containing
      # `..` is ambiguous about where it lands, and ambiguity resolves to refusal.
      case "$p" in
        */../*|*/..)
          printf "guarded:an absolute path containing '..', which can resolve back into the repo"
          return
          ;;
      esac

      # The repo root ITSELF, before the prefix strip. The strip requires a trailing
      # `REPO_ROOT/`, so a path exactly equal to the root fell through to the "outside
      # this repo" branch and was ALLOWED -- meaning the guard refused `rm -rf src`
      # and permitted `rm -rf <the whole checkout>`. The most severe bypass found on
      # this branch, and it was one character of prefix away from the rule that
      # catches everything beneath it.
      if [ -n "$REPO_ROOT" ] && { [ "$p" = "$REPO_ROOT" ] || [ "$p" = "$REPO_ROOT/" ]; }; then
        printf 'guarded:the repository root itself (%s)' "$REPO_ROOT"
        return
      fi
      # REPO_ROOT is physical now, so a path spelled through a symlinked checkout does
      # not match it textually. Canonicalise the path's own directory prefix the same
      # way before the comparison, or the fix above simply inverts the bug: physical
      # paths start working and logical ones stop.
      # Canonicalise the path's own directory prefix before ANY of the tests below.
      #
      # This used to run only when the path did NOT already start with REPO_ROOT --
      # it was added to rescue a checkout spelled through a symlink, and the inside
      # case looked like it needed nothing. It did: a symlinked component INSIDE the
      # repo is followed by the kernel and not by a textual prefix test, so
      #
      #   ln -s ../src out/srclink          (allowed: creates a link under out/)
      #   Write out/srclink/mail/cli.py     (allowed: `out/` is an artifact directory)
      #
      # wrote tracked source through a path whose every component read as permitted.
      # Both steps are legal alone; the bypass is the composition -- the same shape as
      # the /tmp symlink case below, which WAS caught only because /tmp happens to sit
      # outside the repo. The guarded-prefix rules must be applied to where the path
      # LANDS, so canonicalisation belongs ahead of the inside/outside split rather
      # than inside one arm of it.
      if [ -n "$REPO_ROOT" ] && [ "$p" != "$REPO_ROOT" ]; then
        _pdir=$(dirname "$p")
        if [ -d "$_pdir" ]; then
          _pcanon=$(cd -P "$_pdir" 2>/dev/null && pwd -P) || _pcanon=""
          if [ -n "$_pcanon" ]; then
            p="$_pcanon/$(basename "$p")"
          fi
        fi
      fi
      if [ -n "$REPO_ROOT" ] && [ "${p#"$REPO_ROOT"/}" != "$p" ]; then
        rel="${p#"$REPO_ROOT"/}"
        # The repo-relative remainder can itself begin `./` once the prefix comes off.
        while [ "${rel#./}" != "$rel" ]; do
          rel="${rel#./}"
        done
        # A remainder that is now empty means the path WAS the root, reached via a
        # spelling the equality test above did not catch (`<repo>/.`, `<repo>//`).
        # Those collapse to "" here rather than to the root string.
        if [ -z "$rel" ]; then
          printf 'guarded:the repository root itself (%s)' "$REPO_ROOT"
          return
        fi
      else
        # Before allowing an outside path: does it RESOLVE back into the repo?
        #
        # The textual test above asks where a path is spelled, and a symlink makes
        # that a different question from where it lands. Two individually legal steps
        # composed into a bypass of the boundary this file calls strong:
        #
        #   ln -s <repo>/src/mail/cli.py /tmp/out     (allowed: writes to /tmp)
        #   Write /tmp/out                            (allowed: /tmp is outside)
        #
        # ...and the kernel follows the link into tracked source. Review found it.
        #
        # Resolved with `cd -P` on the PARENT directory, not on the path itself: the
        # target may not exist yet (a new artifact), while its parent almost always
        # does. That keeps the check working for creates as well as overwrites, and
        # `cd -P` resolves every symlinked component without a fork.
        #
        # RESIDUAL GAP, stated rather than implied: a link created between this check
        # and the write, or a path whose parent does not exist yet, is not covered.
        # The sibling guard documents symlinked operands as a won't-fix for the same
        # reason -- a TOCTOU window cannot be closed from a PreToolUse hook. This
        # closes the reachable-today case, not the class.
        if [ -n "$REPO_ROOT" ]; then
          local _parent _resolved
          _parent=$(dirname "$p")
          if [ -d "$_parent" ]; then
            _resolved=$(cd -P "$_parent" 2>/dev/null && pwd -P) || _resolved=""
            if [ -n "$_resolved" ]; then
              local _real="$_resolved/$(basename "$p")"
              if [ "$_real" = "$REPO_ROOT" ] || [ "${_real#"$REPO_ROOT"/}" != "$_real" ]; then
                printf 'guarded:a path that resolves into the repo (%s)' "$_real"
                return
              fi
            fi
          fi
          # The path itself may BE a symlink whose target is inside the repo, even
          # when its parent is outside. `readlink` is a builtin-free one-shot read of
          # the link value; a non-link yields nothing and costs nothing.
          if [ -L "$p" ]; then
            # Follow the CHAIN, not one hop. A single `readlink` saw only the first
            # link, so `ln -s <repo>/src/x /tmp/a; ln -s /tmp/a /tmp/b` left a Write
            # to /tmp/b reading `_target=/tmp/a` -- outside the repo, allowed, while
            # the kernel followed the chain into tracked source. Both `ln -s` calls
            # are legal on their own; the bypass is in the composition.
            #
            # Bounded at 40 hops, which is above every OS's own ELOOP limit, so a
            # link cycle exits the loop rather than hanging. Reaching the bound means
            # the chain is unresolvable, and an unresolvable path is refused rather
            # than allowed -- the same fail-closed rule the rest of this file follows.
            local _target="$p" _hop=0 _dir
            while [ -L "$_target" ] && [ "$_hop" -lt 40 ]; do
              _dir=$(dirname "$_target")
              _target=$(readlink "$_target" 2>/dev/null) || break
              case "$_target" in
                /*) ;;
                ?*) _target="$_dir/$_target" ;;
                *) break ;;
              esac
              _hop=$((_hop + 1))
            done
            if [ "$_hop" -ge 40 ]; then
              printf 'guarded:a symlink chain too long to resolve (possible cycle)'
              return
            fi
            if [ -n "$_target" ] && [ "$_target" != "$p" ]; then
              _target=$(cd -P "$(dirname "$_target")" 2>/dev/null && pwd -P)/$(basename "$_target")
              if [ "$_target" = "$REPO_ROOT" ] || [ "${_target#"$REPO_ROOT"/}" != "$_target" ]; then
                printf 'guarded:a symlink resolving into the repo (%s)' "$_target"
                return
              fi
            fi
          fi
        fi
        # A genuinely outside path. The scratchpad and /tmp artifacts land here,
        # which is the intended allow.
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

  # DERIVED rule, checked before the explicit list: the first segment names a
  # directory that exists at the repo root AND is not a generated-output directory.
  # Covers every tracked tree without anyone maintaining a list -- which is what the
  # list below kept failing to be.
  #
  # The exclusion matters and the first version omitted it: `out/` exists at the root,
  # is gitignored, and is where generated artifacts go, so "directory exists" alone
  # blocked `out/report.json` -- refusing the very thing a read-only role is supposed
  # to produce.
  #
  # EXISTENCE IS THE WRONG TEST, and the exclusion list is why this kept failing.
  # A workflow workspace holds stages/, outputs/, validation/ (persistence.py
  # _SUBDIRS) plus dispatch/, analysis/, context/ and whatever a workflow names in
  # writes_to. The runner CREATES those before a stage writes, so each one flipped
  # from allowed to blocked the moment it existed -- rejecting the stage's required
  # artifact. The suite's ALLOW case passed only because the directory happened to be
  # absent when it ran, which is a false pass rather than evidence.
  #
  # So the real question is "is this TRACKED content?", not "does it exist?". Asked
  # cheaply and without forking git: a directory the repo tracks has an entry in the
  # index, and every artifact root here is gitignored or untracked. `git check-ignore`
  # would fork per call; instead we treat a directory as tracked only when it is NOT
  # one of the known artifact/generated roots AND it exists. The list below is
  # therefore load-bearing and is kept in sync with persistence.py _SUBDIRS.
  local first="${bare%%/*}"
  case "$first" in
    # Generated / vendored roots (.gitignore, CLAUDE.md "Ignore During Scanning").
    out|_out|backups|.venv|.cache|.git|node_modules|__pycache__|.pytest_cache)
      first="" ;;
    # Workflow workspace roots. stages/outputs/validation are persistence.py
    # _SUBDIRS; the rest are conventional writes_to destinations in this tree.
    stages|outputs|validation|dispatch|analysis|context|design|artifacts|workspace)
      first="" ;;
  esac
  if [ -n "$REPO_ROOT" ] && [ -n "$first" ] && [ -d "$REPO_ROOT/$first" ]; then
    if [ "$bare" = "$first" ]; then
      printf 'guarded:the tracked directory %s itself' "$first"
    else
      printf 'guarded:tracked content (under %s/)' "$first"
    fi
    return
  fi

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
  if _is_repo_root_file "$bare" "$strict"; then
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
  #
  #    SEPARATORS GLUED TO THE TARGET must be split before word-splitting, or they
  #    stay attached to it: `echo x >AGENTS.md; make test` yields the token
  #    `AGENTS.md;`. Prefix rules tolerate that (`src/mail/cli.py;` still starts with
  #    `src/`, which is why a src/ example appeared to be safe), but every EXACT
  #    comparison fails on it -- repo-root files, the bare directory token, the repo
  #    root itself. So `echo x >AGENTS.md; make test` wrote a root policy file while
  #    `echo x >src/...; make test` was blocked by luck. Split them here rather than
  #    trimming the token later, so one normalisation serves every rule.
  redir=${CMD//>>/ >}
  redir=${redir//>|/ >}
  # `>&` is TWO different operators sharing a spelling, and they must not collapse to
  # the same marker once redirect targets are classified strictly:
  #   `echo x >&AGENTS.md`  -- a real write to a file
  #   `make test 2>&1`      -- duplicates a file descriptor; writes no file
  # Both used to normalise to `>`, and the resulting bare `1` was harmless only because
  # the NON-strict path requires a root file to already exist (none is named `1`).
  # Strict classification drops that existence test, so `1` would be judged a new
  # repo-root file and refused -- breaking `make test 2>&1`, which is this repo's own
  # documented way to run its suite. A descriptor is not a filename, so it is marked
  # apart here rather than being distinguished after the fact.
  # ...but ONLY when a DIGIT follows. `>&1` duplicates a descriptor; `>&AGENTS.md` is
  # an ordinary write, and an earlier round found it as a live bypass. Marking every
  # `>&` as a descriptor reinstated that bypass -- caught here by the suite's BLOCK
  # half, one edit after the ALLOW half caught the opposite mistake.
  redir=${redir//>&0/ >FD }
  redir=${redir//>&1/ >FD }
  redir=${redir//>&2/ >FD }
  redir=${redir//>&/ >}
  redir=${redir//>/ > }
  redir=${redir//&&/ }
  redir=${redir//||/ }
  redir=${redir//;/ }
  redir=${redir//|/ }
  redir=${redir//&/ }
  redir=${redir//$'\n'/ }
  redir=${redir//$'\r'/ }
  # Tokens are collected into TWO lists, because strictness is a property of the TOKEN,
  # not of the tool:
  #
  #   strict_targets -- unambiguous write destinations: a redirect operand, or the
  #     destination of a known mutator. These are filenames the shell is about to
  #     create, exactly like Write's `file_path`, so a repo-root name is guarded
  #     whether or not it exists yet.
  #   targets -- everything else, judged non-strictly.
  #
  # Split because `echo x > new.py` and `touch new.py` CREATED new source at the repo
  # root while `Write new.py` was blocked. Round 11 made the existence test
  # tool-dependent; that was the right idea applied at the wrong granularity, since one
  # Bash command string mixes both kinds -- `rm -rf srcfoo` and the `1` of `2>&1` are
  # bare words that must stay non-strict, while the operand of `>` is a path by
  # construction.
  targets=""
  strict_targets=""
  prev=""
  for tok in $redir; do
    if [ "$prev" = ">" ]; then
      strict_targets="$strict_targets $tok"
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
  #    NEWLINES and a bare `&` are separators too, and omitting them was a hole rather
  #    than a nicety: `read -ra` consumes only the first physical line, so everything
  #    after a newline was never inspected at all -- `cat README.md\nsed -i '' …
  #    src/mail/cli.py` was allowed outright. `&` backgrounds the first command and
  #    starts a second, so it splits for the same reason `&&` does. Order matters:
  #    `&&` must be replaced before the bare `&`, or it becomes two empty separators.
  segs=${CMD//&&/;}
  segs=${segs//||/;}
  segs=${segs//|/;}
  segs=${segs//&/;}
  segs=${segs//$'\n'/;}
  segs=${segs//$'\r'/;}
  IFS=';' read -ra _segments <<< "$segs"
  for seg in "${_segments[@]}"; do
    # shellcheck disable=SC2086
    set -- $seg
    [ "$#" -gt 0 ] || continue
    word=${1##*/}          # /bin/sed -> sed
    word=${word#\\}        # \sed     -> sed
    case "$word" in
      touch|tee|truncate)
        # CREATING mutators, so their operands are STRICT: each of these brings a
        # named file into existence, which makes the operand a filename by
        # construction -- the same standing as a redirect target or Write's file_path.
        # Without this, `touch new.py` created new source at the repo root while
        # `Write new.py` was blocked, because the root-file rule required the file to
        # already exist.
        #
        # Split from the group below by MEASUREMENT, not by reading: each command was
        # run against a non-existent path to see whether a file appeared. touch, tee
        # and truncate create; rm, rmdir, unlink, shred, chmod and chown all error.
        shift
        strict_targets="$strict_targets $(_option_values "$@") $(_drop_opt_values "$@")"
        ;;
      rm|rmdir|shred|unlink|chmod|chown|patch)
        # NON-creating mutators, so their operands stay NON-strict. These act on a
        # file that must already exist, and their operands are bare shell words rather
        # than paths by construction: `rm -rf srcfoo` names nothing and must not be
        # refused as a new repo-root file. Making this group strict re-introduced
        # exactly the over-blocking the existence test was added to prevent, and the
        # suite's ALLOW half caught it.
        #
        # `patch` belongs here rather than with the creating group: it can create a
        # file, but only one the DIFF names -- never the bare operand.
        #
        # `_option_values` unglues `--opt=path` and `-tpath` forms so a path hidden in
        # an option value survives the `-*` filter downstream. Applied to the whole
        # group rather than to the one command review named: `patch --directory=src`
        # was the reported case, but the shape is the same for any of these, and
        # fixing instances one at a time is what produced rounds 10, 12 and 13 finding
        # it separately in cp, install, mv, patch and ln.
        shift
        targets="$targets $(_option_values "$@") $*"
        ;;
      install)
        # Wrong in BOTH directions before this, which is why it needs its own arm:
        #   install --target-directory=src /tmp/evil.py   -- the destination hides in
        #     an option VALUE, and the `-*` filter skipped it, so the write was allowed
        #   install src/mail/cli.py /tmp/copy.py          -- an ordinary copy READS the
        #     source, and treating every operand as a target refused it
        # With -d every operand is a directory being created; otherwise the shape
        # matches cp -- last operand is the destination, the rest are sources.
        shift
        _dmode=0
        for a in "$@"; do
          case "$a" in
            -d|--directory) _dmode=1 ;;
            --*) ;;
            # Clustered, e.g. -vd -- but NOT the `d` of `install -tdir`, which is part
            # of the attached value. See _cluster_flags.
            -*) case "$(_cluster_flags "${a#-}" t)" in *d*) _dmode=1 ;; esac ;;
          esac
        done
        _idir=$(_target_dir "$@")
        if [ -n "$_idir" ]; then
          strict_targets="$strict_targets $_idir"
        elif [ "$_dmode" -eq 1 ]; then
          # -d creates each operand as a directory.
          for a in "$@"; do
            case "$a" in -*) ;; *) targets="$targets $a" ;; esac
          done
        else
          strict_targets="$strict_targets $(_last_operand "$@")"
        fi
        ;;
      ln)
        # A HARD link is a second NAME for the same inode, so every operand matters --
        # including the source, which `cp` treats as a harmless read.
        #
        # `ln src/mail/cli.py /tmp/out` was allowed under the cp model (only the
        # destination classified), and a later Write to /tmp/out then edited the
        # TRACKED FILE. No amount of path resolution finds that: the two names are
        # equally real and neither is a link to the other. This is a different class
        # from every symlink fix on this branch, which are all about FOLLOWING a link.
        #
        # So for `ln` without -s, every operand is a target. With -s it is a symlink
        # and the cp model is right -- creating a symlink writes only the link itself,
        # and the symlink resolver above catches a later write through it.
        shift
        _symbolic=0
        for a in "$@"; do
          case "$a" in
            -s|--symbolic) _symbolic=1 ;;
            --*) ;;
            # `-tsrc` is `-t` with an ATTACHED VALUE, not a cluster: everything after
            # the `t` is a directory NAME, so scanning the whole token for an `s` read
            # the `s` of `src` as `-s` and switched this arm to symlink semantics --
            # which treats the source operand as a harmless read. _cluster_flags stops
            # at the first value-taking letter, so only `-vs`-style letters count.
            -*) case "$(_cluster_flags "${a#-}" t)" in *s*) _symbolic=1 ;; esac ;;
          esac
        done
        if [ "$_symbolic" -eq 0 ]; then
          # Every operand is a target here -- but `-tsrc` and `--target-directory=src`
          # are single tokens starting with `-`, so the `-*` filter downstream drops
          # them and the destination directory goes with them. `_option_values` unglues
          # both spellings back into their own operands.
          targets="$targets $(_option_values "$@") $*"
          continue
        fi
        _tdir=$(_target_dir "$@")
        if [ -n "$_tdir" ]; then
          strict_targets="$strict_targets $_tdir"
        else
          strict_targets="$strict_targets $(_last_operand "$@")"
        fi
        ;;
      cp)
        # Normally the final operand is written. `cp a b c dir/` writes into dir/
        # alone, and the earlier operands are sources being READ -- blocking those is
        # what made `cp src/mail/cli.py /tmp/copy.py` fail.
        #
        # EXCEPT with -t/--target-directory, which moves the destination to the front
        # and makes every positional operand a source. `cp -t src /tmp/evil.py` writes
        # under src/ while the last-operand rule looked only at /tmp/evil.py and
        # allowed it. Review found that; the suite pins both spellings.
        shift
        _tdir=$(_target_dir "$@")
        if [ -n "$_tdir" ]; then
          strict_targets="$strict_targets $_tdir"
        else
          strict_targets="$strict_targets $(_last_operand "$@")"
        fi
        ;;
      mv)
        # mv is NOT like cp: it REMOVES the source. `mv src /tmp/elsewhere` destroys
        # the tree just as surely as `rm -rf src`, so both ends are write targets.
        #
        # Every operand is already a target, so `-t src` is covered -- but
        # `--target-directory=src` is ONE token that the `-*` filter downstream
        # discards as a flag, taking the destination with it. Unglued here so the
        # value survives as its own operand.
        shift
        targets="$targets $(_option_values "$@") $*"
        ;;
      sed)
        # Rewrites in place only with -i. Without it, sed reads and prints.
        #
        # Detected by SHAPE, not by listing spellings. The previous version enumerated
        # `-i`, `-i.`, `--in-place` and two quoted forms, and missed `-iE` and `-Ei` --
        # both of which edit in place on GNU and BSD sed. Enumerating option spellings
        # drifts exactly like enumerating tracked files did, so: any short-option
        # cluster containing `i`, or the long form, counts.
        _inplace=0
        for a in "$@"; do
          case "$a" in
            --in-place*) _inplace=1 ;;
            --*) ;;                       # some other long option
            -*)
              # A short-option cluster: -i, -iE, -Ei, -i.bak, -n -i, …
              case "${a#-}" in
                *i*) _inplace=1 ;;
              esac
              ;;
          esac
        done
        if [ "$_inplace" -eq 1 ]; then
          shift
          targets="$targets $*"
        fi
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

  strict_targets=${strict_targets//\"/ }
  strict_targets=${strict_targets//\'/ }

  # Tag each token with its strictness and walk one list. The tag is a prefix added and
  # removed here rather than a sentinel VALUE in the list, because a sentinel is itself
  # a legal filename and nothing would stop an operand from matching it.
  tagged=""
  for tok in $strict_targets; do tagged="$tagged 1:$tok"; done
  for tok in $targets;        do tagged="$tagged 0:$tok"; done

  for tagged_tok in $tagged; do
    tok_strict=${tagged_tok%%:*}
    tok=${tagged_tok#*:}
    case "$tok" in
      ""|-*) continue ;;   # empty, or a flag rather than a path
    esac
    # A token carrying unexpanded shell syntax is not a literal filename, whatever its
    # provenance: `> $P` is a redirect, but `$P` is not the name of the file that gets
    # written. Judging it strictly made it a new repo-root file and refused the command.
    # These are the Bash branch's documented weak spot -- the value is unknowable from
    # here -- so they fall back to the non-strict reading rather than being invented.
    case "$tok" in
      *'$'*|*'`'*|*'*'*|*'?'*|*'['*) tok_strict=0 ;;
    esac
    # A digits-only token is a size, a file descriptor, a line count or an exit code --
    # never a source filename. Strict classification would read it as a NEW repo-root
    # file (no existence test) and refuse the command. A repo-root file that really is
    # named `0` is still caught by the non-strict path's existence test.
    case "$tok" in
      *[!0-9]*) ;;
      ?*) tok_strict=0 ;;
    esac
    # A duplicated file descriptor (`2>&1`), not a filename. Marked at normalisation
    # time; see the `>&` note above.
    [ "$tok" = "FD" ] && continue
    verdict=$(classify_path "$tok" "" "$tok_strict")
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
# The payload's cwd, so a relative file_path is judged where it actually lands.
#
# Falls back to REPO_ROOT rather than to "no base", which was a fail-open. The claim
# that no-base "treats the path as repo-root-relative" was only true of the TEXTUAL
# prefix tests; the symlink resolver needs a real absolute path to follow a link, so
# with no cwd it never ran. `out/srclink/mail/cli.py`, where out/srclink -> ../src, was
# classified by its literal spelling -- `out/` is an artifact directory -- and ALLOWED,
# while the identical payload WITH a cwd was blocked. A missing optional field is not
# authorization, and the strong Write/Edit guarantee cannot depend on the harness
# choosing to send one.
#
# REPO_ROOT is the right base because the prefix rules are written repo-relative
# anyway, so it reproduces the intended reading of a bare `src/mail/cli.py` while also
# giving the resolver something to resolve. If REPO_ROOT itself is unknown the guard
# has already failed closed upstream.
CWD=$(jq -r 'if (.cwd | type) == "string" then .cwd else "" end' <<< "$PAYLOAD" 2>/dev/null || echo "")
if [ -z "${CWD//[[:space:]]/}" ]; then
  CWD="$REPO_ROOT"
fi

VERDICT=$(classify_path "$FILE" "$CWD" 1)
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
