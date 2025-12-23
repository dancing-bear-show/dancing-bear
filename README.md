# Personal Assistants

Unified, dependency-light CLIs for personal workflows across mail, calendars, schedules,
phone layouts, resumes, and WhatsApp. Built to be safe by default (plan and dry-run first),
with a single YAML source of truth for Gmail and Outlook filters.

## Quick Start

- Create venv and install:
  - `make venv`
- See help:
  - `./bin/assistant <mail|calendar|schedule|resume|phone|whatsapp|maker> --help`
  - `./bin/mail-assistant --help`
  - `./bin/calendar-assistant --help`
  - `./bin/schedule-assistant --help`

## Core CLIs

- Mail (Gmail and Outlook): `./bin/mail-assistant`
- Calendar (Outlook + Gmail scans): `./bin/calendar-assistant`
- Schedule (plan/apply calendar events): `./bin/schedule-assistant`
- Resume: `./bin/resume-assistant`
- Phone (iOS layout tooling): `./bin/phone`
- WhatsApp (local-only search): `./bin/whatsapp`
- Maker tools: `./bin/maker`

## Credentials and Profiles

Prefer profiles in `~/.config/credentials.ini` and avoid passing tokens on the CLI.

Example:
```
[mail.gmail_personal]
credentials = /Users/you/.config/google_credentials.gmail_personal.json
token = /Users/you/.config/token.gmail_personal.json

[mail.outlook_personal]
outlook_client_id = <YOUR_APP_ID>
tenant = consumers
outlook_token = /Users/you/.config/outlook_token.json
```

Create starter creds:
- `mkdir -p ~/.config && cp credentials.example.json ~/.config/credentials.json`
- One-shot auth helper:
  - `./bin/mail-assistant-auth`

Legacy paths still supported:
- `~/.config/sre-utils/credentials.ini`
- `~/.config/sreutils/credentials.ini`

## Mail Workflows (Gmail and Outlook)

Labels:
- Export: `./bin/mail-assistant labels export --out labels.yaml`
- Plan: `./bin/mail-assistant labels plan --config labels.yaml [--delete-missing]`
- Sync: `./bin/mail-assistant labels sync --config labels.yaml --dry-run`

Filters:
- Export: `./bin/mail-assistant filters export --out filters.yaml`
- Plan: `./bin/mail-assistant filters plan --config filters.yaml [--delete-missing]`
- Sync: `./bin/mail-assistant filters sync --config filters.yaml --dry-run`

Unified filters source of truth:
- Gmail only:
  - `python3 -m mail workflows gmail-from-unified --config config/filters_unified.yaml [--delete-missing] [--apply]`
- Gmail + Outlook (auto-detect):
  - `python3 -m mail workflows from-unified --config config/filters_unified.yaml [--delete-missing] [--apply]`
  - `--providers gmail,outlook` to control providers
  - `--no-outlook-move-to-folders` to disable Outlook folder moves

Outlook auth (device code):
- Start: `./bin/mail-assistant --profile outlook_personal outlook auth device-code`
- Complete: `./bin/mail-assistant --profile outlook_personal outlook auth poll --flow ~/.config/msal_flow.json --token ~/.config/outlook_token.json`
- One-shot (silent if cached): `./bin/mail-assistant --profile outlook_personal outlook auth ensure`

## Calendar (Outlook)

Plan, verify, and apply from YAML:
- Verify: `./bin/calendar --profile outlook_personal outlook verify-from-config --config out/plan.yaml`
- Apply: `./bin/calendar --profile outlook_personal outlook add-from-config --config out/plan.yaml`

Locations and cleanup:
- Update locations from Outlook: `./bin/calendar --profile outlook_personal outlook update-locations --config out/plan.yaml --calendar "Your Family"`
- Remove events from plan: `./bin/calendar --profile outlook_personal outlook remove-from-config --config out/plan.yaml --calendar "Your Family" --apply`
- Deduplicate series: `./bin/calendar --profile outlook_personal outlook dedup --calendar "Your Family" --from 2025-01-01 --to 2026-12-31 --prefer-delete-nonstandard --keep-newest --apply`

## Schedule Assistant

Plan, apply, verify, and sync events:
- Plan: `./bin/schedule-assistant plan --source schedules/classes.csv --out out/schedule.plan.yaml`
- Apply (dry-run): `./bin/schedule-assistant apply --plan out/schedule.plan.yaml --dry-run`
- Apply: `./bin/schedule-assistant apply --plan out/schedule.plan.yaml --apply --calendar "Your Family"`
- Verify: `./bin/schedule-assistant verify --plan out/schedule.plan.yaml --calendar "Your Family" --from 2025-10-01 --to 2025-12-31`
- Sync: `./bin/schedule-assistant sync --plan out/schedule.plan.yaml --calendar "Your Family" --from 2025-10-01 --to 2025-12-31 --dry-run`

## iOS (Phone Assistant)

- Export device layout: `./bin/phone export-device --out out/ios.IconState.yaml`
- Build plan: `./bin/phone plan --layout out/ios.IconState.yaml --out out/ios.plan.yaml`
- Checklist: `./bin/phone checklist --plan out/ios.plan.yaml --layout out/ios.IconState.yaml --out out/ios.checklist.txt`
- Build profile: `./bin/phone profile build --plan out/ios.plan.yaml --out out/ios.mobileconfig`

## WhatsApp (local-only)

- Search text: `./bin/whatsapp search --contains school --limit 20`
- Search by contact: `./bin/whatsapp search --contact "Teacher" --since-days 30`

## LLM Utilities

- Inventory: `./bin/llm inventory --stdout`
- Familiarize capsule: `./bin/llm familiar --stdout`
- Policies: `./bin/llm policies --stdout`
- Derive all capsules: `./bin/llm derive-all --out-dir .llm`

Per-app capsules:
- `./bin/llm --app calendar derive-all --out-dir .llm --include-generated`
- `./bin/llm --app schedule derive-all --out-dir .llm --include-generated`
- `./bin/llm --app resume derive-all --out-dir .llm --include-generated`
- `./bin/llm --app desk derive-all --out-dir .llm --include-generated`
- `./bin/llm --app phone derive-all --out-dir .llm --include-generated`
- `./bin/llm --app whatsapp derive-all --out-dir .llm --include-generated`

## Directory Layout

- `bin/` - CLI wrappers
- `config/` - canonical YAML inputs
- `out/` - derived outputs and plans
- `.llm/` - agent context, flows, capsules
- `tests/` - unittest suite

## Cleaning and Tests

- Clean: `make clean`
- Deep clean: `make distclean`
- Tests: `make test` or `python3 -m unittest -v`

## Convenience Wrappers (cars-sre-utils style)

Mail wrappers:
- `bin/gmail-auth` -> `mail-assistant auth`
- `bin/gmail-labels-export` -> `mail-assistant labels export`
- `bin/gmail-labels-sync` -> `mail-assistant labels sync`
- `bin/gmail-filters-export` -> `mail-assistant filters export`
- `bin/gmail-filters-sync` -> `mail-assistant filters sync`
- `bin/gmail-filters-impact` -> `mail-assistant filters impact`
- `bin/gmail-filters-sweep` -> `mail-assistant filters sweep`

Outlook wrappers:
- `bin/outlook-auth-device-code` -> `mail-assistant outlook auth device-code`
- `bin/outlook-auth-poll` -> `mail-assistant outlook auth poll`
- `bin/outlook-auth-ensure` -> `mail-assistant outlook auth ensure`
- `bin/outlook-auth-validate` -> `mail-assistant outlook auth validate`
- `bin/outlook-rules-list` -> `mail-assistant outlook rules list`
- `bin/outlook-rules-export` -> `mail-assistant outlook rules export`
- `bin/outlook-rules-plan` -> `mail-assistant outlook rules plan`
- `bin/outlook-rules-sweep` -> `mail-assistant outlook rules sweep`
- `bin/outlook-rules-sync` -> `mail-assistant outlook rules sync`
- `bin/outlook-rules-delete` -> `mail-assistant outlook rules delete`
- `bin/outlook-categories-list` -> `mail-assistant outlook categories list`
- `bin/outlook-categories-export` -> `mail-assistant outlook categories export`
- `bin/outlook-categories-sync` -> `mail-assistant outlook categories sync`
- `bin/outlook-folders-sync` -> `mail-assistant outlook folders sync`
- `bin/outlook-calendar-add` -> `mail-assistant outlook calendar add`
- `bin/outlook-calendar-add-recurring` -> `mail-assistant outlook calendar add-recurring`
- `bin/outlook-calendar-add-from-config` -> `mail-assistant outlook calendar add-from-config`

Phone wrappers:
- `bin/ios-export` -> `phone export-device`
- `bin/ios-plan` -> `phone plan`
- `bin/ios-checklist` -> `phone checklist`
- `bin/ios-profile-build` -> `phone profile build`
- `bin/ios-manifest-create` -> `phone manifest create`
- `bin/ios-manifest-build-profile` -> `phone manifest build-profile`
- `bin/ios-manifest-from-device` -> `phone manifest from-device`
- `bin/ios-manifest-install` -> `phone manifest install`
- `bin/ios-analyze` -> `phone analyze`
- `bin/ios-auto-folders` -> `phone auto-folders`
- `bin/ios-unused` -> `phone unused`
- `bin/ios-prune` -> `phone prune`
- `bin/ios-iconmap-refresh` -> `cfgutil get-icon-layout + phone export-device`

Security:
- Never commit credentials or tokens.
- Keep secrets under `~/.config/` or other local-only paths.
