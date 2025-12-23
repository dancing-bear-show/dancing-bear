CLI Wrappers

Overview
- Thin entry points to run local package CLIs without installing system‑wide.

Included
- `mail` — Mail (Gmail/Outlook) CLI.
- `calendars` — Calendar helper CLI.
- `apply-calendar-locations` — Apply locations for Blas, Bruce (+ beginners), Bennet plans.

Usage
- Prefer profile-based invocation:
  - `PROFILE=outlook_personal ./bin/apply-calendar-locations --dry-run`
  - `./bin/mail-assistant --profile gmail_personal filters export --out out/filters.gmail.yaml`

