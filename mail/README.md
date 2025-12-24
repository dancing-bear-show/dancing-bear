Mail Assistant

Overview
- Gmail/Outlook CLI for labels, filters/rules, signatures and cache helpers.
- Uses profiles in `~/.config/credentials.ini` (e.g., `--profile gmail_personal`, `--profile outlook_personal`).

Quick Start
- Venv: `python3 -m venv .venv && source .venv/bin/activate && pip install -e .`
- Help: `./bin/mail-assistant --help`
- Agentic capsule (LLM): `python3 -m mail --agentic`
- LLM utilities wrapper: `./bin/llm agentic --stdout` (or `--write .llm/AGENTIC.md`)
- Initialize LLM meta: `./bin/llm derive-all --out-dir .llm` (or `--stdout`). Generated files (AGENTIC.md, DOMAIN_MAP.md) are built on demand; pass `--include-generated` to write them.
- LLM domain map: `./bin/llm domain-map --stdout` (or `--write .llm/DOMAIN_MAP.md`)
- LLM inventory (JSON): `./bin/llm inventory --format json --stdout`
- Gmail export filters: `./bin/mail-assistant --profile gmail_personal filters export --out out/filters.gmail.export.yaml`
- Gmail sync filters: `./bin/mail-assistant --profile gmail_personal filters sync --config config/filters_unified.yaml --dry-run`
- Outlook rules plan: `./bin/mail-assistant --profile outlook_personal outlook rules plan --config out/filters.outlook.yaml`

Outlook Authentication (first time)
- Device-code flow (recommended):
  - Start: `./bin/mail-assistant --profile outlook_personal outlook auth device-code`
  - Complete the on-screen link/code, then persist token:
    `./bin/mail-assistant --profile outlook_personal outlook auth poll --flow ~/.config/msal_flow.json --token ~/.config/outlook_token.json`
- One-liner (silent if cache exists):
  - `./bin/mail-assistant --profile outlook_personal outlook auth ensure`

Profiles
- Configure credentials/token paths and Outlook client ID via `~/.config/credentials.ini` under sections:
  - `[mail.gmail_personal]` → `credentials`, `token`
  - `[mail.outlook_personal]` → `outlook_client_id`, `tenant`, `outlook_token`

Notes
- Optional deps lazily imported: Google API client, PyYAML, MSAL, requests.
- Keep YAML human-editable; unknown keys are ignored on sync.
