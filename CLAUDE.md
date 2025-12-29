# Claude Code Project Instructions

## Project Overview

Personal Assistants: unified, dependency-light CLIs for personal workflows across mail, calendars, schedules, phone layouts, resumes, and WhatsApp. Built to be safe by default (plan and dry-run first), with a single YAML source of truth for Gmail and Outlook filters.

**Constraints:** Python 3.11, dependency-light, stable public CLI

**Primary consumers:** LLM agents — CLI schemas, help text, and agentic capsules are designed for token-efficient LLM consumption. Keep output terse and accurate.

## Quick Start

```bash
# Setup
make venv

# Run tests
make test

# CLI help
./bin/assistant <mail|calendar|schedule|resume|phone|whatsapp|maker> --help
./bin/mail-assistant --help
./bin/calendar-assistant --help
```

## Architecture

```
mail/                     # Gmail/Outlook providers, CLI wiring, helpers
calendars/                # Outlook calendar CLI + Gmail scans
schedule/                 # plan/apply calendar schedules
resume/                   # extract/summarize/render resumes
phone/                    # iOS layout tooling
whatsapp/                 # local-only ChatStorage search
desk/                     # desktop/workspace tooling
maker/                    # utility generators
bin/                      # entry wrappers and helper scripts
core/                     # shared helpers
tests/                    # lightweight unittest suite
.llm/                     # LLM context, flows, capsules
config/                   # YAML inputs (canonical source of truth)
out/                      # derived outputs and plans
```

## LLM Context Files

Read in order for best context:
1. `.llm/CONTEXT.md` - system overview and rules
2. `.llm/MIGRATION_STATE.md` - current status and remaining work
3. `.llm/PATTERNS.md` - copy-paste templates for common tasks
4. `.llm/DOMAIN_MAP.md` - where things live in the codebase

## Development Rules

**Do:**
- Keep CLI flags/subcommands stable; add new under `labels`, `filters`, `outlook`
- Prefer wrapper executables (`./bin/mail-assistant`) over `python -m`
- Use profiles in `~/.config/credentials.ini`; avoid `--credentials/--token`
- Apply lazy imports for optional deps (Google APIs, PyYAML)
- Keep helpers small, focused; prefer OO where cohesive (e.g., LabelSync, FilterSync)
- Update README minimally when adding user-facing commands; add tests for new CLI surfaces

**LLM Consumer Rules:**
- Keep help text terse (1-line descriptions, no prose)
- Ensure `--help` output matches actual implementation
- Verify agentic schema (`--agentic`) accurately reflects CLI structure
- Use `--agentic-compact` output for token efficiency
- Test CLI discovery: `./bin/llm agentic --stdout` must be accurate
- Flows in `.llm/FLOWS.yaml` must reference valid CLI paths

**Avoid:**
- Broad refactors that rename modules or move public entry points
- Heavy new dependencies; global imports for optional modules
- Emitting secrets/tokens in logs or passing them via flags
- Bare `except Exception: continue/pass` blocks without a `# nosec` comment explaining the intent (e.g., `# nosec B110 - skip malformed entries silently`)
- Verbose help strings that waste tokens
- Mismatched argument names between argparse and code

## Testing

- Run tests: `make test` or `python3 -m unittest -v`
- CI: `.github/workflows/ci.yml` runs tests on push and PRs
- Add targeted tests only for new CLI surfaces/behaviors
- Never run tests that require network/secrets without explicit user approval

## Key Commands

```bash
# Token-efficient agentic schemas (prefer over --help)
./bin/mail-assistant --agentic --agentic-format yaml --agentic-compact
./bin/llm agentic --stdout

# Domain map
./bin/llm domain-map --stdout

# Flows
./bin/llm flows --list
./bin/llm flows --id <flow_id> --format md
```

## Credentials (Profiles)

Use profiles in `~/.config/credentials.ini`:

```ini
[mail.gmail_personal]
credentials = /path/to/google_credentials.json
token = /path/to/token.json

[mail.outlook_personal]
outlook_client_id = <YOUR_APP_ID>
tenant = consumers
outlook_token = /path/to/outlook_token.json
```

## Config Source of Truth

- Canonical filters: `config/filters_unified.yaml`
- Derived configs: `out/filters.gmail.from_unified.yaml`, `out/filters.outlook.from_unified.yaml`
- Always run plan first, then apply with dry-run, then apply for real

## Security

- Never commit `credentials.json` or tokens
- Restrict scopes to labels/settings/readonly/modify where required
- If sensitive data appears in logs, redact and rotate immediately

## PR Reviews

When reviewing PRs, follow `.github/CLAUDE_REVIEW.md` for detailed guidelines. Key points:
- Prioritize: Security > Bugs > Breaking Changes > Tests > Maintainability
- Use severity markers: 🔴 Blocking, 🟡 Suggestions, 🟢 Nice to Have
- Include file:line references and concrete fix suggestions
- Skip style nitpicks and generated files

## Ignore During Scanning

Skip these heavy/non-core paths: `.venv/`, `.cache/`, `.git/`, `maker/`, `_disasm/`, `out/`, `_out/`, `backups/`, `personal_assistants.egg-info/`
