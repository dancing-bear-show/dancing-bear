Mail Assistant — Agent Context

Overview
- CLI to manage Gmail and Outlook: labels, filters/rules, signatures.
- Unified source of truth for filters lives at `~/.config/dancing-bear/filters_unified.yaml` (outside checkout; `config/filters_unified.example.yaml` is the tracked template).
- Derived provider configs are generated from unified (do not hand-edit provider outputs).
- AGENTS.md is domain-specific; general agent patterns live in `.llm/PATTERNS.md`.

Key Workflows
- Plan before apply (prefer exact-match destructive syncs only after review):
  - Gmail plan: `./bin/mail filters plan --config ./filters.gmail.yaml --delete-missing`
  - Outlook plan: `./bin/mail outlook rules.plan --config ./filters.outlook.yaml --move-to-folders`
- Verify no drift after apply:
  - Gmail: `filters export` and compare with `./filters.gmail.yaml`
  - Outlook: `outlook rules.list` and spot-check against the derived Outlook filters YAML

Auth & Profiles
- Prefer profiles in INI: `~/.config/credentials.ini`.
- Sections: `[mail]` or `[mail.<profile>]`.
- Keys: `credentials`, `token`, `outlook_client_id`, `tenant`, `outlook_token`.
- Use `--profile` instead of passing `--credentials`/`--token` repeatedly.

CLI Basics
- Help: `./bin/mail --help`
- LLM utilities: `./bin/llm agentic --stdout` (or `--write .llm/AGENTIC.md`)
- Agentic schema: `./bin/mail --agentic --agentic-format yaml --agentic-compact`
- Initialize LLM capsules: `./bin/llm derive-all --out-dir .llm` (use `--stdout` to print summary). Generated files (AGENTIC.md, DOMAIN_MAP.md) are built on demand; use `--include-generated` to write them.
- Labels: export/sync with YAML; keep DSL human-editable with brief comments.
- Filters: export Gmail rules; derive from unified; audit and optimize similar rules.

Coding Style
- Python 3.11; optional deps are lazily imported inside functions.
- Small, focused helpers; keep public CLI stable (additive changes only).
