#!/usr/bin/env bash
# PreToolUse hook (matcher: Write|Edit) -- block writes to sensitive files.
#
# Ported and adapted to dancing-bear's INI credential layout. Where the original
# guarded a .env/Google-Workspace stack, this guards the files core/constants.py and
# mail/config_resolver.py actually resolve.
#
# Contract: exit 2 blocks the tool call and shows stderr to Claude. Exit 0 allows.
#
# This is the Write/Edit-tool half of the pair; block-destructive-bash.sh covers the
# same files on the Bash side. Both are needed: a deny rule and a hook that only
# watches one door leave the other one open.
#
# SCOPE: this is an ACCIDENT guard, not a security boundary. It stops a reflexive write
# to a credential file. It matches path STRINGS, so a symlinked path, a path assembled
# from an expansion the hook cannot evaluate, or a write routed through the Bash tool
# instead of Write/Edit are all outside what it can see. See the "Known gaps (won't fix)"
# section in README.md; anything that genuinely must not happen needs filesystem
# permissions or a sandbox rather than a string check.
#
# Note this duplicates part of permissions.deny (which already denies Write/Edit on
# **/credentials.ini and friends). The MECHANISM here is the sturdier of the two: deny
# rules can be overridden by a project-level settings file, a PreToolUse hook exiting 2
# cannot. That says nothing about coverage -- an unbypassable hook still only blocks the
# paths it recognizes.

set -u

# Fail CLOSED on a malformed payload.
#
# `jq -r .tool_input.file_path` on garbage prints nothing and exits nonzero. Taking
# that as an empty FILE means no pattern matches and the hook exits 0 -- a spurious
# ALLOW caused by the failure of the thing meant to inspect the write. A hook that
# cannot see the path does not know what it is approving.
PAYLOAD=$(cat)
if ! FILE=$(jq -er ".tool_input.file_path" <<< "$PAYLOAD" 2>/dev/null); then
  echo "Blocked: could not parse the PreToolUse payload (.tool_input.file_path missing, null, or not JSON)." >&2
  echo "Failing closed rather than allowing an uninspected write." >&2
  exit 2
fi

# A non-string .file_path is NOT a parse failure as far as jq is concerned.
#
# `{"file_path": []}` and `{"file_path": {}}` are truthy JSON values, so `jq -er`
# exits 0 and prints "[]" or "{}". `{"file_path": 0}` prints "0". None of those match
# any pattern below, so the hook exited 0 and allowed a write it had never actually
# inspected -- the same spurious-ALLOW shape the parse check above exists to prevent,
# arriving through a door that check does not watch.
FILE_TYPE=$(jq -r '.tool_input.file_path | type' <<< "$PAYLOAD" 2>/dev/null || echo "unknown")
if [ "$FILE_TYPE" != "string" ]; then
  echo "Blocked: .tool_input.file_path is a $FILE_TYPE, not a string." >&2
  echo "Failing closed rather than allowing a write the hook cannot read." >&2
  exit 2
fi

# An empty or whitespace-only path names nothing the hook can judge. Fail closed for
# the same reason as the non-string case.
if [ -z "${FILE//[[:space:]]/}" ]; then
  echo "Blocked: .tool_input.file_path is empty." >&2
  echo "Failing closed rather than allowing an uninspected write." >&2
  exit 2
fi

# Protected DIRECTORY segments, checked FIRST.
#
# CHANGED: the template carve-out below used to run before this. It returns early with
# exit 0, so any basename that merely looked like a template exempted the whole path
# from every directory rule underneath it -- `.ssh/.env.example` and
# `.git/hooks/.env.sample` were both allowed writes into directories this hook exists
# to protect. A carve-out for "this FILE is a harmless template" must never be able to
# vouch for the DIRECTORY the file sits in.
#
# Writing into .git/ by hand corrupts repository state in ways that are not
# recoverable with ordinary git commands. Use git itself.
DIR_PATTERNS=(
  ".ssh/"
  ".gnupg/"
  ".aws/"
  ".git/"
)

for p in "${DIR_PATTERNS[@]}"; do
  if [[ "$FILE" == *"$p"* ]]; then
    echo "Blocked: $FILE writes into the protected directory segment $p" >&2
    echo "No filename exempts a write into this directory, template-looking or not." >&2
    exit 2
  fi
done

# The guard's own source, and the settings file that wires it up.
#
# This hook protected credential files while leaving ITSELF writable, which makes every
# other rule in the file advisory: a Write to .claude/hooks/block-protected-paths.sh
# replacing the body with `exit 0`, or an edit to .claude/settings.json removing the
# PreToolUse entry, disarms the guard, and the very next tool call is judged by the
# disarmed version. block-destructive-bash.sh had the same hole on the Bash side
# (`echo x > .claude/hooks/...`); both halves are closed together, because closing one
# door of a pair is what these two files keep learning the hard way.
#
# Scoped to hooks/ and settings*.json rather than all of .claude/: agents legitimately
# write skills, agent definitions, and workflow YAML under .claude/, and blocking those
# would make the guard unusable. Only the enforcing machinery is off-limits. Editing
# these files is a deliberate act the user can do themselves.
case "$FILE" in
  *.claude/hooks/*|.claude/hooks/*)
    echo "Blocked: $FILE modifies the guard hooks themselves." >&2
    echo "A hook that can rewrite its own source enforces nothing -- the next tool call would be" >&2
    echo "judged by the rewritten version. Edit these files yourself outside the session." >&2
    exit 2
    ;;
esac
case "${FILE##*/}" in
  settings.json|settings.local.json|settings*.json)
    case "$FILE" in
      *.claude/*|.claude/*)
        echo "Blocked: $FILE is the settings file that wires up the guard hooks." >&2
        echo "Removing the PreToolUse entry disarms every protection in them. Edit it yourself" >&2
        echo "outside the session." >&2
        exit 2
        ;;
    esac
    ;;
esac

# Checked-in templates are safe -- they carry placeholder values and exist to be
# edited. Carved out before the .env substring test below, which would otherwise
# catch every one of them.
#
# CHANGED: matched on the exact BASENAME rather than as a `*.env.example` glob over
# the whole path. The glob form also accepted `.env.example.bak`, which is a real
# config file someone copied, not a template. Same reasoning as the Bash-side hook.
#
# CHANGED AGAIN: the `*.env.example` arm is gone too. It kept the whole-path glob's
# problem in a smaller form -- any basename ENDING in `.env.example` was exempt, so
# `foo.env.example` and `prod.env.sample` were writable regardless of what they held.
# The comment above and the README both define this as an EXACT basename exemption; the
# wildcard made the code disagree with both, and a secret only had to be named
# `prod.env.sample` to opt into the carve-out. A template is the file the repo ships,
# and it is named `.env.example`. Kept in sync with _is_template in
# block-destructive-bash.sh: the two halves of the pair disagreeing about what a
# template is, is how a file one door refuses becomes readable through the other.
case "${FILE##*/}" in
  .env.example|.env.template|.env.sample) exit 0 ;;
esac

# Matching is a case-SENSITIVE substring test against the path, so "credentials.ini"
# also matches "credentials.ini.bak". Over-blocking is the safe direction: the cost of
# a false positive is one clarifying question, the cost of a false negative is a
# destroyed credential file that nothing in this repo can regenerate.
PATTERNS=(
  # This repo's credential set, from core/constants.py and mail/config_resolver.py.
  "credentials.ini"
  "credentials.json"
  "outlook_token.json"
  "msal_flow.json"
  "token.json"
  # Universal secrets.
  ".env"
  ".aws/credentials"
  ".npmrc"
  "id_rsa"
  "id_ed25519"
  # Key material. .pem is the generic PKCS/OpenSSL spelling; .p8 and .p12 are used by
  # this repo specifically -- apple_music loads a MusicKit private key as .p8, and
  # phone resolves a device supervision identity as .p12. A leaked .p8 signs Apple
  # Music API tokens; a leaked .p12 can re-supervise a device.
  ".pem"
  ".p8"
  ".p12"
)

for p in "${PATTERNS[@]}"; do
  if [[ "$FILE" == *"$p"* ]]; then
    echo "Blocked: $FILE matches protected pattern $p" >&2
    exit 2
  fi
done

exit 0
