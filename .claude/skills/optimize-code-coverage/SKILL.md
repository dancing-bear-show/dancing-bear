---
name: optimize-code-coverage
description: Test quality and coverage verification. Checks test structure, helper reuse (fixtures/factories), parametrization, assertions, and coverage gaps. Use after writing tests to ensure quality and coverage targets are met (80%+ on new code).
allowed-tools: Bash, Read, Edit, Write, Glob, Grep, Agent, Skill
skills:
  - dancing-bear-rules
---

# Optimize Code — Coverage Pass

Delegates to `workflows/code/optimize-code.yaml` with `skip_checks=reuse,complexity,security,arch`,
running only the coverage scan dimension. Findings are applied and rechecked automatically.

## When to Use

- After writing tests for new functionality
- Pre-PR test quality gate
- When coverage is below 80% on new code
- User says "check test quality", "verify coverage", or "improve test coverage"

## How to Run

Bootstrap `source_root` and `test_path` from context:
- `source_root`: the `<domain>/` directory of the files you just wrote or changed
- `test_path`: the corresponding `tests/<domain>/` directory
- `pr_number`: optional — if you have an open PR, pass it to scope file detection to that PR's diff

**IMPORTANT**: Use the `/workflow` skill — do NOT call `./bin/workflow run --execute` directly. It only writes dispatch files and exits (status=pending). The `/workflow` skill is what actually spawns agents, waits for results, and handles human gates.

```python
Skill(skill="workflow", args="--workflow workflows/code/optimize-code.yaml --params source_root=<domain>/ --params test_path=tests/<domain>/ --params skip_checks=reuse,complexity,security,arch")
```

With a PR number:

```python
Skill(skill="workflow", args="--workflow workflows/code/optimize-code.yaml --params pr_number=314 --params source_root=<domain>/ --params test_path=tests/<domain>/ --params skip_checks=reuse,complexity,security,arch")
```

## What Runs

Focuses on the coverage scan dimension — other dimensions can be added via skip_checks.
The workflow runs the full correction and recheck cycle:

1. **pre-check-auth** — verify GitHub and qlty connections
2. **scan-changed-files** — identify .py files changed vs main (or PR diff)
3. **mps-scan-coverage** — test gap detection, coverage %, CI block coverage check
4. **mps-collate-findings** — collate coverage findings into unified report
5. **apply-corrections** — fix all critical + auto-fixable minor coverage findings
6. **recheck-lint** — `ruff check` + `pytest` to confirm fixes
7. **human-gate** — present coverage summary, ask to commit/open PR

## Workflow Params

| Param | Default | Description |
|-------|---------|-------------|
| `source_root` | `""` | Path prefix for changed source files, e.g. `workflow/` |
| `test_path` | `""` | Test directory to run, e.g. `tests/workflow/` |
| `pr_number` | `""` | Optional PR number — scopes file detection to that PR's diff |
| `skip_checks` | `reuse,complexity,security,arch` | Passed automatically — controls which scan dimensions run |
| `auth_domains` | `"github,qlty"` | Comma-separated auth pre-flight services |
