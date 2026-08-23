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

### too-many-parameters
- **severity**: minor
- **check**: Verify that no function or method signature has more than 5
  parameters (excluding `self`/`cls`). Long parameter lists are error-prone at
  call sites (easy to swap same-typed positional args), hard to extend without
  breaking every caller, and a signal that related data should travel together.
  This limit is enforced by `[smells.function_parameters]` in `.qlty/qlty.toml`,
  which is set to 6 (qlty's threshold is the trigger point, not the ceiling).
  Keep the two in sync — when they diverge, reviewers flag signatures the
  tooling stays silent on. Note the tool trips one argument earlier than that
  on keyword-only signatures; see the counting caveat below before treating a
  reported count as the real parameter count.
- **triggers**: A `def`/`async def` with 6+ parameters (excluding `self`/`cls`);
  especially 3+ parameters sharing the same primitive type (e.g. multiple
  `str`/`int` args in a row) where call-site argument order is easy to
  transpose by mistake.
- **example**: `def send_invite(name: str, email: str, org: str, role: str,
  team: str, expires_at: datetime) -> None` — 6 parameters, four of them `str`,
  easy to pass in the wrong order. Fix: introduce a `@dataclass` grouping the
  related fields (e.g. `InviteRequest`) and take a single instance as the
  parameter: `def send_invite(invite: InviteRequest) -> None`. Prefer this over
  `**kwargs` or a plain `dict`, which lose type hints and IDE support.
- **counting caveat**: qlty's reported count is not the function's arity. It
  **excludes** `self`/`cls`, but it counts the bare `*` separator as if it were a
  parameter. A keyword-only signature therefore reports one higher than it
  actually takes — `def f(*, a, b, c, d, e)` takes 5 arguments and is reported
  as `count = 6`. Verified directly with a module-level fixture:
  `def nostar_6_real(a, b, c, d, e, f)` reports 6, while
  `def star_6_real(a, b, c, *, d, e, f)` — same six real parameters, one added
  `*` — reports **7**. `def f_mix(a, b, *, c, d, e)` (5 real) reports 6, and
  `def b_4kw(*, a, b, c, d)` (4 real) is not flagged at all.
  Note that a *method* cannot discriminate the rule: on
  `def request(self, m, p, *, a, b, c)`, "counts `self`, ignores `*`" and
  "ignores `self`, counts `*`" both predict 6. Use a module-level fixture.
  Always read the signature before acting on a count — subtract one whenever a
  `*` is present, and treat the adjusted arity as the real one.
- **accepted exceptions**: two shapes trip the count without carrying the risk
  this concern describes. Confirm which one applies before filing a finding.

  1. **Keyword-only signatures.** Keyword-only arguments cannot be transposed
     at a call site, so the stated failure mode is structurally impossible —
     and per the counting caveat above, these signatures are also over-reported
     by one. Prefer adding `*` over splitting a cohesive signature to lower a
     count. This is the dominant shape by a wide margin — e.g.
     `worker/queue_ops.py` `write_manifest`-style helpers and
     `phone/profile.py` `build_mobileconfig` (5 keyword-only arguments,
     reported as 6, already using extracted dataclasses).

     Don't trust a hardcoded tally here; counts drift as the repo grows. Get the
     current split with:

     ```bash
     ./bin/qlty-assistant scan --expect-min 1 --format json \
       | python3 -c "import json,sys,collections; d=json.load(sys.stdin); \
     f=[x for x in d['findings'] if x['rule']=='function-parameters' and x['file'].startswith('src/')]; \
     print(collections.Counter(x['value'] for x in f))"
     ```

     Anything reporting 6 has a real arity of 5 and is at or under the limit;
     only `>= 7` is worth reading closely.

  2. **Click command callbacks.** A function decorated with `@click.command` /
     `@click.option` has its signature dictated by the decorators — Click binds
     by parameter name, so collapsing the arguments into a dataclass breaks the
     CLI, which is a public-surface break under CLAUDE.md. `telemetry/
     cli_sessions.py` `agents` and `telemetry/parse_transcripts.py`
     `parse_transcripts` are both this case, and both are genuinely 6
     positional arguments — the only two current findings that are not
     separator-inflated. Each already forwards into a request dataclass
     (`AgentQueryRequest`, `TranscriptParseRequest`) on the first line of the
     body, which is this concern's prescribed fix applied as far as Click
     allows.

  qlty cannot distinguish either shape — `[smells.function_parameters]` exposes
  only `enabled` and `threshold`, with no keyword-only awareness — so these
  remain visible in `mode = "comment"` output. That is expected; do not raise
  the threshold to silence them, since doing so also stops flagging genuinely
  positional signatures.

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
