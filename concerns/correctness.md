# Correctness Review Guide

## When loaded

Load this guide when the diff contains `.py` files. Applies to all Python source
changes — new functions, modified logic, CLI `run()` methods, and datetime handling.

## Concerns

### return-type-mismatch
- **severity**: critical
- **check**: Verify return types match function signatures and call sites.
- **triggers**: New or modified functions with type-annotated return types;
  callers that assign or pass the return value.
- **example**: Function declares `-> list[str]` but returns `None` on an early
  exit path; caller then iterates over the result and raises `TypeError`.

### silent-failure
- **severity**: critical
- **check**: Verify exceptions are not swallowed without re-raise, log, or
  user-visible error. Also verify that functions returning `(status, data)` tuples
  have their status component checked by the caller — ignoring the status and
  unpacking only `data` silently discards error information.
- **triggers**: `except` blocks; `try/except` without `raise`, `log`, or
  `sys.exit`; bare `except:` clauses; callers that do `_, data = fn()` or
  `result[1]` on a two-element return without checking `result[0]`; `or []` /
  `or {}` applied to values that could carry error information.
- **example**: `except Exception: pass` in a data-fetch method — the caller
  receives `None` and proceeds as if the fetch succeeded. Bare `except` blocks
  require `# nosec B110/B112` with an explanation of intent.
- **see also**: `exit-code-coverage` in tests.md — tests that only check
  `exit_code == 0` won't catch silent failures swallowed by the code under test.

### unhandled-edge-case
- **severity**: major
- **check**: Verify `None`, empty collections, and zero-value inputs are
  handled at function boundaries.
- **triggers**: Functions accepting optional args (`| None`, default `None`);
  list/dict arguments consumed without a length check; division or modulo
  operations.
- **example**: `items[0]` called on a list that may be empty; division by
  `total` without a zero guard.

### wrong-exit-code
- **severity**: major
- **check**: Verify `sys.exit()` calls use exit codes consistent with the
  documented exit code semantics for the module.
- **triggers**: `sys.exit()` calls in CLI files; error-handling branches in
  `run()` methods.
- **example**: `sys.exit(1)` on a connection timeout; `sys.exit(0)` after a
  validation failure. Check `core/cli_errors.py` for `ExitCode` constants.

### naive-timestamp-conversion
- **severity**: major
- **check**: Verify timestamp arithmetic uses timezone-aware datetimes throughout — from parse
  to comparison to output. Watch for silent UTC-local mismatches when converting epoch floats
  or parsing ISO strings without a timezone suffix.
- **triggers**: `datetime.fromtimestamp(` without `tz=timezone.utc`; `datetime.fromisoformat(`
  on strings that may lack a `+00:00` or `Z` suffix; arithmetic between a naive and an
  aware datetime; `.total_seconds()` on a timedelta derived from mixed-aware/naive subtraction.
- **example**: `datetime.fromtimestamp(ts)` on a Unix epoch returns a local-time datetime —
  subtracting it from `datetime.now(timezone.utc)` raises `TypeError` at runtime. Fix:
  `datetime.fromtimestamp(ts, tz=timezone.utc)` throughout.

### unvalidated-passthrough
- **severity**: major
- **check**: Verify that values accepted from external sources (CLI args, API responses, config
  files) are validated or sanitised before being used in shell commands, file paths, or format
  strings — never passed through raw.
- **triggers**: `args.<field>` used directly in `subprocess` / `os.system` / f-string shell
  args; API response fields fed into `open()` paths or `str.format()`; config values
  interpolated into URLs without encoding.
- **example**: `subprocess.run(["git", "checkout", args.branch])` is safe; but
  `subprocess.run(f"git checkout {args.branch}", shell=True)` is a shell-injection vector
  when `branch` contains spaces or shell metacharacters. Fix: always pass args as a list, never
  through `shell=True` with user-controlled input.

### datetime-timezone-naive
- **severity**: major
- **check**: Verify `datetime.utcnow()` and naive `strptime()` results are
  replaced with timezone-aware equivalents using `datetime.now(timezone.utc)`.
- **triggers**: Any `.py` file importing `datetime`; `datetime.utcnow()`,
  `datetime.now()` without a tz argument, `datetime.strptime(` without
  explicit UTC attachment, `.timestamp()` called on a naive datetime, manual
  `+'Z'` string concatenation instead of `.isoformat()`.
- **example**: `datetime.utcnow()` in a calendar date filter — deprecated in
  Python 3.12 and produces non-deterministic UTC offsets when the runner
  timezone differs from UTC. Fix: `datetime.now(timezone.utc)` and
  `.isoformat()` throughout.

### undeclared-flag-constraint
- **severity**: major
- **check**: Verify that when a flag's help text documents a dependency on another flag (e.g. "requires --profile"), the constraint is enforced in the parser or `run()` with an error message — not just documented. Also verify the semantics match: if a spec describes a flag one way but the implementation treats it differently, that is an undeclared semantic mismatch.
- **triggers**: `add_argument(` with a `help=` string containing "requires", "only with", or "must be used with"; CLI `run()` methods that accept a flag combination without checking the constraint.
- **example**: `--dry-run` is described as requiring `--apply`, but `run()` accepts both flags independently and silently ignores `--dry-run`. Fix: enforce constraints in `run()` and align help text with actual parameter semantics.

### api-response-no-fallback
- **severity**: minor
- **check**: Verify that output rows derived from API responses fall back to user-provided arguments when the API returns an empty or missing field, rather than silently emitting a blank value.
- **triggers**: Output rows built from API response fields that could be empty or absent; CLI output that echoes a resource field the user already provided.
- **example**: `{"title": response.get("title")}` — if the API returns `""` for the title, the user sees a blank row even though `args.title` has the correct value. Fix: `"title": response.get("title") or args.title`.

### silent-truncation
- **severity**: major
- **check**: Verify that string truncation of IDs, UIDs, or keys is never silent — truncation must either raise a clear error or produce a deterministic, collision-resistant result.
- **triggers**: `str[:N]` on ID, UID, key, or slug values; any length cap applied before storing or publishing a resource.
- **example**: `uid = raw_uid[:40]` silently truncates — two configs whose UIDs differ only after character 40 will collide. Fix: raise `ValueError` when the raw value exceeds the limit, or use a hash-suffixed slug.

### vacuous-all-check
- **severity**: major
- **check**: Verify that `all(...)` and `any(...)` calls are not applied to a potentially-empty iterable when an empty collection should be treated as a failure, not a pass.
- **triggers**: `all(` over a generator or list that derives from `.get(`, `filter(`, or a list comprehension of a nullable collection; boolean flags set from `all(...)` expressions used as a validation result.
- **example**: `all(item["ok"] for item in results if item)` — when all items are filtered out, `all([])` returns `True`, so validation passes even though no item was checked. Fix: `bool(results) and all(...)` or use `any(...)` semantics where appropriate.

### inconsistent-fallback-default
- **severity**: major
- **check**: Verify that the same optional/missing field has a consistent fallback value at every call site — mixing `""` and `"unknown"` (or `None` and `0`) for the same key produces different behavior in different code paths.
- **triggers**: `dict.get("key", ...)` where the same field key appears more than once with different default values; f-strings or format strings that embed the same optional field in multiple places with different guards.
- **example**: `item.get("label", "unknown")` in one path and `i.get("label", "")` in another — downstream comparisons or exports diverge silently. Pick one fallback and apply it consistently.

### lowercase-any-annotation
- **severity**: critical
- **check**: Verify type annotations use `Any` from `typing`, not the lowercase builtin `any`. Using `any` as a type annotation compiles without error but defeats type checking entirely.
- **triggers**: `def ` or `->` followed by `: any` or `-> any`; type annotations where `any` appears without an uppercase `A`; missing `from typing import Any`.
- **example**: `def process(args: any) -> None:` — `any` is the builtin function, not a type. Fix: `from typing import Any` and `def process(args: Any) -> None:`.

### cli-flag-dead-code
- **severity**: major
- **check**: Verify every flag declared in `add_argument()` is consumed in the corresponding `run()` method — either read via `args.<flag>` or forwarded to a called function.
- **triggers**: `add_argument(` in parser setup; argparse flags whose name does not appear in the same file's `run()` body; `--format choices` that advertise an option the handler has no branch for.
- **example**: `parser.add_argument("--verbose", action="store_true")` defined but `run()` never reads `args.verbose` — the flag silently has no effect. Fix: wire it into the handler logic or remove the argument declaration.

### resource-leak
- **severity**: major
- **check**: Verify that `tempfile.mkdtemp()` calls, raw file handles opened without a `with` block, and `sys.modules` injections all have a corresponding cleanup path — either a context manager or an explicit `del`/`shutil.rmtree` in a `finally` block.
- **triggers**: `tempfile.mkdtemp(` not inside `with tempfile.TemporaryDirectory()`; `open(` assigned to a variable without `with`; `sys.modules["..."] =` outside a `with patch.dict(...)` block or test teardown.
- **example**: `tmp = tempfile.mkdtemp()` with no cleanup — temp directory persists and accumulates across test runs. Fix: `with tempfile.TemporaryDirectory() as tmp:`.

### env-var-not-exported
- **severity**: major
- **check**: Verify that shell variables intended to be read by Python subprocesses via `os.environ` are declared with `export`, not as bare shell assignments.
- **triggers**: Shell scripts or hook files that assign a variable (`VAR=value`) and then invoke a Python subprocess or `./bin/` CLI that reads `os.environ["X"]`.
- **example**: `PROFILE=$(...)` followed by `./bin/mail-assistant --profile $PROFILE` where Python reads `os.environ["PROFILE"]` — the variable is not exported so `os.environ` raises `KeyError`. Fix: `export PROFILE=$(...)`.

### hardcoded-magic-constant
- **severity**: major
- **check**: Verify numeric literals that duplicate a named constant defined in the same module are replaced with the constant. Silent bypass of a named constant means the literal drifts when the constant is updated.
- **triggers**: Numeric literals in `.py` files where a constant with the same value is importable from a sibling `constants.py` or defined at module level.
- **example**: `max_h = 7.5 - MARGIN / 2` where `PAGE_HEIGHT = 7.5` is defined at module level — when `PAGE_HEIGHT` is updated, `max_h` silently uses the old value. Fix: `max_h = PAGE_HEIGHT - MARGIN`.

### silent-type-coercion-on-wrong-input
- **severity**: major
- **check**: Verify that functions receiving structured input (lists from YAML/JSON) raise or surface an error when the input is the wrong type, rather than silently normalizing to an empty collection and returning as if the input were valid but empty.
- **triggers**: `if not isinstance(x, list): return ()` or `or []` / `or {}` coercions inside YAML/config parsers; functions that return `[]` on both "no results" and "input was malformed."
- **example**: `def _parse_includes(block): if not isinstance(block, list): return ()` — when a YAML author writes `include: {file: x.yaml}` (a mapping instead of a list), the function silently returns no includes, dropping the entry without any error. Fix: raise a descriptive error.

### positional-parameter-should-be-keyword-only
- **severity**: minor
- **check**: Verify that internal/sentinel parameters (recursion guards, accumulator sets) are declared keyword-only (`def f(x, *, _visited=None)`). Positional access allows callers to accidentally populate an internal parameter.
- **triggers**: Private parameters (leading `_`) that are not the first parameter in a signature; recursion-guard parameters of type `set | None` or `list | None` with `default=None`.
- **example**: `def _expand(path, _visited=None)` — a caller writing `_expand(path, some_set)` accidentally seeds the visited set. Fix: `def _expand(path, *, _visited=None)`.

### broad-except-shadows-narrower-handler
- **severity**: major
- **check**: Verify that `except Exception` blocks do not swallow typed exceptions that a narrower outer handler is meant to catch.
- **triggers**: Functions with nested `try/except Exception` inside a call stack where an outer `except SpecificError` block depends on the exception propagating; `except Exception as e: print(...)` patterns that do not re-raise.
- **example**: Inner `except Exception` catches all exceptions and only prints to stderr — a `ValueError` on invalid input never reaches the outer `except ValueError` block. Fix: narrow the inner handler to the specific exceptions expected there.

### hook-invokes-package-module
- **severity**: major
- **check**: Verify that hooks and scripts invoke project CLIs via `./bin/<entrypoint>` rather than `python -m <package>`, which fails when the package is not installed in the active environment.
- **triggers**: Hook files or scripts that invoke Python via `python -m personal_assistants.` or `python -m <module_path>`; subprocess calls that use `python -m` for project-internal CLI execution.
- **example**: A hook calls `subprocess.run([sys.executable, "-m", "mail.cli", ...])` — this fails with `ModuleNotFoundError` in any environment where `pip install -e .` has not been run. Fix: replace with `["./bin/mail-assistant", ...]`.

### query-unbounded
- **severity**: major
- **check**: Verify that queries and data scans load a bounded result set — every query has a limit, page_size, or streaming path.
- **triggers**: API queries with no page_size parameter; `f.read().split()` calls where only a tail/head slice is needed; list comprehensions over query results with no bound.
- **example**: `messages = api.list_messages()` with no page size — returns every message on the first production run with a large mailbox. Fix: add a `max_results` parameter at the query layer.

### noqa-f401-on-used-import
- **severity**: minor
- **check**: Verify that `# noqa: F401` suppressions are only applied to imports that are genuinely unused in the file — not to imports that are actively referenced in the same file.
- **triggers**: Any `.py` file containing `# noqa: F401` where the suppressed import name appears in the file body.
- **example**: `from .parser import parse  # noqa: F401` — `parse` is then called in the same file, making the suppression incorrect. Fix: remove `# noqa: F401` from any import that is actually referenced.

### help-text-behavior-mismatch
- **severity**: major
- **check**: Verify that every CLI flag's `help=` string accurately describes the flag's actual implementation behavior.
- **triggers**: CLI `add_argument(` calls where the `help=` string describes a capability that is only triggered by a different input path; help strings containing "auto-extracted from" or "supports" when the implementation only handles that case elsewhere.
- **example**: `--config` help reads "YAML config or URL (auto-fetched)" but URL fetching only runs for positional args — passing a URL to `--config` directly uses the string as a file path. Fix: narrow the help string to describe only what the flag itself handles.

### cli-error-to-stdout
- **severity**: major
- **check**: Verify that error messages are written to stderr, not stdout — stdout is the structured output channel and must not contain human-readable error text.
- **triggers**: CLI `run()` methods or dispatch handlers that call `print(f"Unknown command: {cmd}")` or `print("Error: ...")` without `file=sys.stderr`.
- **example**: `print(f"Unknown command: {args.command}")` in a CLI dispatch handler outputs to stdout. When a caller pipes to `jq`, the error text corrupts the JSON stream. Fix: `print(f"Unknown command: {args.command}", file=sys.stderr); sys.exit(3)`.

### docstring-implementation-mismatch
- **severity**: major
- **check**: Verify that module and function docstrings accurately describe what the implementation currently does — docstrings that claim behavior the code does not perform mislead callers.
- **triggers**: Docstrings for functions that have been refactored or partially implemented; module-level docstrings that describe a feature set broader than what the code provides.
- **example**: A `_filter_records()` docstring says it returns only records within a date range, but the implementation returns all records matching a file pattern with no date check. A caller relying on the docstring contract gets records outside the expected range. Fix: update the docstring to match the actual behavior.

### silent-wrong-nesting-level
- **severity**: major
- **check**: Verify that API response field access uses the correct nesting depth. Reading `response["field"]` when the value lives at `response["meta"]["field"]` silently returns `None` without raising, producing wrong output that passes all type checks.
- **triggers**: `.get("folderUid")`, `.get("uid")`, `.get("title")` on API response dicts where the API documentation shows the field nested under a sub-key (`meta`, `data`, `result`, `attributes`); field access on Grafana dashboard JSON which nests metadata under `meta`.
- **example**: `folder_uid = dashboard.get("folderUid")` — Grafana's API places `folderUid` at `dashboard["meta"]["folderUid"]`; the top-level key is absent, so `folder_uid` is `None` and all downstream folder-filtering silently skips every dashboard. Fix: `folder_uid = dashboard.get("meta", {}).get("folderUid")`.

### emit-one-in-poll-loop
- **severity**: major
- **check**: Verify that polling loops do not call `emit_one()` on every tick — each call prints a standalone JSON or YAML object, producing multiple concatenated top-level objects that are not valid JSON or YAML and cannot be parsed by downstream consumers. Also verify that any `print(json.dumps(...))` in a poll loop uses `flush=True` — without it, stdout is block-buffered when piped and tick output is held until the buffer fills or the process exits.
- **triggers**: `emit_one(` calls inside `while True:`, `for ... in range(...)`, or any other loop body; CLIs with `--format json` or `--format yaml` that run a polling loop and emit one record per iteration; poll-until-done patterns where each status check calls the output helper directly; `print(json.dumps(...))` in a poll loop without `flush=True`.
- **example**: A CI poll loop calls `emit_one(record, fmt='json')` on each tick. After 5 ticks, stdout contains 5 separate `{...}` objects separated only by newlines — not a JSON array. `jq '.[].status'` fails with `parse error: Invalid numeric literal at EOF`. Separately, `print(json.dumps(record))` in a poll loop without `flush=True` causes output to be held in Python's block buffer when stdout is piped — a caller running `./bin/monitor-poll ... | jq` sees nothing until the buffer fills or the process exits. Fix: collect all tick records in a list and call `emit_rows(records, fmt=fmt)` once after the loop exits. For genuinely streaming NDJSON output, use `print(json.dumps(record), flush=True)` and document that the format is ndjson so callers use a line-by-line parser. Evidence: PR #528.

### unguarded-api-call-cli
- **severity**: major
- **check**: Verify that API and network calls in CLI `run()` methods are wrapped in exception handlers that return a controlled non-zero exit code — unguarded calls produce tracebacks instead of actionable error messages and violate the CLI's documented exit code contract.
- **triggers**: CLI `run()` methods that call client methods (`client.get_pipeline(...)`, `client.get_project_status(...)`, HTTP calls) without a surrounding `try/except`; poll loops where each tick calls a network client without error handling; `cli_main()` entry points that do not catch general `Exception` when the `run()` method makes network calls.
- **example**: `result = client.get_pipeline(pipeline_id)` inside a poll loop with no try/except. When a transient network error occurs, the CLI crashes with a full traceback — callers in workflows see exit code 1 (Python exception) rather than the documented exit code 2 (connection error). Fix: `try: result = client.get_pipeline(pipeline_id) except (ConnectionError, TimeoutError) as e: print(f"Connection error: {e}", file=sys.stderr); return 2`. Evidence: PR #492.

### exit-code-table-incomplete
- **severity**: major
- **check**: Verify that the module-level exit code table documents every return code the implementation can produce — omitted codes cause callers to misclassify error types and build incorrect retry or alerting logic.
- **triggers**: Module docstrings that include an explicit exit-code table (e.g. `Exit codes: 0=success, 1=not-found`) when the implementation also returns additional codes not listed; poll loops or error handlers that return codes like `rc=2` (connection/auth) that are absent from the documented table; `not-found` and `connection-error` paths that share the same return code contrary to the table's claims.
- **example**: A module docstring documents `Exit codes: 0 = success, 1 = failure/timeout` but both poll loop functions return `2` on API/network exceptions. Workflow orchestrators that rely on `rc=1` to distinguish a real test failure from a transient connectivity issue will misclassify network outages as test failures. Fix: add `2 = connection/auth error` to the table and verify that `not-found` (rc=1) and `connection-error` (rc=2) use distinct return values throughout the module. Evidence: PR #492.

### regex-unicode-scope-change
- **severity**: major
- **check**: Verify that `\w` used in a regex compiled without `re.ASCII` is intentional — by default Python's `\w` matches all Unicode word characters, not just `[A-Za-z0-9_]`, silently broadening what was previously an ASCII-only pattern.
- **triggers**: Python files where a `[A-Za-z0-9_]` character class is replaced with `\w` (e.g. to satisfy SonarQube or reduce complexity) without adding `re.ASCII` (or `re.A`) to the compile flags; regex patterns used for identifier validation, placeholder substitution, or slug matching that previously used an explicit ASCII character class.
- **example**: `re.compile(r'\{(\w+)\}')` replaces the prior `re.compile(r'\{([A-Za-z0-9_]+)\}')`. Without `re.ASCII`, `\w` now matches accented letters, CJK word characters, and other Unicode word chars — `{café}` and `{変数}` become valid placeholder names. If the intent is to keep the original ASCII-only contract while satisfying the linter, compile with `re.compile(r'\{(\w+)\}', re.ASCII)` so `\w == [A-Za-z0-9_]`. Evidence: PR #543.

### threadpool-result-submission-order
- **severity**: major
- **check**: Verify that `ThreadPoolExecutor` results are collected via `as_completed()` rather than by calling `future.result()` in the original submission-order loop — awaiting in submission order reintroduces head-of-line blocking, and if stable output order matters, sort the collected rows afterward rather than relying on submission order.
- **triggers**: `ThreadPoolExecutor` usage where a list of `future.result()` calls is made inside the same `for` loop used to `submit()` the futures; code that collects parallel results without importing `as_completed` from `concurrent.futures`; `emit_rows(` called with rows built directly from an `as_completed()` loop with no subsequent sort.
- **example**:
  ```python
  # bad — future.result() in submission order re-serializes the pool
  futures = [executor.submit(fetch, pr) for pr in pr_numbers]
  rows = [f.result() for f in futures]  # slow first PR blocks all later ones

  # good — collect via as_completed, then sort for stable output
  from concurrent.futures import as_completed
  futures = {executor.submit(fetch, pr): pr for pr in pr_numbers}
  rows = [f.result() for f in as_completed(futures)]
  rows.sort(key=lambda r: r["pr_number"])  # restore deterministic order
  ```
  Evidence: PR #632 — 5 occurrences.

### emit-rows-columns-kwarg-wrong
- **severity**: critical
- **check**: Verify that `emit_rows()` calls use the `headers=` keyword argument, not `columns=` — `emit_rows` does not accept `columns=`, and passing it raises `TypeError` at runtime before any output is produced. Also verify accompanying tests assert on `headers=`, not `columns=` — a test asserting on the wrong kwarg name silently skips validating the real call.
- **triggers**: `emit_rows(` call sites passing a `columns=` keyword argument; test files asserting on a `columns` kwarg in `call_args` for an `emit_rows` call.
- **example**:
  ```python
  # bad — raises TypeError at runtime
  emit_rows(rows, args.format, columns=["group", "count"])

  # good
  emit_rows(rows, args.format, headers=["group", "count"])
  ```
  ```python
  # bad test — columns is never set, so this assertion is silently skipped
  call_kwargs = mock_emit.call_args.kwargs
  if "columns" in call_kwargs:
      assert call_kwargs["columns"] == ["group", "count"]

  # good test — asserts on the real kwarg unconditionally
  assert mock_emit.call_args.kwargs["headers"] == ["group", "count"]
  ```

### hardcoded-default-branch-master
- **severity**: major
- **check**: Verify that workflow YAML and shell steps operating on an external or parameterized repo do not hardcode `master` as the default branch — use a configurable param or discover the actual default branch before checking it out.
- **triggers**: Workflow YAML stage descriptions or inline scripts containing `git checkout master`, `--base master`, or similar literal `master` references where the target repo is a variable rather than a fixed, known-master repo.
- **example**:
  ```yaml
  # bad — assumes the target repo's default branch is master
  description: |
    cd {repo_path} && git checkout master && git pull

  # good — parameterize the base branch
  trigger:
    params:
      base_branch: "main"
  description: |
    cd {repo_path} && git checkout {base_branch} && git pull
  ```
  If the target repo uses `main` (or any non-`master` default), the hardcoded checkout fails and the workflow stops mid-run.

### mixed-import-style-same-module
- **severity**: minor
- **check**: Verify a single module is not imported both as `import X` / `import X as m` and via `from X import Y` in the same file — pick one style per module and use it consistently.
- **triggers**: A `.py` file containing both `import core.http` (or `import core.http as http_mod`) and `from core.http import HttpClient` for the same module; test files that import a module under test multiple ways across different test functions.
- **example**: `tests/core_tests/test_http.py` uses `from core.http import HttpClient` in some test functions and `import core.http as http_mod` in others within the same file — readers can't tell at a glance which name refers to the module vs. the class, and mocking/patching targets become inconsistent (`core.http.HttpClient` vs. `HttpClient`). Fix: pick one style for the whole file — typically `from core.http import HttpClient` for direct use, or `import core.http as http_mod` only when patching module-level attributes (e.g. `importlib.reload(http_mod)`).

### httpclient-base-url-drops-query-string
- **severity**: critical
- **check**: Verify that callers of the shared `HttpClient` do not pass a full URL (including a query string) to the constructor and then an empty path to `.get()`/`.post()` — `HttpClient._build_url()` always discards any query string on `base_url` (it only builds the query from the `params` argument), so this is a guaranteed silent drop, not something that depends on concatenation logic.
- **triggers**: `HttpClient(url)` where `url` contains a `?`; `.get("")` or `.get("/")` calls immediately following construction with a full URL; call sites migrated from raw `requests.get(full_url)` to `HttpClient` without splitting the URL into base + path + params.
- **example**: `HttpClient(f"https://api.example.com/v1/resource?key={api_key}").get("")` — `_build_url()` reads only `urlsplit(self.base_url).path`, never `.query`, so `?key=...` is always silently discarded regardless of how the path/params are combined. Fix: `HttpClient("https://api.example.com").get("/v1/resource", params={"key": api_key})` — pass the query string via the `params` argument, not baked into the base URL.

### print-to-logger-silences-cli-output
- **severity**: major
- **check**: Verify that replacing `print()` with `logger.info()`/`logger.debug()` in a CLI-facing code path does not silently suppress user-visible output — check whether `logging.basicConfig()` (or equivalent handler/level setup) is configured anywhere in the CLI's execution path. Without it, Python's root logger defaults to `WARNING`, so `INFO`/`DEBUG` calls are suppressed; `logger.warning()`/`logger.error()` still emit, so the risk is specific to info/debug-level calls, not logging in general.
- **triggers**: Diffs that replace `print(` with `logger.info(`/`logger.debug(` inside `run()` methods, CLI output helpers, or any code path whose output the user is expected to see; modules that call `logging.getLogger(__name__)` without a corresponding `logging.basicConfig()` call reachable from the CLI entry point.
- **example**: A CLI's `run()` method is refactored from `print(f"Synced {n} labels")` to `logger.info(f"Synced {n} labels")` — since no `logging.basicConfig()` is called anywhere in the process, the root logger's default `WARNING` level suppresses the `INFO` call and the message never appears. The command appears to succeed with no output. Fix: keep `print()` for user-facing CLI output; reserve `logging.info`/`.debug` for diagnostic output that is explicitly configured with a handler and level, or verify `logging.basicConfig(level=logging.INFO)` is set before the log call can run.

### false-optional-return-type
- **severity**: minor
- **check**: Verify that `Optional`/`| None` and `Union` return-type annotations reflect branches the function body actually produces — an annotation broader than the real behavior (e.g. `dict[str, Any | None]` when no value is ever `None`) forces every caller to add dead null-checks and obscures the function's real contract.
- **triggers**: Return type annotations containing `| None` or `Optional[` where no `return None` (or return of a variable that can be `None`) appears on any code path in the function body; `list[str | None]`, `tuple[str, str | None]` and similar container-of-optional annotations where every element actually assigned is non-None.
- **example**: `def parse_header(raw: str) -> dict[str, Any | None]:` where every dict value assigned in the body is a concrete string or int, never `None` — callers write `if value is not None:` guards that can never be false. Fix: narrow the annotation to `dict[str, Any]` (or the concrete value type) so it matches actual behavior; this is the inverse problem of `inaccurate-type-annotations` in patterns.md, which covers annotations that are too *wide* in element type, not falsely nullable.

### unpaginated-gh-api-call
- **severity**: major
- **check**: Verify that `gh api` calls (in shell scripts, workflow YAML, or Python subprocess invocations) against list endpoints (PRs, issues, comments, runs) include `--paginate`, or an explicit `per_page`/`page` loop — GitHub's REST API defaults to 30 items per page and silently returns only the first page otherwise.
- **triggers**: `gh api repos/.../pulls` or similar list-returning endpoints invoked without `--paginate`; workflow YAML stages or scripts that collect PR/issue/comment data via `gh api` and feed it into aggregation or reporting logic without a pagination flag.
- **example**: `gh api repos/org/repo/pulls/123/comments` on a PR with 45 review comments returns only the first 30 — a report built from this silently under-counts findings with no error. Fix: `gh api repos/org/repo/pulls/123/comments --paginate`.

### abstract-method-ellipsis-body
- **severity**: minor
- **check**: Verify that abstract method bodies use `...` consistently with the rest of the codebase's convention (or switch to `raise NotImplementedError` if that is the established convention) — mixing both styles for the same kind of stub within one file or module is what triggers review noise, not the choice of `...` itself.
- **triggers**: `@abstractmethod` definitions where the body is `...` in some methods and `raise NotImplementedError` (or `pass`) in sibling methods of the same class or module.
- **example**: A new abstract base class defines five methods with `...` bodies while an existing sibling base class in the same module uses `raise NotImplementedError("...")` — pick one convention per module and apply it to all abstract stubs added in the same diff.

### unvalidated-env-var-parse
- **severity**: major
- **check**: Verify that `os.getenv`/`os.environ.get` values feeding a numeric or path conversion either use a documented fallback helper (see `core/http.py`'s `_parse_env_int`/`_parse_env_float`, which wrap the conversion in `try/except` with a `# nosec B110` fallback-to-default comment) or explicitly validate the value before use. A bare `int(os.getenv(...))` raises an unhandled `ValueError` when the variable is set but malformed, and a `TypeError` when it is unset (`os.getenv` returns `None` and `int(None)`/`Path(None)` both fail) — both cases surface deep in a constructor rather than at the CLI boundary with an actionable message.
- **triggers**: `int(os.getenv(`, `float(os.getenv(`, `Path(os.getenv(`, or `os.environ[...]` conversions with no surrounding `try/except`, no fallback helper, and no default passed as `os.getenv(name, default)`; new env-var-driven config (paths, timeouts, retry counts) added outside `core/http.py`'s existing pattern.
- **example**: `Path(os.getenv("TELEMETRY_DATA_DIR"))` in `telemetry/otel/reader.py`'s `OTLPDataDir.from_env()` is safe because an empty/unset value short-circuits to `default()` — but a hypothetical `int(os.getenv("OTEL_FLUSH_INTERVAL"))` with no `try/except` would raise `ValueError: invalid literal for int()` if the operator sets `OTEL_FLUSH_INTERVAL=5s` instead of `5`, or `TypeError: int() argument must be a string...not 'NoneType'` if it's unset entirely. Fix: mirror `core/http.py`'s `_parse_env_int` pattern — catch both error types and fall back to a documented default.

### sqlite-connection-not-closed
- **severity**: major
- **check**: Verify that `sqlite3.connect(...)` calls have an explicit `conn.close()` in a `finally` block — a bare `conn = sqlite3.connect(...)` (or `with sqlite3.connect(...) as conn:`) with no corresponding close leaks a file handle and, on some platforms, leaves the database file locked for subsequent readers/writers in the same process. Note that `with sqlite3.connect(...) as conn:` is a common trap: it only commits/rolls back the transaction on exit, it does **not** close the connection — `whatsapp/search.py`'s `_connect_ro()` currently relies on this pattern (`with _connect_ro(path) as conn:`) and does not explicitly close, so it is a candidate to harden rather than a model to copy. `phone/backup.py`'s explicit `con.close()` is the pattern new call sites should follow.
- **triggers**: `sqlite3.connect(` assigned to a variable with no enclosing `try/finally` and no `.close()` call later in the same function; `with sqlite3.connect(...) as conn:` used as if it closes the connection; helper functions that open a connection, run a query, and `return` the result without closing the connection on the return path; a new sqlite-backed reader/writer added under `telemetry/` or elsewhere that doesn't explicitly close.
- **example**: `conn = sqlite3.connect(db_path); cursor = conn.execute(query); return cursor.fetchall()` — the connection is never closed, leaking a file handle per call. A tempting but incomplete fix is `with sqlite3.connect(db_path) as conn: return conn.execute(query).fetchall()` — this commits the (implicit) transaction but leaves the connection open. The reliable fix: `conn = sqlite3.connect(db_path)` then `try: return conn.execute(query).fetchall() finally: conn.close()`.

### domain-exception-not-clierror
- **severity**: major
- **check**: Verify that domain-specific exception classes subclass `CLIError` (or an appropriate CLIError subtype — `NotFoundError`, `AuthError`, `UsageError`) rather than bare `Exception`, `RuntimeError`, `ValueError`, or `FileNotFoundError`; and that CLI boundaries raise `CLIError` instead of calling `sys.exit()` directly.
- **triggers**: `class FooError(Exception):` or `class FooError(RuntimeError):` or `class FooError(ValueError):` in domain modules; `raise FileNotFoundError(...)` at a CLI boundary; `sys.exit(N)` inside a domain module's `run()` or command handler where `CLIApp.run()` is the outer boundary; `raise ValueError(...)` or `raise RuntimeError(...)` in `_process_safe`, `consume()`, or `run()` methods.
- **example**:
  ```python
  # bad — bare Exception subclass bypasses CLIApp error routing
  class LayoutLoadError(Exception):
      def __init__(self, code, message): ...

  # bad — sys.exit bypasses handle_error()
  if not config_path.exists():
      print('Config not found', file=sys.stderr)
      sys.exit(2)

  # good — CLIError subclass integrates with handle_error() dispatch
  from core.cli_errors import CLIError, ExitCode
  class LayoutLoadError(CLIError):
      def __init__(self, code: int, message: str):
          super().__init__(message, ExitCode(code))

  # good — raise propagates to CLIApp boundary for clean formatting
  if not config_path.exists():
      raise CLIError('Config not found', ExitCode.NOT_FOUND)
  ```

### stdout-stderr-output-contract-drift
- **severity**: major
- **check**: Verify that when a change routes output from one stream to another (e.g. bare `print()` on stdout → `OutputWriter.print_error()` on stderr), all tests asserting on that output are updated to redirect the correct stream. A test using `redirect_stdout` to capture output that was moved to stderr will silently pass while capturing nothing.
- **triggers**: A diff that changes a producer or base-class error method from bare `print()` (stdout) to `OutputWriter.print_error()` / `sys.stderr` (or vice versa); `BaseProducer` subclasses whose `_produce_success` routes errors through `OutputWriter`; tests that use `contextlib.redirect_stdout` to assert on error/status messages; `print_error()` introduced in a base class while domain tests assert on stdout.
- **example**:
  ```python
  # before — BaseProducer.print_error writes to stdout
  class BaseProducer:
      @staticmethod
      def print_error(msg): print(msg)  # stdout

  # test captures stdout correctly
  with redirect_stdout(buf):
      producer.produce(bad_envelope)
  assert 'Pipeline error' in buf.getvalue()  # passes

  # after — refactor routes through OutputWriter (stderr)
  class BaseProducer:
      def print_error(self, msg): self._writer.print_error(msg)  # stderr

  # bad test — redirect_stdout captures nothing; buf is empty
  with redirect_stdout(buf):
      producer.produce(bad_envelope)
  assert 'Pipeline error' in buf.getvalue()  # silently passes (empty string, guarded assertion)

  # good — update test to match the new stream contract
  with redirect_stderr(buf):
      producer.produce(bad_envelope)
  assert 'Pipeline error' in buf.getvalue()
  ```

### bare-except-missing-nosec
- **severity**: major
- **check**: Verify that every `except Exception` block that *swallows* the error — `pass`, `continue`, or a sentinel return (`return None`/`{}`/`[]`) — carries a `# nosec B110` or `# nosec B112` comment with an inline rationale. Blocks that re-raise or convert the exception into a domain error (e.g. `raise CLIError(...) from exc`) do not swallow it and need no annotation.
- **triggers**: `except Exception` / `except Exception as e` blocks in `.py` source files whose body is `pass`, `continue`, or a bare sentinel return, and that lack a `# nosec` annotation; `_process_safe`, `consume()`, or loader methods that catch `Exception` broadly and continue past the failure. Do NOT trigger on blocks whose body re-raises or raises a domain-specific error.
- **example**: `except Exception: return None` with no annotation — Bandit flags this and reviewers cannot tell whether swallowing the error is intentional or an oversight. Fix: `except Exception:  # nosec B110 - <reason why this is best-effort and not hiding real bugs>`. By contrast, `except Exception as exc: raise CLIError(...) from exc` converts rather than swallows and correctly needs no `# nosec`.

### dict-comprehension-key-collision
- **severity**: major
- **check**: Verify that a dict built by comprehension or loop over a superset of keys cannot have a correct entry silently overwritten by a later one. Confirm the resulting mapping holds the intended value for every key, not merely that every key is present.
- **triggers**: A dict comprehension inverting a name→code table where several names share one code; length or cardinality filters (`if len(k) > 3`) used to pick a "canonical" name; reverse lookups built from an alias-bearing source table.
- **example**: `RRULE_CODE_TO_DAY_NAME = {code: name for name, code in TABLE.items() if len(name) > 3}` — both `"tues"` and `"tuesday"` map to `"TU"`, so `TU` resolves to whichever iterates last and Outlook/Graph day normalization emits the wrong day. Fix: build the mapping explicitly from the authoritative names rather than by filtering a table that also contains aliases.

### optional-widened-into-required-slot
- **severity**: major
- **check**: Verify that a value typed `T | None` is not passed straight into a slot typed `T`. The annotation then claims the field is always present while `None` can flow through it, so downstream code trusts a guarantee the types no longer provide.
- **triggers**: Dataclass/`TypedDict` constructor calls where the argument comes from an optional field and the receiving slot is non-optional; a field loosened to `| None` in a diff without auditing its consumers.
- **example**: `SummaryConfig.session_id` was widened to `str | None`, but `compute_summary()` passes it directly into `SessionSummary.session_id`, typed `str`. Downstream readers see a missing session id while the hints insist it exists. Fix: narrow at the call site, or make the receiving type optional and handle it consistently.

### dict-get-default-not-none-guard
- **severity**: major
- **check**: Verify that `dict.get(key, {})` is not used to guard against an explicit `null` in API or JSON payloads. The default applies only when the key is *absent* — an explicit `None` value is returned as-is and the next `.get()` raises.
- **triggers**: `payload.get("attributes", {})` / `.get("items", [])` on externally-parsed data followed by chained access; provider responses whose schema permits explicit nulls.
- **example**: `song.get("attributes", {}).get("name")` raises `AttributeError` when the API returns `"attributes": null`, because `.get` returns `None` rather than the `{}` default. Fix: `(song.get("attributes") or {}).get("name")`, the defensive form already used elsewhere in that module.

### signature-refactor-stale-call-sites
- **severity**: critical
- **check**: Verify that a signature change — especially removing or merging keyword arguments — updated every call site. Stale kwargs raise `TypeError` only when that line executes, so an untested path stays broken through a green suite.
- **triggers**: A diff changing a widely-called function's parameter list; a PR claiming call sites were "updated atomically"; `grep` for the removed kwarg still returning hits outside the changed file.
- **example**: `HttpClient` moved from `json=`/`data=`/`files=`/`stream=` kwargs to a single `body: HttpRequestBody`, but `maker/print/send_to_printer.py` still passed `files=`/`data=`/`json=` and `wifi/diagnostics_probes.py` still passed `stream=True` — each raising `TypeError` on first use. Fix: grep every removed kwarg name repo-wide before merging.

### frozen-dataclass-mutable-field
- **severity**: minor
- **check**: Verify that `@dataclass(frozen=True)` classes do not carry mutable fields that are mutated after construction. `frozen=True` blocks rebinding the attribute, not `append`/`update` on the object it points at, so the immutability guarantee is misleading.
- **triggers**: `frozen=True` alongside a `list[...]`/`dict[...]` field; code calling `.append()` or `.update()` on a field of a frozen instance; accumulator fields threaded through a pipeline request object.
- **example**: `@dataclass(frozen=True) class DeleteOneRequest` carries a `logs: list[str]` appended to during deletions. The append succeeds because only `request.logs = [...]` is blocked, so readers and type checkers infer an immutability that does not hold. Fix: drop `frozen=True`, or return the logs instead of accumulating into the frozen object.

### config-parser-read-return-unchecked
- **severity**: major
- **check**: Verify that `ConfigParser.read(path)` return values are checked. `read()` swallows permission and open errors and returns an empty list, so an unreadable file is indistinguishable from a successfully parsed empty one.
- **triggers**: `cp.read(path)` where the result is discarded; helpers that walk candidate config files and use "the first readable one"; credential-resolution search orders.
- **example**: An unreadable `credentials.ini` (mode 000) makes `cp.read()` return `[]`, so a caller treats it as the first readable file and returns an empty config — shadowing a later file that *is* readable. Fix: `if not cp.read(path): return None` so an unreadable file is treated as absent, as `core/constants.py:_parse_ini_file` now does.

### silent-unrecognized-value-fallback
- **severity**: major
- **check**: Verify that a well-typed but unrecognized or incomplete field value (an unknown enum-like string, a required sub-field left empty) either raises or is surfaced by validation, rather than silently falling back to a default or being routed to the wrong handler while `validate` still reports OK.
- **triggers**: Dict/YAML field lookups compared against a small fixed set of accepted string values with no `else: raise` branch (`if x == "foo": ... elif x == "bar": ... else: use default`); dict-based dispatch (`layouts.get(name, fallback)`, `handlers.get(kind, default_handler)`) keyed on a user-supplied string; `isinstance(content, SomeType) and content.some_field` gating which renderer runs, where a falsy-but-present `some_field` silently reroutes to a different renderer instead of raising; a `validate`/`lint` subcommand that checks structural shape (types, required keys) but does not check enum-like field values against the accepted set.
- **example**:
  ```python
  # bad — unknown layout name silently falls back, and validate never catches it
  def _resolve_layout(self, layouts, content):
      layout_name = content.layout or DEFAULT_LAYOUT_KEY
      if layout_name in layouts:
          return layouts[layout_name]
      return layouts[_FALLBACK_LAYOUT_KEY]  # no error for a typo'd layout: bullets

  # bad — TableSlide with rows but no headers is silently rendered as a bullet
  # slide, losing every row, and cmd_validate still prints "Validation: OK"
  if isinstance(content, TableSlide) and content.headers:
      self._populate_table_slide(slide, content, theme_color)
  else:
      self._populate_bullet_slide(slide, content, theme_color, ...)

  # good — reject at parse/validate time instead of silently degrading at render time
  if layout_name not in VALID_LAYOUTS:
      raise ValueError(f"Unknown layout {layout_name!r}; expected one of {VALID_LAYOUTS}")
  if isinstance(content, TableSlide) and not content.headers:
      raise ValueError(f"Table slide {content.title!r} has rows but no headers")
  ```
