# Copilot Code Review Instructions

## Project Context

This is a Python 3.11 monorepo containing personal assistant CLIs (mail, calendar, schedule, phone, resume, whatsapp, wifi, desk, maker). The codebase follows a pipeline architecture with Consumer/Processor/Producer patterns.

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
  `FakeOutlookClient` in `tests/fakes/outlook.py`); other shared helpers live in
  `tests/fixtures.py`
- Prefer `assertGreater`/`assertLess` over `assertTrue(a > b)`
- Skip tests requiring network/auth with `@unittest.skip` and reason

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

## Files to Skip

Don't review these paths:
- `.venv/`, `__pycache__/`, `*.egg-info/`
- `out/`, `_out/`, `backups/`
- `_disasm/` (read-only reference)

## Commit Message Format

Expect conventional commits: `type(scope): description`
- Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`
- Scopes: `mail`, `calendar`, `phone`, `resume`, `whatsapp`, `wifi`, `core`, `tests`
