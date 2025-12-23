Mail Assistant — Agent Context

Overview
- CLI to manage Gmail and Outlook: labels, filters/rules, signatures.
- Unified source of truth for filters lives at `config/filters_unified.yaml`.
- Derived provider configs are generated from unified (do not hand-edit provider outputs).
- AGENTS.md is domain-specific; general agent patterns live in `.llm/PATTERNS.md`.

Key Workflows
- Plan before apply (prefer exact-match destructive syncs only after review):
  - Gmail plan: `./bin/mail-assistant filters plan --config config/filters_unified.yaml --delete-missing`
  - Outlook plan: `./bin/mail-assistant outlook rules plan --config out/filters.outlook.from_unified.yaml --move-to-folders`
- Verify no drift after apply:
  - Gmail: `filters export` and compare with `out/filters.gmail.from_unified.yaml`
  - Outlook: `outlook rules list` and spot-check against `out/filters.outlook.from_unified.yaml`

Auth & Profiles
- Prefer profiles in INI: `~/.config/sre-utils/credentials.ini` (or `~/.config/sreutils/credentials.ini`).
- Sections: `[mail_assistant]` or `[mail_assistant.<profile>]`.
- Keys: `credentials`, `token`, `outlook_client_id`, `tenant`, `outlook_token`.
- Use `--profile` instead of passing `--credentials`/`--token` repeatedly.

CLI Basics
- Help: `./bin/mail-assistant --help`
- LLM utilities: `./bin/llm agentic --stdout` (or `--write .llm/AGENTIC.md`)
- Global agentic flag: `python3 -m mail_assistant --agentic`
- Initialize LLM capsules: `./bin/llm derive-all --out-dir .llm` (use `--stdout` to print summary). Generated files (AGENTIC.md, DOMAIN_MAP.md) are built on demand; use `--include-generated` to write them.
- Labels: export/sync with YAML; keep DSL human-editable with brief comments.
- Filters: export Gmail rules; derive from unified; audit and optimize similar rules.

Coding Style
- Python 3.11; optional deps are lazily imported inside functions.
- Small, focused helpers; keep public CLI stable (additive changes only).
