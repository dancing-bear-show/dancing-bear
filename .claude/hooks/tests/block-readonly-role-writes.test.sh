#!/usr/bin/env bash
# Pipe-test block-readonly-role-writes.sh with the real PreToolUse stdin shape.
#
# WHY THIS FILE EXISTS AT ALL: same reason as its siblings. The hook under test blocks
# the writes it is being tested with, so these cases cannot be exercised by calling
# Write directly -- the hook intercepts first. They have to live in a file read from
# disk. Do not inline them back into ad-hoc tool calls.
#
# The payload shape here is not invented. It was captured from a live PreToolUse call
# made by a spawned researcher subagent, which is how `agent_type` was confirmed to be
# present at all. The fields below mirror that capture.
#
# Usage: bash block-readonly-role-writes.test.sh [path-to-hook]
# Exit:  0 = all pass, 1 = at least one failure. Requires jq.

HOOK="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/block-readonly-role-writes.sh}"

# shellcheck source=./_harness.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_harness.sh"

if [ ! -f "$HOOK" ]; then
  echo "hook not found: $HOOK" >&2
  exit 1
fi
echo "testing: $HOOK"
echo

# The hook derives REPO_ROOT from its own location, so absolute-path cases must be
# built from the same root to be meaningful.
REPO_ROOT=$(cd "$(dirname "$HOOK")/../.." && pwd)

run() { # run <BLOCK|ALLOW> <agent_type> <file_path>
  local expect="$1" agent="$2" path="$3" rc
  jq -n --arg a "$agent" --arg p "$path" \
    '{agent_type:$a,tool_name:"Write",tool_input:{file_path:$p,content:"x"}}' \
    | bash "$HOOK" >/dev/null 2>&1
  rc=$?
  _record "$expect" "$(_classify "$rc")" "$agent -> $path"
}

run_raw() { # run_raw <BLOCK|ALLOW> <label> <raw-json>
  local expect="$1" label="$2" payload="$3" rc
  printf '%s' "$payload" | bash "$HOOK" >/dev/null 2>&1
  rc=$?
  _record "$expect" "$(_classify "$rc")" "$label"
}

echo "--- read-only roles writing tracked source: must BLOCK ---"
run BLOCK researcher "src/mail/cli.py"
run BLOCK researcher "tests/mail_tests/test_cli.py"
run BLOCK researcher "bin/mail-assistant"
run BLOCK researcher "workflows/code/open-pr.yaml"
run BLOCK researcher ".claude/agents/researcher.md"
run BLOCK researcher ".github/workflows/ci.yml"
run BLOCK researcher "concerns/workflow-stages.md"
run BLOCK Plan "src/workflow/models.py"
run BLOCK reviewer "src/core/paths.py"
run BLOCK critic "tests/conftest.py"
run BLOCK fact-checker "src/telemetry/cli.py"
run BLOCK unit-validator "src/mail/meta.py"
run BLOCK cross-unit-validator "src/mail/meta.py"
run BLOCK haiku-reviewer "src/mail/meta.py"
run BLOCK Explore "src/mail/meta.py"

echo
echo "--- the round-3 case: caller NAMES a source path as an output ---"
# A prompt naming src/foo.py as a stage artifact is misconfigured, not authorization.
# This is the case three rounds of prose failed to close.
run BLOCK researcher "src/workflow/linter.py"
run BLOCK Plan "bin/workflow"

echo
echo "--- repo-root configuration files: must BLOCK ---"
run BLOCK researcher "Makefile"
run BLOCK researcher "pyproject.toml"
run BLOCK researcher "typecheck-baseline.json"
run BLOCK researcher "CLAUDE.md"
run BLOCK Plan ".coveragerc"

echo
echo "--- read-only roles writing run artifacts: must ALLOW ---"
# This is the capability PR #392 existed to grant. If these block, the hook has
# re-broken the 70 stages that PR unblocked.
run ALLOW researcher "/tmp/run-workspace/analysis/findings.json"
run ALLOW researcher "/private/tmp/claude-501/scratchpad/probe.json"
run ALLOW Plan "/tmp/ws/design/plan.md"
run ALLOW Plan "/tmp/ws/design/work-packages.json"
run ALLOW researcher "out/report.json"
run ALLOW researcher "analysis/domain-inventory.json"

echo
echo "--- retry case: the artifact already exists, must still ALLOW ---"
# Round 2 of #392: a re-run stage meets its own partial output. Existence must not
# be part of the test, or every retry stalls.
ARTIFACT="$(mktemp -d)/existing-output.json"
printf '{"partial":true}' > "$ARTIFACT"
run ALLOW researcher "$ARTIFACT"
rm -rf "$(dirname "$ARTIFACT")"

echo
echo "--- write-capable roles: must ALLOW even into source ---"
# These roles exist to modify source. Blocking them would break every code stage.
run ALLOW code-writer "src/mail/cli.py"
run ALLOW code-writer-opus "src/mail/cli.py"
run ALLOW tester "tests/mail_tests/test_cli.py"
run ALLOW tester-opus "tests/mail_tests/test_cli.py"
run ALLOW ci-fixer "src/workflow/runner.py"
run ALLOW doc-writer "README.md"
run ALLOW thread-fixer "src/mail/cli.py"
run ALLOW workflow-author "workflows/code/open-pr.yaml"

echo
echo "--- main session (no agent_type): must ALLOW ---"
# The user driving the session directly is not a read-only-contract agent. Blocking
# here would make the repo unusable.
run_raw ALLOW "no agent_type key at all" \
  '{"tool_name":"Write","tool_input":{"file_path":"src/mail/cli.py","content":"x"}}'
run_raw ALLOW "agent_type null" \
  '{"agent_type":null,"tool_name":"Write","tool_input":{"file_path":"src/mail/cli.py","content":"x"}}'
run_raw ALLOW "agent_type empty string" \
  '{"agent_type":"","tool_name":"Write","tool_input":{"file_path":"src/mail/cli.py","content":"x"}}'

echo
echo "--- absolute paths inside the repo: judged like their relative spelling ---"
# `src/mail/cli.py` and `<repo>/src/mail/cli.py` are the same write. A guard that
# answers differently for the two spellings protects nothing.
run BLOCK researcher "$REPO_ROOT/src/mail/cli.py"
run BLOCK researcher "$REPO_ROOT/tests/test_x.py"
run ALLOW code-writer "$REPO_ROOT/src/mail/cli.py"
run BLOCK researcher "./src/mail/cli.py"

echo
echo "--- absolute paths outside the repo: ALLOW (not this repo's source) ---"
run ALLOW researcher "/tmp/somewhere/else.json"
run ALLOW researcher "/var/folders/xy/T/tmpabc/out.json"

echo
echo "--- '..' traversal back into source: must BLOCK ---"
# outputs/../src/mail/cli.py has no src/ prefix as written but resolves into src/.
run BLOCK researcher "outputs/../src/mail/cli.py"
run BLOCK researcher "analysis/../../src/core/paths.py"
run BLOCK Plan "design/../bin/workflow"

echo
echo "--- malformed payloads: must fail CLOSED ---"
# A hook that cannot read its input does not know what it is approving.
run_raw BLOCK "not JSON at all" 'this is not json'
run_raw BLOCK "empty input" ''
run_raw BLOCK "agent_type is an object" \
  '{"agent_type":{},"tool_name":"Write","tool_input":{"file_path":"src/x.py","content":"x"}}'
run_raw BLOCK "agent_type is an array" \
  '{"agent_type":[],"tool_name":"Write","tool_input":{"file_path":"src/x.py","content":"x"}}'
run_raw BLOCK "agent_type is a number" \
  '{"agent_type":7,"tool_name":"Write","tool_input":{"file_path":"src/x.py","content":"x"}}'
run_raw BLOCK "read-only role, file_path missing" \
  '{"agent_type":"researcher","tool_name":"Write","tool_input":{"content":"x"}}'
run_raw BLOCK "read-only role, file_path null" \
  '{"agent_type":"researcher","tool_name":"Write","tool_input":{"file_path":null,"content":"x"}}'
run_raw BLOCK "read-only role, file_path is an object" \
  '{"agent_type":"researcher","tool_name":"Write","tool_input":{"file_path":{},"content":"x"}}'
run_raw BLOCK "read-only role, file_path empty" \
  '{"agent_type":"researcher","tool_name":"Write","tool_input":{"file_path":"","content":"x"}}'
run_raw BLOCK "read-only role, file_path whitespace only" \
  '{"agent_type":"researcher","tool_name":"Write","tool_input":{"file_path":"   ","content":"x"}}'

echo
echo "--- unknown role: treated as write-capable, ALLOW ---"
# A role this hook has never heard of is not assumed read-only. The READONLY_ROLES
# list is the allowlist-of-restriction; guessing would block legitimate new roles.
run ALLOW some-future-role "src/mail/cli.py"

_summary "block-readonly-role-writes"
