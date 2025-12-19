# LLM CLI Migration Checklist

- [x] Inventory every assistant that still shells through `mail_assistant.llm_cli` or `bin/llm`; note the entry files/wrappers to update.
  - Assistants already on the new `LlmConfig` flow: `calendar_assistant/llm_cli.py`, `maker/llm_cli.py`, `phone/llm_cli.py`, `whatsapp/llm_cli.py`.
  - Legacy shim still exporting the shared CLI: `mail_assistant/llm_cli.py` plus wrapper `mail_assistant/bin/llm` and repo-level `bin/llm`; dozens of `mail_assistant/tests/test_llm_*.py` import this path directly.
  - Assistants missing any `llm_cli` (need new module + wrapper + tests): `schedule_assistant`, `resume_assistant`, `desk_assistant`, `ios_home_assistant` (if kept), and any others in `*/assistant` without an `llm_cli.py`.
- [x] For each assistant, add a dedicated `llm_cli.py` using `personal_core.llm_cli.LlmConfig` plus matching `bin/llm-<assistant>` wrappers.
  - New adopters wired this round: `schedule_assistant/llm_cli.py`, `resume_assistant/llm_cli.py`, and `desk_assistant/llm_cli.py` with wrappers (`bin/llm-schedule`, `bin/llm-resume`, `bin/llm-desk`) and smoke tests in `tests/test_*_llm_cli.py`.
  - Remaining legacy shim: `mail_assistant/llm_cli.py` via repo-level `bin/llm`; clean up after final migrations (ios_home_assistant is currently dormant).
- [x] Port or add smoke tests (agentic, derive-all, familiar verbose) so every assistant proves the new CLI path.
  - Added coverage: `tests/test_schedule_llm_cli.py`, `tests/test_resume_llm_cli.py`, `tests/test_desk_llm_cli.py`, `tests/test_phone_llm_cli.py`, `tests/test_maker_llm_cli.py`, `tests/test_calendar_llm_cli.py`, `tests/test_workflows*.py` already cover the rest. Mail assistant keeps its historical suite under `mail_assistant/tests/test_llm_*.py`.
- [x] Update AGENTS/DOMAIN_MAP docs to list the new LLM helpers and expected derive-all artifacts.
  - README + AGENTS call out `llm-schedule`, `llm-resume`, `llm-desk`, `llm --app phone`, `llm-whatsapp` derive commands.
  - Assistant-specific README/AGENTS files now document their `llm-*` commands, and `.llm/DOMAIN_MAP.md` records the derived artifact filenames per assistant.
- [x] Remove the old contributor registry plumbing once every assistant has migrated, keeping `bin/llm` as a thin aggregate if still needed.
  - Deleted `mail_assistant/llm_contrib.py` and the legacy `personal_core/llm_cli_base.py`.
  - `bin/llm` now directly calls `personal_core.llm_cli.main`; the repo-level CLI loads capsule/flow data via `mail_assistant.agentic` instead of a registry.
- [x] Rerun `derive-all --include-generated` per assistant and commit the refreshed `.llm/AGENTIC_*.md`, `DOMAIN_MAP_*.md`, inventory, familiar, and policy capsules.
  - Commands run: `./bin/llm derive-all ...`, `./bin/llm-calendar derive-all ...`, `./bin/llm-schedule derive-all ...`, `./bin/llm-resume derive-all ...`, `./bin/llm-desk derive-all ...`, `./bin/llm-maker derive-all ...`, `./bin/llm --app phone derive-all ...`, `./bin/llm-whatsapp derive-all ...`.
