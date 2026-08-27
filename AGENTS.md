# Repository Agent Hints

This repository hosts personal assistants (mail, calendar, schedule, phone, resume, whatsapp,
wifi, desk, apple_music, maker, charts, diagrams, slides, sheets, qlty, workflow, worker,
telemetry).

## Quick Start for Agents

1. Read `.llm/CONTEXT.md` for system overview and rules
2. Use `.llm/PATTERNS.md` for copy-paste templates
3. Generate the domain map on demand: `./bin/llm domain-map --stdout` (CLI tree + module
   locations; it is not a checked-in file)
4. See `.llm/COMMANDS.md` for curated command reference

## Agentic Schemas (prefer over --help)

```bash
./bin/mail --agentic --agentic-format yaml --agentic-compact
./bin/llm agentic --stdout
./bin/llm domain-map --stdout
```

`./bin/llm inventory --stdout` lists which CLIs expose `--agentic` and which need `--help`.

## Key Rules

- Python 3.11; keep modules dependency-light
- Prefer wrapper executables (`./bin/mail`) over `python -m`
- Use profiles in `~/.config/credentials.ini`; avoid passing tokens on CLI
- Keep public CLI stable; add new commands, don't break existing ones
- Never commit credentials or tokens

## Architecture

19 packages under `src/`:
```
mail/         Gmail/Outlook providers, CLI wiring
calendars/    Outlook calendar CLI + Gmail scans
schedule/     plan/apply calendar schedules
resume/       extract/summarize/render resumes
phone/        iOS layout tooling
whatsapp/     local-only ChatStorage search
wifi/         diagnostics
desk/         macOS filesystem tidying (no bin/ wrapper; python3 -m desk)
apple_music/  Apple Music API
maker/        utility generators
charts/       time-series chart rendering
diagrams/     Mermaid diagram generation
slides/       PowerPoint deck generation from YAML
sheets/       styled .xlsx generation from YAML
qlty/         qlty scan/triage wrapper
workflow/     YAML DAG engine
worker/       background job queue and daemon
telemetry/    Claude Code session telemetry
core/         shared helpers and CLI framework
bin/          entry wrappers (see bin/_wrappers.yaml)
.llm/         LLM context, flows, capsules
config/       YAML inputs (source of truth)
```

Generated output lands outside the checkout (`src/core/paths.py`): `--out-dir`, else
`$DANCING_BEAR_DATA_HOME`, else `$XDG_DATA_HOME/dancing-bear`, else `~/.local/share/dancing-bear`.

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
