# Complexity Review Guide

## When loaded

Load this guide when the diff contains `.py` files.

## Concerns

### high-cognitive-complexity-critical
- **severity**: critical
- **check**: Verify that no function or method exceeds a cognitive complexity
  of 15 as measured by qlty (bandit/ruff complexity metrics). Scoring rules:
    - `if`, `for`, `while`, `try`: +1 + current nesting depth (nesting starts at 0)
    - `except` handler: +1 (no nesting increment)
    - `break`, `continue`: +1 each
    - Boolean chain (`and`/`or`): +(number of operands - 1)
    - Recursive call: +1
  Note: `elif` IS counted — it is an `if` node at incremented nesting depth.
  `else` itself is not counted but its body is traversed, so control flow inside
  `else` blocks does add points.
- **triggers**: New or modified `def` / `async def` in non-test source files
  with multiple `if`/`elif` chains, nested loops, or multi-clause `try` blocks
  where the estimated branching point total exceeds 15; functions longer than
  ~40 lines are a proxy signal worth checking manually.
- **example**: A state machine with 5 `if/elif` arms each containing a nested
  `try/except` exceeds 15 branching points — requires decomposition. Fix:
  extract sub-branches into named helpers, replace `if/elif` chains with
  dispatch tables.
- **note**: qlty enforces this threshold in CI (`~/.qlty/bin/qlty check`);
  catch it before the review cycle with `~/.qlty/bin/qlty check path/to/file.py`.

### high-cognitive-complexity-minor
- **severity**: minor
- **check**: Verify that functions with a cognitive complexity between 11 and
  15 are flagged for simplification. Functions in this range are approaching
  the CI enforcement threshold and warrant refactoring while the cost is low.
- **triggers**: Same triggers as `high-cognitive-complexity-critical` where the
  estimated total falls in the 11–15 range; functions with 2–3 nested `if`/`for`
  combinations or 3+ `try/except` clauses in a single function body.
- **example**: A function with a `for` loop (+1) containing an `if` (+2 at
  depth 1) containing a `try` (+3 at depth 2) with an `except` (+1) registers
  7 points — adding multi-condition guards rapidly crosses 11. Fix: extract
  inner logic into named helpers.

### deep-nesting
- **severity**: minor
- **check**: Verify that function bodies do not exceed 3 levels of indented
  nesting (each `if`, `for`, `while`, `with`, or `try` block adds one level).
  Deep nesting is a leading indicator of high cognitive complexity and makes
  unit testing individual branches impractical.
- **triggers**: `def` bodies with 4+ nested indentation levels (16+ spaces
  inside the function, assuming 4-space indentation); `for` loops containing
  `if` blocks containing another `for` or `with`.
- **example**: A function that opens a file, iterates its lines, conditionally
  parses each, and then matches fields — 4 levels deep. Fix: extract the inner
  parse-and-match logic into a named helper; use early returns / guard clauses
  to flatten outermost conditionals.

### print-not-logging
- **severity**: minor
- **check**: Verify that non-CLI source modules use `logging.getLogger(__name__)`
  for diagnostic output rather than bare `print()` calls. `print()` bypasses
  the log level, formatting, and routing configuration used in production.
- **triggers**: `print(` in `.py` files that are not CLI entry points and do
  not produce intentional structured output; `print(f"...")` or
  `print("error: ..."` in domain, consumer, or core modules.
- **example**: `print(f"Fetching {len(items)} items from API")` in a provider
  module — writes to stdout unconditionally regardless of log level. Fix:
  `logger = logging.getLogger(__name__)` at module level, then
  `logger.debug("Fetching %d items from API", len(items))`. Exception: `print()`
  in CLI command handlers is acceptable when it is the intended human-readable
  output and no structured format flag is in play.

### file-too-large
- **severity**: minor
- **check**: Verify that no single source file grows beyond ~800 lines
  without a clear justification (e.g. a generated file, a large but flat
  data/schema table, or a CLI wiring module with many thin subcommand
  handlers). Large files are a proxy for mixed responsibilities and make
  review, testing, and navigation harder.
- **triggers**: A modified `.py` file that crosses ~800 lines total, or a
  diff that adds 200+ lines to a file already over ~600 lines; a file that
  mixes multiple unrelated classes/concerns (e.g. parsing + I/O + CLI
  wiring in one module).
- **example**: A provider module that started as a thin API client grows to
  900+ lines after accumulating parsing helpers, retry logic, and CLI
  formatting in the same file. Fix: split by responsibility — extract
  parsing/formatting helpers into a sibling module, keep the provider class
  focused on API calls, and re-export from `__init__.py` if needed to avoid
  breaking call sites.
