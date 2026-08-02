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

### thread-join-timeout-unchecked
- **severity**: major
- **check**: Verify that every `thread.join(timeout=N)` call in a test is followed by `assert not thread.is_alive()` to confirm the thread actually finished within the timeout.
- **triggers**: `thread.join(timeout=` in test files without a subsequent `assert not thread.is_alive()` or `assertFalse(thread.is_alive())`; test teardown or concurrent-behavior tests that join threads with a timeout and then proceed to assertions without checking join completion.
- **example**: `t.join(timeout=10)` completes silently whether the thread finished or timed out — if the code under test deadlocks, the test proceeds with the thread still running, assertions pass against stale state, and the background thread is left alive after the test. Fix: `t.join(timeout=10); assert not t.is_alive(), "thread did not finish within 10s"`.

### test-hardcodes-production-constant
- **severity**: major
- **check**: Verify that numeric literals in tests that duplicate a named constant defined in production code import that constant rather than hardcoding the value — a hardcoded copy silently drifts when the production constant changes.
- **triggers**: Test files that hardcode a numeric or string literal (timeout values, retry counts, buffer sizes, thresholds) where the corresponding production module defines a named constant with the same value; `join(timeout=N)` or `sleep(N)` calls in tests where the production code has a `*_TIMEOUT_S` or `*_SLEEP_S` constant.
- **example**: `t.join(timeout=10)` in a test mirrors `_TIMEOUT_S = 10` defined in a production module. If the constant is updated, the test's hardcoded value drifts silently — the timing contract between test and production code is broken without any test failure. Fix: import the constant from the production module and use it in the test.

### test-hardcoded-tmp-path
- **severity**: minor
- **check**: Verify that tests do not use hardcoded `/tmp` paths for temporary files or directories — `/tmp` is Unix-specific and pollutes the filesystem across test runs. Use `tempfile.TemporaryDirectory()` as a context manager instead, which is portable and cleans up automatically.
- **triggers**: Test functions or fixtures that pass `/tmp/...` as a directory argument, output path, or file path sentinel; `patch(... return_value=Path("/tmp/..."))` or `assert result == "/tmp/..."`; worker scripts or test helpers that hardcode `/tmp` as a working directory.
- **example**: `_process_content(data, output_dir=Path("/tmp/charts"))` in a test — `/tmp` is Unix-only and the directory persists after the test. Fix: `with tempfile.TemporaryDirectory() as tmp: _process_content(data, output_dir=Path(tmp))`. For sentinel-only uses where the value is never accessed as a real path, use a relative path like `Path("test-output")` to make the intent clear.

### test-module-attr-mutated-directly
- **severity**: major
- **check**: Verify that tests do not mutate module-level attributes directly (e.g. `module.attr = mock_value` with manual restore in teardown) when `patch.object` or `unittest.mock.patch` would provide automatic, exception-safe cleanup.
- **triggers**: Test files that assign to `module.<attribute>` or `api_module.<function>` directly, with a corresponding manual restore in a `finally` block or after the call; tests that mix direct attribute mutation with `patch.object` calls elsewhere in the same file, indicating an inconsistency; any test that relies on manual `original = module.attr; module.attr = ...; module.attr = original` without a context manager.
- **example**:
  ```python
  # bad — direct mutation, manual restore
  original = api_module.urlopen
  api_module.urlopen = MagicMock(return_value=response)
  try:
      result = cli.run(args)
  finally:
      api_module.urlopen = original  # skipped if this line itself raises

  # good — patch.object handles restore on any exit path
  with patch.object(api_module, 'urlopen', return_value=response):
      result = cli.run(args)
  ```
  If `cli.run()` raises an exception, the `finally` block runs and restores the attribute — but if the restore itself raises (e.g. another exception in teardown), the restore is skipped and subsequent tests see the mutated attribute. `patch.object` uses an internal try/finally that is exception-safe regardless of teardown errors.

### platform-specific-exception-message
- **severity**: major
- **check**: Verify that test assertions do not match on exception message substrings whose exact text is OS-specific or CPython implementation-defined — such strings vary across Python versions and platforms, making tests fragile outside the author's environment.
- **triggers**: Test files that call `assertIn("...", str(exc))` or `assert "..." in str(exc_info.value)` where the matched substring is a CPython error message (e.g. `'dictionary update sequence'`, `'No such file or directory'`, `'Cannot allocate memory'`); `FileNotFoundError`, `ValueError`, `PermissionError`, or `OSError` assertions that pin a specific message format rather than checking the exception type alone.
- **example**:
  ```python
  # bad — CPython-specific message, breaks on PyPy or future CPython
  with self.assertRaises(ValueError) as ctx:
      mapping.update(bad_sequence)
  self.assertIn('dictionary update sequence', str(ctx.exception))

  # good — assert the exception type; message content is an implementation detail
  with self.assertRaises(ValueError):
      mapping.update(bad_sequence)

  # good — if the message must be constrained, assert on an application-defined prefix
  with self.assertRaises(SystemExit):
      resolve_auth_or_exit('missing_profile')
  ```

### test-unused-import
- **severity**: minor
- **check**: Verify that test modules contain no unused imports — every imported name must be referenced in at least one test function, fixture, decorator, or type annotation in the file.
- **triggers**: New or modified test files (`tests/**/*.py`); imports of standard library modules (`time`, `dataclasses`, `typing`), third-party packages, or project symbols that do not appear in the file body.
- **example**:
  ```python
  # bad — SomeClass imported but never used in the test
  from mail.labels import LabelSync

  def test_run_outputs_table(self):
      result = self.cli.run([])
      self.assertIn('Title', result)

  # good — remove the unused import
  def test_run_outputs_table(self):
      result = self.cli.run([])
      self.assertIn('Title', result)
  ```

### test-file-parent-path
- **severity**: minor
- **check**: Verify that test files do not compute the repository root via `Path(__file__).parents[N]` — the parent index is fragile and resolves to the wrong directory if the test file is moved or the directory nesting changes.
- **triggers**: `Path(__file__).parents[` in any test file; `Path(__file__).resolve().parents[` patterns; multi-level parent traversals (`[1]`, `[2]`, `[3]`) anchored to the test file's own location.
- **example**:
  ```python
  # bad — the resolved directory depends on the test file's nesting depth;
  # breaks silently if the test file is reorganised into a different subdirectory
  REPO_ROOT = Path(__file__).resolve().parents[2]

  # good — use an explicit relative path or a project-level constant
  import os
  REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
  ```

### test-calls-mock-not-entry-point
- **severity**: major
- **check**: Verify that tests patching a helper function invoke the real entry point (e.g. `self.cli.run()`) rather than calling the patched mock object directly — calling the mock directly only verifies the mock's own return value, not that production code actually delegates to the patched helper.
- **triggers**: Test functions that `@patch` or `mock.patch` a private helper and then call the mock variable itself rather than invoking the class/CLI method under test; test bodies with no call to `self.cli.run(...)` or the equivalent public entry point after setting up the patch.
- **example**:
  ```python
  # bad — calls the mock directly, never exercises the CLI's run()
  @patch("mail.helpers._get_profile")
  def test_profile_used(self, mock_get_profile):
      mock_get_profile.return_value = "personal"
      result = mock_get_profile()  # verifies nothing about production code
      self.assertEqual(result, "personal")

  # good — exercises the real entry point and asserts delegation
  @patch("mail.helpers._get_profile")
  def test_profile_used(self, mock_get_profile):
      mock_get_profile.return_value = "personal"
      self.cli.run(self.args)
      mock_get_profile.assert_called_once()
  ```

### wildcard-import-test-shim-no-all
- **severity**: minor
- **check**: Verify that any wildcard import shim in a test tree defines `__all__` or carries a suppression comment explaining the re-export intent, so linters do not flag it as a namespace-polluting import.
- **triggers**: Test files that use `from <module> import *` to re-export decompose-sweep shim symbols; `# nosonar` or `# noqa` suppressions on wildcard imports that lack an inline rationale; new shim files under `tests/` created by decompose refactors.
- **example**: `from tests.mail_tests.accounts.test_accounts_processors import *  # nosonar` — no rationale; a future reader cannot distinguish an intentional backward-compat shim from an accidental wildcard. Fix: add a comment — `# nosonar - intentional re-export shim from decompose-sweep; __all__ not defined in source` — or define `__all__` in the imported module to prevent namespace pollution.
