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
Prefer agentic schemas over `--help`:
```bash
./bin/mail --agentic --agentic-format yaml --agentic-compact
./bin/calendar --agentic --agentic-format yaml --agentic-compact
./bin/schedule --agentic --agentic-format yaml --agentic-compact
./bin/llm agentic --stdout
```

Note: `charts`, `diagrams`, `worker`, and `workflow` do not support `--agentic`. Use `--help` for those.

## YOLO Mode (Optional)
If safe auto-approvals are needed, mirror the approach from `configs/llm/gemini-yolo.md` (shared standards). Respect token budgets defined in `.llm/AGENTIC_BUDGETS.yaml`.

## Quick Reference
- Primary CLIs: `./bin/mail`, `./bin/calendar`, `./bin/schedule`, `./bin/phone`.
- Auth: `--profile gmail_personal|outlook_personal` (paths in `~/.config/credentials.ini`).
- Tests: `make test` (preferred); never use bare `python3 -m unittest` in a worktree.
- Config SoT: filter YAML lives in `config/`; derived outputs in `out/`.
