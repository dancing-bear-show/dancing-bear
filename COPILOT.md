# GitHub Copilot / Codex Familiarize

Minimal-token approach for Copilot to get oriented in this repository.

## Startup: Read Context Files

Read these files in order for a fast bootstrap:

### Tier 1: Essential Context (~400 tokens total)
1. **`.llm/QUICK_START.md`** — project overview, primary CLIs, auth, testing.
2. **`.llm/FAMILIARIZE_CORE.md`** — architecture patterns and key rules.

### Tier 2: Detailed Context (On-Demand)
Load only when deeper detail is needed:
- **`.llm/CONTEXT.md`** — full architecture, rules, and commands.
- **`.llm/DOMAIN_MAP.md`** — directory/auth map.
- **`.llm/PATTERNS.md`** — code templates for filters, CLI wiring, etc.

### Tier 3: Automated Capsule
Token-efficient summary:
```bash
./bin/llm familiar --stdout
```

## Tool Discovery: Use --agentic
Prefer agentic schemas over `--help`:
```bash
./bin/mail-assistant --agentic --agentic-format yaml --agentic-compact
./bin/calendar --agentic --agentic-format yaml --agentic-compact
./bin/schedule-assistant --agentic --agentic-format yaml --agentic-compact
./bin/llm --agentic --agentic-format yaml --agentic-compact
```

## YOLO Mode (Optional)
For safe auto-approvals, follow `configs/llm/copilot-yolo.md` guidance (shared with other repos). Honor token budgets from `.llm/AGENTIC_BUDGETS.yaml`.

## Quick Reference
- **Primary CLIs**:
  ```bash
  ./bin/mail-assistant filters plan --config config/filters_unified.yaml --delete-missing
  ./bin/mail-assistant outlook rules plan --config out/filters.outlook.from_unified.yaml --move-to-folders
  ./bin/calendar outlook add-from-config --config config/calendar/your_family_blas.yaml
  ```
- **Auth**: Stored in `~/.config/credentials.ini` (use `--profile gmail_personal|outlook_personal`).
- **Tests**: `python3 -m unittest tests/test_cli.py -v` or `make test`.
- **Code patterns**: Extend helpers in `mail_assistant/providers`, `mail_assistant/utils`, keep CLIs thin, and reuse YAML DSLs.
