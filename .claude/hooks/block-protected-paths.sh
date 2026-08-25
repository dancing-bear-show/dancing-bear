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
# Note this duplicates part of permissions.deny (which already denies Write/Edit on
# **/credentials.ini and friends). The hook is the enforcing layer: deny rules can be
# overridden by a project-level settings file, a PreToolUse hook exiting 2 cannot.

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

# Checked-in templates are safe -- they carry placeholder values and exist to be
# edited. Carved out before the .env substring test below, which would otherwise
# catch every one of them. Same logic as the reference and as the read-side hook.
case "$FILE" in
  *.env.example|*.env.template|*.env.sample) exit 0 ;;
esac

# Matching is a case-SENSITIVE substring test against the path, so "credentials.ini"
# also matches "credentials.ini.bak" and ".git/" matches any path segment containing
# it. Over-blocking is the safe direction: the cost of a false positive is one
# clarifying question, the cost of a false negative is a destroyed credential file
# that nothing in this repo can regenerate.
PATTERNS=(
  # This repo's credential set, from core/constants.py and mail/config_resolver.py.
  "credentials.ini"
  "credentials.json"
  "outlook_token.json"
  "msal_flow.json"
  "token.json"
  # Universal secrets.
  ".env"
  ".ssh/"
  ".gnupg/"
  ".aws/credentials"
  ".npmrc"
  "id_rsa"
  "id_ed25519"
  ".pem"
  # Writing into .git/ by hand corrupts repository state in ways that are not
  # recoverable with ordinary git commands. Use git itself.
  ".git/"
)

for p in "${PATTERNS[@]}"; do
  if [[ "$FILE" == *"$p"* ]]; then
    echo "Blocked: $FILE matches protected pattern $p" >&2
    exit 2
  fi
done

exit 0
