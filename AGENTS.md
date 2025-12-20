# Repository Agent Hints

This repository hosts the personal assistants (mail, calendar, schedule, phone). The same LLM-first standards used in `code/cars-sre-utils` apply here so agents can reuse flows, context capsules, and CLI patterns without relearning a new playbook.

## 🎯 Project Goal (Reminder)
- Provide unified, dependable CLIs for personal email hygiene and calendar workflows across Gmail and Outlook.
- Reduce context needed to manage labels/filters/rules by using human-editable YAML sources of truth plus reproducible plan → apply flows.
- Favor safe automation (plan/dry-run first) while keeping helpers dependency-light and agent friendly.

## 🤝 Coordination
- Assume other agents may be working in parallel; avoid touching unrelated files and call out unexpected changes.

## 🤖 For LLM Agents: Token-Efficient Context System
**Always start with `.llm/CONTEXT.md` before scanning wider files.**

### Familiarize Policy (Capsule-Only Default)
- Default familiarize = load `.llm/familiarize.yaml` only (capsule-order commands).
- On-demand add-ons:
  - `.llm/DOMAIN_MAP.md` for CLI/module maps.
  - `.llm/FAMILIARIZE_CORE.md` for curated policy notes.
  - Prefer agentic CLI schemas over `--help`:  
    `./bin/mail-assistant --agentic --agentic-format yaml --agentic-compact`  
    `./bin/calendar --agentic --agentic-format yaml --agentic-compact`  
    `./bin/llm agentic --stdout`
- Generate or refresh the capsule with `./bin/llm familiar --stdout` (preview) or `./bin/llm familiar-sync`.
- Heed budget guards: `$FAMILIARIZE_TOKEN_BUDGET` and `$BUDGET_BYTES_PER_TOKEN` prevent runaway rewrites; new capsules are skipped if larger than the incumbent.

### Complete LLM Context Stack (~1.9k tokens)
1. `.llm/CONTEXT.md` — system identity, architecture, rules.
2. `.llm/MIGRATION_STATE.md` — current work streams and safe assumptions.
3. `.llm/PATTERNS.md` — copy-paste templates for filters, CLI wiring, etc.
4. `.llm/DOMAIN_MAP.md` — directories, CLIs, auth files.
5. `.llm/FAMILIARIZE_CORE.md` + generated `.llm/familiarize.{yaml,json}` — capsule commands.

### Directory Context Hints
- Look for `.ai-context` or nested `AGENTS.md` files (e.g., under `mail_assistant/`, `calendar_assistant/` directories) for domain-specific instructions.
- Skip heavy exports (`out/`, `_disasm/`) unless explicitly needed for audits.

### Familiar Flows (Preview → Sync → Status)
- Preview only: `./bin/llm familiar --stdout`
- Guarded sync: `./bin/llm familiar-sync`
- Explicit protected write: `./bin/llm familiar --write .llm/familiarize.yaml --preserve`
- Status: `./bin/llm familiar-status --format table`

### LLM Ops & Budgets
- Inventory: `.llm/INVENTORY.md` tracks last-refresh time and dependency highlights. After changing READMEs, `.llm/*`, or dependency manifests, run `./bin/llm inventory --preserve` and commit the updated file.
- Budgets: enforce token caps globally via env or `.llm/AGENTIC_BUDGETS.yaml` (per-app budgets, ratios). Tests check `.llm/familiarize.yaml|json` and `--agentic` outputs respect these limits.
- Capsules: regenerate targeted capsules with  
  `./bin/llm agents|roadmap|migration|policies --write .llm/<CAPSULE>.yaml`  
  or run `./bin/llm derive-all --out-dir .llm --format yaml` to refresh everything.
- Domain map hygiene: keep `.llm/DOMAIN_MAP.md` current whenever CLIs, directories, or auth files move so flows retain accurate routing hints. Assistant capsules live beside the global files:
  - `./bin/llm --app calendar derive-all --out-dir .llm --include-generated`
  - `./bin/llm --app schedule derive-all --out-dir .llm --include-generated`
  - `./bin/llm --app resume derive-all --out-dir .llm --include-generated`
  - `./bin/llm --app desk derive-all --out-dir .llm --include-generated`
  - `./bin/llm --app phone derive-all --out-dir .llm --include-generated`
  - `./bin/llm --app whatsapp derive-all --out-dir .llm --include-generated`

## ⚙️ Dynamic Flows (Maintenance, PR, Calendar/Mail Workflows)
Flows mirror the data-driven system in `cars-sre-utils`.

- Registry: `.llm/FLOWS.yaml` (curated) + `.llm/FLOWS.generated.yaml` (derived; **do not edit**).
- CLI entry points:
  - `./bin/llm flows-list|flows-show|flows-search`
  - `./bin/llm flows-run FLOW_ID --set KEY=value`
  - Use `--include-disabled` to view gated flows; `flows-run --force` bypasses guards.
- Discovery & sync:
  - `./bin/llm flows-derive --apps 'mail,calendar,outlook,ios'`
  - `./bin/llm flows-sync --out .llm/FLOWS.generated.yaml --include-derived`
- Flow schema: `id`, `desc`, `cmd` or `steps`, `params` (defaults), `tags`, `requires` (e.g., `bin:./bin/mail-assistant`, `env:GMAIL_TOKEN`), `hidden`.
- Steps may run sequentially or via `--parallel N`. Use `--worker` to enqueue tasks.

## Agent Priority Rules

### OO & Reuse First
- Reuse existing CLIs (`mail_assistant`, `calendar_assistant`, `schedule_assistant`, `phone`) and helper modules before adding new scripts.
- When extending behavior, keep CLIs thin; push logic into reusable helpers (`mail_assistant/providers`, `mail_assistant/utils`, etc.).

### 1. Use Unified CLIs First
```
# Mail workflows (labels/filters/auth/sync)
./bin/mail-assistant labels plan --config config/labels.yaml
./bin/mail-assistant filters plan --config config/filters_unified.yaml --delete-missing
./bin/mail-assistant outlook rules plan --config out/filters.outlook.from_unified.yaml --move-to-folders

# Calendar workflows
./bin/calendar outlook add-from-config --config config/calendar/...
./bin/schedule-assistant apply --plan out/schedule.plan.yaml --apply

# Phone/iOS helpers
./bin/phone export-device --out out/ios.IconState.yaml
./bin/phone iconmap --out out/ios.iconmap.json
./bin/phone plan --out out/ios.plan.yaml
```
Only add new entry points if these CLIs truly cannot cover the scenario.

### 2. Patterns for CLI Extensions
- Mail CLIs follow provider/pattern modules (LabelSync, FilterSync). Extend them rather than writing bespoke Gmail Graph calls.
- Calendar and phone assistants share YAML DSLs; update DSL helpers (`calendar_assistant/importer`, `phone/model`) for cross-tool reuse.
- Use lazy imports for optional deps (Google APIs, PyYAML, MSAL) to keep `--help` fast.

### 3. Architecture Summary
- **mail_assistant/** — Gmail/Outlook CLIs, providers, YAML DSLs.
- **calendar_assistant/** & **schedule_assistant/** — plan/apply loops for calendars.
- **phone/** — iOS layout export/plan.
- **bin/** — wrappers for the unified CLIs + llm tooling.
- **config/** — canonical YAML (filters, calendar plans).
- **out/** — derived artifacts (plans, exports, audits). Keep new outputs here.

### 4. Development Workflow
1. Check whether an existing CLI/flow covers the request. Prefer plan/dry-run commands.
2. Extend helpers/providers before touching CLI wiring.
3. Keep commands backward compatible (stable flags/subcommands).
4. After changes, run targeted tests plus `make test` (or equivalent) before syncing flows/filters.

## Practical Implementation Guidelines

### Project Structure & Module Organization
- `mail_assistant/` — Gmail/Outlook CLI (labels, filters, signatures).
- `calendar_assistant/`, `schedule_assistant/`, `phone/` — calendar/phone helpers.
- `bin/` — wrapper scripts (e.g., `bin/mail_assistant`, `bin/calendar`, `bin/llm`).
- `tests/` — lightweight CLI/unit tests.
- `_disasm/` — Decompiled references; **do not modify**.
- Preserve existing CLI flags/subcommands; keep edits surgical.

### Build, Test, and Development Commands
- Create venv: `python3 -m venv .venv` (activation optional with `direnv`)
- Install editable deps: `make venv` or `pip install -e .`
- CLI help:
  - `./bin/mail-assistant --help`
  - `./bin/calendar --help`
  - `./bin/schedule-assistant --help`
- Labels: `python3 -m mail_assistant labels export --out labels.yaml`
- Filters:
  - Export: `python3 -m mail_assistant filters export --out filters.yaml`
  - Plan: `./bin/mail-assistant filters plan --config config/filters_unified.yaml --delete-missing`
- Auth: copy `credentials.example.json` to `~/.config/credentials.json`; first run creates `~/.config/token.json`.
- Tests: `make test` or `python3 -m unittest tests/test_cli.py -v`

### Coding Style & Naming Conventions
- Python 3.9; keep modules dependency-light.
- Lazy-import optional deps (Google APIs, MSAL, PyYAML).
- 4-space indentation; `snake_case` for functions/vars; `CapWords` for classes.
- Keep helpers small/focused; prefer incremental refactors and shared utilities.
- YAML DSLs must remain human-editable with concise comments.

### Testing Guidelines
- Framework: `unittest`.
- Add targeted tests for new CLI surfaces or behaviors (name files `test_*.py`).
- Run focused tests via `python3 -m unittest path/to/test_file.py`.

### Refactor Discipline & Coverage
- After refactors, run the full suite: `make test` (or `python3 -m unittest -v`).
- Aim for ≥90% coverage on touched modules when feasible.
- Optional coverage pass: `coverage run -m unittest` + `coverage report -m`.

### Commit & Pull Request Guidelines
- Commit messages: concise, imperative subjects (e.g., `filters: add cineplex sender`).
- PRs: include summary, rationale, before/after CLI examples, README/AGENT updates when needed.
- Never commit secrets or tokens.

### Security & Configuration Tips
- Never commit credentials or tokens; store secrets via env vars or under `~/.config/`.
- Gmail: restrict scopes to labels/settings/readonly/modify as required.
- Outlook: device-code auth flows; prefer categorize-only rules when policies block forwarding.
- If sensitive data appears in logs, redact immediately and rotate tokens.

### Agent-Specific Instructions
- Follow existing patterns (lazy imports, provider helpers).
- Group new commands under the right top-level (`labels`, `filters`, `outlook`, etc.).
- `_disasm/` is read-only reference.
- For new public behavior, add concise README examples and the minimal tests required.

### Config Source of Truth & Sync Policy
- Canonical filters: `config/filters_unified.yaml`.
- Derived configs:
  - Gmail: `out/filters.gmail.from_unified.yaml`
  - Outlook: `out/filters.outlook.from_unified.yaml`
- Workflow:
  1. `./bin/mail-assistant filters plan --config config/filters_unified.yaml --delete-missing`
  2. `./bin/mail-assistant --profile gmail_personal filters sync ... --delete-missing`
  3. `./bin/mail-assistant --profile outlook_personal outlook rules plan|sync --move-to-folders`
  4. Export/verify: `filters export`, `outlook rules list`, compare to derived outputs.
- Favor explicit `from:` domain lists over broad queries; deduplicate/merge similar senders.

### LLM Activation
- Auto-activate on repo entry; keep plans up to date.
- Prefer wrappers (`./bin/mail-assistant`, `./bin/llm`, `./bin/mail-assistant-auth`).
- Default to venv context if present; do not block if absent.
- Prefer persisted credentials (INI) using profiles:
  - `[mail_assistant.gmail_personal]` (`credentials`, `token`)
  - `[mail_assistant.outlook_personal]` (`outlook_client_id`, `tenant`, `outlook_token`)
- Use `--profile` instead of passing credential paths directly.

### LLM Context Files
- `.llm/CONTEXT.md` — overview and rules.
- `.llm/PATTERNS.md` — templates (filters, CLI wiring).
- `.llm/MIGRATION_STATE.md` — outstanding migration work.
- `.llm/DOMAIN_MAP.md` — directory map.
- `.llm/FLOWS.yaml` — curated flows; `.llm/FLOWS.generated.yaml` derived.

### Deduplication & Modular Design
- Apply DRY: factor repeated logic into helpers under `mail_assistant/` or `mail_assistant/cli/`.
- Extract shared CLI argument definitions into helper functions; keep flag names/semantics stable.
- Prefer OO when it improves cohesion (`LabelSync`, `FilterSync`, `OutlookRuleSync`).
- Keep lazy imports inside functions/methods for optional deps.
- When introducing new modules, add a short README/AGENTS pointer and minimal tests for new surfaces.
