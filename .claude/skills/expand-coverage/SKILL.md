---
name: expand-coverage
description: Analyze test coverage gaps on changed or specified files, spawn tester agents to write tests, and verify improvement. Use when you need to get coverage above 80% on new code or expand coverage on existing modules.
allowed-tools: Bash, Read, Edit, Write, Glob, Grep, Task
skills:
  - dancing-bear-rules
---

# Expand Coverage

Find coverage gaps, write tests, and verify improvement.

## When to Use

- After writing new code that needs tests
- User says "add tests" or "improve coverage"
- Coverage below 80% on new/changed files
- As part of `/review-fix` Phase 2

## Step 1: Identify Gaps

```bash
# Coverage gaps on changed files only (fastest)
./bin/test-gaps --only-changed --format table

# Full gap analysis
./bin/test-gaps --format table

# Per-file coverage from qlty
./bin/qlty file-coverage -- --project dancing-bear --format yaml

# Run tests with coverage for a specific domain
python3 -m unittest tests/<domain>/ --cov=<domain> --cov-report=term-missing -x
```

## Step 2: Prioritize

Order by impact:
1. **New files with 0% coverage** — need test skeletons
2. **Changed files below 80%** — need gap tests
3. **Critical paths below 90%** — auth, credentials, API clients

## Step 3: Write Tests

For each file needing coverage:

1. **Read the source** to understand what to test
2. **Read domain conftest.py** for available factories and fixtures:
   - `tests/conftest.py` — global fixtures, AWS popup prevention
   - `tests/<domain>/conftest.py` — domain-specific factories
   - `tests/helpers/` — mock libraries (github_mocks.py, atlassian_adf_mocks.py)
3. **Write tests** following project conventions

### Test Conventions (Mandatory)

- Use `make_*` factories from conftest, never construct dicts manually
- Use conftest constants (`TEST_DATE_CREATED`, `DEFAULT_STATUS`, etc.)
- Patch where the name is **used**, not where it's **defined**
- Specific assertions: `assertEqual`, `assertIn`, `assertIsInstance`
- `@dataclass` for test fixtures

### Coverage Strategy

1. Happy path first
2. Edge cases (None, empty, invalid inputs)
3. Error paths (failures, timeouts, exceptions)
4. Mock all external services

For large coverage expansion, spawn `tester` agents:

```python
Task(subagent_type="tester", prompt="Write tests for <domain>/<module>.py targeting 80%+ coverage. Read tests/<domain>/conftest.py first for available factories.")
```

## Step 4: Verify

```bash
# Run new tests
python3 -m unittest tests/<domain>/test_new.py -x -v

# Check coverage improved
python3 -m unittest tests/<domain>/ --cov=<domain> --cov-report=term-missing -x

# Verify no test gaps remain
./bin/test-gaps --only-changed --fail-on-gaps

# Full suite (no regressions)
python3 -m unittest tests/ -m "" -x
```

## Step 5: Report

Output a summary:

```
## Coverage Expansion Results

| File | Before | After | Tests Added |
|------|--------|-------|-------------|
| domain/module.py | 45% | 82% | 8 |
| domain/cli.py | 0% | 85% | 12 |

Total: N new tests, M files improved
```

## Coverage Targets

| Category | Target |
|----------|--------|
| New code | 80%+ |
| Critical paths (auth, credentials, API) | 90%+ |
| Existing code | Improve toward 85% |
