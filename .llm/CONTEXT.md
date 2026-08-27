LLM Agent Context Cache
Concise reference for agent behavior and repo architecture
Last Reviewed: 2026-08-11

Project Goal (Reminder)
- Provide unified, dependable CLIs for personal workflows (mail, calendar, schedule, resume, phone, WhatsApp, maker).
- Reduce context needed to manage labels/filters/rules with a single human-editable YAML source of truth for Gmail/Outlook.
- Favor safe plan->apply flows and persisted, profile-based credentials for repeatable operations.

System Identity
- Project: Personal Assistants (mail, calendar, schedule, resume, phone, WhatsApp, maker)
- Scope: Gmail/Outlook mail and Outlook calendar workflows plus supporting assistants.
- Constraints: Python 3.11, dependency-light, stable public CLI
- Self-contained: All helpers and utilities are repo-internal; external deps are minimal and lazily imported. This ensures public CLI backwards compatibility and reduces fragility. Internal APIs can be refactored freely—update all call sites atomically without backwards-compatible wrappers.

Familiarize Mode (Strict + Tiers)
- Strict (capsule-only): Read `.llm/familiarize.yaml`; generate with `./bin/llm familiar --stdout`.
- Optional: Domain map (generated on demand): `./bin/llm domain-map --stdout`; compact schemas via `--agentic --agentic-format yaml --agentic-compact`.
- Extended (explicit): Only open heavy files intentionally (README/AGENTS/large exports).

Architecture Overview
```
src/
  mail/         # Gmail/Outlook providers, CLI wiring, helpers
  calendars/    # Outlook calendar CLI + Gmail scans
  schedule/     # plan/apply calendar schedules
  resume/       # extract/summarize/render resumes
  phone/        # iOS layout tooling
  whatsapp/     # local-only ChatStorage search
  desk/         # desktop/workspace tooling
  maker/        # utility generators
  charts/       # render time-series charts from JSON (line/bar/area/dual)
  diagrams/     # Mermaid diagram generation (flowchart/sequence/gantt/pie; telemetry cost/token pies)
  slides/       # generate PowerPoint decks from YAML deck definitions
  sheets/       # generate styled .xlsx spreadsheets from YAML workbook definitions
  workflow/     # YAML DAG workflow engine (parse/compile/run/lint/list/status)
  core/         # shared helpers
  telemetry/    # Claude Code session telemetry (cost, tokens, TUI)
  worker/       # background job queue and daemon
  apple_music/  # Apple Music CLI
  wifi/         # Wi-Fi CLI
  qlty/         # qlty scan/triage wrapper (tiers findings by remediation strategy)
bin/            # entry wrappers and helper scripts
tests/          # lightweight unittest suite
.llm/           # LLM context, flows, capsules
_disasm/        # decompiled refs (read-only)
config/         # YAML input templates (canonical config is outside checkout)
                # Generated output: ~/.local/share/dancing-bear/ (via core/paths.py)
```

Development Rules (do)
- Keep CLI flags/subcommands stable; add new under `labels`, `filters`, `outlook`
- Prefer wrapper executables over `python -m` to match user paths
- Use profiles in `~/.config/credentials.ini`; avoid `--credentials/--token`
- Apply lazy imports for optional deps (Google APIs, PyYAML)
- Keep helpers small, focused; prefer OO where cohesive (e.g., LabelSync, FilterSync)
- Update README minimally when adding user-facing commands; add tests for new CLI surfaces

Development Rules (avoid)
- Broad refactors that rename modules or move public entry points
- Heavy new dependencies; global imports for optional modules
- Emitting secrets/tokens in logs or passing them via flags
- Bare `except Exception: continue/pass` blocks without a `# nosec B110/B112` comment explaining the intent
- Breaking backwards compatibility of public CLI commands or parameters (bin/* entry points)
- Moving utilities to external packages (keep self-contained for stability)
- Maintaining backwards-compatible wrappers for internal APIs (update all call sites instead)

Activation Policy (Recommended)
- At the start of a work session, run unit tests to establish current health when making code changes:
  - Use `make test` (pins `PYTHONPATH` to the checkout). Never run bare `python3 -m unittest` in a worktree — an inherited `PYTHONPATH` silently resolves imports to the main checkout and produces false greens. Fallback: `PYTHONPATH="$PWD/src" python3 -m unittest discover -s tests`.
- If any tests fail, immediately create an execution plan (via the plan tool) to fix them:
  - Steps should include: reproduce failure locally; isolate scope; implement minimal, surgical fix; re-run targeted tests; re-run full suite.
  - Keep fixes focused; do not change unrelated code or public CLI behavior.
  - Avoid adding new dependencies; follow lazy-import patterns for optional deps.
- Share concise progress updates as you triage and fix failures.
- Never run tests that require network/secrets without explicit user approval; stub or skip such paths.

LLM Imperatives
- Activate env when running Python commands only if needed; prefer `direnv` or direct `.venv/bin/python` when relevant.
- `./bin/assistant` apps: apple-music, calendar, mail, maker, music, phone, resume, schedule, slides, whatsapp, wifi. Short wrappers also available: `./bin/mail`, `./bin/calendar`, `./bin/schedule`, `./bin/phone`, `./bin/wifi`, `./bin/whatsapp`, `./bin/maker`, `./bin/qlty-assistant`. The `-assistant` suffixed forms are legacy aliases (except `./bin/qlty-assistant`, whose suffix is required so it does not shadow the real `qlty` binary). `desk` has no bin/ wrapper — use `python3 -m desk`.
- Persist credentials to INI with profiles (single source of truth)
- Default to dry-run style flows for destructive operations; provide plan/apply

Agentic Schemas - Notes
- Prefer compact schemas from CLI over `--help` to save tokens.
- `./bin/mail --agentic --agentic-format yaml --agentic-compact`
- `./bin/llm agentic --stdout`

Familiarization Policy (Fast + Lean)
- Avoid opening large YAML/JSON unless auditing derived vs canonical.
  - Canonical: `~/.config/dancing-bear/filters_unified.yaml` (outside checkout; `config/filters_unified.example.yaml` is the tracked template)
  - Derived/ephemeral (open only for audits): outputs under `~/.local/share/dancing-bear/` (legacy: `_out/**`), `backups/**`, exports
- Ignore heavy/non-core paths during scanning: `.venv/`, `.cache/`, `.git/`, `src/maker/`, `_disasm/`, `_out/` (legacy), `backups/`, `personal_assistants.egg-info/`
- Reading order for new contexts:
  1) `.llm/CONTEXT.md`, `README.md`  (domain map: `./bin/llm domain-map --stdout`)
  2) Entry points: `bin/assistant`, `bin/mail`, `bin/calendar`, `bin/schedule`, `bin/phone`, `bin/wifi`, `bin/whatsapp`, `bin/qlty-assistant`
  3) Shared helpers: `src/core/`
  4) Mail config/DSL: `src/mail/dsl.py`, `src/mail/config_resolver.py`, `src/mail/utils/filters.py`
  5) Providers/APIs: `src/mail/providers/*.py`, `src/mail/gmail_api.py`, `src/core/outlook/`
  6) Tests for shape: `tests/test_cli.py`, `tests/test_cli_filters.py`, `tests/test_workflows*.py`
- Ripgrep quick searches (exclude heavy dirs):
  - `rg -n "(def main\(|argparse|click)" src/mail/ bin/ -g '!{.venv,.git,.cache,_disasm,out,_out,maker,backups}/**'`
  - `rg -n "filters (plan|sync|export)|labels (plan|sync|export)" src/mail/ bin/ -g '!{.venv,.git,.cache,_disasm,out,_out,maker,backups}/**'`
  - `rg -n "filters_unified.yaml|derive|audit|optimize" src/mail/ README.md -g '!{.venv,.git,.cache,_disasm,out,_out,maker,backups}/**'`

Agentic Shortcuts
- `./bin/assistant mail --agentic` or direct `./bin/mail --agentic` - compact agentic capsule from main parser
- `./bin/llm agentic --stdout` - compact agentic capsule (LLM CLI)
- `./bin/llm domain-map --stdout` - programmatic CLI tree + flows (generated on demand; no file)
- `./bin/llm derive-all --out-dir .llm --include-generated --stdout` - ensure core capsules
- `./bin/llm familiar --verbose --write .llm/familiarize.yaml` - token-safe familiarization plan
- `./bin/llm stale --with-status --limit 10` - staleness overview; see also `deps` and `check`

Flows (Curated Workflows)
- List all: `./bin/llm flows --list`
- Show one: `./bin/llm flows --id <flow_id> --format md|yaml|json`
- Examples: `gmail.filters.plan-apply-verify`, `outlook.rules.plan-apply-verify`, `unified.derive`

Messages (Provider-Agnostic)
- `messages search` auto-detects Gmail vs Outlook from `--profile`:
  - Outlook profiles (with `outlook_client_id`) use Graph API `$search`
  - Gmail profiles use standard Gmail query syntax
  - No profile or Gmail profile: `./bin/mail messages search --query "subject:invoice" --json`
  - Outlook profile: `./bin/mail --profile outlook_vanesa messages search --query "invoice" --json`
- Structured search flags (Gmail only; an Outlook profile rejects them with exit 1):
  `--from`, `--to`, `--subject-contains`, `--not-query`, `--has-attachment`, `--unread`
  - Compose with `--query`: `messages search --from a@b.com --subject-contains invoice --unread`
  - `--subject-contains` (not `--subject`, which means "override subject" on `messages reply`)
- Search output contract (STABLE — parsers depend on it):
  - text: exactly 4 tab-separated columns, `id\tsubject\tfrom_header\tsnippet`
  - `--json`: a BARE ARRAY; adds `to_header`, `date` (ISO-8601 UTC), `labels`, `unread`
  - New fields are JSON-only; the text columns never grow
- `messages get` accepts `--id`, `--ids A,B,C`, or `--query`; `--format json` emits a bare
  object for one id and a list for `--ids`
- `messages threads-get` fetches a whole conversation by `--thread-id`, `--id`, or `--query`

Operational Checks (Mail filters/rules)
- Unified is the source of truth: `~/.config/dancing-bear/filters_unified.yaml` is canonical for both Gmail and Outlook (outside checkout; `config/filters_unified.example.yaml` is the tracked template).
- Always run a plan first, then apply:
  - Gmail: `filters plan --config ... [--delete-missing]` then `filters sync --delete-missing`.
  - Outlook: `outlook rules.plan --config ... --move-to-folders` then `outlook rules.sync --delete-missing`.
- After apply, verify no extraneous rules exist outside unified:
  - Gmail: export and compare counts/criteria to the derived filters file.
  - Outlook: `outlook rules.list` and spot-check criteria vs the derived filters file.
- Prefer domain-based criteria over generic `query=` rules; deduplicate and merge substantially similar senders.
- For Kids/* flows, ensure forward-to Vanesa is present and not duplicated across rules.

LLM Maintenance & SLA
- Refresh inventory after CLI/docs changes: `./bin/llm inventory --write .llm/INVENTORY.md`
- Review stale areas weekly: `./bin/llm stale --with-status --limit 10`
- Check dependency hotspots: `./bin/llm deps --by combined --order desc --limit 10`
- Enforce freshness locally: `./bin/llm check --fail-on-stale`
- Exclude noisy areas by default via env: `export LLM_EXCLUDE=backups,_disasm,out,_out`

File-First Credentials (Preferred)
- Use profiles in `~/.config/credentials.ini` (or `$XDG_CONFIG_HOME/credentials.ini`).
- Gmail profile example: `[mail.gmail_personal]` with `credentials` and `token` file paths.
- Outlook profile example: `[mail.outlook_personal]` with `outlook_client_id`, `tenant`, and `outlook_token`.
- Search order: `$CREDENTIALS` -> `$XDG_CONFIG_HOME/credentials.ini` -> `~/.config/credentials.ini`.

Code Quality & Testing
- Linting: `~/.qlty/bin/qlty check <path>` (ruff + bandit + complexity metrics)
- Tests: `make test` (preferred). Fallback in non-worktree: `PYTHONPATH="$PWD/src" python3 -m unittest discover -s tests`. Never bare `python3 -m unittest` in a worktree.
- Coverage: `make cov` (or `make cov-html`)
- CI: `.github/workflows/ci.yml` runs qlty checks + tests with coverage on push/PR
- Add targeted tests only for new CLI surfaces/behaviors
- Security: Use `# nosec B110` (try-except-pass) or `# nosec B112` (try-except-continue) for intentional suppressions

Security
- Never commit `credentials.json` or tokens
- Restrict scopes to labels/settings/readonly/modify where required
- If sensitive data appears in logs, redact and rotate immediately
