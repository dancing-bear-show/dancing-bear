# Personal Assistants

> *You don't need to outrun the bear. You just need to outrun everyone else.*

[![CI](https://github.com/dancing-bear-show/dancing-bear/actions/workflows/ci.yml/badge.svg)](https://github.com/dancing-bear-show/dancing-bear/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: qlty](https://img.shields.io/badge/code%20style-qlty-black)](https://qlty.sh)

**New here? Start with the [Getting Started Guide](GETTING_STARTED.md)** - zero to productive in 10 minutes.

---

Unified, dependency-light CLIs for personal workflows across mail, calendars, schedules,
phone layouts, resumes, and WhatsApp. Built to be safe by default (plan and dry-run first),
with a single YAML source of truth for Gmail and Outlook filters.

**Self-contained repository:** All tools, helpers, and utilities are contained within this repo.
External dependencies are minimized and lazily imported. This design ensures backwards
compatibility of the public CLI interface and reduces fragility from external package changes.
Internal APIs can be refactored freely—all call sites are updated atomically without needing
backwards-compatible wrappers.

## Quick Start

- Create venv and install:
  - `make venv`
- See help:
  - `./bin/assistant <apple-music|calendar|mail|maker|metals|phone|resume|schedule|whatsapp|wifi> --help`
  - `./bin/mail --help`
  - `./bin/calendar --help`
  - `./bin/schedule --help`

## Core CLIs

- Mail (Gmail and Outlook): `./bin/mail`
- Calendar (Outlook + Gmail scans): `./bin/calendar`
- Schedule (plan/apply calendar events): `./bin/schedule`
- Resume (extract/summarize/render): `./bin/assistant resume`
- Phone (iOS layout tooling): `./bin/phone`
- WhatsApp (local-only search): `./bin/whatsapp`
- WiFi (diagnostics): `./bin/wifi`
- Metals (precious metals tracking): `./bin/metals`
- Apple Music: `./bin/apple-music-assistant`
- Desk (macOS filesystem tidying): `python3 -m desk`
- Maker tools: `./bin/maker`

Legacy `-assistant` suffixed binaries still work (e.g., `./bin/mail-assistant`).

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
- Export: `./bin/mail labels export --out labels.yaml`
- Plan: `./bin/mail labels plan --config labels.yaml [--delete-missing]`
- Sync: `./bin/mail labels sync --config labels.yaml --dry-run`

Filters:
- Export: `./bin/mail filters export --out filters.yaml`
- Plan: `./bin/mail filters plan --config filters.yaml [--delete-missing]`
- Sync: `./bin/mail filters sync --config filters.yaml --dry-run`

Unified filters source of truth:
- Gmail only:
  - `python3 -m mail workflows gmail-from-unified --config config/filters_unified.yaml [--delete-missing] [--apply]`
- Gmail + Outlook (auto-detect):
  - `python3 -m mail workflows from-unified --config config/filters_unified.yaml [--delete-missing] [--apply]`
  - `--providers gmail,outlook` to control providers
  - `--no-outlook-move-to-folders` to disable Outlook folder moves

Outlook auth (device code):
- Start: `./bin/mail --profile outlook_personal outlook auth device-code`
- Complete: `./bin/mail --profile outlook_personal outlook auth poll --flow ~/.config/msal_flow.json --token ~/.config/outlook_token.json`
- One-shot (silent if cached): `./bin/mail --profile outlook_personal outlook auth ensure`

Other mail commands:
- Messages: `./bin/mail messages search --query "from:example@gmail.com"`
- Auto categorization: `./bin/mail auto propose` / `./bin/mail auto apply`
- Forwarding: `./bin/mail forwarding list` / `./bin/mail forwarding add`
- Signatures: `./bin/mail signatures export` / `./bin/mail signatures sync`
- Backup: `./bin/mail backup --out backups/`

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
- Plan: `./bin/schedule plan --source schedules/classes.csv --out out/schedule.plan.yaml`
- Apply (dry-run): `./bin/schedule apply --plan out/schedule.plan.yaml --dry-run`
- Apply: `./bin/schedule apply --plan out/schedule.plan.yaml --apply --calendar "Your Family"`
- Verify: `./bin/schedule verify --plan out/schedule.plan.yaml --calendar "Your Family" --from 2025-10-01 --to 2025-12-31`
- Sync: `./bin/schedule sync --plan out/schedule.plan.yaml --calendar "Your Family" --from 2025-10-01 --to 2025-12-31 --dry-run`

## Resume Assistant

Extract, summarize, align, and render resumes from LinkedIn profiles and existing documents.

### Typical Workflow

1. **Extract** unified data from sources (LinkedIn HTML, existing resume):
   ```
   ./bin/assistant resume extract --linkedin profile.html --out candidate.yaml
   ./bin/assistant resume extract --resume old_resume.docx --out candidate.yaml
   ```

2. **Initialize** a candidate skills file from unified data:
   ```
   ./bin/assistant resume candidate-init --data candidate.yaml --out candidate_skills.yaml
   ```

3. **Align** candidate data with a job posting to find keyword matches:
   ```
   ./bin/assistant resume align --data candidate.yaml --job job.yaml --out alignment.json
   ./bin/assistant resume align --data candidate.yaml --job job.yaml --tailored tailored.yaml
   ```

4. **Render** a DOCX resume using a template:
   ```
   ./bin/assistant resume render --data candidate.yaml --template template.yaml --out resume.docx
   ```

### Filtering and Tailoring

Filter skills and experience based on job alignment:
```
./bin/assistant resume render --data candidate.yaml --template template.yaml \
  --filter-skills-alignment alignment.json \
  --filter-exp-alignment alignment.json \
  --out tailored_resume.docx
```

### Structure Extraction

Infer section order and headings from a reference DOCX:
```
./bin/assistant resume structure --source reference.docx --out structure.yaml
./bin/assistant resume render --data candidate.yaml --template template.yaml \
  --structure-from reference.docx --out resume.docx
```

### Summarize

Generate heuristic summaries from unified data:
```
./bin/assistant resume summarize --data candidate.yaml --out summary.yaml
```

## iOS (Phone Assistant)

- Export device layout: `./bin/phone export-device --out out/ios.IconState.yaml`
- Build plan: `./bin/phone plan --layout out/ios.IconState.yaml --out out/ios.plan.yaml`
- Checklist: `./bin/phone checklist --plan out/ios.plan.yaml --layout out/ios.IconState.yaml --out out/ios.checklist.txt`
- Build profile: `./bin/phone profile build --plan out/ios.plan.yaml --out out/ios.mobileconfig`

## WhatsApp (local-only)

- Search text: `./bin/whatsapp search --contains school --limit 20`
- Search by contact: `./bin/whatsapp search --contact "Teacher" --since-days 30`

## WiFi Diagnostics

- Run diagnostics: `./bin/wifi diagnose`

## Desk (macOS Filesystem)

Keep your macOS filesystem tidy: scan, plan, and apply cleanup rules.
- Scan: `python3 -m desk scan --paths ~/Downloads --out scan.yaml`
- Plan: `python3 -m desk plan --config rules.yaml --out plan.yaml`
- Apply: `python3 -m desk apply --plan plan.yaml --dry-run`
- Rules: `python3 -m desk rules list`

## Metals (Precious Metals)

Track precious metals portfolio from email receipts:
- Extract (Gmail): `./bin/metals extract gmail --profile gmail_personal --out metals.yaml`
- Extract (Outlook): `./bin/metals extract outlook --profile outlook_personal --out metals.yaml`
- Costs: `./bin/metals costs --data metals.yaml`
- Spot prices: `./bin/metals spot fetch`
- Premium: `./bin/metals premium --data metals.yaml`
- Build summaries: `./bin/metals build --data metals.yaml --out summaries/`
- Excel merge: `./bin/metals excel merge --data metals.yaml --workbook portfolio.xlsx`

## Apple Music

- Ping/verify: `./bin/apple-music-assistant ping`
- List playlists: `./bin/apple-music-assistant list`
- Export: `./bin/apple-music-assistant export --out playlists.yaml`
- Create playlist: `./bin/apple-music-assistant create --preset workout`
- Dedupe: `./bin/apple-music-assistant dedupe --dry-run`

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
- `resume/` - extract/summarize/render resumes
- `phone/` - iOS layout tooling
- `whatsapp/` - local-only ChatStorage search
- `wifi/` - WiFi diagnostics
- `desk/` - macOS filesystem tidying
- `metals/` - precious metals tracking
- `apple_music/` - Apple Music API
- `maker/` - utility generators
- `core/` - shared helpers

## Code Quality and Testing

### Linting (qlty)
- Check files: `~/.qlty/bin/qlty check path/to/file.py`
- Check module: `~/.qlty/bin/qlty check mail/`
- Auto-fix: `~/.qlty/bin/qlty check --fix path/to/file.py`
- Linters: ruff (style), bandit (security), complexity metrics

### Testing
- Run tests: `make test` or `python3 -m unittest -v`
- With coverage: `coverage run -m unittest discover && coverage report`
- CI runs qlty + tests with coverage on every push/PR

### Security Comments
Use `# nosec B110/B112` (not `# noqa`) for intentional Bandit suppressions:
```python
except Exception:  # nosec B110 - non-fatal cache write
except Exception:  # nosec B112 - skip malformed entries
```

### Cleaning
- Clean: `make clean`
- Deep clean: `make distclean`

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

## Security

- Never commit credentials or tokens.
- Keep secrets under `~/.config/` or other local-only paths.
