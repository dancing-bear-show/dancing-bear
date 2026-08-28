# Copilot Code Review Instructions

## Project Context

This is a Python 3.11 monorepo containing personal assistant CLIs. It ships **19
packages** under `src/` — `apple_music`, `calendars`, `charts`, `core`, `desk`,
`diagrams`, `mail`, `maker`, `phone`, `qlty`, `resume`, `schedule`, `sheets`,
`slides`, `telemetry`, `whatsapp`, `wifi`, `worker`, `workflow` — of which **18
are agentic-schema apps** (`core` is the shared library). The codebase follows a
pipeline architecture with Consumer/Processor/Producer patterns.

All 18 apps support `--agentic --agentic-format json` (added in #291). Agents are
instructed to prefer capsules over `--help`, which makes a wrong command in a
capsule a machine-readable instruction to run something broken — not a stale
comment. `tests/core_tests/test_capsule_parser_drift.py` (#293) resolves every
command a capsule advertises against that CLI's real parser schema.

Do not assume the entry point is `./bin/<app>` — four differ: `apple-music` and
`qlty` use `-assistant` wrappers, `resume` goes through `./bin/assistant resume`,
and `desk` has no wrapper (`python3 -m desk`). `./bin/llm inventory --stdout` is
the authoritative list.

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
stated reason is correct. Suppression codes are linter-specific: `# noqa:` takes
ruff codes, `# NOSONAR` takes SonarQube codes (S3776), `# nosec` takes bandit
codes (B603). A SonarQube code in a `# noqa:` suppresses nothing.

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
- Pin `timeout` and `capture_output`.
- Test the negative: assert the subprocess is **not** invoked when a pre-check
  fails, and that argument validation raises before the process would run.

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
- Signatures should stay within 5 parameters (excluding `self`/`cls`). Note
  qlty's reported count is not real arity — it counts `self`/`cls` and the bare
  `*` separator, so keyword-only signatures report one higher than they take.
  Read the signature before filing a finding, and don't split a cohesive
  signature just to lower a count.
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
