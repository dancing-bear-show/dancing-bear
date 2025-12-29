# Claude PR Review Guidelines

Instructions for Claude when reviewing pull requests in this repository.

## Key Context

**This library is primarily consumed by LLM agents.** The CLI schemas, help text, and agentic capsules are designed for token-efficient LLM consumption, not human reading. Keep this in mind when reviewing.

## Review Philosophy

- **Be constructive, not pedantic** — Focus on issues that matter, not style nitpicks
- **Assume competence** — The author likely considered alternatives; ask rather than dictate
- **Prioritize by impact** — Security > Bugs > Performance > Maintainability > Style
- **Be specific** — Include file paths, line numbers, and concrete suggestions

## What to Look For

### Must Flag (Blocking)

1. **Security Issues**
   - Credentials/tokens in code or logs
   - Command injection (unsanitized input to subprocess/os.system)
   - Path traversal vulnerabilities
   - SQL injection in any database queries
   - Missing input validation at system boundaries

2. **Bugs & Logic Errors**
   - Off-by-one errors, incorrect conditionals
   - Unhandled edge cases (None, empty lists, missing keys)
   - Resource leaks (unclosed files, connections)
   - Race conditions in concurrent code

3. **Breaking Changes**
   - CLI flag/subcommand removals or renames
   - Changed return types or signatures on public functions
   - Removed exports from `__init__.py`

4. **CLI Discovery Accuracy** (Critical for LLM consumers)
   - Incorrect or misleading help text
   - Mismatched argument names between help and implementation
   - Missing or wrong subcommand listings in `--help`
   - Agentic schema (`--agentic`) output doesn't match actual CLI
   - `build_cli_tree()` output is incomplete or wrong
   - Flow specs reference non-existent CLI paths

5. **Token Bloat** (LLM efficiency)
   - Unnecessarily verbose help strings (keep terse for token efficiency)
   - Redundant information in agentic capsules
   - Large default outputs that could be paginated/limited
   - Duplicate content across `.llm/` files

### Should Flag (Non-blocking)

1. **Test Coverage**
   - New CLI commands without tests
   - Complex logic without unit tests
   - Missing edge case coverage

2. **Error Handling**
   - Bare `except:` or `except Exception:` without `# noqa: S110` comment
   - Swallowed exceptions that hide failures
   - Missing error messages for user-facing failures

3. **Code Organization**
   - Functions over 50 lines that could be split
   - Deeply nested conditionals (3+ levels)
   - Duplicate code blocks (3+ occurrences)

### Don't Flag (Unless Asked)

- Minor style preferences (single vs double quotes, etc.)
- Import ordering (let tools handle it)
- Missing docstrings on internal functions
- Type hints on simple, obvious functions
- Comments explaining self-evident code

## Project-Specific Rules

### This Codebase

```
Constraints: Python 3.11, dependency-light, stable CLI
Pattern: Consumer → Processor → Producer pipelines
Config: YAML source of truth in config/
Primary consumers: LLM agents (token efficiency matters)
```

### LLM Consumer Requirements

Since LLMs consume this library's output, verify:

1. **CLI Discovery** — Can an LLM accurately discover available commands?
   ```bash
   # These must produce accurate, complete output:
   ./bin/mail-assistant --help
   ./bin/mail-assistant --agentic --agentic-format yaml --agentic-compact
   ./bin/llm agentic --stdout
   ```

2. **Token Efficiency** — Is output as compact as possible?
   - Help text: 1-line descriptions, no prose
   - Agentic output: structured, no redundancy
   - Default limits on list commands (e.g., `--limit 50`)

3. **Accuracy** — Does help match implementation?
   ```python
   # Check: argument names in add_argument() match what code uses
   parser.add_argument("--days", ...)  # Must match: args.days
   ```

### Check These Patterns

1. **Lazy Imports** — Optional deps (google-api, pyyaml, docx) must use lazy imports:
   ```python
   # Good
   def process():
       from docx import Document  # Lazy

   # Bad
   from docx import Document  # Top-level breaks when not installed
   ```

2. **Pipeline Pattern** — New commands should follow Consumer/Processor/Producer:
   ```python
   # Check: Does new command use the pipeline pattern?
   # mail/*/commands.py should wire Consumer → Processor → Producer
   ```

3. **Dry-Run Support** — Mutating operations need `--dry-run`:
   ```python
   # Check: Does the command modify external state?
   # If yes, must support dry_run parameter
   ```

4. **Exception Suppression** — Must have explanatory comment:
   ```python
   # Good
   except Exception:  # noqa: S110 - skip malformed entries silently
       pass

   # Bad
   except Exception:
       pass
   ```

## Review Output Format

Structure your review as:

```markdown
## Summary
[1-2 sentence overall assessment]

## Issues

### 🔴 Blocking
[List critical issues that must be fixed]

### 🟡 Suggestions
[List non-critical improvements]

### 🟢 Nice to Have
[Optional polish, only if helpful]

## Questions
[Clarifications needed from author]
```

### Example Review

```markdown
## Summary
Solid implementation of the new `filters sweep-range` command. One security concern and a few suggestions.

## Issues

### 🔴 Blocking
- **mail/filters/commands.py:142** — User input passed directly to query without sanitization. Could allow query injection.
  ```python
  # Current
  query = f"from:{args.sender}"

  # Suggested
  query = f"from:{sanitize_query(args.sender)}"
  ```

### 🟡 Suggestions
- **mail/filters/processors.py:89** — Consider adding `--dry-run` support since this modifies message labels.
- **tests/mail_tests/test_filters_sweep.py** — Missing test for empty result set case.

### 🟢 Nice to Have
- The `_batch_messages` helper could be extracted to `mail/utils/` for reuse.

## Questions
- Is the 500 message batch size intentional? Gmail API allows up to 1000.
```

## What NOT to Do

1. **Don't suggest massive refactors** — Small, focused PRs are intentional
2. **Don't add features** — Review what's there, not what could be added
3. **Don't repeat CI feedback** — If tests/lint failed, CI will report it
4. **Don't be vague** — "This could be better" is not actionable
5. **Don't review generated files** — Skip `out/`, `.llm/AGENTIC*.md`, etc.

## File-Specific Guidance

| Path Pattern | Focus On |
|--------------|----------|
| `*/commands.py` | CLI wiring, dry-run support, error messages |
| `*/processors.py` | Business logic, edge cases, error handling |
| `*/consumers.py` | Input validation, payload construction |
| `*/producers.py` | Output formatting, side effects |
| `*/agentic.py` | **CLI accuracy**, token efficiency, complete coverage |
| `*/llm_cli.py` | Correct routing, schema completeness |
| `*/cli.py` | Help text accuracy, argument naming consistency |
| `.llm/*.md` | No stale info, minimal redundancy |
| `tests/**/*.py` | Coverage completeness, mock correctness |
| `config/*.yaml` | Schema validity, no secrets |
| `.github/**` | Workflow security, permissions |

## Skip These Paths

Don't review files in: `.venv/`, `.cache/`, `.git/`, `out/`, `_out/`, `backups/`, `*.egg-info/`
