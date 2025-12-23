# Copilot Code Review Instructions

## Project Context

This is a Python 3.11 monorepo containing personal assistant CLIs (mail, calendar, schedule, phone, resume, whatsapp, wifi, desk, maker). The codebase follows a pipeline architecture with Consumer/Processor/Producer patterns.

## Review Priorities

### High Priority
- Security issues (credential exposure, injection vulnerabilities)
- Breaking changes to public CLI interfaces
- Missing error handling in pipeline processors
- Untested code paths in new features

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
- Use shared fixtures from `tests/fixtures.py` (`FakeGmailClient`, `FakeOutlookClient`)
- Prefer `assertGreater`/`assertLess` over `assertTrue(a > b)`
- Skip tests requiring network/auth with `@unittest.skip` and reason

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
