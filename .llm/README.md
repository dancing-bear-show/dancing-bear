# 🤖 LLM Agent Knowledge Cache

Token‑efficient context for agents working on this repo

## Quick Start for LLM Agents

Read in order for best context:
1. `.llm/CONTEXT.md` — system overview and rules
2. `.llm/MIGRATION_STATE.md` — current status and remaining work
3. `.llm/PATTERNS.md` — copy‑paste templates for common tasks
4. `.llm/DOMAIN_MAP.md` — where things live in the codebase

See `.llm/QUICK_START.md` for a concise command summary.

## Unified CLIs (for agents)
- Prefer unified interface: `./bin/mail-assistant …`
- Use agentic help for compact schemas (avoid `--help`):
  - `./bin/mail-assistant --agentic --agentic-format yaml --agentic-compact`
  - `./bin/llm agentic --stdout`

## Maintenance Tools
- Inventory (regenerate and commit): `./bin/llm inventory --preserve` → updates `.llm/INVENTORY.md`
- Staleness/priorities: `./bin/llm stale --with-status --limit 10`
- Dependency hotspots: `./bin/llm deps --by combined --order desc --limit 10`
- Startup/drift check: `./bin/llm check --fail-on-stale`

## Documentation Organization
- `.llm/*` contains project‑level context tailored for agents
- Component context lives near code (e.g., `mail_assistant/`, `bin/`)

## Agent Handoff
- Humans start with `README.md`
- Agents start with `.llm/CONTEXT.md`, then `PATTERNS.md`

## Context Rules (concise)
- Python 3.9; minimal deps; lazy imports for optional deps
- Preserve CLI flags/subcommands; only add, do not break
- Prefer wrapper scripts: `./bin/assistant <mail|calendar|schedule|resume|phone|whatsapp|maker>`, or direct: `./bin/mail-assistant`, `./bin/calendar-assistant`
- Use persisted profiles in `~/.config/sre-utils/credentials.ini`
- Never commit secrets; mask/redact in logs; rotate if exposed

## Quick Commands
- See `.llm/COMMANDS.md` for a curated list.

Note
- `.llm/MIGRATION_STATE.md` is canonical for migration tracking.
