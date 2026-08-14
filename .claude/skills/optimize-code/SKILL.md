---
name: optimize-code
description: Post-implementation code optimization pass. Checks shared utility reuse (local then core), OO abstractions, bare string literals, cognitive complexity, test quality (fixtures/factories/shared helpers), dataclasses over dicts, dead code, architecture compliance, security/masking, and coverage. Use after writing new code to harden it before PR.
allowed-tools: Bash, Read, Edit, Write, Glob, Grep, Task, Agent, Skill
skills:
  - dancing-bear-rules
---

# Optimize Code

Delegates to `workflows/code/optimize-code.yaml`, which runs 5 quality scans in parallel
(reuse, complexity, coverage, security, and architecture), collates findings, applies
corrections, and rechecks.

## When to Use

- After implementing a feature (before committing or opening a PR)
- User says "optimize", "harden", "clean up", or "polish"
- As a pre-PR quality gate

## How to Run

**IMPORTANT**: Use the `/workflow` skill — do NOT call `./bin/workflow run --execute` directly. It only writes dispatch files and exits (status=pending). The `/workflow` skill is what actually spawns agents, waits for results, and handles human gates.

```python
Skill(skill="workflow", args="--workflow workflows/code/optimize-code.yaml --params source_root=<domain>/ --params test_path=tests/<domain>/")
```

With a PR number (scopes changed-files detection to that PR):

```python
Skill(skill="workflow", args="--workflow workflows/code/optimize-code.yaml --params pr_number=314 --params source_root=<domain>/ --params test_path=tests/<domain>/")
```

Skip specific checks:

```python
Skill(skill="workflow", args="--workflow workflows/code/optimize-code.yaml --params source_root=<domain>/ --params test_path=tests/<domain>/ --params skip_checks=coverage,security")
```

## Workflow Params

| Param | Default | Description |
|-------|---------|-------------|
| `source_root` | `""` | Path prefix for changed source files, e.g. `workflow/` |
| `test_path` | `""` | Test directory to run, e.g. `tests/workflow/` |
| `pr_number` | `""` | Optional PR number — scopes file detection to that PR's diff |
| `skip_checks` | `""` | Comma-separated checks to skip: `reuse,complexity,coverage,security,arch` |
| `auth_domains` | `github,qlty` | Auth pre-flight domains |

## Workflow Stages

1. **pre-check-auth** — verify GitHub and qlty connections
2. **scan-changed-files** — identify .py files changed vs main
3. **parallel scans** (all concurrent):
   - `mps-scan-reuse` — shared utility reuse, bare string literals, domain duplicates
   - `mps-scan-complexity` — cognitive complexity (target < 15) and print-vs-logging
   - `mps-scan-coverage` — test gap detection, coverage %, CI block coverage
   - `mps-scan-security` — hardcoded creds, masking gaps, raw HTTP usage
   - `scan-arch` — dead code, architecture compliance, dataclasses/type hints
4. **mps-collate-findings** — merge all scan results into unified report
5. **apply-corrections** — fix all critical + auto-fixable minor findings
6. **recheck-lint** — `bin/ruff-resolve.sh check` + tests to confirm fixes
7. **human-gate** — present summary, ask to commit/open PR

## Sub-skills (for targeted single-dimension passes)

| Skill | Covers |
|-------|--------|
| `/optimize-code-complexity` | Cognitive complexity only |
| `/optimize-code-coverage` | Coverage gaps and test quality only |
| `/optimize-code-reuse` | Duplication and shared utility reuse only |
| `/optimize-code-security` | Security and masking only |
