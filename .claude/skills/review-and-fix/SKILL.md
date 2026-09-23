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
3. **concern-sweep-dispatch** — pick the domain guides this diff triggers; write the sweep fan-out index
4. **concern-sweep** (parallel fan-out, one agent per guide) — filter each guide to the concerns this diff triggers
5. **review-consolidated** — single-pass review for `pr_size: small`; always skipped here, since this workflow sets `pr_size: large`
6. **concern-sweep-merge** — merge the per-guide sweep results
7. **enumerate-targets** — cross-reference concerns with per-file diffs; produce manifest
8. **validate-concerns** (parallel fan-out) — one agent per manifest entry; write per-finding JSON
9. **cross-unit-check** (parallel with validate-concerns) — cross-file consistency check
10. **consolidate** — merge, de-duplicate, and sort findings; write `consolidated.json` + summary
11. **fact-check-findings** — verify line numbers, evidence quotes, and severity against guide files
12. **human-gate** — present findings; user approves, edits, or discards
13. **post-comments** — post approved findings as inline GitHub PR review comments

**Phase 2 — Fix**

14. **triage-findings** — group findings into code/test/docs/qlty buckets; fetch SQ issues; write `fix-manifest.json`
15. **fix-code** (isolated worktree, parallel) — fix logic bugs and style issues in source files; run ruff after each
16. **fix-tests** (isolated worktree, parallel with fix-code) — add missing tests, strengthen weak assertions
17. **fix-qlty** (isolated worktree, parallel with fix-code and fix-tests) — fix new-code qlty issues; verify gate after
18. **merge-fix-worktrees** — merge the three isolated fix branches back; `verify-fixes` refuses to run on an incomplete merge
19. **verify-fixes** (`kind: execute`) — run ruff, test suite, and qlty gate; write `verify-results.json` with `all_green`
20. **plan-thread-resolution** — gate on `all_green`, map fixed findings to their threads; write `resolve-plan.json`
21. **resolve-threads** (shared fragment) — reply into each thread, then resolve only the verified ones
22. **human-gate-fixes** — present the resolution outcome (including any `forged_marker`); user approves for merge or requests another round

Steps 20–21 were one stage until the reply-and-resolve logic was extracted to
`workflows/shared/pr-thread-resolve.yaml`. The split matters: this workflow
used to resolve threads without replying to them at all, closing a reviewer's
concern with no explanation of what changed.
