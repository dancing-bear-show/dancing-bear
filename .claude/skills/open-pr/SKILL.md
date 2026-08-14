---
name: open-pr
description: Comprehensive pre-PR validation and pull request creation. Runs type checking (mypy), linting (qlty), tests, coverage validation, generates PR description from template, and creates the PR. Use when ready to open a PR for review.
allowed-tools: Bash, Read, Glob, Grep, Write, Task, Agent, Skill
skills:
  - dancing-bear-rules
---

# Open PR

Delegates to `workflows/code/open-pr.yaml` via the `/workflow` skill.

## When to Use

- User says "create PR", "open PR", "/open-pr", or similar
- After completing work on a feature branch
- Runs 6-stage comprehensive validation before PR creation

## How to Run

Derive the params from context before invoking:
- `pr_title`: use the conventional-commit format — read recent commits with `git log origin/main..HEAD --oneline` to determine type and scope
- `test_cmd`: check the project's test runner — use `python3 -m unittest discover -s tests/<domain>/ -t . -q` scoped to the changed domain
- `source_root`: the source directory being changed, e.g. `mail/`
- `test_path`: the corresponding test directory, e.g. `tests/mail_tests/`
- `min_coverage`: default `80` unless the project specifies otherwise
- `auth_domains`: default `github,qlty`

**IMPORTANT**: Use the `/workflow` skill — do NOT call `./bin/workflow run --execute` directly.
`./bin/workflow run --execute` only writes dispatch files and exits immediately (status=pending).
The `/workflow` skill is what actually spawns agents, waits for results, and handles human gates.

```python
Skill(skill="workflow", args="--workflow workflows/code/open-pr.yaml --params pr_title=<VALUE> --params test_cmd=<VALUE> --params source_root=<VALUE> --params test_path=<VALUE> --params min_coverage=80 --params auth_domains=github,qlty")
```

## Workflow Params

| Param | Default | Description |
|-------|---------|-------------|
| pr_title | "" | Required: conventional-commit title e.g. "feat(mail): add label sync" |
| test_cmd | "" | Test suite command e.g. "python3 -m unittest discover -s tests/mail_tests/ -t . -q" |
| source_root | "" | Source root for mypy + qlty scoping e.g. "mail/" |
| test_path | "" | Test directory path e.g. "tests/mail_tests/" |
| min_coverage | "80" | Minimum coverage threshold (percent) |
| auth_domains | "github,qlty" | Comma-separated services for pre-flight auth check |

## Workflow Stages

1. **check-auth** — verify github and qlty credentials before any work begins
2. **scan-validate** — run mypy, qlty lint, and coverage gate; fix issues in-loop
3. **generate-description** — gather diff + commit metadata and write PR description
4. **human-gate** — present generated description for human review and confirmation
5. **push-and-create** — push branch and create PR via `gh pr create`
6. **fact-check** — validate PR description claims against actual diff; report discrepancies
