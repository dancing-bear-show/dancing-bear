---
name: optimize-code-security
description: Security and credential masking audit. Checks for hardcoded credentials, unmasked output, proper secret handling, and secure API patterns. Use to prevent credential leaks and ensure secure data handling before PR.
allowed-tools: Bash, Read, Edit, Write, Glob, Grep, Agent, Skill
skills:
  - dancing-bear-rules
---

# Optimize Code — Security Pass

Delegates to `workflows/code/optimize-code.yaml` with `skip_checks=reuse,complexity,coverage,arch`,
running only the security scan dimension. Findings are applied and rechecked automatically.

## When to Use

- After implementing code that handles credentials, tokens, or API keys
- Pre-PR security check
- When integrating with new external services
- User says "secure", "mask", "check for leaks", or "sanitize output"

## How to Run

Bootstrap `source_root` and `test_path` from context:
- `source_root`: the `<domain>/` directory of the files you just wrote or changed
- `test_path`: the corresponding `tests/<domain>/` directory
- `pr_number`: optional — if you have an open PR, pass it to scope file detection to that PR's diff

**IMPORTANT**: Use the `/workflow` skill — do NOT call `./bin/workflow run --execute` directly. It only writes dispatch files and exits (status=pending). The `/workflow` skill is what actually spawns agents, waits for results, and handles human gates.

```python
Skill(skill="workflow", args="--workflow workflows/code/optimize-code.yaml --params source_root=<domain>/ --params test_path=tests/<domain>/ --params skip_checks=reuse,complexity,coverage,arch")
```

With a PR number:

```python
Skill(skill="workflow", args="--workflow workflows/code/optimize-code.yaml --params pr_number=314 --params source_root=<domain>/ --params test_path=tests/<domain>/ --params skip_checks=reuse,complexity,coverage,arch")
```

## What Runs

Focuses on the security scan dimension — other dimensions can be added via skip_checks.
The workflow runs the full correction and recheck cycle:

1. **pre-check-auth** — verify GitHub and qlty connections
2. **scan-changed-files** — identify .py files changed vs main (or PR diff)
3. **mps-scan-security** — hardcoded credential detection, masking gaps, raw HTTP usage audit
4. **mps-collate-findings** — collate security findings into unified report
5. **apply-corrections** — fix all critical + auto-fixable minor security findings
6. **recheck-lint** — `bin/ruff-resolve.sh check` + tests to confirm fixes
7. **human-gate** — present security summary, ask to commit/open PR

## Workflow Params

| Param | Default | Description |
|-------|---------|-------------|
| `source_root` | `""` | Path prefix for changed source files, e.g. `workflow/` |
| `test_path` | `""` | Test directory to run, e.g. `tests/workflow/` |
| `pr_number` | `""` | Optional PR number — scopes file detection to that PR's diff |
| `skip_checks` | `reuse,complexity,coverage,arch` | Passed automatically — controls which scan dimensions run |
| `auth_domains` | `"github,qlty"` | Comma-separated auth pre-flight services |
