# Quick Start for LLM Agents

Follow this order for fast, token‑efficient familiarization:

1. Read `.llm/CONTEXT.md` for rules and layout
2. Skim `.llm/MIGRATION_STATE.md` for current status
3. Use `.llm/PATTERNS.md` for copy‑paste helpers
4. Consult `.llm/DOMAIN_MAP.md` to find commands/modules

Key commands:
- Create venv: `python3 -m venv .venv && source .venv/bin/activate`
- Install (editable): `pip install -e .`
- Compact agentic capsule: `./bin/mail-assistant --agentic`
- Domain map: `./bin/llm domain-map --stdout`
- Familiarize capsule: `./bin/llm familiar --stdout`
- Flows index: `./bin/llm flows --list`
- Single flow detail: `./bin/llm flows --id gmail.filters.plan-apply-verify --format md`
- Tests: `make test` or `python3 -m unittest -v`

Auth profiles (preferred):
- `~/.config/sre-utils/credentials.ini`
  - `[mail_assistant.gmail_personal]` (credentials, token)
  - `[mail_assistant.outlook_personal]` (outlook_client_id, tenant, outlook_token)

iOS scaffolding flows (examples):
- Export layout: `./bin/llm flows --id ios_export_layout --format md`
- Plan from export: `./bin/llm flows --id ios_scaffold_plan --format md`
- Manual checklist: `./bin/llm flows --id ios_manual_checklist --format md`
- Build .mobileconfig: `./bin/llm flows --id ios_profile_build --format md`
