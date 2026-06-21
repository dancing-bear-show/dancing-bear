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

- User pastes a Semaphore URL
- User says "CI is failing" or "fix CI"
- After a push when CI goes red
- As Phase 4 of `/review-fix`

## How to Run

**IMPORTANT**: Use the `/workflow` skill — do NOT call `./bin/workflow run --execute` directly. It only writes dispatch files and exits (status=pending). The `/workflow` skill is what actually spawns agents, waits for results, and handles human gates.

```python
# From a Semaphore URL
Skill(skill="workflow", args="--workflow workflows/code/ci-debug.yaml --params github-actions_url=<SEMAPHORE_URL> test_cmd='python3 -m unittest tests/<domain>/ -x -q' source_root='<domain>/'")

# From a PR number
Skill(skill="workflow", args="--workflow workflows/code/ci-debug.yaml --params pr_number=<PR_NUMBER> test_cmd='python3 -m unittest tests/<domain>/ -x -q' source_root='<domain>/'")

# Both (Semaphore URL for logs + qlty PR-scoped check)
Skill(skill="workflow", args="--workflow workflows/code/ci-debug.yaml --params github-actions_url=<SEMAPHORE_URL> pr_number=<PR_NUMBER> test_cmd='python3 -m unittest tests/<domain>/ -x -q' source_root='<domain>/'")
```

At least one of `github-actions_url` or `pr_number` must be provided.

## Workflow Params

| Param | Default | Description |
|-------|---------|-------------|
| `github-actions_url` | `""` | Semaphore pipeline URL (optional if pr_number given) |
| `pr_number` | `""` | PR number to check (optional if github-actions_url given) |
| `test_cmd` | `""` | Pytest invocation for local verify (e.g. `python3 -m unittest tests/core/ -x -q`) |
| `source_root` | `""` | Source dir for coverage scoping (e.g. `core/`) |
| `min_coverage` | `"80"` | Minimum new coverage % required by qlty gate |

## Workflow Stages

1. **fetch-failures** — fetch Semaphore failure logs and qlty gate status in parallel.
   Uses `./bin/github-actions fail-summary --pipeline-id <ID> --show-logs` for a structured table
   of failed jobs. For full logs of a specific job, `./bin/github-actions log-tail <JOB_ID>` tails
   the last N lines.
2. **diagnose** — parse raw output, extract structured failure records, write findings.json
3. **fix** — apply targeted fixes for each failure; spawn ci-fixer agent for complex multi-file cases
4. **verify** — run the specific previously-failing tests to confirm each fix landed
5. **recheck** — run the full domain test suite and re-check qlty for regressions
6. **human-gate** — present structured report (N failures found, root cause, fix applied, verification result)
7. **sq-check-qlty** — qlty quality gate fix loop (from shared fragment)
8. **sq-verify-qlty** — final qlty confirmation (from shared fragment)
