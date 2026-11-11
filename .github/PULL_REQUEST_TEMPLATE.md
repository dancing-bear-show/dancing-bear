## Summary
<!-- 1-3 bullet points describing what this PR does -->
-

## Type of Change
<!-- Check all that apply -->
- [ ] `feat` - New feature
- [ ] `fix` - Bug fix
- [ ] `docs` - Documentation only
- [ ] `refactor` - Code change that neither fixes a bug nor adds a feature
- [ ] `test` - Adding or updating tests
- [ ] `chore` - Maintenance (deps, CI, configs)
- [ ] `perf` - Performance improvement

## Context / Motivation
<!-- Why is this change needed? Link to issue if applicable -->


## What Changed
<!-- List key changes, especially breaking ones -->
-

## Testing
- [ ] `make test` passed
- [ ] Targeted tests: <!-- list specific tests if not full suite -->
- [ ] Manual verification: <!-- describe what you tested manually -->
- [ ] Not tested (explain):

## Checklist
- [ ] Commit messages follow conventional format (`type(scope): description`)
- [ ] No secrets, tokens, or credentials added
- [ ] Docs updated if adding user-facing changes
- [ ] Tests added/updated for new functionality
- [ ] CLI flags/commands are backward compatible

## Pre-Submission Validation

<!-- Run these before merging. Catches the most common feedback issues early. -->

### Required Checks
- [ ] Tests passing — confirm output includes `Ran N tests` line:
  ```bash
  make test > /tmp/t.log 2>&1; echo "EXIT=$?"; grep -E "^Ran [0-9]+ tests|^OK|FAILED" /tmp/t.log
  ```
- [ ] qlty clean over changed files:
  ```bash
  git diff --name-only main...HEAD > /tmp/changed.txt
  ~/.qlty/bin/qlty check $(cat /tmp/changed.txt)
  ```
- [ ] Type check on changed files:
  ```bash
  make typecheck-changed
  ```
- [ ] No new dead code:
  ```bash
  make deadcode
  ```
- [ ] New code has test coverage (check with `make cov`)

### Documentation (required if public CLI or docs changed)
- [ ] `--help` output matches implementation
- [ ] `--agentic` schema matches implementation
- [ ] New parameters have type, required status, and defaults documented

## Breaking Changes
<!-- If any, describe migration path -->
None

---
<!-- Optional sections below - delete if not needed -->

## Screenshots / Output
```
(paste relevant CLI output or screenshots)
```

## Risks / Rollback
- Risk level: low | medium | high
- Rollback: revert commit / feature flag / N/A
