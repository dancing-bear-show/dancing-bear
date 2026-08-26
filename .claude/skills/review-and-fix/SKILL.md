---
name: review-and-fix
description: Run adversarial swarm review then auto-fix all findings in parallel. Use when the user says "review and fix", "swarm fix", or wants review and fix in one shot.
allowed-tools: Task, TaskOutput, Bash, Read, Write, Edit, Glob, Grep, TeamCreate, TeamDelete, SendMessage, TaskCreate, TaskUpdate, TaskList, TaskGet, Agent, Skill
skills:
  - dancing-bear-rules
---

# Review and Fix

Delegates to `workflows/code/review-and-fix.yaml`. Phase 1 runs the adversarial swarm review
(diff fetch, concern sweep, per-file validation, consolidation, fact-check, human gate,
inline comment posting). Phase 2 triages findings by fix type, fans out code, test, and
qlty fixes in parallel, verifies everything is green, resolves posted threads, and
presents a summary for final approval.

## When to Use

- User says "review and fix", "swarm fix", or "review then auto-fix"
- One-shot review + remediation before merge
- Existing review findings need automated fixing (set `skip_review: "true"`)

## Derive Params from Context

```bash
# Detect PR number from current branch
GITHUB_TOKEN= gh pr view --json number -q .number
```

If the command returns a number, use it. If the branch has no open PR, ask the user.

## Invocation

**IMPORTANT**: Use the `/workflow` skill — do NOT call `./bin/workflow run --execute` directly. It only writes dispatch files and exits (status=pending). The `/workflow` skill is what actually spawns agents, waits for results, and handles human gates.

```python
Skill(skill="workflow", args="--workflow workflows/code/review-and-fix.yaml --params pr_number=314 test_cmd='python3 -m unittest tests/grafana/ -f -q' source_root=grafana/ test_path=tests/grafana/")
```

Skip Phase 1 if review already ran and findings are in `/tmp/review-and-fix-{pr_number}/outputs/`:

```python
Skill(skill="workflow", args="--workflow workflows/code/review-and-fix.yaml --params pr_number=314 skip_review=true")
```

## Params

| Param | Default | Description |
|-------|---------|-------------|
| `pr_number` | `""` | PR number (required; auto-detected from branch if blank) |
| `test_cmd` | `""` | e.g. `python3 -m unittest tests/grafana/ -f -q` |
| `source_root` | `""` | e.g. `grafana/` |
| `test_path` | `""` | e.g. `tests/grafana/` |
| `min_coverage` | `"80"` | Coverage threshold (percent, no % sign) |
| `auth_domains` | `"github,qlty"` | Auth domains to pre-check |
| `skip_review` | `"false"` | Set `"true"` to jump straight to Phase 2 |

## Workflow Stages

**Phase 1 — Review**

1. **init** — create workspace directories (`outputs/`, `outputs/diffs/`, `outputs/findings/`, `validation/`)
2. **fetch-pr-context** — PR metadata, per-file diffs, commit history, PR description
3. **concern-sweep** — load domain guides, filter to concerns triggered by this diff
4. **enumerate-targets** — cross-reference concerns with per-file diffs; produce manifest
5. **validate-concerns** (parallel fan-out) — one agent per manifest entry; write per-finding JSON
6. **cross-unit-check** (parallel with validate-concerns) — cross-file consistency check
7. **consolidate** — merge, de-duplicate, and sort findings; write `consolidated.json` + summary
8. **fact-check-findings** — verify line numbers, evidence quotes, and severity against guide files
9. **human-gate** — present findings; user approves, edits, or discards
10. **post-comments** — post approved findings as inline GitHub PR review comments

**Phase 2 — Fix**

11. **triage-findings** — group findings into code/test/docs/qlty buckets; fetch SQ issues; write `fix-manifest.json`
12. **fix-code** (worker_queue, parallel) — fix logic bugs and style issues in source files; run ruff after each
13. **fix-tests** (worker_queue, parallel with fix-code) — add missing tests, strengthen weak assertions; run python3 -m unittest per fix
14. **fix-qlty** (parallel with fix-code and fix-tests) — fix new-code SQ issues; verify gate after
15. **verify-fixes** — run ruff, test suite, and SQ gate; confirm all green
16. **resolve-threads** — resolve GitHub threads for findings that were fixed
17. **human-gate-fixes** — present fix summary; user approves for merge or requests another round
