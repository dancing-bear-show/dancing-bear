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

# shellcheck source=./_harness.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_harness.sh"

if [ ! -f "$HOOK" ]; then
  echo "hook not found: $HOOK" >&2
  exit 1
fi
echo "testing: $HOOK"
echo

run() { # run <BLOCK|ALLOW> <file_path>
  local expect="$1" path="$2" rc
  jq -n --arg p "$path" '{tool_name:"Write",tool_input:{file_path:$p,content:"x"}}' | bash "$HOOK" >/dev/null 2>&1
  rc=$?
  _record "$expect" "$(_classify "$rc")" "$path"
}

run_raw() { # run_raw <BLOCK|ALLOW> <label> <raw-json>
  local expect="$1" label="$2" payload="$3" rc
  printf '%s' "$payload" | bash "$HOOK" >/dev/null 2>&1
  rc=$?
  _record "$expect" "$(_classify "$rc")" "$label"
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
run BLOCK "$HOME/.aws/config"
run BLOCK "$HOME/.npmrc"
run BLOCK "/etc/ssl/server.pem"
run BLOCK "certs/client.pem"
run BLOCK ".env"
run BLOCK "backend/.env.local"
run BLOCK "$HOME/.config/.env.production"

echo
echo "--- REGRESSION 14: .p8 and .p12 key material (want BLOCK) ---"
# apple_music loads a MusicKit private key as .p8; phone resolves a device
# supervision identity as .p12. A leaked .p8 signs Apple Music API tokens; a leaked
# .p12 can re-supervise a device. Neither extension was in the protected set.
run BLOCK "$HOME/.config/AuthKey_ABC123.p8"
run BLOCK "certs/supervision.p12"
run BLOCK "$HOME/Library/supervision-identity.p12"
run BLOCK "keys/musickit.p8"
# Matching is a substring test by design, so `.p8` mid-path blocks too. That is the
# over-blocking direction this hook chooses on purpose: one clarifying question costs
# less than a signed-token key leaking through a filename nobody thought to guard.
run BLOCK "docs/chapter.p8.md"

echo
echo "--- git internals (want BLOCK) ---"
run BLOCK ".git/config"
run BLOCK ".git/HEAD"
run BLOCK "/Users/me/code/dancing-bear/.git/hooks/pre-commit"

echo
echo "--- REGRESSION 11: template names cannot vouch for a protected DIRECTORY ---"
# The template carve-out used to run FIRST and `exit 0` early, so any basename that
# looked like a template exempted the entire path from every directory rule below it.
# A carve-out for "this FILE is harmless" must never vouch for the directory it is in.
run BLOCK ".ssh/.env.example"
run BLOCK "$HOME/.ssh/.env.template"
run BLOCK ".git/.env.sample"
run BLOCK ".git/hooks/.env.example"
run BLOCK "$HOME/.gnupg/.env.example"
run BLOCK "$HOME/.aws/.env.sample"

echo
echo "--- REGRESSION 17: template exemption is exact, not a suffix substring ---"
# `.env.example.bak` is a copy of a real config, not a template.
run BLOCK ".env.example.bak"
run BLOCK "backend/.env.template.old"
run BLOCK "prod.env.sample.real"

echo
echo "--- REGRESSION 19: the guard's own machinery is not writable (want BLOCK) ---"
# This hook protected credential files while leaving ITSELF writable, which makes every
# other rule advisory: a Write replacing the body with `exit 0`, or an edit to
# .claude/settings.json removing the PreToolUse entry, disarms the guard -- and the very
# next tool call is judged by the disarmed version. Every protection here is downstream
# of these paths, so they have to hold first or none of the rest is worth anything.
run BLOCK ".claude/hooks/block-protected-paths.sh"
run BLOCK ".claude/hooks/block-destructive-bash.sh"
run BLOCK ".claude/hooks/statusline.sh"
run BLOCK ".claude/hooks/tests/block-protected-paths.test.sh"
run BLOCK ".claude/settings.json"
run BLOCK ".claude/settings.local.json"
run BLOCK "/Users/me/code/dancing-bear/.claude/hooks/block-destructive-bash.sh"
# The hooks' own README is inside hooks/ and is blocked with them. Documentation that
# describes the guard sits close enough to the guard that the simple rule wins over a
# carve-out nobody would remember to keep correct.
run BLOCK ".claude/hooks/README.md"
# Scoped to the enforcing machinery only: agents legitimately author skills, agent
# definitions, and workflow YAML under .claude/, and blocking those makes the guard
# unusable rather than safe.
run ALLOW ".claude/skills/dancing-bear-rules/SKILL.md"
run ALLOW ".claude/agents/code-writer.md"
run ALLOW ".claude/workflows/optimize-code.yaml"
run ALLOW ".claude/WRITING_GUIDE.md"
# A settings.json OUTSIDE .claude/ is an ordinary project file (VS Code, tsconfig-alikes).
run ALLOW "settings.json"
run ALLOW ".vscode/settings.json"

echo
echo "--- REGRESSION 8: non-string and empty file_path fail closed (want BLOCK) ---"
# `jq -er` succeeds on [] and {} -- they are truthy JSON. The value then matches no
# pattern and the hook exited 0, approving a write it never inspected.
run_raw BLOCK 'file_path is an array'  '{"tool_name":"Write","tool_input":{"file_path":[],"content":"x"}}'
run_raw BLOCK 'file_path is an object' '{"tool_name":"Write","tool_input":{"file_path":{},"content":"x"}}'
run_raw BLOCK 'file_path is a number'  '{"tool_name":"Write","tool_input":{"file_path":0,"content":"x"}}'
run_raw BLOCK 'file_path is a bool'    '{"tool_name":"Write","tool_input":{"file_path":false,"content":"x"}}'
run_raw BLOCK 'file_path is empty'     '{"tool_name":"Write","tool_input":{"file_path":"","content":"x"}}'
run_raw BLOCK 'file_path is whitespace' '{"tool_name":"Write","tool_input":{"file_path":"  ","content":"x"}}'
run_raw BLOCK 'file_path is null'      '{"tool_name":"Write","tool_input":{"file_path":null,"content":"x"}}'
run_raw BLOCK 'file_path is absent'    '{"tool_name":"Write","tool_input":{"content":"x"}}'
run_raw BLOCK 'payload is not JSON'    'this is not json'
run_raw BLOCK 'payload is empty'       ''

echo
echo "--- checked-in templates (want ALLOW) ---"
run ALLOW ".env.example"
run ALLOW "backend/.env.template"
run ALLOW "config/.env.sample"
run ALLOW "docs/deploy/.env.example"

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
run ALLOW "src/workflow/compiler.py"
run ALLOW "Makefile"
run ALLOW ".github/workflows/ci.yml"
# "credentials" appearing in a docs filename is prose, not a credential file.
run ALLOW "docs/credentials-setup.md"
# .gitignore is a normal tracked file -- it must not trip the ".git/" segment rule.
run ALLOW ".gitignore"
run ALLOW ".gitattributes"
# ".p8"/".p12" need the leading dot, so an identifier containing "p8" is not a key.
run ALLOW "src/slides/p8_layout.py"
run ALLOW "src/phone/p12_reader.py"

echo
_summary "block-protected-paths"
exit $?
