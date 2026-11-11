# Copilot Code Review Instructions

## Project Context

This is a Python 3.11 monorepo containing personal assistant CLIs. It ships **20
packages** under `src/` — `apple_music`, `calendars`, `charts`, `core`, `desk`,
`diagrams`, `github_assistant`, `mail`, `maker`, `phone`, `qlty`, `resume`,
`schedule`, `sheets`, `slides`, `telemetry`, `whatsapp`, `wifi`, `worker`,
`workflow` — of which **19 are agentic-schema apps** (`core` is the shared
library). The codebase follows a
pipeline architecture with Consumer/Processor/Producer patterns.

All 19 apps support `--agentic --agentic-format json` (added in #291). Agents are
instructed to prefer capsules over `--help`, which makes a wrong command in a
capsule a machine-readable instruction to run something broken — not a stale
comment. `tests/core_tests/test_capsule_parser_drift.py` (#293) resolves every
command a capsule advertises against that CLI's real parser schema.

Do not assume the entry point is `./bin/<app>` — three differ: `apple-music` and
`qlty` use `-assistant` wrappers, and `resume` goes through
`./bin/assistant resume`. `./bin/llm inventory --stdout` is
the authoritative list.

## False-Positive Guards

Do NOT flag these patterns — they are intentional and correct:

### TYPE_CHECKING Imports

`TYPE_CHECKING` guards are used for forward references and to break import
cycles. Names imported under `if TYPE_CHECKING:` look unused at runtime but
are referenced in annotations. Before flagging an import as unused, check
whether the full file uses it in a type annotation, default argument, or
`isinstance()` call.

```python
from __future__ import annotations  # enables string-form annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from mail.providers.gmail import GmailClient  # used in: def send(client: GmailClient)
```

**Never flag**: an import whose only references are in type annotations, when
`from __future__ import annotations` is present at the top of the file.

### stderr vs stdout

Diagnostic output (warnings, errors, progress) belongs on stderr; data output
(JSON, CSV, YAML, tables) belongs on stdout. Flag the REVERSE of this — data
going to stderr or diagnostics going to stdout — not code that correctly sends
errors to stderr:

```python
# Correct — do NOT flag
print("No messages found", file=sys.stderr)
print(json.dumps(result))                    # data to stdout

# Flag this — data on stderr
print(json.dumps(result), file=sys.stderr)
```

## Verification Must Actually Verify

The most valuable findings in this repo's recent history are checks that **pass
while verifying nothing**. A false green is indistinguishable from a real one, so
flag any of these on sight:

- **Bare `python3 -m unittest`** (#282). In a worktree an inherited `PYTHONPATH`
  resolves imports to the *main checkout*, so tests run against unmodified source
  and pass. Require `make test`, or `PYTHONPATH="$PWD/src"`.
- **`qlty check` scanning zero files** (#282, #289). The exclusion was
  `**/.claude/**`, which matched the `.claude/` dir inside every agent worktree;
  a scan there reported `✔ No issues` against 0 files. Now narrowed to
  `**/.claude/worktrees/**`. Treat a surprisingly clean scan as suspect and
  confirm the file count.
- **Bare `ruff check`** — there is no standalone `ruff` on PATH. CI lints through
  `qlty check`. Use `make lint`.
- **A workflow/guard that reports success without doing the work** (#287): a
  dry run of the branch-hygiene workflow found a false-clean *inside the
  workflow written to prevent false-cleans*.

Reviewing code is not the same as running it. Three defects in #287 were
invisible across five review rounds and immediate on the first execution.

## qlty Findings Are Not All Real

Before requesting a change to satisfy a qlty finding, confirm the finding is real
(#275, #289). Known artifact classes:

- **`function-parameters` over-reports by one** on keyword-only signatures — it
  counts the bare `*` separator as a parameter. The threshold is 7 *reported*,
  which is 6 real; the written standard is still max 5 real. Read the signature.
- **`similar-code` on symlinks** — `bin/*` wrappers are symlinks to
  `bin/_router.py`; qlty followed each one and reported 24 clones of a single
  file.
- **`similar-code` on data tables and parallel test suites** — structurally
  identical entries in a literal dict, or per-command test classes that mirror
  parallel production code, have no shared logic to extract.
- Roughly 17 `similar-code` groups are an accepted baseline (#275), not a
  regression.
- Test fixtures/factories legitimately take wide keyword surfaces and are
  excluded from smells via `test_patterns` in `.qlty/qlty.toml`.

Prefer a genuine refactor; where a rule genuinely misfires, a suppression with a
stated reason is correct. Suppression codes are linter-specific:
- `# noqa: <code>` — ruff codes only (e.g. `F401`, `E402`). Never put a bandit
  or SonarQube code here; it suppresses nothing and may cause ruff to warn.
- `# nosec <code>` — bandit codes only (e.g. `B603`, `B607`).
- `# NOSONAR` — SonarQube suppression. **This codebase does not use SonarQube.**
  A `# NOSONAR` comment in this repo is dead annotation; use `# nosec` instead.
- Suppress bandit false positives with a reason comment explaining intent
  (see `tests/mail_tests/test_config_resolver.py` for the house style).

A SonarQube code in a `# noqa:` suppresses nothing — the same mismatch in
reverse. Always match the suppression syntax to the tool that produces the
finding.

## Review Priorities

### High Priority
- Security issues (credential exposure, injection vulnerabilities)
- Breaking changes to public CLI interfaces
- Missing error handling in pipeline processors
- Untested code paths in new features
- Cognitive complexity above 15 in any function (enforced by qlty in CI)

### Medium Priority
- Unused imports and dead code
- Missing type hints on public functions
- Empty except clauses without explanatory comments
- Inconsistent naming conventions

### Low Priority
- Minor style inconsistencies
- Documentation formatting
- Test organization

## Code Standards

### Imports
- Use `from __future__ import annotations` for forward references
- Lazy import optional dependencies (google-api, msal, pyyaml) inside functions
- Group imports: stdlib, third-party, local

### Error Handling
- All `except` clauses must have explanatory comments if they pass
- Pipeline processors should return `ResultEnvelope` with diagnostics on error
- Never silently swallow exceptions in CLI commands

### Testing
- Use shared fakes from `tests/fakes/` (`FakeGmailClient` in `tests/fakes/gmail.py`,
  `FakeOutlookClient` in `tests/fakes/outlook.py`, DOCX fakes in
  `tests/fakes/docx.py`); other shared helpers live in `tests/fixtures.py`
- Prefer `assertGreater`/`assertLess` over `assertTrue(a > b)`
- Skip tests requiring network/auth with `@unittest.skip` and reason
- A test must assert behaviour. Do not add tests whose only purpose is to import
  a module and raise its coverage number; `*/__main__.py` is omitted in
  `.coveragerc` for exactly this reason. Conversely, do not exempt a module
  because it reports 0% — check why first. `src/telemetry/tui/` reported 0%
  only because `textual` was an undeclared optional dep, which is
  indistinguishable from untested code.
- Cover both the happy and the sad path. Several recent fixes (#292, #294, #297,
  #298) were rendering defects that a happy-path-only test suite passed over.

### Type Boundaries

An active migration is closing `dict[str, Any]` boundaries onto typed schemas
(#279, #290, #294, #295). Two rules follow from it:

- Do not accept `Resume | dict` (or similar unions) at an entry point and lift
  the dict internally. `Resume.from_dict` applies one-directional upgrades that
  **rewrite** the data — a scalar `summary` becomes a single-item list, `list[str]`
  bullets become `PriorityItem`s, contact values get promoted to top-level
  scalars. The same dict was a type error on one path and silently normalized on
  its sibling (#295). Require the typed object; convert at the outer edge.
- Flag sibling entry points in one module that disagree on whether they accept a
  typed value or a dict. That asymmetry is the bug.

### Subprocess Calls

`subprocess` invocations carry a pinned contract (#299). When reviewing one:

- argv must be a `list` of `str`, and `shell=` must never be passed.
- Assert the invocation element-by-element, not with `assertIn`. Paths
  containing spaces, quotes, `;`, `$( )`, backticks, `&&` or `|` must reach argv
  verbatim — a path with a space stays one element.
- **`timeout=` is required** on every `subprocess.run`, `check_output`, and
  `call` invocation; an unbounded wait hangs CI and blocks the whole runner.
  For `Popen`, an unbounded `communicate()` or `wait()` has the same effect.
  Bounded waits and intentionally detached daemons (documented as such) are fine.
- Pin `capture_output`.
- Test the negative: assert the subprocess is **not** invoked when a pre-check
  fails, and that argument validation raises before the process would run.

### Mask Before Emit

Credential values, tokens, and secrets must be masked **before** they appear in
any log message, exception text, or diagnostic output — masking applied after a
value was already emitted is not a fix.

```python
# Flag this — token leaks into logs before masking
log.debug("token=%s", token)
log.debug("token=%s", mask(token))  # too late if the first line already ran

# Correct — mask first, never emit the raw value
log.debug("token=%s", mask(token))
```

The same rule applies to truncation: if a value is truncated before display,
truncate before masking, not the other way around — a suffix-truncated secret
may still be reconstructable.

### Workflow YAML

- Workflows call tested CLI surfaces; do not embed Python in workflow YAML
  (#270). Embedded code is untestable and unauditable.
- `writes_to` gets no `{param}` substitution, and `kind: validate` stages
  discard `description` — the contract must live in `validation.criteria`.
  Neither is visible to `workflow lint`.

### Complexity

Enforced by qlty in CI; see `concerns/complexity.md` for the full guide.

- Cognitive complexity must not exceed 15 per function. Scoring: `if`/`for`/
  `while`/`try` add 1 + current nesting depth; `except` adds 1 flat; `break`/
  `continue` add 1 each; a boolean chain adds (operands - 1); recursion adds 1.
  `elif` counts as an `if` at incremented depth. `else` is not itself counted,
  but its body is traversed.
- Flag functions in the 11-15 range for simplification while the cost is low.
- Keep function bodies within 3 levels of nesting.
- Prefer named helpers, dispatch tables over `if`/`elif` chains, and early
  returns to flatten nesting.
- Signatures should stay within 5 real parameters. qlty's reported count is not
  real arity — it *excludes* `self`/`cls` but counts the bare `*` separator as a
  parameter, so a keyword-only signature reports one higher than it takes. Read
  the signature before filing a finding, and don't split a cohesive signature
  just to lower a count. Full counting caveat, with verified fixtures, in
  `concerns/complexity.md#too-many-parameters`.
- Files over ~800 lines warrant a split by responsibility.

### CLI Conventions
- Keep public flags/subcommands stable (additive changes only)
- Support `--agentic` flag for token-efficient schema output
- Use profiles from `~/.config/credentials.ini` over CLI credential args
- Internal APIs are refactored freely — update all call sites atomically. Do
  **not** add backwards-compatible wrappers or re-export facades for internal
  moves. This applies to test patch targets too. Public `bin/*` entry points are
  the opposite: those stay stable.
- Note that some `llm_cli.py` modules look like removable facades but are live
  `llm --app <name>` dispatch targets resolved by string literal in
  `core/llm_handlers.py`'s `_APP_MODULES`. Deleting one breaks dispatch silently.

### Generated Output and PII
- Generated artifacts are written **outside the checkout**, resolved by
  `src/core/paths.py` (`--out-dir` → `$DANCING_BEAR_DATA_HOME` →
  `$XDG_DATA_HOME/dancing-bear` → `~/.local/share/dancing-bear`).
- New output-producing code must call `core.paths.output_dir("<domain>")` rather
  than defaulting to a relative path. A relative default resolves against the
  working directory, which wrote resumes carrying PII into the checkout (#269).
- Test fixtures must never be seeded from real profile data — goldens built from
  them are committed permanently (#268).

## Concern Library

`concerns/` holds the detailed review guides this file summarises — 14 guides,
each concern carrying a check, triggers, and a worked example. **Where this file
and a concern guide disagree, the guide wins**; it is the maintained source and
carries the reasoning. Load selectively by the file types in the diff rather
than reading them all. (Per-guide concern counts live in `concerns/README.md`;
they are not repeated here, as that table has already drifted from the actual
`###` heading counts.)

The canonical selection rules live in `concerns/selection.yaml` — that file is
the single source of truth for which guide applies to which file type or path.
(Copilot cannot run the CLI selector, so consult the YAML directly for the full
rule set.)

Two concerns worth knowing before filing a finding, because both are commonly
reported backwards:

- `complexity.md#too-many-parameters` — qlty's count excludes `self`/`cls` but
  counts the bare `*`, so keyword-only signatures over-report by one.
- `security.md#nosec-rationale-accuracy` — a `nosec`/`NOSONAR` comment whose
  stated reason does not match what the code actually does is itself a finding.
  Check the rationale, not just the presence of a suppression.

## Files to Skip

Don't review these paths:
- `.venv/`, `__pycache__/`, `*.egg-info/`
- `out/`, `_out/`, `backups/`
- `_disasm/` (read-only reference)

## Commit Message Format

Expect conventional commits: `type(scope): description`
- Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`
- Scopes are the app or area, not a fixed enum. Domain scopes: `mail`,
  `calendars`, `schedule`, `phone`, `resume`, `whatsapp`, `wifi`, `desk`,
  `slides`, `sheets`, `charts`, `diagrams`, `workflow`, `telemetry`, `worker`,
  `qlty`, `core`, `cli`, `bin`. Cross-cutting scopes also in active use:
  `workflows` (the YAML DAGs under `workflows/`, distinct from the `workflow`
  engine), `agents`, `tooling`, `lint`, `tests`, `coverage`, `security`,
  `vulture`, `claude`.
