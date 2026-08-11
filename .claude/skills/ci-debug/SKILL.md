---
name: ci-debug
description: Diagnose and fix GitHub Actions CI failures. Given a URL, PR number, or "CI is failing", parses logs, identifies root cause, fixes locally, and verifies. Use when CI is red and you need to get it green.
allowed-tools: Bash, Read, Edit, Write, Glob, Grep, Task, Agent, Skill
skills:
  - dancing-bear-rules
---

# CI Debug

Delegates to `workflows/code/ci-debug.yaml`.

## When to Use

- User pastes a GitHub Actions run URL
- User says "CI is failing" or "fix CI"
- After a push when CI goes red
- As Phase 4 of `/review-fix`

## How to Run

**IMPORTANT**: Use the `/workflow` skill — do NOT call `./bin/workflow run --execute` directly. It only writes dispatch files and exits (status=pending). The `/workflow` skill is what actually spawns agents, waits for results, and handles human gates.

```python
# From a GitHub Actions run URL
Skill(skill="workflow", args="--workflow workflows/code/ci-debug.yaml --params github-actions_url=<RUN_URL> test_cmd='python3 -m unittest tests/<domain>/ -x -q' source_root='<domain>/'")

# From a PR number
Skill(skill="workflow", args="--workflow workflows/code/ci-debug.yaml --params pr_number=<PR_NUMBER> test_cmd='python3 -m unittest tests/<domain>/ -x -q' source_root='<domain>/'")

# Both (run URL for logs + qlty PR-scoped check)
Skill(skill="workflow", args="--workflow workflows/code/ci-debug.yaml --params github-actions_url=<RUN_URL> pr_number=<PR_NUMBER> test_cmd='python3 -m unittest tests/<domain>/ -x -q' source_root='<domain>/'")
```

At least one of `github-actions_url` or `pr_number` must be provided.

## Workflow Params

| Param | Default | Description |
|-------|---------|-------------|
| `github-actions_url` | `""` | GitHub Actions run URL (optional if pr_number given) |
| `pr_number` | `""` | PR number to check (optional if github-actions_url given) |
| `test_cmd` | `""` | Test invocation for local verify (e.g. `python3 -m unittest tests/core/ -x -q`) |
| `source_root` | `""` | Source dir for coverage scoping (e.g. `core/`) |
| `min_coverage` | `"80"` | Minimum new coverage % required by qlty gate |

## Workflow Stages

1. **fetch-failures** — fetch GitHub Actions failure logs and qlty gate status in parallel.
   Uses `gh run view <RUN_ID> --log-failed` for the failing job output and
   `gh pr checks <PR> --json name,state,detailsUrl` to resolve which run to inspect.
2. **diagnose** — parse raw output, extract structured failure records, write findings.json
3. **fix** — apply targeted fixes for each failure; spawn ci-fixer agent for complex multi-file cases
4. **verify** — run the specific previously-failing tests to confirm each fix landed
5. **recheck** — run the full domain test suite and re-check qlty for regressions
6. **human-gate** — present structured report (N failures found, root cause, fix applied, verification result)
7. **sq-check-qlty** — qlty quality gate fix loop (from shared fragment)
8. **sq-verify-qlty** — final qlty confirmation (from shared fragment)
