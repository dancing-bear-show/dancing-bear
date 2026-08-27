# GitHub Copilot Familiarize

Minimal-token approach for Copilot to get oriented in this repository.

## Startup: Read Context Files

Read these files in order for a fast bootstrap:

### Tier 1: Essential Context (~400 tokens total)
1. **`.llm/CONTEXT.md`** — system overview, architecture, and rules.
2. **`.llm/COMMANDS.md`** — curated command reference.

### Tier 2: Detailed Context (On-Demand)
Load only when deeper detail is needed:
- **`./bin/llm domain-map --stdout`** — CLI tree, flows index, binaries (generated on demand).
- **`.llm/PATTERNS.md`** — code templates for filters, CLI wiring, etc.
- **`.llm/MIGRATION_STATE.md`** — provider abstraction status.

### Tier 3: Automated Capsule
Token-efficient summary:
```bash
./bin/llm familiar --stdout
```

## Tool Discovery: Use --agentic
Prefer agentic schemas over `--help`:
```bash
./bin/mail --agentic --agentic-format yaml --agentic-compact
./bin/calendar --agentic --agentic-format yaml --agentic-compact
./bin/schedule --agentic --agentic-format yaml --agentic-compact
./bin/llm agentic --stdout
```

All 18 apps support `--agentic`. `./bin/llm inventory --stdout` prints the exact invocation for each — `./bin/<app>` is wrong for four of them.

## Token Budgets
Honor token budgets from `.llm/AGENTIC_BUDGETS.yaml`.

## Quick Reference
- Primary CLIs:
  ```bash
  ./bin/mail filters plan --config filters.gmail.from_unified.yaml --delete-missing
  ./bin/mail outlook rules.plan --config filters.outlook.from_unified.yaml --move-to-folders
  ./bin/calendar outlook add-from-config --config config/calendar/your_family_blas.yaml
  ```
  Outlook and config subcommands are dot-separated (`rules.plan`, `derive.filters`), not
  space-separated.
- Auth: stored in `~/.config/credentials.ini` (use `--profile gmail_personal|outlook_personal`).
- Tests: `make test` (preferred); never use bare `python3 -m unittest` in a worktree.
- Code patterns: extend helpers in `src/mail/providers`, `src/mail/utils`, keep CLIs thin, reuse YAML DSLs.
