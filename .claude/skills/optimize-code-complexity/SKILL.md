---
name: optimize-code-complexity
description: Cognitive complexity refactoring. Identifies functions exceeding complexity thresholds and applies refactoring patterns (dispatch tables, helper extraction, early returns). Use to improve code readability and maintainability.
allowed-tools: Bash, Read, Edit, Write, Glob, Grep, Agent, Skill
skills:
  - dancing-bear-rules
---

# Optimize Code — Complexity Pass

Delegates to `workflows/code/optimize-code.yaml` with `skip_checks=reuse,coverage,security,arch`,
running only the complexity scan dimension. Findings are applied and rechecked automatically.

## When to Use

- After implementing complex logic
- When functions exceed complexity grade C (complexity > 10)
- Pre-PR simplification check
- User says "simplify", "reduce complexity", or "improve readability"

## How to Run

Bootstrap `source_root` and `test_path` from context:
- `source_root`: the `<domain>/` directory of the files you just wrote or changed
- `test_path`: the corresponding `tests/<domain>/` directory
- `pr_number`: optional — if you have an open PR, pass it to scope file detection to that PR's diff

**IMPORTANT**: Use the `/workflow` skill — do NOT call `./bin/workflow run --execute` directly. It only writes dispatch files and exits (status=pending). The `/workflow` skill is what actually spawns agents, waits for results, and handles human gates.

```python
Skill(skill="workflow", args="--workflow workflows/code/optimize-code.yaml --params source_root=<domain>/ --params test_path=tests/<domain>/ --params skip_checks=reuse,coverage,security,arch")
```

With a PR number:

```python
Skill(skill="workflow", args="--workflow workflows/code/optimize-code.yaml --params pr_number=314 --params source_root=<domain>/ --params test_path=tests/<domain>/ --params skip_checks=reuse,coverage,security,arch")
```

## What Runs

Focuses on the complexity scan dimension — other dimensions can be added via skip_checks.
The workflow runs the full correction and recheck cycle:

1. **pre-check-auth** — verify GitHub and qlty connections
2. **scan-changed-files** — identify .py files changed vs main (or PR diff)
3. **mps-scan-complexity** — cognitive complexity audit (target < 15), print-vs-logging check
4. **mps-collate-findings** — collate complexity findings into unified report
5. **apply-corrections** — fix all critical + auto-fixable minor complexity findings
6. **recheck-lint** — `bin/ruff-resolve.sh check` + tests to confirm fixes
7. **human-gate** — present complexity summary, ask to commit/open PR

## Workflow Params

| Param | Default | Description |
|-------|---------|-------------|
| `source_root` | `""` | Path prefix for changed source files, e.g. `workflow/` |
| `test_path` | `""` | Test directory to run, e.g. `tests/workflow/` |
| `pr_number` | `""` | Optional PR number — scopes file detection to that PR's diff |
| `skip_checks` | `reuse,coverage,security,arch` | Passed automatically — controls which scan dimensions run |
| `auth_domains` | `"github,qlty"` | Comma-separated auth pre-flight services |
