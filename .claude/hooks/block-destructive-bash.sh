#!/usr/bin/env bash
# PreToolUse hook (matcher: Bash) -- block destructive commands and shell access
# to this repo's credential files.
#
# Ported from a .env/Google-Workspace-shaped original and adapted to dancing-bear's
# INI credential layout. The secret paths here are the ones core/constants.py and
# mail/config_resolver.py actually resolve, not a generic guess.
#
# Contract: exit 2 blocks the tool call and shows stderr to Claude. Exit 0 allows.
#
# WHY THIS HOOK EXISTS AT ALL
# ---------------------------
# settings.json `permissions.deny` entries like Read(**/credentials.ini) bind the
# READ TOOL. They say nothing about `cat ~/.config/credentials.ini`, which is a Bash
# call and walks straight past every one of them. Same for Edit(**/credentials.ini)
# versus `echo x > ~/.config/credentials.ini`. A deny rule is a routing decision
# inside the harness; the shell is a different door. This hook is the enforcing
# layer on that door -- and unlike a deny rule, which a project-level settings file
# can override, a PreToolUse hook exiting 2 cannot be overridden from inside the
# session.
#
# DESIGN NOTE: OPERANDS, NOT COMMAND WORDS
# ----------------------------------------
# An earlier version paired a fixed READERS list against a protected filename in one
# regex: `(cat|less|grep|...)[^|;&]*credentials\.ini`. That shape has two holes that
# are not fixable by extending the list.
#
#   1. The list can never be complete. `base64 ~/.config/credentials.ini` discloses
#      the file just as thoroughly as `cat` does, and so does
#      `python3 -c 'print(open("...credentials.ini").read())'`. Every new binary on
#      the box is another entry someone has to remember to add.
#   2. The command word has to be spelled the way the list spells it.
#      `/bin/cat credentials.ini` and `\cat credentials.ini` both run cat; neither
#      matches a bare `cat` anchored at a command boundary.
#
# So the protected-path check below runs over the command's OPERANDS, independently
# of which command word precedes them. If a protected path appears anywhere in the
# command as a bare operand, the command is blocked. Neither list survives.
#
# Cost of that choice: `git commit -m "docs: describe credentials.ini setup"` is
# blocked. That is the intended direction. A false positive costs one clarifying
# question and is resolved by the user running the command themselves with a leading
# `!`; a false negative costs a disclosed OAuth refresh token, which cannot be
# un-printed. Every block message says so, so the refusal reads as a decision rather
# than a bug.

set -u

# Fail CLOSED on a malformed payload.
#
# `jq -r .tool_input.command` on garbage prints nothing and exits nonzero. With the
# original's `CMD=$(jq ...)` that silently yielded an empty CMD, every pattern
# missed, and the hook exited 0 -- a spurious ALLOW produced by the failure of the
# very thing meant to inspect the command. A hook that cannot read its input does
# not know what it is approving, so it must refuse.
PAYLOAD=$(cat)
if ! CMD=$(jq -er ".tool_input.command" <<< "$PAYLOAD" 2>/dev/null); then
  echo "Blocked: could not parse the PreToolUse payload (.tool_input.command missing, null, or not JSON)." >&2
  echo "Failing closed rather than allowing an uninspected command." >&2
  exit 2
fi

# A non-string .command is NOT a parse failure as far as jq is concerned.
#
# `{"command": {}}` and `{"command": []}` are truthy JSON values, so `jq -er` exits 0
# and prints "{}" or "[]". `{"command": 0}` prints "0". None of those match any
# pattern below, so the hook exited 0 and allowed a call it had never actually
# inspected -- the same spurious-ALLOW shape as the parse failure above, arriving
# through a door the parse check does not watch. Type is checked separately.
CMD_TYPE=$(jq -r '.tool_input.command | type' <<< "$PAYLOAD" 2>/dev/null || echo "unknown")
if [ "$CMD_TYPE" != "string" ]; then
  echo "Blocked: .tool_input.command is a $CMD_TYPE, not a string." >&2
  echo "Failing closed rather than allowing a command the hook cannot read." >&2
  exit 2
fi

# An empty or whitespace-only command has nothing to inspect. It is almost certainly
# a malformed payload rather than a real call, and allowing it teaches nothing while
# leaving a hole shaped exactly like the non-string case above.
if [ -z "${CMD//[[:space:]]/}" ]; then
  echo "Blocked: .tool_input.command is empty." >&2
  echo "Failing closed rather than allowing an uninspected command." >&2
  exit 2
fi

# ---------------------------------------------------------------------------
# 0. Shared vocabulary
# ---------------------------------------------------------------------------

# Where a command word can begin. A command name only counts at one of these, so
# "concatenate" does not read as "cat" and "sedate" does not read as "sed".
#
# The openers of a command substitution belong here too: $(cat credentials.ini) and
# the backtick spelling each start a fresh command. The original omitted `(` and the
# backtick until a live `export $(cat .env | xargs)` walked past the check -- one
# paren away from the block.
#
# `\` is here because the shell treats `\rm` as rm with alias expansion suppressed:
# it runs the real binary. A guard that misses `\rm -rf /` is not guarding rm.
#
# Defined ONCE and reused by every pattern below. Two copies of a character class is
# how one of them ends up missing a character.
CMD_START='(^|[|;&(`\\[:space:]])'

# This repo's credential filenames, resolved from core/constants.py (credentials.ini
# under $CREDENTIALS's dir, $XDG_CONFIG_HOME, or ~/.config) and
# mail/config_resolver.py (the four JSON token files beside it).
#
# Matched as bare filenames rather than full paths on purpose: the directory varies
# with $XDG_CONFIG_HOME and $CREDENTIALS, and a copy of credentials.ini sitting in
# /tmp is exactly as sensitive as the original. See the "configured credential paths"
# section in the README for the limits of that choice.
DB_SECRET_FILES='credentials\.ini|credentials\.json|outlook_token\.json|msal_flow\.json|token\.json'

# Key-material extensions. This repo genuinely uses two of them: apple_music loads a
# MusicKit private key as .p8, and phone resolves a device supervision identity as
# .p12. A leaked .p8 signs Apple Music API tokens; a leaked .p12 can re-supervise a
# device. .pem covers the generic PKCS/OpenSSL spelling of the same material.
KEY_EXTENSIONS='\.pem|\.p8|\.p12'

UNIVERSAL_SECRETS="\\.ssh/|\\.gnupg/|\\.aws/credentials|\\.npmrc|id_rsa|id_ed25519|$KEY_EXTENSIONS"

# Repository internals. Hand-editing .git/ corrupts repository state in ways ordinary
# git commands cannot undo. block-protected-paths.sh already guards this on the
# Write/Edit side; without the Bash half, `echo x > .git/config` walks past it -- the
# exact tool-versus-shell gap this whole file exists to close.
REPO_INTERNALS='\.git/'

# `.env` and `.env.<suffix>`, but not `.env.example` and friends -- those are handled
# by the exact-token carve-out in _is_template below, not by a substring scrub.
DOTENV='\.env([^a-zA-Z0-9_.-]|\.[a-zA-Z0-9_-]+|$)'

# Everything a protected-path operand can look like.
SECRET_TARGET="($DOTENV|$DB_SECRET_FILES|$UNIVERSAL_SECRETS|$REPO_INTERNALS)"

# NOTE: there is deliberately no READERS or WRITERS list here any more.
#
# Two lists used to gate the credential checks: readers (cat, less, grep, jq, ...) and
# writers (tee, cp, mv, install, dd, truncate, ln). Both are gone rather than extended,
# because both were unfixable as lists -- see the design note at the top of the file.
#
# The writers list is worth one extra word. `rm` was never on it, and `rm` is also not
# recursive+force in the common case, so `rm -f ~/.config/credentials.ini` fell through
# BOTH checks: the rm-target block above skipped it for lacking -rf, and the write
# block skipped it for not being a listed writer. Deleting credentials.ini destroys
# every profile section exactly as thoroughly as truncating it does, and nothing in
# this repo regenerates it. Matching on the operand covers `rm`, `shred`, `unlink`,
# `rsync`, `chmod`, and whatever the next one turns out to be, without an edit here.

# Checked-in templates are safe: they carry placeholder values and exist to be read
# and diffed against a real config.
#
# CHANGED: this used to be a substring scrub, `sed 's/\.env\.(example|template|sample)//g'`,
# applied to the whole command before matching. That deletes the substring wherever it
# occurs, so `cat /tmp/client.env.example.bak` became `cat /tmp/client.bak` -- a real
# file containing real secrets, now invisible to every pattern. Same for
# `echo x > .env.example.bak`. The carve-out now applies per-token and only to a token
# that IS a template path, never to one that merely contains a template-looking span.
_is_template() {
  case "${1##*/}" in
    .env.example|.env.template|.env.sample) return 0 ;;
    *.env.example|*.env.template|*.env.sample) return 0 ;;
  esac
  return 1
}

# ---------------------------------------------------------------------------
# 1. Destructive commands
# ---------------------------------------------------------------------------

# These are string-matched because they have no meaningful "target" to resolve --
# a DROP TABLE is destructive regardless of which table, and a force-push is
# destructive regardless of which remote.
#
# `push.*-f` deliberately has no trailing space. It used to: `push.*-f `. A flag at
# the very end of the command has no trailing space, so `git push -f` -- the shortest
# and most likely spelling of the thing being blocked -- fell straight through while
# `git push -f origin main` was caught. The word boundary is `(\s|$)` instead, which
# still keeps `--force-with-lease` and `-file` from matching as `-f`.
PATTERNS=(
  "DROP[[:space:]]+TABLE"
  "DROP[[:space:]]+DATABASE"
  "TRUNCATE"
  "push.*--force"
  "push.*[[:space:]]-[a-zA-Z]*f([[:space:]]|$)"
  "reset --hard"
)

for p in "${PATTERNS[@]}"; do
  if grep -qiE "$p" <<< "$CMD"; then
    echo "Blocked: destructive pattern \"$p\" detected" >&2
    exit 2
  fi
done

# --- rm -rf: match the resolved TARGET, not the flag spelling -----------------
#
# CHANGED FROM THE REFERENCE. The original grep'd the literal string "rm -rf /",
# which matches any absolute path: `rm -rf /Users/me/scratch` was blocked as if it
# were `rm -rf /`. The original's own comment records this firing twice on
# legitimate cleanup. It also let every equivalent spelling through -- `rm -fr /`,
# `rm --recursive --force /`, `rm -rf //`.
#
# The fix the original describes but does not implement: normalize the flags, pull
# out the actual operands, expand ~ and $HOME, then compare the resolved path
# against a protected-prefix list. A path is destructive because of where it points,
# not because of how the flags were typed.
#
# Direction of error is still deliberate: an unresolvable or ambiguous target is
# treated as protected. Over-blocking costs one clarifying question; under-blocking
# costs a home directory.

# Resolve one raw token into a comparable absolute-ish path. Shared by the rm check
# and the protected-operand check so the two cannot drift on how they expand `~`.
_normalize_target() {
  local target="$1"
  # Strip surrounding quotes.
  target=$(sed -E 's/^["'"'"']//; s/["'"'"']$//' <<< "$target")
  target=${target//\$HOME/$HOME}
  target=${target//\$\{HOME\}/$HOME}
  case "$target" in
    "~") target="$HOME" ;;
    "~/"*) target="$HOME/${target#\~/}" ;;
  esac
  # Collapse repeated slashes so `//` and `///` land on `/` like the kernel treats them.
  target=$(sed -E 's#/+#/#g' <<< "$target")
  # A trailing slash is cosmetic: `/etc/` is `/etc`. Keep bare "/" intact.
  [ "$target" != "/" ] && target="${target%/}"
  printf '%s' "$target"
}

# Resolve `.` and `..` segments textually, without touching the filesystem.
#
# `rm -rf /tmp/../etc` is `rm -rf /etc`, and `rm -rf ..` is the parent of wherever the
# agent happens to be -- which in a worktree is `.claude/worktrees/`, holding every
# other session's work. Without this, both read as unremarkable paths: the first never
# matches a protected prefix because of the literal "/tmp/" head, and the second is
# relative and was skipped outright.
#
# realpath is not used because it resolves symlinks against the live filesystem and
# returns empty for a nonexistent path -- an empty result would then be compared
# against the protected list and silently pass. Textual resolution has no such hole.
_resolve_dots() {
  local path="$1" out="" seg
  local prefix=""
  case "$path" in
    /*) prefix="/" ;;
    *) prefix="" ;;
  esac
  # A relative path is resolved against the cwd so `..` has something to climb from.
  if [ -z "$prefix" ]; then
    path="$PWD/$path"
    prefix="/"
  fi
  local IFS='/'
  # shellcheck disable=SC2086
  for seg in $path; do
    case "$seg" in
      ""|".") continue ;;
      "..") out="${out%/*}" ;;
      *) out="$out/$seg" ;;
    esac
  done
  printf '%s' "${out:-/}"
}

# Protected prefixes.
#
# /home and /private are new. /home is where Linux keeps user homes -- CI runs there,
# and `rm -rf /home` was previously as unremarkable as `rm -rf /opt/homebrew`.
# /private is the macOS root that /tmp, /etc and /var are all symlinks into, so
# `rm -rf /private/etc` reached the same inode as `rm -rf /etc` while dodging the
# check for it.
PROTECTED_ROOTS=(/ "$HOME" /Users /home /etc /usr /var /System /Library /opt /bin /sbin /Applications /private)

# Temp ROOTS are protected too; only their descendants are scratch.
#
# The carve-out below allows /tmp/?* -- at least one character after the slash. The
# roots themselves fell through it into the protected-prefix loop, where /tmp is not
# listed either, so `rm -rf /tmp` was allowed outright. Deleting all of /tmp takes out
# every other session's scratch directory, including this repo's own
# /private/tmp/claude-501 tree.
TEMP_ROOTS=(/tmp /private/tmp /var/tmp)

_block_rm_target() {
  echo "Blocked: 'rm' with recursive+force targeting the protected path $1" >&2
  echo "This resolves to a system, temp-root, or home directory, not workspace scratch space." >&2
  echo "If this is genuinely what you want, run it yourself with a leading ! in the prompt." >&2
  exit 2
}

if grep -qE "${CMD_START}rm([[:space:]]|$)" <<< "$CMD"; then
  # Every rm invocation in the command, one per line. A compound command can hold
  # more than one (`cd /tmp && rm -rf a; rm -rf /`), and checking only the first
  # would miss the dangerous half.
  RM_CALLS=$(grep -oE "${CMD_START}rm[[:space:]][^|;&\`)]*" <<< "$CMD" | sed -E 's/^[|;&(`\\[:space:]]*//')

  while IFS= read -r call; do
    [ -n "$call" ] || continue

    # Recursive AND force, in any spelling: -rf, -fr, -r -f, --recursive --force,
    # -Rf. Bundled short flags are checked characterwise so -rvf counts.
    RECURSIVE=0; FORCE=0
    for tok in $call; do
      case "$tok" in
        --recursive) RECURSIVE=1 ;;
        --force) FORCE=1 ;;
        --*) ;;
        -*)
          case "$tok" in *[rR]*) RECURSIVE=1 ;; esac
          case "$tok" in *f*) FORCE=1 ;; esac
          ;;
      esac
    done
    [ "$RECURSIVE" -eq 1 ] && [ "$FORCE" -eq 1 ] || continue

    # Operands: everything that is not the command word and not a flag.
    for tok in $call; do
      case "$tok" in
        rm|-*) continue ;;
      esac

      target=$(_normalize_target "$tok")

      # `~otheruser` expands to another account's home. It cannot be resolved here
      # (no shell expansion is performed on the payload), and guessing is worse than
      # refusing: block rather than treat a literal "~bob" as a relative path, which
      # is what the fall-through to the relative-path branch used to do.
      case "$target" in
        "~"*) _block_rm_target "$target (a ~user home directory)" ;;
      esac

      # Resolve . and .. BEFORE any prefix comparison. /tmp/../etc must be compared
      # as /etc, not as a path that merely starts with the allowed /tmp/.
      RAW_TARGET="$target"
      target=$(_resolve_dots "$target")

      # A RELATIVE path that climbs out of the workspace is not workspace-local, no
      # matter how harmless `rm -rf ..` looks. From a session worktree it resolves to
      # .claude/worktrees/, holding every other session's uncommitted work; from the
      # main checkout it resolves to the parent of the repo. Neither is scratch space,
      # and neither is caught by the absolute-prefix rules below -- both land under
      # $HOME, which the "under home but not home itself" branch allows.
      WORKSPACE_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || printf '%s' "$PWD")
      case "$RAW_TARGET" in
        /*) ;;
        *..*)
          # `rm -rf build/../out` still lands inside the checkout and is fine.
          case "$target" in
            "$WORKSPACE_ROOT"/?*) ;;
            *)
          echo "Blocked: 'rm -rf $RAW_TARGET' resolves to $target, which is outside the workspace." >&2
          echo "A relative path containing '..' escapes the checkout; in a session worktree it points" >&2
          echo "at .claude/worktrees/, holding every other session's uncommitted work." >&2
          echo "Name the directory explicitly, or run it yourself with a leading ! in the prompt." >&2
              exit 2
              ;;
          esac
          ;;
      esac

      # Explicitly-safe scratch space, checked BEFORE the protected list because
      # /tmp on macOS is a symlink under /private and the repo itself lives under
      # /Users -- both would otherwise trip a protected prefix. The `?*` requires at
      # least one character past the slash, so the roots themselves are NOT carved
      # out here; they are blocked by the TEMP_ROOTS loop below.
      case "$target" in
        /tmp/?*|/private/tmp/?*|/var/tmp/?*|"${TMPDIR:-/nonexistent}"/?*) continue ;;
      esac
      for troot in "${TEMP_ROOTS[@]}"; do
        [ "$target" = "$troot" ] && _block_rm_target "$target"
      done
      # `.claude/worktrees` holds every OTHER session's isolated checkout, including
      # uncommitted work that exists nowhere else. It sits inside the repo, so the
      # workspace carve-out below would otherwise wave it through. Checked before that
      # carve-out for exactly that reason.
      case "$target" in
        */.claude/worktrees|*/.claude)
          echo "Blocked: 'rm -rf $target' would delete every other session's isolated worktree," >&2
          echo "including uncommitted work that exists nowhere else." >&2
          echo "Remove one worktree with 'git worktree remove <path>', or run it yourself with a" >&2
          echo "leading ! in the prompt." >&2
          exit 2
          ;;
      esac

      # Anything under the current repo checkout is the agent's own workspace.
      REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || true)
      if [ -n "$REPO_ROOT" ] && [ "$target" != "$REPO_ROOT" ]; then
        case "$target" in "$REPO_ROOT"/?*) continue ;; esac
      fi

      # An exact match on a protected root is fatal (`rm -rf /usr`, `rm -rf ~`).
      for prot in "${PROTECTED_ROOTS[@]}"; do
        [ "$target" = "$prot" ] && _block_rm_target "$target"
      done

      # Protected SUBTREES. `$HOME/*` used to be an unconditional allow, on the
      # reasoning that ~/.cache/foo is disposable. It is -- but so is ~/.ssh under
      # the same rule, and `rm -rf ~/.ssh` destroys every private key on the machine
      # while `rm -rf ~/.config` takes credentials.ini with it. The named subtrees
      # are carved back out of that allow.
      case "$target" in
        "$HOME"/.ssh|"$HOME"/.ssh/*|"$HOME"/.gnupg|"$HOME"/.gnupg/*|"$HOME"/.aws|"$HOME"/.aws/*|"$HOME"/.config|"$HOME"/.config/*|"$HOME"/.claude|"$HOME"/.claude/*)
          _block_rm_target "$target"
          ;;
      esac

      case "$target" in
        "$HOME"/*) : ;;   # under home but not home itself -- allowed, e.g. ~/.cache/foo
        /Users/*/*) : ;;  # under some home, more than one level deep -- allowed
        /home/*/*) : ;;
        /Users/*|/home/*)
          echo "Blocked: 'rm -rf $target' targets an entire user home directory." >&2
          exit 2
          ;;
        /etc/*|/usr/*|/var/*|/System/*|/Library/*|/bin/*|/sbin/*|/Applications/*|/private/*)
          echo "Blocked: 'rm' with recursive+force under the system path $target" >&2
          exit 2
          ;;
      esac
    done
  done <<< "$RM_CALLS"
fi


# ---------------------------------------------------------------------------
# 2. The append carve-out for credentials.ini
# ---------------------------------------------------------------------------
#
# Append is deliberately NOT blocked for credentials.ini. `>>` and `tee -a` are how a
# new profile section gets added without destroying the existing ones, so blocking
# them would contradict the rule this hook exists to enforce -- CLAUDE.md's "Never
# overwrite ~/.config/credentials.ini" is a rule about truncation, and appending is
# the sanctioned way to edit the file.
#
# CHANGED: the carve-out used to be unscoped. `>>` was rewritten to a placeholder
# across the WHOLE command before any matching, so it exempted the append no matter
# what the target was: `echo x >> ~/.config/token.json` and `tee -a ~/.ssh/id_rsa`
# were both allowed. Appending to a token file corrupts the JSON and invalidates the
# session; appending to id_rsa corrupts a private key; `echo x >> .env` creates or
# extends a secret file outright. None of those have the "adding a profile section"
# justification that earned credentials.ini its exemption.
#
# It is now scoped two ways: the exempt token's BASENAME must be exactly
# credentials.ini (so token.json cannot ride along), and the exemption applies to that
# one token only. Everything else in the command is still checked, so
# `echo x >> ~/.config/credentials.ini && cat ~/.ssh/id_rsa` still blocks on the cat.

# Every append target in the command: `>> path`, `tee -a path`, `tee --append path`.
APPEND_TARGETS=$(
  {
    grep -oE '>>[[:space:]]*[^[:space:]|;&]+' <<< "$CMD" | sed -E 's/^>>[[:space:]]*//'
    grep -oE "${CMD_START}tee[[:space:]]+(-a|--append)[[:space:]]+[^[:space:]|;&]+" <<< "$CMD" \
      | sed -E 's/.*(-a|--append)[[:space:]]+//'
  } 2>/dev/null | sed '/^$/d'
)

# True when $1 is one of those append targets AND names credentials.ini.
_is_exempt_append() {
  local candidate norm t
  candidate=$(_normalize_target "$1")
  case "${candidate##*/}" in
    credentials.ini) ;;
    *) return 1 ;;
  esac
  while IFS= read -r t; do
    [ -n "$t" ] || continue
    norm=$(_normalize_target "$t")
    [ "$norm" = "$candidate" ] && return 0
  done <<< "$APPEND_TARGETS"
  return 1
}

# ---------------------------------------------------------------------------
# 3. Protected paths as command OPERANDS
# ---------------------------------------------------------------------------
#
# `Read(**/credentials.ini)` in permissions.deny binds the Read tool only. This is
# the Bash-side equivalent. The failure mode being prevented is specific: a compound
# call bundles `cat ~/.config/credentials.ini` next to an allowed `./bin/mail ...`,
# the whole thing reads as routine, and OAuth client secrets and Outlook refresh
# tokens land in the transcript. Once printed they are disclosed -- there is no
# un-printing a token.
#
# CHANGED: this no longer requires a READERS or WRITERS command word before the path.
# See the design note at the top of the file. Any bare mention of a protected path as
# an operand blocks, which covers `/bin/cat`, `\cat`, `base64`, `rm -f`, and
# `python3 -c 'open("...credentials.ini")'` without needing any of them enumerated.
# It also closes the .git/ write hole: block-protected-paths.sh guarded `.git/` on the
# Write/Edit side while `echo x > .git/config` walked straight past on the Bash side.

# Split the command into candidate operand tokens. Shell metacharacters, quotes, and
# redirect arrows all become separators, so a redirect target arrives as its own token
# and a path embedded in a `-c` script string surfaces as its own token too -- that is
# what catches
# `python3 -c 'print(open(os.path.expanduser("~/.config/credentials.ini")).read())'`.
TOKENS=$(tr '|;&`()<>,"'"'"' ' '\n' <<< "$CMD" | sed '/^$/d')

# Directories known to hold credential files. Used only for the unresolvable-token
# check below, where the filename is not visible and the directory is all there is.
#
# $XDG_CONFIG_HOME is here because core/constants.py searches it for credentials.ini
# ahead of ~/.config, so `cat "$XDG_CONFIG_HOME/anything"` is a read out of a
# credential directory whose real path this hook cannot see.
SENSITIVE_DIRS='\.config|\.ssh|\.gnupg|\.aws|\.claude|(^|/)etc(/|$)|XDG_CONFIG_HOME'

# Environment variables that core/constants.py and mail/config_resolver.py resolve to
# a credential FILE PATH rather than to a directory. $CREDENTIALS in particular is
# accepted as a full path, so `CREDENTIALS=/tmp/my-secrets.ini` makes an arbitrarily
# named file the active credential store -- and a filename-matching hook cannot see
# that. These names are blocked wherever they appear, with no path-shape requirement,
# because the variable IS the path. See the README section "Configured credential
# paths" for why the hook refuses rather than shelling out to resolve them.
CREDENTIAL_VARS='CREDENTIALS|OUTLOOK_TOKEN|GOOGLE_APPLICATION_CREDENTIALS|GMAIL_TOKEN|MSAL_FLOW'

_report_protected() {
  echo "Blocked: the command references the protected path '$1'." >&2
  echo "Credential files hold OAuth client secrets and refresh tokens; printing one discloses it," >&2
  echo "and writing or deleting one destroys profile sections nothing in this repo regenerates." >&2
  echo "If you need a specific value, ask the user; to check that a profile exists, use 'ls'." >&2
  echo "Appending a new section to credentials.ini with >> or tee -a is still allowed." >&2
  echo "If the reference is genuinely harmless (a docs filename, a commit message), run the" >&2
  echo "command yourself with a leading ! in the prompt -- this guard over-blocks on purpose," >&2
  echo "because a false positive costs one question and a false negative costs a disclosed token." >&2
  exit 2
}

_report_unresolvable() {
  echo "Blocked: '$1' is a glob or an unresolved expansion pointing into a directory that holds" >&2
  echo "credential files. The hook cannot expand it without running shell code from the payload," >&2
  echo "and the expansion may cover credentials.ini and every token file at once -- strictly" >&2
  echo "worse than naming one of them." >&2
  echo "Name the specific non-credential file, or run it yourself with a leading ! in the prompt." >&2
  echo "Over-blocking is the correct failure direction here." >&2
  exit 2
}

while IFS= read -r raw; do
  [ -n "$raw" ] || continue

  # A KEY=path assignment hides the path after the `=`; check both spellings.
  for candidate in "$raw" "${raw#*=}"; do
    [ -n "$candidate" ] || continue

    # Checked-in templates are readable and editable by design.
    _is_template "$candidate" && continue

    # The one sanctioned write to a protected file.
    _is_exempt_append "$candidate" && continue

    if grep -qE "$SECRET_TARGET" <<< "$candidate"; then
      _report_protected "$candidate"
    fi

    # A variable that names a credential file outright. No path shape required: the
    # variable is the whole path, so `cat $CREDENTIALS` has no `/` to key off.
    if grep -qE "\\\$\{?($CREDENTIAL_VARS)\}?" <<< "$candidate"; then
      _report_unresolvable "$candidate"
    fi

    # Unresolvable expansions. A token with no glob character and no `$` in it is
    # fully resolved and was already judged by the check above.
    case "$candidate" in
      *'*'*|*'?'*|*'['*|*'{'*|*'$'*) ;;
      *) continue ;;
    esac
    # A token with no path shape at all (a bare `$?`, a `{}` in a find -exec, a `$1`)
    # is not a path and must not block ordinary work.
    case "$candidate" in
      */*|'~'*) ;;
      *) continue ;;
    esac
    if grep -qE "($SENSITIVE_DIRS)" <<< "$(_normalize_target "$candidate")"; then
      _report_unresolvable "$candidate"
    fi
  done
done <<< "$TOKENS"

exit 0
