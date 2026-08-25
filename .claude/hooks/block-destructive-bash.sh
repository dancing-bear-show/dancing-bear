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

# Splice line continuations before ANY scan runs.
#
# `rm \<newline>  -rf /` is one command to the shell: the backslash-newline is removed
# during tokenization and never reaches rm. Every scan below is line-oriented, though --
# grep works a line at a time -- so this arrived as two lines, "rm \" (a call with no
# flags, failing the recursive+force test) and "  -rf /" (no rm, so not a call at all).
# Neither half looked dangerous and the command ran in full.
#
# Splicing here rather than in each pattern means there is exactly one place this can be
# got wrong.
#
# Done in bash rather than sed on purpose: BSD sed (macOS, where this repo is developed)
# and GNU sed (the CI runner) disagree about labels and `N` in a one-liner script, and a
# splice that silently no-ops on one of the two platforms is worse than no splice --
# it would pass the suite locally and leave the hole open in CI, or the reverse.
while [[ "$CMD" == *\\$'\n'* ]]; do
  CMD="${CMD%%\\$'\n'*} ${CMD#*\\$'\n'}"
done
# Collapse the runs of leading whitespace the splice leaves behind, so the flag tokens
# of a continued command are separated by exactly one space like any other call.
CMD=$(tr -s '[:space:]' ' ' <<< "$CMD")

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
# QUOTES ARE COMMAND BOUNDARIES TOO. `sh -c 'rm -rf /'` opens a fresh command at the
# quote, not at a metacharacter: without `'` and `"` in this class the regex saw no rm
# at all, RM_CALLS came back empty, and the single most destructive command in this
# file's vocabulary exited 0. Same for `bash -c "rm -rf /"`. The nested-shell check
# below is the real defence, but the boundary class must not be the thing that hides
# the payload from it.
#
# Defined ONCE and reused by every pattern below. Two copies of a character class is
# how one of them ends up missing a character.
CMD_START='(^|[|;&(`\\'"'"'"[:space:]])'

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

# A directory name matches at a directory BOUNDARY: a following slash, or end of
# string. `\.ssh/` alone required the trailing slash -- but _normalize_target strips
# exactly that slash before the comparison, so the directory ITSELF never matched its
# own pattern. `rm -rf /home/alice/.ssh` normalized to a token ending in ".ssh", missed
# here, then matched the `/home/*/*` "under some home, more than one level deep" allow
# branch and deleted another account's entire key store. The end-of-string alternative
# is what closes that; it is spelled once, here, so the two call sites cannot drift.
DIR_BOUNDARY='(/|$)'

UNIVERSAL_SECRETS="\\.ssh$DIR_BOUNDARY|\\.gnupg$DIR_BOUNDARY|\\.aws/credentials|\\.npmrc|id_rsa|id_ed25519|$KEY_EXTENSIONS"

# Repository internals. Hand-editing .git/ corrupts repository state in ways ordinary
# git commands cannot undo. block-protected-paths.sh already guards this on the
# Write/Edit side; without the Bash half, `echo x > .git/config` walks past it -- the
# exact tool-versus-shell gap this whole file exists to close.
REPO_INTERNALS='\.git/'

# The guard's own source, and the settings file that wires it up.
#
# This is the bootstrap hole: nothing stopped `echo x > .claude/hooks/block-destructive-bash.sh`.
# The path sits inside REPO_ROOT, so the workspace carve-out waved it through, and it
# matches no credential filename. An agent could therefore rewrite this file to `exit 0`
# -- or edit .claude/settings.json to unwire the hook entirely -- and the VERY NEXT tool
# call would be judged by the rewritten guard. Every other protection in this file is
# downstream of these two paths, so they have to be protected first or none of the rest
# is worth anything.
#
# Scoped to hooks/ and settings*.json rather than all of .claude/: agents legitimately
# write skills, agent definitions, and workflow YAML under .claude/, and blocking those
# would make the guard unusable. Only the enforcing machinery is off-limits.
GUARD_INTERNALS='\.claude/hooks/|\.claude/settings[^/]*\.json'

# `.env` and its variants, but not `.env.example` and friends -- those are handled by
# the exact-token carve-out in _is_template below, not by a substring scrub.
#
# CHANGED: this used to accept only a dot-suffix (`.env.local`) or a non-name character
# after `.env`, which excluded the two spellings people actually use for the same
# secret. `.envrc` is direnv's file and routinely holds exported API keys; the
# `.env-production` / `.env_local` dash and underscore spellings are as common as the
# dotted one. Both read as ordinary words to the old pattern and both were allowed --
# while block-protected-paths.sh, matching the bare substring ".env", blocked them on
# the Write side. The two halves of the pair disagreeing about what a secret is meant a
# file the Write tool refused to create could still be read by `cat`.
DOTENV='\.env([^a-zA-Z0-9_.-]|[._-][a-zA-Z0-9_-]+|rc|$)'

# Everything a protected-path operand can look like.
SECRET_TARGET="($DOTENV|$DB_SECRET_FILES|$UNIVERSAL_SECRETS|$REPO_INTERNALS|$GUARD_INTERNALS)"

# Protected DIRECTORY segments, as distinct from protected FILE names.
#
# These exist because a directory operand carries no filename to match. `cp -r ~/.config
# /tmp` and `tar czf /tmp/x.tgz ~/.ssh` copy every credential and every private key
# wholesale, but the token is just a directory: no protected basename, no glob, no `$`.
# The operand loop's `*) continue` fast path -- which exists to keep ordinary tokens
# cheap -- skipped them for exactly that reason, so the two commands that exfiltrate the
# MOST were the ones that matched the least.
#
# Anchored at a boundary on both sides so `myconfig` and `.config-backup` do not match
# while `.config` and `.config/foo` do.
#
# Split in two because the two halves are checked at DIFFERENT points in the operand
# loop, and collapsing them back into one list would reintroduce a bug in each
# direction:
#
#   DIR_SEGMENTS_HARD  runs before the template carve-out. Nothing exempts these, so a
#                      file named .env.example inside ~/.ssh cannot vouch for ~/.ssh.
#   DIR_SEGMENTS_SOFT  runs before the template carve-out too, but AFTER the append
#                      carve-out, because ~/.config is where credentials.ini lives and
#                      appending a profile section to it is the one sanctioned write.
#                      Putting .config in the hard list blocks the append the whole
#                      carve-out exists to permit.
# `.claude` is deliberately NOT in either list. Blocking the whole directory would stop
# an agent reading its own skills, agent definitions and workflow YAML -- ordinary work
# it does constantly. Only the enforcing machinery inside it is protected, by
# GUARD_INTERNALS above. The `rm -rf .claude` case is handled separately in the rm
# section, where deleting the directory wholesale is a different act from reading a file
# in it.
PROTECTED_DIR_SEGMENTS_HARD='(^|/)(\.ssh|\.gnupg|\.aws)(/|$)'
PROTECTED_DIR_SEGMENTS_SOFT='(^|/)\.config(/|$)'

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
  # Shell whitespace, not one literal space. `git reset --hard` was the only pattern in
  # this list still spelled with a hard-coded " ": `git reset   --hard` and the tab
  # spelling both ran a working-tree-destroying reset while matching nothing. Every
  # other entry here already used [[:space:]]+; this one was simply missed.
  "reset[[:space:]]+--hard"
)

for p in "${PATTERNS[@]}"; do
  if grep -qiE "$p" <<< "$CMD"; then
    echo "Blocked: destructive pattern \"$p\" detected" >&2
    exit 2
  fi
done

# --- Nested shell evaluation: fail closed ------------------------------------
#
# `sh -c 'rm -rf /'` hands a STRING to another shell, which parses it under rules this
# hook does not implement. Every check below reasons about tokens of $CMD; the inner
# script is one such token, and its contents are not operands of anything as far as
# this file is concerned. Quoting the payload was enough to hide the single most
# destructive command in the vocabulary.
#
# Adding quotes to CMD_START (see above) makes the inner `rm -rf /` visible to the rm
# check, which handles that one spelling. It does not generalize: `sh -c "$SCRIPT"`,
# `eval "$CMD"`, and a base64-decoded pipeline are all unreadable no matter how the
# tokenizer is tuned, because the dangerous text does not exist until the outer shell
# runs. Inspecting a string that has not been constructed yet is not a thing a static
# check can do.
#
# So this refuses rather than inspects. That is the same call the glob and
# unresolved-variable branches make, for the same reason: an expansion this hook cannot
# perform may cover anything, and "anything" includes `rm -rf /`.
#
# `xargs` is here only when a shell is what it invokes -- `xargs rm` is ordinary and
# stays allowed, because its operands are visible and the rm check reads them.
if grep -qE "${CMD_START}(sh|bash|zsh|ksh|dash|fish)[[:space:]]+(-[a-zA-Z]*[[:space:]]+)*-[a-zA-Z]*c([[:space:]]|$)" <<< "$CMD" \
   || grep -qE "${CMD_START}eval([[:space:]]|$)" <<< "$CMD" \
   || grep -qE "${CMD_START}xargs[[:space:]][^|;&]*[[:space:]](sh|bash|zsh|ksh|dash|fish)([[:space:]]|$)" <<< "$CMD"; then
  echo "Blocked: the command evaluates a string as shell code (sh -c, bash -c, eval, or xargs into a shell)." >&2
  echo "The inner script is parsed by another shell under rules this guard does not implement, so its" >&2
  echo "contents cannot be inspected -- 'sh -c \"rm -rf /\"' looks like an ordinary quoted argument here." >&2
  echo "Run the inner command directly so its operands are visible to this check, or if you genuinely" >&2
  echo "need the nested shell, run it yourself with a leading ! in the prompt." >&2
  exit 2
fi

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
  # Undo shell escaping BEFORE any pattern match.
  #
  # `cat ~/.config/credentials\.ini` runs an ordinary read of credentials.ini -- the
  # backslash is consumed by the shell and never reaches the filesystem. It does reach
  # the regex, though, where `credentials\.ini` does not match `credentials\.ini` as
  # written in DB_SECRET_FILES (that pattern's backslash escapes the dot, it does not
  # match a literal one). One stray backslash, typed anywhere in the path, turned every
  # filename rule off. Stripping the escapes here means the checks compare the path the
  # kernel will actually see.
  target=$(sed -E 's/\\(.)/\1/g' <<< "$target")
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
#
# /root is the Linux root account's home. It is not under /home, so none of the
# /home/<user> reasoning reached it, and on a CI runner where $HOME is /home/runner the
# "$HOME" entry does not cover it either -- `rm -rf /root` was allowed outright. It is
# another user's home directory in every sense that matters here; the only thing unusual
# about it is that it lives at the top level.
PROTECTED_ROOTS=(/ "$HOME" /Users /home /root /etc /usr /var /System /Library /opt /bin /sbin /Applications /private)

# Temp ROOTS are protected too; only their descendants are scratch.
#
# The carve-out below allows /tmp/?* -- at least one character after the slash. The
# roots themselves fell through it into the protected-prefix loop, where /tmp is not
# listed either, so `rm -rf /tmp` was allowed outright. Deleting all of /tmp takes out
# every other session's scratch directory, including this repo's own
# /private/tmp/claude-501 tree.
#
# /private/var/tmp is the canonical spelling of /var/tmp on macOS (/var is a symlink to
# private/var). Symlink canonicalization rewrites the target before it reaches this
# loop, so without the resolved spelling `rm -rf /var/tmp` -- deleting every other
# session's scratch -- would compare against nothing and fall through.
TEMP_ROOTS=(/tmp /private/tmp /var/tmp /private/var/tmp)

_block_rm_target() {
  echo "Blocked: 'rm' with recursive+force targeting the protected path $1" >&2
  echo "This resolves to a system, temp-root, or home directory, not workspace scratch space." >&2
  echo "If this is genuinely what you want, run it yourself with a leading ! in the prompt." >&2
  exit 2
}

# How `rm` can be spelled and still be rm.
#
# The detector used to require a BARE `rm` at a command boundary, which is the exact
# hole the READERS list was rewritten to close -- and the fix was never carried across
# to the rm detector, so it survived here for the most destructive command in the file.
# `/bin/rm -rf /` and `"rm" -rf /` both run the real binary while matching nothing, and
# `/` is not a credential filename, so the operand checks further down did not catch
# them either. Three ways to spell it, none of them exotic:
#
#   /bin/rm -rf /      an absolute path to the binary
#   "rm" -rf /         quoted, which suppresses alias lookup exactly like \rm does
#   'rm' -rf /         the single-quoted spelling of the same thing
#
# The leading `[^[:space:]|;&]*/` accepts any directory prefix; the quote alternatives
# are spelled out because a quote is a command boundary in CMD_START, so the quoted
# forms arrive with the quote already consumed as the boundary character.
RM_NAME='("|'"'"')?([^[:space:]|;&()<>"'"'"']*/)?rm("|'"'"')?'

if grep -qE "${CMD_START}${RM_NAME}([[:space:]]|$)" <<< "$CMD"; then
  # Every rm invocation in the command, one per line. A compound command can hold
  # more than one (`cd /tmp && rm -rf a; rm -rf /`), and checking only the first
  # would miss the dangerous half.
  # The trailing sed strips the boundary character AND the command name in whatever
  # spelling it appeared, so the operand loop below sees a uniform "flags and operands"
  # string regardless of whether the call was `rm`, `/bin/rm`, or `"rm"`. Without that
  # second substitution `/bin/rm` survives into the token list, where `/bin` reads as an
  # operand under a protected system prefix and blocks every rm call in the repo.
  RM_CALLS=$(grep -oE "${CMD_START}${RM_NAME}[[:space:]][^|;&\`)]*" <<< "$CMD" \
    | sed -E 's/^[|;&(`\\'"'"'"[:space:]]*//' \
    | sed -E 's/^("|'"'"')?([^[:space:]|;&()<>"'"'"']*\/)?rm("|'"'"')?[[:space:]]/ /')

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

      # An UNRESOLVED expansion or an ambiguous glob must fail closed HERE, before
      # _resolve_dots ever sees it.
      #
      # The design comment at the top of this section already promises this ("an
      # unresolvable or ambiguous target is treated as protected"), but only $HOME was
      # ever expanded, so every other variable fell through as an ordinary string.
      # `TARGET=/; rm -rf "$TARGET"` left the literal token `$TARGET`, which has no
      # leading slash, so _resolve_dots helpfully resolved it against $PWD into
      # "$PWD/\$TARGET" -- a path comfortably inside the workspace, matching the repo
      # carve-out and exiting 0. The most dangerous possible value for that variable is
      # the one the check then failed to consider.
      #
      # The same applies to `rm -rf $SOME/*` and `rm -rf ~/*`: a glob's expansion is
      # decided by the filesystem at run time, and this hook does not get to see it.
      case "$target" in
        *'$'*|*'*'*|*'?'*|*'['*)
          echo "Blocked: 'rm -rf $tok' has a target this guard cannot resolve." >&2
          echo "The token contains an unexpanded variable, a command substitution, or a glob, so what it" >&2
          echo "deletes is decided at run time by state the hook cannot see -- and '/' is a possible value." >&2
          echo "Name the directory literally, or run it yourself with a leading ! in the prompt." >&2
          exit 2
          ;;
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

      # A symlinked COMPONENT makes a textually-safe path point anywhere.
      #
      # Everything above compares strings, but rm follows symlinks in the path leading
      # to its target. `ln -s / /tmp/root` then `rm -rf /tmp/root/etc` reads as an
      # ordinary /tmp descendant and is carved out as scratch three lines below, while
      # actually deleting /etc. The textual normalization that makes `/tmp/../etc` safe
      # is exactly what cannot see this: the escape is in the filesystem, not the string.
      #
      # NOT plain `realpath`/`readlink -f` on the whole path: both return EMPTY for a
      # path that does not exist, and an empty string compared against the protected
      # list passes silently -- the same trap _resolve_dots was written to avoid, which
      # is why that function is textual. Deleting a path that does not exist yet is
      # ordinary (`rm -rf build/out` before a first build), so emptiness here is
      # common, not exceptional.
      #
      # So: walk DOWN from the root and resolve only the components that actually exist,
      # stopping at the first one that does not. An existing prefix is resolvable and
      # gets resolved; a nonexistent tail cannot contain a symlink, because a symlink is
      # a thing that exists. If the resolved prefix differs from the textual one, the
      # path crosses a link and the textual comparisons above were judging a different
      # location than rm will touch -- so re-judge, and if the resolution cannot be
      # established at all, refuse.
      _resolve_symlinks() {
        local path="$1" walked="" seg resolved
        local IFS='/'
        # shellcheck disable=SC2086
        for seg in $path; do
          [ -n "$seg" ] || continue
          walked="$walked/$seg"
          if [ -L "$walked" ]; then
            # A symlink component. Resolve it with the shell's own -P cd, which does not
            # invent a result for a missing path the way realpath's fallbacks do.
            resolved=$(cd -P "$walked" 2>/dev/null && pwd -P) || return 1
            walked="$resolved"
          elif [ ! -e "$walked" ]; then
            # First nonexistent component: nothing below it can be a link. The rest of
            # the path is textual and already normalized.
            break
          fi
        done
        printf '%s' "$walked"
      }

      if ! CANONICAL=$(_resolve_symlinks "$target"); then
        echo "Blocked: 'rm -rf $target' passes through a symbolic link this guard could not resolve." >&2
        echo "A link component makes a textually-safe path point somewhere else entirely -- a link to /" >&2
        echo "turns '/tmp/x/etc' into '/etc' -- and an unresolvable one cannot be shown to stay inside" >&2
        echo "scratch space. Name the real path, or run it yourself with a leading ! in the prompt." >&2
        exit 2
      fi
      # Re-run the dot resolution: cd -P returns an absolute path, but the tail spliced
      # onto it is still raw.
      CANONICAL=$(_resolve_dots "$CANONICAL")

      # A differing canonical path is NOT itself suspicious -- on macOS /tmp is a
      # symlink to /private/tmp, so every legitimate scratch delete resolves to a
      # different string than it was written as. Demanding textual equality here blocked
      # `rm -rf /tmp/claude-scratch/build`, which is the single most common cleanup this
      # guard has to allow.
      #
      # What matters is whether the path is STILL inside a scratch boundary once
      # resolved. So the target is replaced by its canonical form and every check from
      # here down judges that instead -- `/tmp/root/etc` becomes `/etc` and is blocked
      # by the system-prefix rules on its own merits, while `/tmp/scratch/build` becomes
      # `/private/tmp/scratch/build` and is carved out by the /private/tmp branch just
      # below. Judging the real location is the whole point; the written one was never
      # what rm would act on.
      target="$CANONICAL"

      # Explicitly-safe scratch space, checked BEFORE the protected list because
      # /tmp on macOS is a symlink under /private and the repo itself lives under
      # /Users -- both would otherwise trip a protected prefix. The `?*` requires at
      # least one character past the slash, so the roots themselves are NOT carved
      # out here; they are blocked by the TEMP_ROOTS loop below.
      #
      # /private/var/tmp is listed alongside /var/tmp because on macOS /var is itself a
      # symlink to private/var, so canonicalization rewrites every /var/tmp path into a
      # /private/var/tmp one before this comparison happens. Listing only the written
      # spelling meant `rm -rf /var/tmp/build` resolved to a path matching no scratch
      # branch and was blocked as a system path -- the symlink fix breaking a case it
      # was never aimed at. Both spellings of each temp root, for the same reason
      # /private/tmp appears next to /tmp.
      case "$target" in
        /tmp/?*|/private/tmp/?*|/var/tmp/?*|/private/var/tmp/?*|"${TMPDIR:-/nonexistent}"/?*) continue ;;
      esac
      for troot in "${TEMP_ROOTS[@]}"; do
        [ "$target" = "$troot" ] && _block_rm_target "$target"
      done
      # `.claude/worktrees` holds every OTHER session's isolated checkout, including
      # uncommitted work that exists nowhere else. It sits inside the repo, so the
      # workspace carve-out below would otherwise wave it through. Checked before that
      # carve-out for exactly that reason.
      #
      # The `/*` descendant form is the case that actually matters. Protecting only the
      # worktrees DIRECTORY meant `rm -rf .claude/worktrees/other-session` -- naming one
      # specific sibling session -- resolved to a path inside REPO_ROOT, matched neither
      # `*/.claude/worktrees` nor `*/.claude`, and hit the workspace carve-out below.
      # Deleting one named worktree is the precise, targeted version of the thing the
      # broad form was blocked for, and it destroys another session's uncommitted work
      # just as permanently.
      #
      # But the descendant form needs one carve-out of its own, or it blocks all
      # ordinary work: this hook usually RUNS from inside .claude/worktrees/<session>,
      # so every path in the agent's own checkout -- `out/`, `build/`, `.venv` -- is
      # itself a `*/.claude/worktrees/*` path. Blocking those would make a session
      # unable to clean its own scratch directories. The agent's own worktree is its
      # workspace; the sibling worktrees beside it are what must not be touched.
      # The carve-out is for paths inside the agent's own worktree that are NOT
      # themselves .claude paths. Without that second half it swallows the very cases
      # this block exists for: `rm -rf .claude/worktrees/other-session` is relative, so
      # it resolves under the current worktree and would match the carve-out before ever
      # reaching the pattern below it.
      # `.git` holds every commit, branch and reflog entry that is not pushed. Deleting
      # it turns the checkout into an ordinary directory of files and discards all of
      # it. It sits inside the workspace, so the carve-out immediately below waves it
      # through -- and SECRET_TARGET's `\.git/` needs a trailing slash, which path
      # normalization strips, so the exact directory never matched that either. The
      # file-level protection covered `.git/config` while the whole directory was free
      # to delete.
      case "$target" in
        */.git|*/.git/*)
          echo "Blocked: 'rm -rf $target' deletes the repository metadata." >&2
          echo "That discards every unpushed commit, branch, stash and reflog entry -- history that" >&2
          echo "exists nowhere else. The working files survive; nothing else does." >&2
          echo "If you meant to start over, clone afresh, or run it yourself with a leading ! in the" >&2
          echo "prompt." >&2
          exit 2
          ;;
      esac

      SELF_WORKTREE=$(git rev-parse --show-toplevel 2>/dev/null || printf '%s' "$PWD")

      # The exact repository root, as distinct from anything under it.
      #
      # The carve-out below is written `"$SELF_WORKTREE"/?*` -- at least one character
      # past the slash -- so the root itself deliberately falls through it. Nothing
      # afterwards caught it: a checkout under $HOME or /home matches the "under some
      # home, more than one level deep" allow branch, so `rm -rf /path/to/this/checkout`
      # deleted the entire working tree, .git and all. Same shape as the TEMP_ROOTS bug
      # (roots fell through a `?*` carve-out written for descendants), in a different
      # place.
      if [ -n "$SELF_WORKTREE" ] && [ "$target" = "$SELF_WORKTREE" ]; then
        echo "Blocked: 'rm -rf $target' deletes this entire repository checkout." >&2
        echo "That takes the working tree, .git, and any uncommitted work in it." >&2
        echo "Delete specific directories inside it, use 'git worktree remove' for a worktree, or" >&2
        echo "run it yourself with a leading ! in the prompt." >&2
        exit 2
      fi

      case "$target" in
        "$SELF_WORKTREE"/.claude|"$SELF_WORKTREE"/.claude/*) ;;  # fall through to block
        "$SELF_WORKTREE"/?*) continue ;;   # the agent's own workspace -- allowed
      esac
      case "$target" in
        */.claude/worktrees|*/.claude/worktrees/*|*/.claude)
          echo "Blocked: 'rm -rf $target' would delete another session's isolated worktree," >&2
          echo "including uncommitted work that exists nowhere else." >&2
          echo "Remove one worktree with 'git worktree remove <path>', or run it yourself with a" >&2
          echo "leading ! in the prompt." >&2
          exit 2
          ;;
      esac

      # NOTE: the "anything under the current repo checkout is the agent's own
      # workspace" carve-out now lives in the .claude block above, merged with the
      # sibling-worktree exception it has to be ordered against. Keeping them apart
      # meant two `git rev-parse --show-toplevel` calls deciding the same question, and
      # the .claude exception only works if it is evaluated first.

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

      # A protected subtree belonging to ANOTHER user's home, reached by absolute path.
      #
      # The `$HOME/.ssh` case above only covers the CURRENT user, because it interpolates
      # $HOME. `rm -rf /home/alice/.ssh` names someone else's key store outright and was
      # matched by the `/home/*/*` allow branch immediately below ("under some home, more
      # than one level deep"), which is exactly where it lands. Whose home it is does not
      # change what .ssh holds.
      case "$target" in
        /Users/*/.ssh|/Users/*/.ssh/*|/home/*/.ssh|/home/*/.ssh/*|\
        /Users/*/.gnupg|/Users/*/.gnupg/*|/home/*/.gnupg|/home/*/.gnupg/*|\
        /Users/*/.aws|/Users/*/.aws/*|/home/*/.aws|/home/*/.aws/*|\
        /Users/*/.config|/Users/*/.config/*|/home/*/.config|/home/*/.config/*|\
        /Users/*/.claude|/Users/*/.claude/*|/home/*/.claude|/home/*/.claude/*)
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
        # /opt/* was missing while bare /opt was in PROTECTED_ROOTS, so the root was
        # guarded and everything real inside it was not: `rm -rf /opt/homebrew` removes
        # an entire package manager and every tool installed through it.
        # /root/* rather than a `/root/*/*`-style allow: unlike /home and /Users, /root
        # IS a single user's home rather than a container of them, so its descendants
        # are that user's dotfiles and keys, not separate accounts.
        /etc/*|/usr/*|/var/*|/System/*|/Library/*|/opt/*|/root/*|/bin/*|/sbin/*|/Applications/*|/private/*)
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
# It is now scoped three ways: the exempt token's BASENAME must be exactly
# credentials.ini (so token.json cannot ride along); the exemption applies to that one
# token only, so `echo x >> ~/.config/credentials.ini && cat ~/.ssh/id_rsa` still blocks
# on the cat; and -- see below -- the path must appear ONLY as an append target.
#
# CHANGED AGAIN: the previous version compared path STRINGS with no notion of which
# occurrence it was looking at. `_is_exempt_append` answered "is there an append to this
# path somewhere in the command?", so a single `>>` vouched for every other mention of
# the same path. Two live bypasses came out of that:
#
#   cat ~/.config/credentials.ini && echo "[x]" >> ~/.config/credentials.ini
#       -- the trailing append exempted the leading `cat`, disclosing the file.
#   echo x > ~/.config/credentials.ini && echo y >> ~/.config/credentials.ini
#       -- the append exempted the TRUNCATING `>`, destroying every profile section.
#       That is precisely the write CLAUDE.md's "never overwrite credentials.ini" names,
#       let through by the carve-out that exists to serve that same rule.
#
# The token loop below cannot tell which occurrence of a repeated path it is holding --
# `tr` discards position. Rather than rebuild the tokenizer into a positional parser,
# the exemption now requires that EVERY occurrence of the path in the command be an
# append. Counting is enough because the two are equivalent for the case that matters:
# if the appends account for all mentions, no reader and no truncating write can be
# hiding among them. A mixed command loses the carve-out entirely, which is the correct
# direction -- the user can still append in a command that does only that.
TOTAL_CREDS_MENTIONS=$(grep -oE '[^[:space:]|;&<>"'"'"']*credentials\.ini' <<< "$CMD" | wc -l | tr -d '[:space:]')

# Every append target in the command: `>> path`, `tee -a path`, `tee --append path`.
APPEND_TARGETS=$(
  {
    grep -oE '>>[[:space:]]*[^[:space:]|;&]+' <<< "$CMD" | sed -E 's/^>>[[:space:]]*//'
    grep -oE "${CMD_START}tee[[:space:]]+(-a|--append)[[:space:]]+[^[:space:]|;&]+" <<< "$CMD" \
      | sed -E 's/.*(-a|--append)[[:space:]]+//'
  } 2>/dev/null | sed '/^$/d'
)

# How many of those append targets are credentials.ini.
APPEND_CREDS_COUNT=$(grep -cE '(^|/)credentials\.ini$' <<< "$APPEND_TARGETS" || true)

# True when $1 names credentials.ini, is one of the append targets, AND no other
# occurrence of that path exists in the command.
_is_exempt_append() {
  local candidate norm t
  candidate=$(_normalize_target "$1")
  case "${candidate##*/}" in
    credentials.ini) ;;
    *) return 1 ;;
  esac
  # A reader or a truncating `>` elsewhere in the command means at least one mention is
  # not accounted for by an append. Refuse the carve-out for all of them.
  [ "$TOTAL_CREDS_MENTIONS" -eq "$APPEND_CREDS_COUNT" ] || return 1
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
#
# The three MAIL_ASSISTANT_/IOS_ names were missing. They are not hypothetical:
# core/auth.py reads MAIL_ASSISTANT_GMAIL_CREDENTIALS and MAIL_ASSISTANT_GMAIL_TOKEN
# and runs each through os.path.expanduser as a credential path, and
# phone/cli/cmd_merge.py reads IOS_CREDS_FILE and puts it at the FRONT of the
# credential-ini search path -- so it names the file that shadows every other one.
# `cat "$IOS_CREDS_FILE"` was allowed outright. Only the path-valued names belong here:
# MAIL_ASSISTANT_OUTLOOK_CLIENT_ID and _TENANT are opaque values, not paths, and adding
# them would block ordinary configuration work for no gain.
CREDENTIAL_VARS='CREDENTIALS|OUTLOOK_TOKEN|GOOGLE_APPLICATION_CREDENTIALS|GMAIL_TOKEN|MSAL_FLOW|MAIL_ASSISTANT_GMAIL_CREDENTIALS|MAIL_ASSISTANT_GMAIL_TOKEN|IOS_CREDS_FILE'

# Bare expansions that name a whole protected directory rather than a path inside one.
#
# `tar -czf /tmp/home.tgz "$HOME"` archives the entire home directory -- every
# credential, every key, every token -- into a file the agent can then read. The
# unresolvable-token check below never saw it, because that check requires a `*/` path
# shape and these tokens have no slash at all. `~` alone and `$XDG_CONFIG_HOME` alone
# have the same problem and the same consequence: $XDG_CONFIG_HOME is the directory
# core/constants.py searches for credentials.ini first.
BARE_HOME_EXPANSIONS='^(~|\$\{?(HOME|XDG_CONFIG_HOME|XDG_DATA_HOME)\}?)$'

_report_protected() {
  echo "Blocked: the command references the protected path '$1'." >&2
  echo "Credential files hold OAuth client secrets and refresh tokens; printing one discloses it," >&2
  echo "and writing or deleting one destroys profile sections nothing in this repo regenerates." >&2
  echo "If you need a specific value, ask the user. Listing the directory does not work around" >&2
  echo "this either -- naming a credential DIRECTORY blocks too, because 'cp -r ~/.config /tmp'" >&2
  echo "discloses more than reading one file does." >&2
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

    # Normalized ONCE, up front, and reused by every check below. The escape-stripping
    # in _normalize_target is what makes `credentials\.ini` match the credentials.ini
    # patterns at all, so a check that skips normalization is a check with a backslash
    # hole in it.
    NORM=$(_normalize_target "$candidate")

    # Protected DIRECTORY segments, checked BEFORE the template carve-out.
    #
    # This ordering is the whole fix. `_is_template` returns early with `continue`, so
    # any token whose BASENAME looked like a template exempted the entire path from
    # every rule below it -- `cat ~/.ssh/.env.example` and `cat .git/.env.sample` were
    # both allowed reads out of directories this hook exists to protect. A carve-out
    # saying "this FILE is a harmless template" must never be able to vouch for the
    # DIRECTORY the file sits in; anyone can drop a file named .env.example into ~/.ssh.
    #
    # block-protected-paths.sh already checks directories first and carries the same
    # comment. The Bash half did not, so the identical bug survived on this side of the
    # pair -- which is the recurring lesson with these two files: a fix applied to one
    # door is not a fix.
    #
    # `.git/` is in this same check rather than left to SECRET_TARGET below, for the
    # same ordering reason: `cat .git/.env.sample` would otherwise be exempted by the
    # template carve-out before REPO_INTERNALS ever ran.
    if grep -qE "$PROTECTED_DIR_SEGMENTS_HARD|$REPO_INTERNALS|$GUARD_INTERNALS" <<< "$NORM"; then
      _report_protected "$candidate"
    fi

    # The one sanctioned write to a protected file. Checked BEFORE the .config
    # directory rule, because ~/.config is exactly where credentials.ini lives -- a
    # directory rule that ran first would block the append this carve-out exists for.
    _is_exempt_append "$candidate" && continue

    # The remaining protected directories. Still ahead of the template carve-out, so
    # `cat ~/.config/.env.example` cannot use a template basename to read out of a
    # credential directory.
    if grep -qE "$PROTECTED_DIR_SEGMENTS_SOFT" <<< "$NORM"; then
      _report_protected "$candidate"
    fi

    # Checked-in templates are readable and editable by design.
    _is_template "$candidate" && continue

    if grep -qE "$SECRET_TARGET" <<< "$NORM"; then
      _report_protected "$candidate"
    fi

    # A bare `~`, `$HOME`, or `$XDG_CONFIG_HOME` as an operand names a whole protected
    # directory. Checked here, before the `*/` path-shape requirement below, because
    # these tokens have no slash and that requirement is exactly what let them past.
    if grep -qE "$BARE_HOME_EXPANSIONS" <<< "$candidate"; then
      _report_unresolvable "$candidate"
    fi

    # A variable that names a credential file outright. No path shape required: the
    # variable is the whole path, so `cat $CREDENTIALS` has no `/` to key off.
    if grep -qE "\\\$\{?($CREDENTIAL_VARS)\}?" <<< "$candidate"; then
      _report_unresolvable "$candidate"
    fi

    # Unresolvable expansions. A token with no glob character and no `$` in it is
    # fully resolved and was already judged by the checks above.
    #
    # NOTE the `$HOME`-expanded case: _normalize_target has already turned `$HOME/.ssh`
    # into a literal path, so a token that WAS an expansion may arrive here fully
    # resolved. It was judged by PROTECTED_DIR_SEGMENTS above, which is why that check
    # runs on $NORM rather than on the raw token.
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
    if grep -qE "($SENSITIVE_DIRS)" <<< "$NORM"; then
      _report_unresolvable "$candidate"
    fi
  done
done <<< "$TOKENS"

exit 0
