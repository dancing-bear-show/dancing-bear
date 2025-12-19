Personal assistants (reconstituted)

This repository was reconstructed from Python bytecode caches located at:

  /Users/briansherwin/Library/Caches/com.apple.python/Users/briansherwin/personal

What’s here
- Packages: mail_assistant, resume_assistant, schedule_assistant, tests
- Source was decompiled from Python 3.9 bytecode. Some functions may be incomplete
  due to unsupported opcodes in Python 3.9.0; placeholders like "# WARNING: Decompyle incomplete"
  denote areas that need manual repair.
- Original import structure, module names, and many literals/logging calls were recovered.
- Current runtime target: Python 3.11 (see `.python-version`).

## Contributors Quick Start
- Create venv and install: `make venv`
- Run help: `./bin/mail-assistant --help` or `.venv/bin/mail-assistant --help`
- Calendar Assistant: `./bin/calendar --help` (alias: `./bin/calendar-assistant --help`)
  - Schedule Assistant: `./bin/schedule-assistant --help`
- Single entry: `./bin/assistant <mail|calendar|schedule|resume|phone|whatsapp|maker> --help`
- Gmail auth: keep `~/.config/credentials.json`; first run creates `~/.config/token.json`.
- Create a starter credentials file:
  - `mkdir -p ~/.config && cp credentials.example.json ~/.config/credentials.json` then fill in your client id/secret.
  - One-shot auth helper:
    - `./bin/mail-assistant-auth` (or `./bin/mail-assistant-auth --credentials ~/.config/credentials.json --token ~/.config/token.json`)
- Prefer the executable and persisted creds:
  - Use `./bin/mail-assistant` (no `python3 -m ...`).
  - Persist credentials once to `~/.config/credentials.ini` (single source of truth) and omit flags thereafter.
    - Profiles (recommended):
      - `[mail_assistant.gmail_personal]`\n`credentials = /Users/you/.config/google_credentials.gmail_personal.json`\n`token = /Users/you/.config/token.gmail_personal.json`
      - `[mail_assistant.outlook_personal]`\n`outlook_client_id = <YOUR_APP_ID>`\n`tenant = consumers`\n`outlook_token = /Users/you/.config/outlook_token.json`
    - Legacy paths `~/.config/sre-utils/credentials.ini` and `~/.config/sreutils/credentials.ini` are still read for backwards compatibility.
- Labels
  - Export: `./bin/mail-assistant labels export --out labels.yaml` (or `python3 -m mail_assistant …`)
  - Plan: `./bin/mail-assistant labels plan --config labels.yaml [--delete-missing]`
  - Sync: `./bin/mail-assistant labels sync --config labels.yaml --dry-run`
- Filters
  - Export: `./bin/mail-assistant filters export --out filters.yaml`
  - Sync: `./bin/mail-assistant filters sync --config filters.yaml --dry-run`
  - Plan (recommended first): `./bin/mail-assistant filters plan --config filters.yaml [--delete-missing]`
  - Unified workflow (agentic):
    - Gmail-only: `python3 -m mail_assistant workflows gmail-from-unified --config config/filters_unified.yaml [--delete-missing] [--apply]`
    - All configured providers (auto-detect Gmail + Outlook):
      - `python3 -m mail_assistant workflows from-unified --config config/filters_unified.yaml [--delete-missing] [--apply]`
      - Control providers: `--providers gmail,outlook`
      - Outlook folder moves on by default; disable with `--no-outlook-move-to-folders`

## Directory Conventions
- `out/` — default location for derived outputs and plans (tracked as needed; keep tidy).
- `logs/` — runtime logs (gitignored).

Cleaning
- Remove venv only: `make clean`
- Deep clean ephemeral artifacts and caches: `make distclean`
  - Purges: `out/`, `logs/`, coverage files, Python caches (`__pycache__/`, `.pytest_cache/`), local tooling caches (`.cache/`, `.mypy_cache/`, `.direnv/`), and `*.egg-info`.
- Calendar (Outlook)
  - Verify plan (safe):
    - `./bin/calendar-assistant --profile outlook_personal outlook verify-from-config --config out/plan.yaml`
  - Apply plan (create):
    - `./bin/calendar-assistant --profile outlook_personal outlook add-from-config --config out/plan.yaml`
    - Tips: add `--no-reminder` to disable alerts on created items (or set per-event in YAML via `reminder: off` or `reminder_minutes: 0`).
    - Tip: add `--no-reminder` to suppress event reminders/alerts on creation
  - Update locations from Outlook to YAML (pull full addresses):
    - `./bin/calendar-assistant --profile outlook_personal outlook update-locations --config out/plan.yaml --calendar "Your Family"`
    - Notes: `outlook locations-enrich` uses `config/locations.yaml` to map facility short names to full addresses when enriching.
  - Remove events matching a plan (cleanup):
    - `./bin/calendar-assistant --profile outlook_personal outlook remove-from-config --config out/plan.yaml --calendar "Your Family" --apply`
    - Use `--subject-only` to match by subject regardless of time/weekday (useful for wholesale cleanup)
  - Deduplicate series (keep newest, drop non-standard locations):
    - `./bin/calendar-assistant --profile outlook_personal outlook dedup --calendar "Your Family" --from 2025-01-01 --to 2026-12-31 --prefer-delete-nonstandard --keep-newest --apply`
  - One-offs (report):
    - `./bin/calendar-assistant --profile outlook_personal outlook list-one-offs --calendar "Your Family" --from 2025-09-01 --to 2026-06-30 --out out/one_offs.yaml`
  - Reminders (bulk set):
    - Turn off across a window: `./bin/calendar-assistant --profile outlook_personal outlook reminders-set --calendar "Activities" --from 2025-01-01 --to 2026-06-30 --off`
    - Set minutes: `./bin/calendar-assistant --profile outlook_personal outlook reminders-set --calendar "Activities" --from 2025-01-01 --to 2026-06-30 --minutes 5`
  - Notes:
    - Locations in add-from-config accept `Name (street, city, state POSTAL)` and are parsed into Outlook structured addresses.
    - Facility short-name to full address mapping lives in `config/locations.yaml` and is used by `outlook locations-enrich`.
    - Use profiles in `~/.config/credentials.ini`; Outlook device-code flows live at `~/.config/outlook_token.json`.
    - Outlook first-time login (device code):
      - Start: `./bin/mail-assistant --profile personal outlook auth device-code`
      - Complete the on-screen link/code, then persist token:
        `./bin/mail-assistant --profile personal outlook auth poll --flow ~/.config/msal_flow.json --token ~/.config/outlook_token.json`
      - Or one-shot (silent if cached): `./bin/mail-assistant --profile personal outlook auth ensure`
- Tests: `make test` or `python3 -m unittest -v`

### Convenience Wrappers (cars-sre-utils style)
- `bin/gmail-auth` → `mail-assistant auth`
- `bin/gmail-labels-export` → `mail-assistant labels export`
- `bin/gmail-labels-sync` → `mail-assistant labels sync`
- `bin/gmail-filters-export` → `mail-assistant filters export`
- `bin/gmail-filters-sync` → `mail-assistant filters sync`
- `bin/gmail-filters-impact` → `mail-assistant filters impact`
- `bin/gmail-filters-sweep` → `mail-assistant filters sweep`

- `bin/outlook-auth-device-code` → `mail-assistant outlook auth device-code`
- `bin/outlook-auth-poll` → `mail-assistant outlook auth poll`
- `bin/outlook-auth-ensure` → `mail-assistant outlook auth ensure`
- `bin/outlook-auth-validate` → `mail-assistant outlook auth validate`
- `bin/outlook-rules-list` → `mail-assistant outlook rules list`
- `bin/outlook-rules-export` → `mail-assistant outlook rules export`
- `bin/outlook-rules-plan` → `mail-assistant outlook rules plan`
- `bin/outlook-rules-sweep` → `mail-assistant outlook rules sweep`
- `bin/outlook-rules-sync` → `mail-assistant outlook rules sync`
- `bin/outlook-rules-delete` → `mail-assistant outlook rules delete`
- `bin/outlook-categories-list` → `mail-assistant outlook categories list`
- `bin/outlook-categories-export` → `mail-assistant outlook categories export`
- `bin/outlook-categories-sync` → `mail-assistant outlook categories sync`
- `bin/outlook-folders-sync` → `mail-assistant outlook folders sync`
- `bin/outlook-calendar-add` → `mail-assistant outlook calendar add`
- `bin/outlook-calendar-add-recurring` → `mail-assistant outlook calendar add-recurring`
- `bin/outlook-calendar-add-from-config` → `mail-assistant outlook calendar add-from-config`

#### iOS (Phone Assistant)
- `bin/ios-export` → `phone export-device` (legacy backup export is deprecated)
- `bin/ios-plan` → `phone plan`
- `bin/ios-checklist` → `phone checklist`
- `bin/ios-profile-build` → `phone profile build`
- `bin/ios-manifest-create` → `phone manifest create`
- `bin/ios-manifest-build-profile` → `phone manifest build-profile`
- `bin/ios-manifest-from-device` → `phone manifest from-device`
- `bin/ios-manifest-install` → `phone manifest install`
- `bin/ios-analyze` → `phone analyze`
- `bin/ios-auto-folders` → `phone auto-folders`
- `bin/ios-unused` → `phone unused`
- `bin/ios-prune` → `phone prune`
- `bin/ios-iconmap-refresh` → `cfgutil get-icon-layout + phone export-device`

All arguments are forwarded as-is; existing flags remain unchanged.
- Security: never commit credentials or tokens; keep them under `~/.config/` or other local-only paths.

### Env Setup (agentic)
- Create venv and persist credentials in one go:
  - Gmail only:
    - `./bin/mail-assistant env setup --profile gmail_personal --credentials ~/.config/google_credentials.gmail_personal.json --token ~/.config/token.gmail_personal.json`
  - Outlook only:
    - `./bin/mail-assistant env setup --profile outlook_personal --outlook-client-id <APP_ID> --tenant consumers --outlook-token ~/.config/outlook_token.json`
  - Both Gmail + Outlook:
    - `./bin/mail-assistant env setup --profile personal --credentials ~/…/google_credentials.json --token ~/…/token.json --outlook-client-id <APP_ID> --tenant consumers --outlook-token ~/…/outlook_token.json`
- Flags:
  - `--venv-dir .venv` (default), `--no-venv`, `--skip-install`
 - `--copy-gmail-example/--no-copy-gmail-example` copies `credentials.example.json` → `~/.config/credentials.json` if missing
- Auto-activation (optional):
  - Install `direnv` and run `direnv allow` in the repo root. The provided `.envrc` will:
    - Auto-activate `.venv` when present
    - Export `PYTHONPATH` to include the repo root
    - Prefer local `bin/` wrappers on PATH
    - Add Apple Configurator `cfgutil` to PATH for live icon-map exports
  - To set up the venv: `./bin/setup_venv`

### LLM Utilities
- Quick inventory: `./bin/llm inventory --stdout` (writes/reads `.llm/INVENTORY.md`)
- Familiarize capsule: `./bin/llm familiar --stdout` (single-file steps)
- Policies capsule: `./bin/llm policies --stdout`
- Ensure all capsules exist: `./bin/llm derive-all --out-dir .llm`
- Assistant capsules (agentic + domain map + familiar + policies) via a unified CLI:
  - Calendar: `./bin/llm --app calendar derive-all --out-dir .llm --include-generated`
  - Schedule: `./bin/llm --app schedule derive-all --out-dir .llm --include-generated`
  - Resume: `./bin/llm --app resume derive-all --out-dir .llm --include-generated`
  - Desk: `./bin/llm --app desk derive-all --out-dir .llm --include-generated`
  - Phone: `./bin/llm --app phone derive-all --out-dir .llm --include-generated`
  - WhatsApp: `./bin/llm --app whatsapp derive-all --out-dir .llm --include-generated`
- Staleness (plan review):
  - Areas: `./bin/llm stale --by area --limit 10 --with-status`
  - Files: `./bin/llm stale --by file --limit 10 --format text`
  - Fail CI when stale: `./bin/llm stale --with-status --fail-on-stale`
  - Priority (deps × staleness): `./bin/llm stale --with-priority --with-status`
- Dependencies overview:
  - `./bin/llm deps --by combined --limit 10 --format table`
 - CI alias:
   - `./bin/llm check` (equivalent to `stale --by area --with-status --fail-on-stale`)

### Schedule Assistant
- Plan from CSV/XLSX/PDF/website into canonical YAML:
  - `./bin/schedule-assistant plan --source schedules/classes.csv --out out/schedule.plan.yaml`
- Apply a plan (dry-run by default; require --apply to write):
  - `./bin/schedule-assistant apply --plan out/schedule.plan.yaml --dry-run`
  - `./bin/schedule-assistant apply --plan out/schedule.plan.yaml --apply --calendar "Your Family"`
- Verify (by subject or by subject@time) within a window:
  - `./bin/schedule-assistant verify --plan out/schedule.plan.yaml --calendar "Your Family" --from 2025-10-01 --to 2025-12-31 --match subject-time`
- Sync (create missing; optionally delete extraneous one-offs):
  - Safe dry-run: `./bin/schedule-assistant sync --plan out/schedule.plan.yaml --calendar "Your Family" --from 2025-10-01 --to 2025-12-31`
  - Apply with cleanup: `./bin/schedule-assistant sync --plan out/schedule.plan.yaml --calendar "Your Family" --from 2025-10-01 --to 2025-12-31 --delete-missing --apply`
  - Also remove entire unplanned series: add `--delete-unplanned-series` (use with care)
  - Matching mode:
    - Default: `--match subject-time` (exact subject@time)
    - Looser: `--match subject` (presence-by-subject only)
 - Export Outlook calendar → YAML (backup):
   - `./bin/schedule-assistant export --calendar "Activities" --from 2025-10-01 --to 2025-12-31 --out config/calendar/activities.yaml --profile outlook_personal`


## LLM/Agent Quick Start
- Start with `.llm/CONTEXT.md` then `.llm/PATTERNS.md`
- Migration tracker: `.llm/MIGRATION_STATE.md`
- Domain map: `.llm/DOMAIN_MAP.md`
- Human overview remains here; agent-specific cache lives under `.llm/`

## CLI Overview (current)
- Top-level groups: `auth`, `labels`, `filters`, `backup`, `cache`, `auto`, `forwarding`, `signatures`, `accounts`, `outlook`
- Profiles: prefer `--profile gmail_personal|outlook_personal` using `~/.config/credentials.ini`
- Common snippets:
  - Labels: `labels list|export|sync|doctor|prune-empty|learn|apply-suggestions|delete|sweep-parents`
  - Filters: `filters export|plan|impact|sync|sweep|sweep-range|delete|prune-empty`
  - Backup: `backup --out-dir backups/$(date +%Y%m%d_%H%M%S)`
  - Cache: `cache stats|clear|prune --days N`
  - Auto: `auto propose|apply|summary`
  - Forwarding: `forwarding list|add --email you@example.com`
  - Signatures: `signatures export|sync|normalize`
  - Accounts: `accounts list|export-*/sync-*|plan-* --config config/accounts.yaml`
  - Outlook: `outlook auth device-code|poll`, `outlook categories list|export|sync`, `outlook rules list|export|plan|sync|sweep`, `outlook folders sync`
  - Config: `config inspect [--path ~/.config/credentials.ini] [--only-mail]`
  - Unified: `config derive labels|filters`, `config optimize filters`, `config audit filters`

Examples
- Cache
  - `./bin/mail-assistant cache stats --cache .cache/mail`
  - `./bin/mail-assistant cache prune --cache .cache/mail --days 30`
  - `./bin/mail-assistant cache clear --cache .cache/mail`
- Auto (Gmail)
  - Propose: `./bin/mail-assistant auto propose --days 14 --only-inbox --out auto_proposal.json --dry-run`
  - Summary: `./bin/mail-assistant auto summary --proposal auto_proposal.json`
  - Apply: `./bin/mail-assistant auto apply --proposal auto_proposal.json --cutoff-days 7 --dry-run`
 - Signatures
   - Export: `./bin/mail-assistant signatures export --out signatures.yaml`
   - Normalize: `./bin/mail-assistant signatures normalize --config signatures.yaml --out-html sig.html --var displayName="John Doe"`
   - Sync: `./bin/mail-assistant signatures sync --config signatures.yaml --dry-run`
- Outlook quickstart (device-code)
  - `./bin/mail-assistant --profile outlook_personal outlook auth device-code`
  - Then: `./bin/mail-assistant --profile outlook_personal outlook auth poll --flow ~/.config/msal_flow.json --token ~/.config/outlook_token.json`
  - Dry-run categories: `./bin/mail-assistant --profile outlook_personal outlook categories sync --config labels.yaml --dry-run`
 - Auth validation
   - Gmail: `./bin/mail-assistant --profile gmail_personal auth --validate`
   - Outlook: `./bin/mail-assistant --profile outlook_personal outlook auth validate`
 - Config inspect (redacted)
   - All mail sections: `./bin/mail-assistant config inspect --only-mail`
   - Specific file: `./bin/mail-assistant config inspect --path ~/.config/credentials.ini`

## Gmail Profiles & Commands
- Select profile: `--profile gmail_personal`
- Suggestions: `./bin/mail-assistant labels learn --days 30 --only-inbox --out config/labels_suggestions.yaml`
- Apply (dry-run): `./bin/mail-assistant labels apply-suggestions --config config/labels_suggestions.yaml --dry-run`
- Sweeps (parent labels): `./bin/mail-assistant labels sweep-parents --names Kids,VIP --dry-run`
- Prune empties: `./bin/mail-assistant labels prune-empty --limit 10 --sleep-sec 0.5`

## Outlook (Device Code + Profiles)
- Select profile: `--profile outlook_personal`
- Device code (non-blocking):
  - Initiate: `./bin/mail-assistant --profile outlook_personal --verbose outlook auth device-code`
  - Poll: `./bin/mail-assistant --profile outlook_personal --verbose outlook auth poll --flow ~/.config/msal_flow.json --token ~/.config/outlook_token.json`
- Categories (dry-run/apply):
  - Dry-run: `./bin/mail-assistant --profile outlook_personal outlook categories sync --config config/labels_after_merge.yaml --dry-run`
  - Apply: `./bin/mail-assistant --profile outlook_personal outlook categories sync --config config/labels_after_merge.yaml`
- Rules (dry-run): `./bin/mail-assistant --profile outlook_personal outlook rules sync --config config/filters_from_suggestions.yaml --dry-run`
  - Note: Outlook rules have stricter constraints. Forwarding in rules may be blocked by policy on consumer accounts. Use categorization-only rules in Outlook and keep forwarding on Gmail where needed.

## Current Status Snapshot
- Executable-first CLI with profile-aware credentials (single INI at `~/.config/credentials.ini`).
- Gmail: providers, prune-empty, sweep-parents, suggestions apply, targeted filters (e.g., Finance/TD, VIP/Family/Vanesa), and forwarding (Gmail) in place.
- Outlook: device-code auth + polling with persistent token. Categories applied; rules dry-runs compare. ForwardTo in Outlook rules may be blocked by tenant policy—use categorize-only rules and Gmail for forwarding.

## Provider Migration (In Progress)
- New architecture introduces a shared `BaseProvider` with adapters per provider.
  - Implemented: `GmailProvider` (wraps existing `GmailClient`).
  - Implemented: `OutlookProvider` (wraps `OutlookClient` for categories/rules).
  - Resolver: `_build_provider_for_account` selects Gmail or Outlook for accounts commands.
- DRY utilities added:
  - `mail_assistant/utils/batch.py` — chunking helpers used in sweeps.
  - `mail_assistant/yamlio.py` — YAML load/dump helpers.

## Phone Assistant (New)

Plan-only, read-only CLI that analyzes your Home Screen layout from a device (cfgutil) or a local Finder backup and produces:

- A normalized export (YAML) of apps/folders/dock
- A scaffold plan (pins + folder buckets)
- A manual move checklist to apply on device

Commands
- Export layout from device (cfgutil):
  - `./bin/phone export-device --out out/ios.IconState.yaml`
- Download raw icon map (cfgutil JSON/plist):
  - `./bin/phone iconmap --out out/ios.iconmap.json`
- Scaffold a plan from the current layout:
  - `./bin/phone plan --out out/ios.plan.yaml`
- Generate a manual move checklist from a plan:
  - `./bin/phone checklist --plan out/ios.plan.yaml --out out/ios.checklist.txt`

Notes
- `phone export` (backup-based) is deprecated; prefer `phone export-device`.
- Finder backup support still exists for legacy flows under `~/Library/Application Support/MobileSync/Backup/`.
- No device writes: iOS does not expose APIs to rearrange icons. Use the checklist to apply changes manually.

Supervised/MDM automation
- If you want to auto-apply layout (apps/folders/dock) via a profile, supervise the device with Apple Configurator and install a Home Screen Layout `.mobileconfig`.
- Exhaustive setup guide: docs/phone_configurator.md

  - `mail_assistant/dsl.py` — Outlook normalization extracted from CLI.
  - `mail_assistant/utils/cli_helpers.py` — provider ctor + criteria preview.
- Migrated commands to provider:
  - Single-account: `labels list/export`, all `filters` subcommands.
  - Accounts: `export-labels`, `sync-labels`, `export-filters`, `plan-labels`, `plan-filters`, `export-signatures`.
  - Forwarding and signatures (Gmail) now go through the provider.
  - Outlook paths use the provider resolver (sweeps/signatures not supported by Graph).
- Provider capabilities: `providers/*.py` expose `capabilities()` to gate features.
- YAML centralization: labels/filters exports, backups, and accounts exports now use `yamlio`.
- Tests: added small unit tests for utils and provider capabilities.
  - Utils tests: `tests/test_utils_cli_helpers.py`, `tests/test_utils_filters.py`, `tests/test_utils_filters_more.py`, `tests/test_yamlio.py`
  - DSL tests: `tests/test_dsl.py`

Next steps
- Finish centralizing remaining YAML reads/writes via `yamlio`.
- Add capability checks where useful to provide clearer messages on unsupported features.

Notes
- If you still have a Time Machine snapshot or backup of ~/personal, restoring from that will yield pristine sources.
- To try alternative decompilers, consider using the built pycdc binary under /tmp/pycdc-src/build/pycdc
  or future versions of decompyle3 that fully support 3.9.0.

Binaries
- bin/mail_assistant: Python wrapper to run the CLI

Label workflow (export → edit → sync)
- Export: `python3 -m mail_assistant labels export --out labels.yaml`
- Edit `labels.yaml` under `labels:` entries. Optionally add redirects:

  labels:
    - name: Receipts
      labelListVisibility: labelShow
      messageListVisibility: show
      color: {backgroundColor: "#0b804b", textColor: "#ffffff"}
  redirects:
    - from: "Old/Receipts"
      to: "Receipts"

- Dry-run sync: `python3 -m mail_assistant labels sync --config labels.yaml --dry-run`
- Apply changes: add `--delete-missing` to prune extra labels (skips system labels).
- Merge old→new on messages and delete source: add `--sweep-redirects`.

Filters (including forwarding)
- Export filters: `python3 -m mail_assistant filters export --out filters.yaml`
- Edit `filters.yaml` to include entries like:

  filters:
    - name: Forward payroll
      match:
        from: payroll@company.com
        subject: Pay Stub
      action:
        add: ["Work/HR"]
        remove: ["INBOX"]
        forward: archive@mydomain.com  # must be a verified forwarding address in Gmail

- Sync: `python3 -m mail_assistant filters sync --config filters.yaml --dry-run`
- Apply: drop `--dry-run`; optionally `--delete-missing` to remove filters not in YAML.

System categories in DSL
- You can set Gmail tab categories using friendly keys; the tool maps them to system labels:
  - action:
      categorizeAs: promotions   # or forums, updates, social, personal
  - or multiple:
      categories: [promotions, forums]
- These are equivalent to adding system labels:
  - CATEGORY_PROMOTIONS, CATEGORY_FORUMS, CATEGORY_UPDATES, CATEGORY_SOCIAL, CATEGORY_PERSONAL
- You can mix with user labels:
  - action:
      add: ["Lists/Commercial"]
      categories: [promotions]

Forwarding addresses
- List: `python3 -m mail_assistant forwarding list`
- Add/register: `python3 -m mail_assistant forwarding add --email you@example.com`
  - Gmail sends a verification email to that address; click to accept.
  - Use `--require-forward-verified` with `filters sync` to ensure only verified addresses are referenced.


Binaries
- bin/mail_assistant: Python wrapper to run the CLI

Filters workflow (export current → edit DSL)
- Export Gmail filters to YAML DSL:

  python3 -m mail_assistant filters export --out filters.yaml

- The DSL structure (example):

  filters:
    - id: "1234567890"        # original Gmail filter id (informational)
      criteria:
        from: "news@site.com"
        query: "newsletter OR weekly"
        hasAttachment: false
        size: {bytes: 10240, comparison: larger}
      action:
        addLabels: ["Newsletters"]
        removeLabels: ["INBOX", "UNREAD"]   # archive + mark read
        forward: "alias@example.com"

Notes
- Label names are resolved during export; system labels appear as names like "INBOX", "TRASH", "CATEGORY_UPDATES".
- Future: a `filters sync` command can be added to apply the DSL back to Gmail.

Requirements
- Python 3.11
- Install: `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib pyyaml`

Gmail Auth
- Obtain Google OAuth credentials (OAuth client for Desktop app).
- Run: `python3 -m mail_assistant auth --credentials ~/.config/credentials.json --token ~/.config/token.json`
- Subsequent commands can reuse `--credentials`/`--token` or defaults under `~/.config/`.

Virtual Env + Executable
- Create venv and install editable package with console script:

  make venv

- Directly run the wrapper script (shebang):

  ./bin/mail_assistant --help

- After installing via venv, a console command is available:

  .venv/bin/mail-assistant --help

Tests
- Run tests in venv:

  make test


Binaries
- bin/mail_assistant: Python wrapper to run the CLI
Batched multi-account operations
- Define accounts in a YAML file:

  accounts:
    - name: personal
      provider: gmail
      credentials: ~/.config/credentials.json
      token: ~/.config/token.json
      cache: .cache/personal
    - name: work
      provider: gmail
      credentials: conf/work_credentials.json
      token: conf/work_token.json
      cache: .cache/work

- List accounts:
  - `python3 -m mail_assistant accounts list --config accounts.yaml`
- Export labels/filters for all or some accounts:
  - `python3 -m mail_assistant accounts export-labels --config accounts.yaml --out-dir exports/labels`
  - `python3 -m mail_assistant accounts export-filters --config accounts.yaml --out-dir exports/filters --accounts personal`
- Sync one configuration to many accounts (1→N):
  - `python3 -m mail_assistant accounts sync-labels --config accounts.yaml --labels config/labels.yaml --dry-run`
  - `python3 -m mail_assistant accounts sync-filters --config accounts.yaml --filters config/filters.yaml --dry-run`

Provider abstraction
- Current implementation supports `gmail` and `outlook` (Microsoft Graph).
- Core operations abstracted: list/create/update/delete labels, list/create/delete filters, list/add forwarding addresses.
- Caching: pass `--cache` per command or in accounts.yaml to enable on-disk caches for config endpoints and message sweeps.

Outlook provider (nearest mapping)
- Labels map to Outlook Categories (`/me/outlook/masterCategories`).
  - Color mapping uses Outlook’s built-in color names; YAML `color: {name: "preset"}` is accepted.
  - Visibility settings don’t exist in Outlook; they are ignored.
- Filters map to Inbox Rules (`/me/mailFolders/inbox/messageRules`).
  - Supported: match.from/to/subject (basic contains), action.add (assign categories), action.forward (forwardTo).
  - Not supported: action.remove (no direct remove via rules) — skipped with no-op.
- Auth uses Microsoft Graph device-code flow.
  - accounts.yaml example:

    accounts:
      - name: outlook
        provider: outlook
        client_id: YOUR_PUBLIC_CLIENT_ID
        tenant: consumers   # or your tenant GUID/domain
        token: ~/.config/outlook_token.json
        cache: .cache/outlook
Batched multi-account operations
Testing
- Dev requirements (from repo root): `pip install -r requirements-dev.txt`
- Run tests (from repo root): `pytest`

LLM prompt templates
- See `llm/` for `.llm` templates used to guide heuristics and UI text:
  - `llm/auto_propose.llm` — refine low-interest classification
  - `llm/labels_doctor.llm` — suggest label normalization
  - `llm/signatures_normalize.llm` — generate portable HTML signatures

Prompt Templates (.llm)
- See `/.llm` for reusable prompts used during configuration and audits:
  - `.llm/auto_propose.llm` — low-interest classification, avoids trial confirmations, suggests parent links
  - `.llm/labels_doctor.llm` — renames/merges and parent-label suggestions
  - `.llm/filters_explain.llm` — explain which filters match and why
  - `.llm/learn_suggestions.llm` — summarize learn proposals for review

Current Capabilities Snapshot
- Categories DSL: `action.categorizeAs` / `action.categories` → Gmail tabs (promotions/forums/updates/social/personal)
- Parent label rules (label-based):
  - Kids from Kids/* (e.g., Kids/Activities, Kids/Scouts) ⇒ add Kids
  - Lists from Lists/* (Commercial, Newsletters) ⇒ add Lists
  - Finance from Finance/* (Receipts, Orders, Merchants, Bills, Chase) ⇒ add Finance
  - Alumni from Alumni/* ⇒ add Alumni
- Learn/apply suggestions:
  - `labels learn` → domain→label proposals
  - `labels apply-suggestions` → create rules (optional sweep)
- Progressive sweeps:
  - `filters sweep-range` → iterate windows (e.g., 0..3650 days in 90/180‑day steps)
- Cleanup patterns:
  - Remove Lists/Newsletters from trial-confirmation subjects
- Custom mappings (examples):
  - Finance: TD/JPM/RBC/BMO/CIBC/AmEx/PayPal/Stripe/Square/Chase/WellsFargo/BoA/CapitalOne/Discover/HSBC/Fidelity/Schwab/Vanguard
  - Lists/Commercial: Adidas/IKEA/Patagonia/LEGO/Ridge/Anker/SharkNinja/Starbucks/Reebok/BestBuy/Costco/HomeDepot/Nike/NorthFace/Columbia/Lululemon/Gap/Apple
  - Lists/Newsletters: Substack, TheFutureParty
  - Political: mail.house.gov, senate.gov

Key Config Files
- `config/filters_*.yaml` — curated rule sets (finance, lists, kids, politics, forwarding, parents)
- `config/cleanup_*.yaml` — cleanup passes (e.g., trial confirmation)
- `reports_impact_*.md` — generated impact reports (counts per rule for 7d/180d)
 - Outlook parity
   - Categories: `./bin/mail-assistant --profile outlook_personal outlook categories list | export --out labels.yaml | sync --config labels.yaml`
   - Rules (categories): `./bin/mail-assistant --profile outlook_personal outlook rules plan --config filters.yaml`
   - Rules (move to folders): add `--move-to-folders` to `plan|sync` to move to a folder named after the first added label
## Unified Rules (imperative)
- Prefer a single unified config for all providers:
  - Labels: `config/labels_current.yaml`
  - Filters: `config/filters_unified.yaml` (match: from/to/subject/query; action: add/remove/forward/moveToFolder)
- Derive per provider from unified:
  - `./bin/mail-assistant config derive labels --in config/labels_current.yaml --out-gmail out/labels.gmail.yaml --out-outlook out/labels.outlook.yaml`
  - `./bin/mail-assistant config derive filters --in config/filters_unified.yaml --out-gmail out/filters.gmail.yaml --out-outlook out/filters.outlook.yaml`
- Optimize unified filters (merge same-destination rules with OR’d senders):
  - `./bin/mail-assistant config optimize filters --in config/filters_unified.yaml --out config/filters_unified.optimized.yaml --preview`
- Audit coverage (what % of Gmail’s simple rules are not unified):
  - Export Gmail: `./bin/mail-assistant --profile gmail_personal filters export --out out/filters.gmail.export.yaml`
  - Audit: `./bin/mail-assistant config audit filters --in config/filters_unified.yaml --export out/filters.gmail.export.yaml --preview-missing`

Defaults & current status
- Outlook defaults to move-to-folder (from first `action.add` label). Use `--categories-only` to turn off.
- Gmail auto-archives (remove INBOX) for low-priority labels in unified filters:
  - `Lists/Commercial`, `Lists/Newsletters`, `Lists/Updates`, `Cloud/OneDrive`, plus `Finance/ETrade`, `Finance/JPMorgan`.
- Retailers and finance senders are merged via `config optimize filters` for compact, maintainable rules.
- Coverage audit: simple Gmail rules currently 100% covered (0% not unified).

## GitHub
- Commit only unified sources and baselines:
  - Commit: `config/labels_current.yaml`, `config/filters_unified.yaml`, and optional baselines like `config/filters_unified.baseline.yaml`.
  - Do not commit derived outputs under `out/` (ephemeral) or secrets (credentials/tokens under `~/.config/`).
- Commit messages and PRs:
  - Use scoped subjects (e.g., `filters: add paypal + retailers`, `outlook: folders sync`).
  - Include a short summary of changes and updated audit results.
  - Attach command snippets used (derive/optimize/audit) and any sweep scope you ran (pages/top/days).
- Typical PR checklist:
  - Derive: `config derive labels|filters` from unified
  - Optimize: `config optimize filters --preview`
  - Audit: `config audit filters --in config/filters_unified.yaml --export out/filters.gmail.export.yaml --preview-missing`
  - Sync (local validation): Gmail/Outlook rules and a modest sweep (dry-runs preferred in CI)
- Baseline snapshots (optional):
  - Save current state to `config/filters_unified.baseline.yaml` before large edits and commit alongside README changes.

## Outlook Parity & Folders
- Move-to-folder is default for Outlook rules (derived from the first `action.add` label). Disable with `--categories-only`.
- Create Outlook folders to mirror Gmail label hierarchy: `./bin/mail-assistant --profile outlook_personal outlook folders sync --config out/labels.gmail.yaml`
- Sweep (modest): `outlook rules sweep --pages 1 --top 20 --use-cache`; aggressive: increase `--pages/--top`, `--clear-cache` to refresh.
