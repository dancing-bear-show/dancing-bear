# WhatsApp Assistant Agent Notes

- Scope: read-only helpers for the local macOS WhatsApp database (`ChatStorage.sqlite`).
- Entry point: `./bin/whatsapp` (module `whatsapp.__main__`).
- Profiles/tokens are **not** required; everything stays on-device.
- Primary workflow: `search` for strings/contacts, optionally restricting by sender or time window.
- LLM helpers: `./bin/llm --app whatsapp agentic --stdout`, `./bin/llm --app whatsapp domain-map --stdout`, `./bin/llm --app whatsapp derive-all --out-dir .llm --include-generated`.
