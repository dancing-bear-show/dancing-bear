Calendar Assistant

Overview
- Adds single or recurring Outlook events, lists calendar windows, verifies plans, and applies/updates event locations from YAML.

 Key Commands
- Add single: `./bin/calendar --profile outlook_personal outlook add --subject "Soccer" --calendar "Your Family" --start 2025-10-10T17:00 --end 2025-10-10T18:00 --location "Venue (street, city, ST POSTAL)"`
- Add recurring: `./bin/calendar --profile outlook_personal outlook add-recurring --subject "Class" --repeat weekly --byday MO --interval 1 --range-start 2025-10-01 --until 2025-12-15 --start-time 17:00 --end-time 17:30 --location "Name at Facility 123 Main St, City, ST A1A 1A1"`
- Agentic capsule: `./bin/calendar --agentic`
 - LLM utilities (calendar): `./bin/llm --app calendar agentic --stdout` | `./bin/llm --app calendar domain-map --stdout` | `./bin/llm --app calendar derive-all --out-dir .llm`
- Suppress reminders: add `--no-reminder` to any create command
- Apply locations from YAML: `./bin/calendar --profile outlook_personal outlook apply-locations --config out/calendar/blas_current.plan.yaml --all-occurrences` (example path; adjust to your plan file)
- Turn off reminders in a window: `./bin/calendar --profile outlook_personal outlook reminders-off --calendar "Your Family" --from 2025-01-01 --to 2025-12-31 --all-occurrences`
- Legacy CLI: `./bin/calendar-assistant`

Appointment Settings (bulk)
- Apply categories/showAs/sensitivity/reminders from YAML rules across a window:
  - `./bin/calendar --profile outlook_personal outlook settings-apply --calendar "Activities" --from 2025-01-01 --to 2026-06-30 --config config/appointment_settings.yaml --dry-run`
- YAML example:
  ```yaml
  settings:
    defaults:
      show_as: busy
      is_reminder_on: true
      reminder_minutes: 5
    rules:
      - match:
          subject_contains: ["Swim", "Hockey"]
        set:
          categories: ["Kids", "Sports"]
          reminder_minutes: 10
      - match:
          subject_regex: "Parent-Teacher.*"
        set:
          categories: ["School"]
          sensitivity: private
  ```

Reminders Sweep
- Disable reminders across multiple years/calendars using the helper script:
  - `./bin/reminders-off-sweep -p outlook_personal -c "Your Family,Activities" -s 2021 -e 2026`
  - Add `-n` for a dry-run preview.

Schedule Importer (scaffold)
- Import a rec centre schedule into a dedicated calendar from CSV/XLSX (PDF/website planned):
  - `./bin/calendar --profile outlook_personal outlook schedule-import --calendar "Community Centre" --source schedules/fall.csv --kind csv --tz America/Toronto`
- CSV/XLSX columns supported:
  - One-off events: `Subject`, `Start` (YYYY-MM-DDTHH:MM), `End` (YYYY-MM-DDTHH:MM), `Location`, `Notes`
  - Recurring events: `Subject`, `Recurrence` (`weekly`|`daily`|`monthly`), `ByDay` (e.g., `MO,WE` for weekly), `StartTime` (HH:MM 24h), `EndTime`, `StartDate` (YYYY-MM-DD), `Until` (or `EndDate`) or `Count`, `Location` (or `Address`), `Notes`
- Creates the calendar if missing. Use `--dry-run` to preview.
  - Add `--no-reminder` to suppress event reminders/alerts when importing

Location Format
- Prefer: `Name (street, city, ST POSTAL)` or `Name at Facility street, city, ST POSTAL`.
- Canadian postal codes with or without space are supported (e.g., `L4G 1J5`).
