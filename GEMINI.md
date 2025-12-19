# Gemini Familiarize

Minimal-token guidance for Google Gemini to understand this repository.

## Startup: Automated Capsule
Generate and ingest the summary capsule:
```bash
./bin/llm familiar --stdout
```
This yields a YAML snapshot covering policies, roadmap, migration status, and agent workflows.

## On-Demand Context
Load only as needed:
- `.llm/CONTEXT.md` — architecture, rules, commands.
- `.llm/DOMAIN_MAP.md` — directory/auth map.
- `.llm/PATTERNS.md` — code templates for filters, CLI wiring, tests.

## Tool Discovery: Use --agentic
Avoid `--help`; prefer agentic schemas:
```bash
./bin/mail-assistant --agentic --agentic-format yaml --agentic-compact
./bin/calendar-assistant --agentic --agentic-format yaml --agentic-compact
./bin/schedule-assistant --agentic --agentic-format yaml --agentic-compact
./bin/llm --agentic --agentic-format yaml --agentic-compact
```

## YOLO Mode (Optional)
If safe auto-approvals are needed, mirror the approach from `configs/llm/gemini-yolo.md` (shared standards). Respect token budgets defined in `.llm/AGENTIC_BUDGETS.yaml`.

## Quick Reference
- CLIs: `./bin/mail-assistant`, `./bin/calendar-assistant`, `./bin/schedule-assistant`, `./bin/phone`.
- Auth: leverage `--profile gmail_personal|outlook_personal` (paths in `~/.config/credentials.ini`).
- Tests: `python3 -m unittest tests/test_cli.py -v`, `make test`.
- Config SoT: `config/filters_unified.yaml` for filters/rules; derived outputs in `out/`.
