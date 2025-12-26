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
- Phone (iOS layout tooling): `./bin/phone` or `./bin/phone-assistant`
- WhatsApp (local-only search): `./bin/whatsapp`
- WiFi (diagnostics): `./bin/wifi` or `./bin/wifi-assistant`
- Metals (precious metals tracking): `./bin/metals`
- Apple Music: `./bin/apple-music-assistant`
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

Context and navigation:
- Domain map: `./bin/llm domain-map --stdout`
- Inventory: `./bin/llm inventory --stdout`
- Familiarize: `./bin/llm familiar --stdout` (compact) or `--verbose`
- Agentic capsule: `./bin/llm agentic --stdout`

Flows (curated workflows):
- List all: `./bin/llm flows --list`
- Show flow: `./bin/llm flows --id <flow_id> --format md`
- Filter by tags: `./bin/llm flows --tags mail,gmail`

Code health:
- Staleness: `./bin/llm stale --with-status --limit 10`
- Dependencies: `./bin/llm deps --by combined --order desc --limit 10`
- CI check: `./bin/llm check --fail-on-stale`

Derive capsules:
- `./bin/llm derive-all --out-dir .llm`
- Per-app: `./bin/llm --app <app> derive-all --out-dir .llm --include-generated`

## Directory Layout

- `bin/` - CLI wrappers and entry points
- `config/` - canonical YAML inputs (source of truth)
- `out/` - derived outputs and plans
- `.llm/` - agent context, flows, capsules
- `tests/` - unittest suite

App modules:
- `mail/` - Gmail/Outlook providers, filters, labels, signatures
- `calendars/` - Outlook calendar + Gmail scans
- `schedule/` - plan/apply calendar schedules
- `phone/` - iOS layout tooling
- `whatsapp/` - local-only ChatStorage search
- `wifi/` - WiFi diagnostics
- `metals/` - precious metals tracking
- `apple_music/` - Apple Music API
- `maker/` - utility generators
- `core/` - shared helpers

## Cleaning and Tests

- Clean: `make clean`
- Deep clean: `make distclean`
- Tests: `make test` or `python3 -m unittest -v`

## Specialty Binaries

iOS device tooling:
- `bin/ios-install-profile` - Install .mobileconfig profiles
- `bin/ios-setup-device` - Initial device setup
- `bin/ios-use-device` - Switch active device
- `bin/ios-verify-layout` - Verify layout against plan
- `bin/ios-pages-sync` - Sync pages layout
- `bin/ios-iconmap-refresh` - Refresh icon map from device
- `bin/ios-hotlabel` - Hot-label app icons
- `bin/ios-identity-verify` - Verify signing identity
- `bin/ios-p12-to-der` - Convert P12 to DER format

Metals:
- `bin/extract-metals` - Extract metals data from Gmail
- `bin/extract-metals-costs` - Extract cost data
- `bin/outlook-metals-scan` - Scan Outlook for metals emails
- `bin/metals-premium` - Calculate premiums
- `bin/metals-spot-series` - Spot price series
- `bin/build-metals-summaries` - Build summary reports

Calendar:
- `bin/apply-calendar-locations` - Batch apply locations

## Security

- Never commit credentials or tokens.
- Keep secrets under `~/.config/` or other local-only paths.
