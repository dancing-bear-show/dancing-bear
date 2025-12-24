# Repository Agent Hints

This repository hosts personal assistants (mail, calendar, schedule, phone, resume, whatsapp, maker).

## Quick Start for Agents

1. Read `.llm/CONTEXT.md` for system overview and rules
2. Use `.llm/PATTERNS.md` for copy-paste templates
3. Check `.llm/DOMAIN_MAP.md` for CLI tree and module locations
4. See `.llm/COMMANDS.md` for curated command reference

## Agentic Schemas (prefer over --help)

```bash
./bin/mail-assistant --agentic --agentic-format yaml --agentic-compact
./bin/llm agentic --stdout
./bin/llm domain-map --stdout
```

## Key Rules

- Python 3.11; keep modules dependency-light
- Prefer wrapper executables (`./bin/mail-assistant`) over `python -m`
- Use profiles in `~/.config/credentials.ini`; avoid passing tokens on CLI
- Keep public CLI stable; add new commands, don't break existing ones
- Never commit credentials or tokens

## Architecture

```
mail/           # Gmail/Outlook providers, CLI wiring
calendars/       # Outlook calendar CLI + Gmail scans
schedule/       # plan/apply calendar schedules
resume/         # extract/summarize/render resumes
phone/                    # iOS layout tooling
whatsapp/                 # local-only ChatStorage search
maker/                    # utility generators
bin/                      # entry wrappers
core/                     # shared helpers
.llm/                     # LLM context, flows, capsules
config/                   # YAML inputs (source of truth)
out/                      # derived outputs and plans
```

## Testing

```bash
make test  # or: python3 -m unittest -v
```

## Per-Module Context

Look for `AGENTS.md` files in subdirectories for domain-specific instructions:
- `mail/AGENTS.md`
- `calendars/AGENTS.md`
- `phone/AGENTS.md`
- etc.
