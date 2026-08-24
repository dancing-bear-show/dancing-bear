# Repository Agent Hints

This repository hosts personal assistants (mail, calendar, schedule, phone, resume, whatsapp,
wifi, desk, apple_music, maker, charts, diagrams, workflow, worker, telemetry).

## Quick Start for Agents

1. Read `.llm/CONTEXT.md` for system overview and rules
2. Use `.llm/PATTERNS.md` for copy-paste templates
3. Check `.llm/DOMAIN_MAP.md` for CLI tree and module locations
4. See `.llm/COMMANDS.md` for curated command reference

## Agentic Schemas (prefer over --help)

```bash
./bin/mail --agentic --agentic-format yaml --agentic-compact
./bin/llm agentic --stdout
./bin/llm domain-map --stdout
```

Note: `charts`, `diagrams`, `worker`, and `workflow` do not support `--agentic`. Use `--help` for those.

## Key Rules

- Python 3.11; keep modules dependency-light
- Prefer wrapper executables (`./bin/mail`) over `python -m`
- Use profiles in `~/.config/credentials.ini`; avoid passing tokens on CLI
- Keep public CLI stable; add new commands, don't break existing ones
- Never commit credentials or tokens

## Architecture

17 packages under `src/`:
```
mail/         Gmail/Outlook providers, CLI wiring
calendars/    Outlook calendar CLI + Gmail scans
schedule/     plan/apply calendar schedules
resume/       extract/summarize/render resumes
phone/        iOS layout tooling
whatsapp/     local-only ChatStorage search
wifi/         diagnostics
desk/         macOS filesystem tidying
apple_music/  Apple Music API
maker/        utility generators
charts/       time-series chart rendering
diagrams/     Mermaid diagram generation
workflow/     YAML DAG engine
worker/       background job queue and daemon
telemetry/    Claude Code session telemetry
core/         shared helpers and CLI framework
bin/          entry wrappers (see bin/_wrappers.yaml)
.llm/         LLM context, flows, capsules
config/       YAML inputs (source of truth)
out/          derived outputs and plans
```

## Testing

```bash
make test
# or: PYTHONPATH="$PWD/src" python3 -m unittest discover -s tests
```

Never run bare `python3 -m unittest` in a worktree — an inherited `PYTHONPATH` silently
resolves imports to the main checkout and produces false greens. Use `make check-env` to
verify your environment.

## Per-Module Context

Look for `AGENTS.md` files in subdirectories for domain-specific instructions:
- `src/mail/AGENTS.md`
- `src/calendars/AGENTS.md`
- `src/phone/AGENTS.md`
