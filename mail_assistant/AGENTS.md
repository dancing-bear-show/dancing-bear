Scope
- Domain-specific guidance for the Mail Assistant repo only.
- General agent patterns and coding conventions live under `.llm/` (see `.llm/PATTERNS.md`).

Domain
- Purpose: Gmail/Outlook CLI for labels, filters/rules, signatures.
- Canonical config: unified filters live at `config/filters_unified.yaml`.
- Derive provider configs; do not hand-edit derived outputs in `out/`.
- Keep public CLI stable (additive changes only); preserve existing flags/subcommands.

Sync Policy (Unified → Providers)
- Plan before apply; prefer exact-match destructive syncs only with explicit review.
- Gmail: `filters plan|sync` with optional `--delete-missing`.
- Outlook: `outlook rules plan|sync`; prefer `--move-to-folders`, use `--categories-only` when required.
- After applying, verify no drift by exporting/listing and comparing to derived outputs.

Providers
- Gmail: only use verified forwarding addresses; avoid creating forwards if not verified.
- Outlook: tenant policy may block `forwardTo`; prefer categories-only actions.

Security
- Never commit credentials or tokens. Use profiles in `~/.config/credentials.ini`.
- Profiles: `[mail_assistant.<profile>]` → `credentials`, `token`, `outlook_client_id`, `tenant`, `outlook_token`.

Agent Utilities
- Capsule: `./bin/mail-assistant --agentic` (compact context with CLI tree + flow map).
- Domain map: `./bin/llm domain-map --stdout` (or `--write .llm/DOMAIN_MAP.md`).
- Initialize LLM meta: `./bin/llm derive-all --out-dir .llm`.

References
- Detailed agent context: `.llm/CONTEXT.md`.
- Implementation patterns: `.llm/PATTERNS.md`.
