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

run_bash() { # run_bash <BLOCK|ALLOW> <agent_type> <command>
  local expect="$1" agent="$2" cmd="$3" rc
  jq -n --arg a "$agent" --arg c "$cmd" \
    '{agent_type:$a,tool_name:"Bash",tool_input:{command:$c}}' \
    | bash "$HOOK" >/dev/null 2>&1
  rc=$?
  _record "$expect" "$(_classify "$rc")" "bash[$agent]: $cmd"
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

echo
echo "--- Bash routes into tracked source: must BLOCK ---"
# The Write-only version of this hook was trivially bypassable: every one of these
# reached the shell untouched, because `researcher` and `Plan` both still have Bash.
# Review caught it; these are the negative tests that pin the fix.
run_bash BLOCK researcher "echo 'x = 1' > src/mail/cli.py"
run_bash BLOCK researcher "echo 'x = 1' >> src/mail/cli.py"
run_bash BLOCK researcher "sed -i '' 's/foo/bar/' src/mail/cli.py"
run_bash BLOCK researcher "printf 'x' > tests/workflow_tests/test_linter.py"
run_bash BLOCK researcher "cp /tmp/evil.py src/mail/cli.py"
run_bash BLOCK researcher "tee src/mail/cli.py < /tmp/evil.py"
run_bash BLOCK researcher "cat /tmp/x > bin/mail-assistant"
run_bash BLOCK Plan "sed -i '' 's/a/b/' workflows/code/open-pr.yaml"
run_bash BLOCK reviewer "rm src/core/paths.py"
run_bash BLOCK researcher "mv /tmp/x .claude/agents/researcher.md"
run_bash BLOCK researcher "touch concerns/new-concern.md"
# A qualified or escaped spelling of a listed mutator is matched on its basename.
run_bash BLOCK researcher "/bin/sed -i '' 's/a/b/' src/mail/cli.py"
# A later segment is judged on its own command word -- a harmless first half must not
# vouch for a mutating second half.
run_bash BLOCK researcher "cat README.md && sed -i '' 's/a/b/' src/mail/cli.py"
# Repo-root config files are guarded the same way.
run_bash BLOCK researcher "echo x > Makefile"
run_bash BLOCK researcher "echo x > typecheck-baseline.json"
# '..' traversal back into source.
run_bash BLOCK researcher "echo x > outputs/../src/mail/cli.py"
# Absolute in-repo spelling must be judged like the relative one.
run_bash BLOCK researcher "echo x > $REPO_ROOT/src/mail/cli.py"

echo
echo "--- Bash that must still be ALLOWED ---"
# A guard that blocks ordinary work is as broken as one that blocks nothing. Reading
# source is the researcher's whole job, so reads must survive.
run_bash ALLOW researcher "cat src/mail/cli.py"
run_bash ALLOW researcher "grep -rn 'AppMeta' src/"
run_bash ALLOW researcher "rg --files src/"
run_bash ALLOW researcher "make test"
run_bash ALLOW researcher "./bin/workflow list"
run_bash ALLOW researcher "git status"
run_bash ALLOW researcher "git diff --name-only main...HEAD"
run_bash ALLOW researcher "python3 -m unittest tests.workflow_tests.test_linter"
run_bash ALLOW researcher "echo '{}' > /tmp/ws/analysis/findings.json"
run_bash ALLOW researcher "echo '{}' > analysis/findings.json"
run_bash ALLOW Plan "echo '# plan' > /tmp/ws/design/plan.md"
# Write-capable roles are untouched on the Bash path too.
run_bash ALLOW code-writer "echo 'x = 1' > src/mail/cli.py"
run_bash ALLOW tester "sed -i '' 's/a/b/' tests/test_x.py"
run_bash ALLOW ci-fixer "echo x > src/workflow/runner.py"
# Main session: no agent_type, never restricted.
run_raw ALLOW "main session bash into src/" \
  '{"tool_name":"Bash","tool_input":{"command":"echo x > src/mail/cli.py"}}'

echo
echo "--- Bash malformed payloads: must fail CLOSED ---"
run_raw BLOCK "researcher bash, command missing" \
  '{"agent_type":"researcher","tool_name":"Bash","tool_input":{}}'
run_raw BLOCK "researcher bash, command null" \
  '{"agent_type":"researcher","tool_name":"Bash","tool_input":{"command":null}}'
run_raw BLOCK "researcher bash, command is an object" \
  '{"agent_type":"researcher","tool_name":"Bash","tool_input":{"command":{}}}'
run_raw BLOCK "researcher bash, command empty" \
  '{"agent_type":"researcher","tool_name":"Bash","tool_input":{"command":""}}'
run_raw BLOCK "researcher bash, command whitespace only" \
  '{"agent_type":"researcher","tool_name":"Bash","tool_input":{"command":"   "}}'

echo
echo "--- the bare directory token itself: must BLOCK ---"
# `rm -rf src/` was blocked while `rm -rf src` was allowed -- one character between
# refusal and deleting the tree. The prefix test matched "src/" only, so the token
# that names the directory never matched. Both spellings are pinned for every tree.
for d in src tests bin config configs workflows .claude .github .qlty concerns docs .llm; do
  run_bash BLOCK researcher "rm -rf $d"
  run_bash BLOCK researcher "rm -rf $d/"
done
run_bash BLOCK researcher "mv src /tmp/elsewhere"
run_bash BLOCK researcher "mv tests /tmp/elsewhere"
run_bash BLOCK Plan "rm -rf workflows"
run BLOCK researcher "src"
run BLOCK researcher "tests"
# A directory whose NAME merely starts with a guarded name is not that directory.
run_bash ALLOW researcher "rm -rf srcfoo"
run_bash ALLOW researcher "rm -rf /tmp/src"
run ALLOW researcher "/tmp/src/out.json"

echo
echo "--- tracked configuration trees: must BLOCK ---"
# Both confirmed tracked with `git ls-files`: config/filters_unified.example.yaml and
# .qlty/qlty.toml. Only `configs/` was listed, so a read-only role could rewrite the
# lint configuration that judges its own branch.
run BLOCK researcher "config/filters_unified.example.yaml"
run BLOCK researcher ".qlty/qlty.toml"
run_bash BLOCK researcher "echo x > config/filters_unified.example.yaml"
run_bash BLOCK researcher "sed -i '' 's/a/b/' .qlty/qlty.toml"
run BLOCK Plan "configs/launchd.plist"

echo
echo "--- the >& redirect form: must BLOCK ---"
# `echo x >&src/mail/cli.py` left the token as `&src/mail/cli.py` under the generic
# `>` normalisation, so nothing classified the path. `>&` is now rewritten first.
run_bash BLOCK researcher "echo x >&src/mail/cli.py"
run_bash BLOCK researcher "echo x >& src/mail/cli.py"
run_bash BLOCK researcher "echo x >&tests/test_x.py"
# The fd-duplication spellings are digits, not paths, and must stay allowed.
run_bash ALLOW researcher "make test >&1"
run_bash ALLOW researcher "./bin/workflow list 2>&1"
run_bash ALLOW researcher "grep -rn AppMeta src/ 2>&1 | head"

echo
echo "--- './' segments must not defeat the prefix test: must BLOCK ---"
# `a/./b` and `a/b` name the same file, but every guarded-prefix test is textual, so
# one inserted `/./` was enough to walk past all of them -- on Write AND on a redirect.
# The collapse loops in the hook are what these pin.
run BLOCK researcher "$REPO_ROOT/./src/mail/cli.py"
run BLOCK researcher "$REPO_ROOT/././src/mail/cli.py"
run BLOCK researcher "$REPO_ROOT/./tests/test_x.py"
run BLOCK researcher "./src/mail/cli.py"
run BLOCK researcher "././src/mail/cli.py"
run BLOCK researcher "./././bin/mail-assistant"
run_bash BLOCK researcher "echo x > $REPO_ROOT/./src/mail/cli.py"
run_bash BLOCK researcher "echo x > ././src/mail/cli.py"
run_bash BLOCK researcher "sed -i '' 's/a/b/' ./src/mail/cli.py"
# The bare-directory arm must survive the collapse too.
run_bash BLOCK researcher "rm -rf ./src"
run_bash BLOCK researcher "rm -rf $REPO_ROOT/./src"
# A './' path that is NOT guarded still has to be allowed -- the collapse must not
# turn every relative path into a refusal.
run ALLOW researcher "./analysis/findings.json"
run ALLOW researcher "././outputs/report.json"

echo
echo "--- every repo-root file, not a hand-maintained subset: must BLOCK ---"
# ROOT_CONFIG_FILES listed 11 names while `git ls-files` reports 20 at the root, so
# nine were writable -- including AGENTS.md, COPILOT.md and GEMINI.md. Rewriting those
# changes the instructions LATER agents consume, a more durable compromise than
# editing one source file. Now derived from the path shape, so it cannot drift.
for f in AGENTS.md COPILOT.md GEMINI.md CONTRIBUTING.md SECURITY.md LICENSE \
         GETTING_STARTED.md .python-version requirements-dev.txt \
         credentials.example.json docker-compose.otel.yaml \
         Makefile pyproject.toml CLAUDE.md README.md typecheck-baseline.json \
         .coveragerc .bandit .envrc .gitignore; do
  run BLOCK researcher "$f"
done
run_bash BLOCK researcher "echo x > AGENTS.md"
run_bash BLOCK researcher "sed -i '' 's/a/b/' CLAUDE.md"
# A file that only LOOKS root-level because it is outside the repo stays allowed.
run ALLOW researcher "/tmp/AGENTS.md"
run ALLOW researcher "analysis/AGENTS.md"

echo
echo "--- repeated separators must not defeat the prefix test: must BLOCK ---"
# `<repo>//src/mail/cli.py` left rel=/src/mail/cli.py after the REPO_ROOT prefix came
# off -- a leading slash matching no guarded prefix. Same class as the `/./` bug, one
# variant over.
run BLOCK researcher "$REPO_ROOT//src/mail/cli.py"
run BLOCK researcher "src//mail/cli.py"
run BLOCK researcher "$REPO_ROOT//.//src//mail/cli.py"
run BLOCK researcher "tests//workflow_tests//test_linter.py"
run_bash BLOCK researcher "echo x > $REPO_ROOT//src/mail/cli.py"
run_bash BLOCK researcher "rm -rf src//"
run ALLOW researcher "/tmp//out.json"

echo
echo "--- reads through mutating commands must be ALLOWED ---"
# Treating every operand of cp/sed/dd/ln as a write target contradicted the
# write-target-only design and blocked ordinary work: `cp src/x /tmp/y` is a normal
# way to produce an artifact, and `sed -n` prints without writing.
run_bash ALLOW researcher "cp src/mail/cli.py /tmp/copy.py"
run_bash ALLOW researcher "cp src/mail/cli.py src/core/paths.py /tmp/"
run_bash ALLOW researcher "sed -n '1,5p' src/mail/cli.py"
run_bash ALLOW researcher "sed 's/a/b/' src/mail/cli.py"
run_bash ALLOW researcher "dd if=src/mail/cli.py of=/tmp/out.bin"
run_bash ALLOW researcher "ln -s src/mail/cli.py /tmp/link.py"

echo
echo "--- ...while the write forms of those same commands still BLOCK ---"
run_bash BLOCK researcher "cp /tmp/x.py src/mail/cli.py"
run_bash BLOCK researcher "cp /tmp/a.py /tmp/b.py src/"
run_bash BLOCK researcher "sed -i '' 's/a/b/' src/mail/cli.py"
run_bash BLOCK researcher "sed --in-place 's/a/b/' src/mail/cli.py"
run_bash BLOCK researcher "dd if=/tmp/x of=src/mail/cli.py"
run_bash BLOCK researcher "ln -s /tmp/x src/mail/cli.py"
run_bash BLOCK researcher "mv /tmp/x.py src/mail/cli.py"
run_bash BLOCK researcher "touch src/newfile.py"
run_bash BLOCK researcher "tee src/mail/cli.py < /tmp/x"

echo
echo "--- KNOWN GAPS: documented, not fixed (see the SCOPE note in the hook) ---"
# These are ALLOWed by design. A string matcher cannot evaluate what the shell will do
# to the string, and block-destructive-bash.sh's header records four adversarial rounds
# and 68 findings establishing that widening the matcher does not converge.
#
# They are asserted rather than omitted so the gap is visible and a future change that
# closes one of them shows up as a failing expectation to update -- not as a silent
# improvement nobody noticed, and not as a hole nobody wrote down.
run_bash ALLOW researcher "P=src/mail/cli.py; echo x > \$P"
run_bash ALLOW researcher "python3 -c \"open('src/mail/cli.py','w').write('x')\""
run_bash ALLOW researcher "echo x > src\${IFS}/mail/cli.py"
# A mutating tool that is not in the command-word list. The list can never be
# complete -- that is the reason the SCOPE note calls the Bash branch weak, and the
# reason the strong guarantee is claimed only for Write/Edit.
run_bash ALLOW researcher "some-unknown-tool --out src/mail/cli.py"

_summary "block-readonly-role-writes"
