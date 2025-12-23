# Claude Code Project Instructions

## Project Overview

Personal Assistants: unified, dependency-light CLIs for personal workflows across mail, calendars, schedules, phone layouts, resumes, and WhatsApp. Built to be safe by default (plan and dry-run first), with a single YAML source of truth for Gmail and Outlook filters.

**Constraints:** Python 3.11, dependency-light, stable public CLI

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
mail_assistant/           # Gmail/Outlook providers, CLI wiring, helpers
calendar_assistant/       # Outlook calendar CLI + Gmail scans
schedule_assistant/       # plan/apply calendar schedules
resume_assistant/         # extract/summarize/render resumes
phone/                    # iOS layout tooling
whatsapp/                 # local-only ChatStorage search
maker/                    # utility generators
bin/                      # entry wrappers and helper scripts
core/, personal_core/     # shared helpers
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

**Avoid:**
- Broad refactors that rename modules or move public entry points
- Heavy new dependencies; global imports for optional modules
- Emitting secrets/tokens in logs or passing them via flags

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
[mail_assistant.gmail_personal]
credentials = /path/to/google_credentials.json
token = /path/to/token.json

[mail_assistant.outlook_personal]
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

## Ignore During Scanning

Skip these heavy/non-core paths: `.venv/`, `.cache/`, `.git/`, `maker/`, `_disasm/`, `out/`, `_out/`, `backups/`, `personal_assistants.egg-info/`
