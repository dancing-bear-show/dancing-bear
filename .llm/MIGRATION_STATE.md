Provider Abstraction Migration State
Canonical tracker for provider-based architecture

Current Status
- Base provider abstraction present; Gmail and Outlook paths implemented where applicable
- Profile-aware credentials via `~/.config/sre-utils/credentials.ini`
- Outlook device-code auth split into `outlook auth device-code` and `outlook auth poll`
- Gmail commands include labels: prune-empty/sweep-parents; filters: export/plan/sync (dry-run first)
- YAML read/write helpers centralized; optional JSON cache helpers available

Remaining Work (targeted)
- Migrate any direct `yaml.safe_*` calls to `yamlio` helpers in non-export paths
- Ensure capability gating for features not supported by a provider (e.g., Outlook signatures)
- Consider aligning Outlook rules caching with JSON cache helpers for parity

Core Migration Plan (personal_core -> core)
- Scope: move shared LLM/auth/yaml/text/assistant helpers into `core` and keep `personal_core` as compatibility shims until cutover.
- Current Progress: `core/*` modules created (agentic, textio, yamlio, auth, assistant, assistant_cli, llm_cli); imports updated across assistants/LLM wrappers; `personal_core` shims in place; entry point uses `core.assistant_cli`.
- Remaining Work:
  - Decide when to drop `personal_core*` from packaging and remove shims.
  - Update any remaining docs/tests that treat `personal_core` as primary, if needed.
  - Run targeted sanity checks: `./bin/llm --help`, `python3 -m unittest tests/test_llm_cli.py -v`, plus optional full suite.
- Notes: keep shims until downstream uses are migrated; removing shims requires updating external references.

CLI Rename Plan (assistant names)
- Goals: drop the "-assistant" suffix in CLIs while keeping package names stable, centralize shared code under `core`, and keep compatibility shims (DRY, OO reuse, high testing).
- Phase 0: define the CLI name map (old → new) and pick a pilot assistant.
- Phase 1: add new CLI wrappers + entry points (e.g., `mail`, `calendar`, `schedule`) while keeping old names; add tests so both names route correctly.
- Phase 2: update docs, flows, and `.llm/DOMAIN_MAP.md` to reference the new CLI names.
- Phase 3: deprecate old CLI names after downstream usage migrates.
- Validation: run targeted tests per assistant + `tests/test_assistant_cli.py`, then full suite when ready.

Testing
- Keep tests lightweight; add only for new CLI surfaces or helpers touched

Notes
- A legacy file `.llm/MIGRAGION_PLAN.md` exists and is retained for reference
- This file is the canonical, up-to-date tracker
