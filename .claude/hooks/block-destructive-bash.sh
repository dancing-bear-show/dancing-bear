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

# ---------------------------------------------------------------------------
# 1. Destructive commands
# ---------------------------------------------------------------------------

# These are string-matched because they have no meaningful "target" to resolve --
# a DROP TABLE is destructive regardless of which table, and a force-push is
# destructive regardless of which remote.
PATTERNS=(
  "DROP[[:space:]]+TABLE"
  "DROP[[:space:]]+DATABASE"
  "TRUNCATE"
  "push.*--force"
  "push.*-f "
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
if grep -qE '(^|[|;&(`[:space:]])rm([[:space:]]|$)' <<< "$CMD"; then
  # Every rm invocation in the command, one per line. A compound command can hold
  # more than one (`cd /tmp && rm -rf a; rm -rf /`), and checking only the first
  # would miss the dangerous half.
  RM_CALLS=$(grep -oE '(^|[|;&(`[:space:]])rm[[:space:]][^|;&`)]*' <<< "$CMD" | sed -E 's/^[|;&(`[:space:]]*//')

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

      # Strip quotes, expand the two forms that resolve to $HOME, and collapse
      # repeated slashes so `//` and `///` land on `/` like the kernel treats them.
      target=$(sed -E 's/^["'"'"']//; s/["'"'"']$//' <<< "$tok")
      target=${target//\$HOME/$HOME}
      target=${target//\$\{HOME\}/$HOME}
      case "$target" in
        "~") target="$HOME" ;;
        "~/"*) target="$HOME/${target#\~/}" ;;
      esac
      target=$(sed -E 's#/+#/#g' <<< "$target")
      # A trailing slash is cosmetic: `/etc/` is `/etc`. Keep bare "/" intact.
      [ "$target" != "/" ] && target="${target%/}"

      # Explicitly-safe scratch space, checked BEFORE the protected list because
      # /tmp on macOS is a symlink under /private and the repo itself lives under
      # /Users -- both would otherwise trip a protected prefix.
      case "$target" in
        /tmp/?*|/private/tmp/?*|/var/tmp/?*|"${TMPDIR:-/nonexistent}"/?*) continue ;;
      esac
      # Anything under the current repo checkout is the agent's own workspace.
      REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || true)
      if [ -n "$REPO_ROOT" ] && [ "$target" != "$REPO_ROOT" ]; then
        case "$target" in "$REPO_ROOT"/?*) continue ;; esac
      fi
      # Relative paths (./out, build/, *.pyc) are workspace-local by definition.
      case "$target" in /*) ;; *) continue ;; esac

      # Protected prefixes. An exact match is fatal (`rm -rf /usr`), and so is a
      # direct child of / or /Users (`rm -rf /etc`, `rm -rf /Users/brian`) -- the
      # latter is someone's whole home directory.
      for prot in / "$HOME" /Users /etc /usr /var /System /Library /opt /bin /sbin /Applications; do
        if [ "$target" = "$prot" ]; then
          echo "Blocked: 'rm' with recursive+force targeting the protected path $target" >&2
          echo "This resolves to a system or home directory, not workspace scratch space." >&2
          exit 2
        fi
      done
      case "$target" in
        "$HOME"/*) : ;;   # under home but not home itself -- allowed, e.g. ~/.cache/foo
        /Users/*/*) : ;;  # under some home, more than one level deep -- allowed
        /Users/*)
          echo "Blocked: 'rm -rf $target' targets an entire user home directory." >&2
          exit 2
          ;;
        /etc/*|/usr/*|/var/*|/System/*|/Library/*|/bin/*|/sbin/*|/Applications/*)
          echo "Blocked: 'rm' with recursive+force under the system path $target" >&2
          exit 2
          ;;
      esac
    done
  done <<< "$RM_CALLS"
fi

# ---------------------------------------------------------------------------
# 2. Secret-file READS via the shell
# ---------------------------------------------------------------------------
#
# `Read(**/credentials.ini)` in permissions.deny binds the Read tool only. This is
# the Bash-side equivalent. The failure mode being prevented is specific: a
# compound call bundles `cat ~/.config/credentials.ini` next to an allowed
# `./bin/mail ...`, the whole thing reads as routine, and OAuth client secrets and
# Outlook refresh tokens land in the transcript. Once printed they are disclosed --
# there is no un-printing a token.
READERS="cat|bat|less|more|head|tail|nl|xxd|od|strings|grep|rg|ag|awk|sed|jq|cut|sort|uniq"

# Checked-in templates are safe and are excluded before matching. This repo ships
# config/filters_unified.example.yaml in the same spirit; .env.example and friends
# stay readable so a template can be diffed against a real config.
SCRUBBED=$(sed -E 's/\.env\.(example|template|sample)//g' <<< "$CMD")

# Where a command word can begin. A reader only counts at one of these, so
# "concatenate" does not read as "cat" and "sedate" does not read as "sed".
#
# The openers of a command substitution belong here too: $(cat credentials.ini) and
# the backtick spelling each start a fresh command. The original omitted `(` and the
# backtick until a live `export $(cat .env | xargs)` walked past the check -- one
# paren away from the block.
#
# Defined ONCE and reused by every pattern below. Two copies of a character class is
# how one of them ends up missing a character.
CMD_START='(^|[|;&(`[:space:]])'

# This repo's credential filenames, resolved from core/constants.py (credentials.ini
# under $CREDENTIALS's dir, $XDG_CONFIG_HOME, or ~/.config) and
# mail/config_resolver.py (the four JSON token files beside it).
#
# Matched as bare filenames rather than full paths on purpose: the directory varies
# with $XDG_CONFIG_HOME and $CREDENTIALS, and a copy of credentials.ini sitting in
# /tmp is exactly as sensitive as the original.
DB_SECRET_FILES='credentials\.ini|credentials\.json|outlook_token\.json|msal_flow\.json|token\.json'
UNIVERSAL_SECRETS='\.ssh/|\.gnupg/|\.aws/credentials|\.npmrc|id_rsa|id_ed25519'

SECRET_PATHS=(
  # .env and .env.<anything>, with templates already scrubbed out above.
  "$CMD_START($READERS)[^|;&]*\.env([^a-zA-Z0-9_.-]|\.[a-zA-Z0-9_-]+|$)"
  "$CMD_START($READERS)[^|;&]*($DB_SECRET_FILES)"
  "$CMD_START($READERS)[^|;&]*($UNIVERSAL_SECRETS)"
)

for p in "${SECRET_PATHS[@]}"; do
  if grep -qE "$p" <<< "$SCRUBBED"; then
    echo "Blocked: reading a credential file through the shell bypasses the Read(**/credentials.ini) deny rules." >&2
    echo "These files hold OAuth client secrets and refresh tokens; printing one discloses it." >&2
    echo "If you need a specific value, ask the user. To check a profile exists, use 'ls' or grep for the section header only." >&2
    exit 2
  fi
done

# ---------------------------------------------------------------------------
# 3. Secret-file WRITES via the shell
# ---------------------------------------------------------------------------
#
# The mirror image of the block above. Edit(**/credentials.ini) and
# block-protected-paths.sh both guard these files, but every one of those binds a
# file-editing TOOL. `echo "[mail.x]" > ~/.config/credentials.ini` is a Bash call and
# walks past all of them. So do tee, cp, mv, and dd.
#
# For this repo the stakes are specific: credentials.ini is hand-maintained and holds
# every profile. A truncating redirect onto it destroys every section at once, and
# nothing in the repo can regenerate it -- CLAUDE.md's "Never overwrite
# ~/.config/credentials.ini" is exactly this failure.
#
# Append is deliberately NOT blocked. `>>` and `tee -a` are how a new profile section
# gets added without destroying the existing ones, so blocking them would contradict
# the rule this hook exists to enforce. Both spellings are neutralized before
# matching rather than special-cased in each pattern -- one substitution instead of
# an append carve-out repeated in every regex, where one copy would eventually drift.
WRITERS="tee|cp|mv|install|dd|truncate|ln"

SECRET_TARGET="(\.env([^a-zA-Z0-9_.-]|\.[a-zA-Z0-9_-]+|$)|$DB_SECRET_FILES|$UNIVERSAL_SECRETS)"

WRITE_SCRUBBED=$(sed -E 's/>>/@APPEND@/g; s/(^|[|;&(`[:space:]])tee[[:space:]]+(-a|--append)([[:space:]]|$)/\1@APPEND@\3/g' <<< "$SCRUBBED")

SECRET_WRITES=(
  # Truncating redirect: `> credentials.ini`, `>creds`, `>| x`, `2> x`. By this point
  # `>>` has been rewritten to @APPEND@, so it cannot match.
  ">[|]?[^>|;&]*$SECRET_TARGET"
  # Writer commands. Also fires when a secret is the SOURCE (`cp ~/.config/credentials.ini /tmp`),
  # which is copying a credential file somewhere more readable -- worth blocking either way.
  "$CMD_START($WRITERS)[^|;&]*$SECRET_TARGET"
)

for p in "${SECRET_WRITES[@]}"; do
  if grep -qE "$p" <<< "$WRITE_SCRUBBED"; then
    echo "Blocked: writing a credential file through the shell bypasses the Edit(**/credentials.ini) deny rules." >&2
    echo "A truncating redirect onto credentials.ini destroys every profile section at once." >&2
    echo "Ask the user to run it themselves with a leading ! in the prompt. Appending with >> or tee -a is allowed." >&2
    exit 2
  fi
done

exit 0
