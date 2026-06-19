# Tests Review Guide

## When loaded

Load this guide when the diff contains test files (`tests/**/*.py`) or when
source files introduce new `sys.exit()` paths, HTTP clients, or mock boundaries.

## Concerns

### exit-code-coverage
- **severity**: major
- **check**: Verify every `sys.exit()` path in changed CLI files has a
  corresponding test that asserts the exit code.
- **triggers**: `sys.exit()` in source files; changed CLI command handler
  functions.
- **example**: A new `sys.exit(1)` on API failure has no test exercising
  it — the exit code contract is untested and may silently regress.
- **see also**: `silent-failure` in correctness.md — if the code under test
  swallows exceptions and exits 0, exit-code-only assertions will pass even
  when the operation failed.

### network-not-mocked
- **severity**: major
- **check**: Verify all HTTP and socket calls in unit tests are patched; no
  real network activity in tests not explicitly approved for network access.
- **triggers**: New or modified test files; new HTTP client usage; new
  `requests`, `urllib`, or `httpx` imports in tests.
- **example**: A test for a mail provider creates a client and calls `fetch()`
  without patching `requests.get` — the test suite makes real API calls in CI.
  Never run tests that require network/secrets without explicit user approval.

### weak-assertion
- **severity**: minor
- **check**: Verify assertions use specific forms (`assertEqual`, `assertIn`,
  `assertIsInstance`) rather than generic forms (`assertTrue(x is not None)`,
  `assert x`).
- **triggers**: New or modified test functions; `assert ` statements;
  `assertTrue`, `assertFalse` calls.
- **example**: `assertTrue(result)` passes for any truthy value; use
  `assertEqual(result, {"key": "expected"})` to pin the exact output.

### patch-target-wrong
- **severity**: major
- **check**: Verify mocks patch the symbol where it is **used**, not where it
  is **defined**.
- **triggers**: `@patch(`, `mock.patch(` in test files; imports that alias
  names across module boundaries.
- **example**: `@patch("requests.get")` when the module under test does
  `from requests import get` — the patch target should be
  `mail.gmail_api.get`, not `requests.get`.

### conditional-test-assertion
- **severity**: major
- **check**: Verify test assertions are unconditional — not guarded by `if value:`
  or `if value is not None:` without a corresponding assertion for the falsy/None
  case. A guarded assertion silently passes when data is unexpectedly empty,
  hiding regressions.
- **triggers**: `if ` followed by `assert` in test functions; `if result:` blocks
  containing the only assertion for that value; `if value is not None:` with no
  `else: assert value is not None` counterpart.
- **example**: `if config.labels: assert len(config.labels) > 0` — passes silently
  when `labels` is `[]` or `None`. Fix: `assert config.labels` as an unconditional
  assertion first, then assert the contents.

### mock-setup-no-assertion
- **severity**: major
- **check**: Verify that every mock configured in a test has at least one assertion
  on its call behavior — `assert_called_once_with(...)`, `assert_not_called()`, or
  a check on `call_args_list`. A mock that is configured but never asserted passes
  whether the code under test called it 0 or 100 times.
- **triggers**: Test functions that create a `MagicMock` or use `@patch` but contain
  no `assert_called`, `assert_called_once_with`, `assert_not_called`, or `call_count`
  assertion for that mock; test names containing "does not call" or "skips" with no
  `assert_not_called()` in the body.
- **example**: `mock_client = MagicMock(); run(args); assert result == 0` — verifies
  exit code but never checks whether `mock_client.sync` was called; a refactor that
  accidentally skips the sync passes undetected. Fix: add
  `mock_client.sync.assert_called_once_with(expected_args)`.

### mutable-test-fixture
- **severity**: major
- **check**: Verify test helper functions return fresh mutable objects (dicts, lists,
  sets) on every call — not references to a shared module-level instance. Shared
  mutable fixtures cause cross-test pollution when one test mutates the shared reference.
- **triggers**: Module-level `dict`, `list`, or `set` variables returned directly from
  test helper functions (not `.copy()`); factory functions in `tests/fixtures.py` or
  `tests/fakes/` that return `_DEFAULT_X` without copying.
- **example**: `_DEFAULT_LABEL = {"id": "a1", "name": "Test"}; def get_default_label():
  return _DEFAULT_LABEL` — all callers share the same dict, so `test_a` mutating
  `result["name"] = "Other"` pollutes `test_b`. Fix: `return _DEFAULT_LABEL.copy()`.

### test-data-builder-gap
- **severity**: minor
- **check**: Verify test fixture data is constructed via the project's factory helpers
  from `tests/fixtures.py` or `tests/fakes/` rather than as inline raw dict/list
  literals. Inline fixtures diverge silently when the production schema changes.
- **triggers**: Test files that build domain objects (mail labels, filters, calendar
  events) as `{...}` dict literals without importing a factory helper; new test files
  that do not import from `tests/fixtures.py` when helpers exist for that domain.
- **example**: `label = {"id": "a1", "name": "Test", "type": "user"}` constructed
  inline — when the label schema adds a required field, the factory helper is updated
  and all tests using it stay valid, but the inline dict silently misses the new field.
  Fix: use or create a factory helper in `tests/fixtures.py`.

### test-fixture-hardcoded-timestamp
- **severity**: major
- **check**: Verify that test fixtures do not use hardcoded absolute timestamps —
  a fixed datetime drifts outside the default time window as wall-clock time advances,
  causing tests to fail silently or produce different results over time.
- **triggers**: Test files that set a `timestamp`, `created_at`, `start_time`, or
  similar field to a fixed ISO-8601 string or Unix epoch constant; tests that exercise
  `--since`, `--window`, or date-range filtering against hardcoded timestamps.
- **example**: `event = {"start": "2026-01-15T10:00:00Z"}` — this timestamp is within
  a 7-day window when written but falls outside it months later, silently breaking any
  test that exercises time-window filtering. Fix: generate the timestamp relative to
  `datetime.now(timezone.utc)` — e.g. `(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()`.

### unused-mock-attribute
- **severity**: minor
- **check**: Verify that every mock attribute or return value configured in a test is
  either asserted on or used by the code under test — configured-but-unused mock
  attributes mislead future readers about what the code actually calls.
- **triggers**: Test functions that assign a `MagicMock()` method where the code under
  test never calls that method; `mock.return_value = ...` configurations for methods not
  exercised by the specific test path.
- **example**: `mock_client.get_quota = MagicMock()` is set up in a test, but the
  handler under test never calls `get_quota` — only `list_labels` is called. The unused
  configuration misleads reviewers into thinking `get_quota` is part of the tested
  behavior. Fix: remove unused mock attribute assignments; if checking that a method is
  NOT called, add an explicit `mock_client.get_quota.assert_not_called()`.

### test-run-command
- **severity**: major
- **check**: Verify tests are run with `make test` or `python3 -m unittest -v` — not
  pytest. This repo uses the standard `unittest` framework; pytest is not a dependency.
  With coverage: `coverage run -m unittest discover && coverage report`.
- **triggers**: PR descriptions or test instructions that reference `pytest` commands;
  new test files that use pytest-specific fixtures (`@pytest.fixture`, `conftest.py`
  with `yield` fixtures, `pytest.mark.*`) rather than `unittest.TestCase`.
- **example**: A new test file imports `pytest` and uses `@pytest.fixture` — this
  requires an undeclared dependency. Fix: use `unittest.TestCase` with `setUp`/
  `tearDown` and `unittest.mock` for all patching.
