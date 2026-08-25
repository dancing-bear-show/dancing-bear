#!/usr/bin/env bash
# Pipe-test block-protected-paths.sh with the real PreToolUse stdin shape.
#
# WHY THIS FILE EXISTS AT ALL: same reason as its sibling. The hook under test blocks
# the very writes it is being tested with, so an agent cannot exercise these cases by
# calling Write directly -- the hook intercepts first. The cases have to live in a
# file that is read from disk. Do not inline them back into ad-hoc tool calls.
#
# The hook is resolved as a sibling of this script's parent directory. Override with
# argument 1.
#
# Usage: bash block-protected-paths.test.sh [path-to-hook]
# Exit:  0 = all pass, 1 = at least one failure. Requires jq.

HOOK="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/block-protected-paths.sh}"
fail=0

if [ ! -f "$HOOK" ]; then
  echo "hook not found: $HOOK" >&2
  exit 1
fi
echo "testing: $HOOK"
echo

run() { # run <BLOCK|ALLOW> <file_path>
  local expect="$1" path="$2" rc got
  jq -n --arg p "$path" '{tool_name:"Write",tool_input:{file_path:$p,content:"x"}}' | bash "$HOOK" >/dev/null 2>&1
  rc=$?
  got=ALLOW; [ "$rc" -eq 2 ] && got=BLOCK
  if [ "$got" = "$expect" ]; then
    printf 'ok    %-5s  %s\n' "$got" "$path"
  else
    printf 'FAIL  want=%s got=%s  %s\n' "$expect" "$got" "$path"; fail=1
  fi
}

echo "--- this repo's credential files (want BLOCK) ---"
run BLOCK "$HOME/.config/credentials.ini"
run BLOCK "$HOME/.config/credentials.json"
run BLOCK "$HOME/.config/token.json"
run BLOCK "$HOME/.config/outlook_token.json"
run BLOCK "$HOME/.config/msal_flow.json"
run BLOCK "/opt/xdg/credentials.ini"
run BLOCK "credentials.ini"
run BLOCK "$HOME/.config/credentials.ini.bak"

echo
echo "--- universal secrets (want BLOCK) ---"
run BLOCK "$HOME/.ssh/id_rsa"
run BLOCK "$HOME/.ssh/config"
run BLOCK "$HOME/.ssh/id_ed25519"
run BLOCK "$HOME/.gnupg/secring.gpg"
run BLOCK "$HOME/.aws/credentials"
run BLOCK "$HOME/.npmrc"
run BLOCK "/etc/ssl/server.pem"
run BLOCK "certs/client.pem"
run BLOCK ".env"
run BLOCK "backend/.env.local"
run BLOCK "$HOME/.config/.env.production"

echo
echo "--- git internals (want BLOCK) ---"
run BLOCK ".git/config"
run BLOCK ".git/HEAD"
run BLOCK "/Users/me/code/dancing-bear/.git/hooks/pre-commit"

echo
echo "--- checked-in templates (want ALLOW) ---"
run ALLOW ".env.example"
run ALLOW "backend/.env.template"
run ALLOW "config/.env.sample"

echo
echo "--- ordinary source paths (want ALLOW) ---"
run ALLOW "src/mail/cli.py"
run ALLOW "src/core/constants.py"
run ALLOW "src/mail/config_resolver.py"
run ALLOW "tests/foo.py"
run ALLOW "tests/mail_tests/test_cli.py"
run ALLOW "README.md"
run ALLOW "CLAUDE.md"
run ALLOW "config/filters_unified.example.yaml"
run ALLOW "out/filters.gmail.from_unified.yaml"
run ALLOW ".claude/hooks/README.md"
run ALLOW "src/workflow/compiler.py"
run ALLOW "Makefile"
# "credentials" appearing in a docs filename is prose, not a credential file.
run ALLOW "docs/credentials-setup.md"
# .gitignore is a normal tracked file -- it must not trip the ".git/" segment rule.
run ALLOW ".gitignore"

echo
[ "$fail" -eq 0 ] && echo "ALL PASS" || echo "FAILURES PRESENT"
exit "$fail"
