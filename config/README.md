Configuration

Overview
- Human‑editable YAML for labels, filters/rules, and calendar plans.
- Unified sources (preferred):
  - `filters_unified.yaml` → derive per‑provider outputs via CLI.
  - `labels_current.yaml` → derive Gmail/Outlook labels.
  - `calendar/` → canonical calendar plans (per calendar or per child) for backup.
 - Archived: legacy forwarding overlays consolidated into `filters_unified.yaml`.
   See `backups/filters_forwarding_vanesa.archived.yaml` for reference only.

Derivation
- Filters: `./bin/mail-assistant config derive filters --in config/filters_unified.yaml --out-gmail out/filters.gmail.yaml --out-outlook out/filters.outlook.yaml`
- Labels: `./bin/mail-assistant config derive labels --in config/labels_current.yaml --out-gmail out/labels.gmail.yaml --out-outlook out/labels.outlook.yaml`

Notes
- Avoid secrets in YAML. Keep DSLs concise and documented inline.

Calendar
- Directory: `config/calendar/`
  - Example plans: `your_family_blas.yaml`, `your_family_bruce.yaml`
  - Activities calendar: `activities.yaml` (empty scaffold to fill with drop‑in/community events)
  - Verify and sync with Outlook:
    - Verify: `./bin/schedule-assistant verify --plan config/calendar/your_family_blas.yaml --calendar "Your Family" --from 2025-10-01 --to 2025-12-31 --match subject-time`
    - Sync (dry-run): `./bin/schedule-assistant sync --plan config/calendar/your_family_bruce.yaml --calendar "Your Family" --from 2025-10-01 --to 2025-12-31`
    - Apply with cleanup: add `--delete-missing --apply` (and optionally `--delete-unplanned-series`)
  - Export from Outlook (backup):
    - `./bin/schedule-assistant export --calendar "Activities" --from 2025-10-01 --to 2025-12-31 --out config/calendar/activities.yaml --profile outlook_personal`
