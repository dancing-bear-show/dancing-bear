Schedule Assistant

Overview
- Placeholder for future schedule planning and apply helpers.
- For now, use the Calendar Assistant’s schedule import to create Outlook events from CSV/XLSX/PDF/website inputs.

Recommended Commands
- Import schedules into a dedicated calendar:
  - `./bin/calendar-assistant --profile outlook_personal outlook schedule-import --calendar "Community Centre" --source schedules/fall.csv --kind csv --tz America/Toronto`
- Plan to YAML (ephemeral):
  - `./bin/schedule-assistant plan --source schedules/fall.csv --out out/schedule.plan.yaml`
- Apply from plan (dry-run by default):
  - `./bin/schedule-assistant apply --plan out/schedule.plan.yaml --dry-run`
  - `./bin/schedule-assistant apply --plan out/schedule.plan.yaml --apply --calendar "Your Family"`
- LLM capsules (agentic/domain-map/familiar/policies):
  - `./bin/llm --app schedule agentic --stdout`
  - `./bin/llm --app schedule domain-map --stdout`
  - `./bin/llm --app schedule derive-all --out-dir .llm --include-generated --stdout`
- Notes:
  - Write plans to `out/` (tracked).

Notes
- When the Schedule Assistant CLI becomes available, this wrapper (`./bin/schedule-assistant`) will invoke it directly.
- Keep inputs under `config/` or a local `schedules/` folder; write outputs to `out/`.
