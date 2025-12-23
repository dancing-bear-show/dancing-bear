# Per-App LLM Checklist

For each app below, ensure the following artifacts and docs stay in sync (rename docs/targets accordingly if the app name changes).

## Mail
- [x] `bin/llm` derives `AGENTIC.md` / `DOMAIN_MAP.md` via `./bin/llm derive-all --out-dir .llm --include-generated`.
- [x] README / `mail/AGENTS.md` reference `./bin/llm derive-all` and capsule outputs.
- [x] Tests under `mail/tests/test_llm_*.py` cover agentic/familiar/flows.
- [ ] For optional app-specific runs, prefer `./bin/llm --app mail <cmd>` to keep syntax consistent across apps.

## Calendar
- [x] Run `./bin/llm --app calendar derive-all --out-dir .llm --include-generated`.
- [x] `calendars/README.md` notes the `llm --app calendar ...` commands.
- [x] `calendars/tests/test_llm_cli.py` stays green.

## Schedule
- [x] Run `./bin/llm --app schedule derive-all --out-dir .llm --include-generated`.
- [x] `schedule/README.md` and `AGENTS.md` reference `llm --app schedule`.
- [x] `tests/test_schedule_llm_cli.py` covers agentic + derive-all.

## Resume
- [x] Run `./bin/llm --app resume derive-all --out-dir .llm --include-generated`.
- [x] `resume/README.md` and `AGENTS.md` mention `llm --app resume`.
- [x] `tests/test_resume_llm_cli.py` stays up to date.

## Desk
- [x] Run `./bin/llm --app desk derive-all --out-dir .llm --include-generated`.
- [x] `desk/README.md` / `AGENTS.md` guide `llm --app desk` usage.
- [x] `tests/test_desk_llm_cli.py` exercises agentic + derive-all.

## Maker
- [x] Run `./bin/llm --app maker derive-all --out-dir .llm --include-generated`.
- [x] Maker README/AGENTS describe `llm --app maker` commands.
- [x] `tests/test_maker_llm_cli.py` and `tests/test_maker_derive_all_generated.py` cover CLI behavior.

## Phone
- [x] Run `./bin/llm --app phone derive-all --out-dir .llm --include-generated`.
- [x] Phone README/AGENTS reference `llm --app phone`.
- [x] `tests/test_phone_llm_cli.py` covers the CLI.

## WhatsApp
- [x] Run `./bin/llm --app whatsapp derive-all --out-dir .llm --include-generated`.
- [x] `whatsapp/AGENTS.md` references the `llm --app whatsapp` helper.
- [x] Add/update tests if the CLI gains new surfaces (tracked via `tests/test_whatsapp_cli.py`).
