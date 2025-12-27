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
- Scope: move shared LLM/auth/yaml/text/assistant helpers into `core`.
- Status: ✅ COMPLETE (Dec 2024)
  - `core/*` modules created (agentic, textio, yamlio, auth, assistant, assistant_cli, llm_cli)
  - All imports updated to use `core.*` directly
  - `personal_core/` removed (no shims needed)

CLI Rename Plan (assistant names)
- Goals: drop the "-assistant" suffix in CLIs while keeping package names stable, centralize shared code under `core`, and keep compatibility shims (DRY, OO reuse, high testing).
- Phase 0: ✅ COMPLETE - CLI name map defined, wrappers consolidated.
- Phase 1: ✅ COMPLETE - New CLI wrappers (`mail`, `calendar`, `schedule`, etc.) in place; legacy `-assistant` aliases preserved.
- Phase 2: ✅ COMPLETE - Docs and flows reference new CLI names.
- Phase 3: Legacy `-assistant` aliases retained for compatibility; deprecation optional.
- Validation: `tests/test_assistant_cli.py` + full suite passing.

bin/ Wrapper Consolidation (completed Dec 2024)
- Config-driven generation: `bin/_wrappers.yaml` defines 14 Python entry points + 5 legacy aliases.
- Generator: `bin/_gen_wrappers.py` reads config and generates wrappers; `make bin-wrappers` to regenerate.
- Removed: 36 bash shortcut wrappers (gmail-*, outlook-*, ios-*); use CLI directly:
  - `./bin/mail filters export` (was: `gmail-filters-export`)
  - `./bin/mail outlook rules.sync` (was: `outlook-rules-sync`)
  - `./bin/phone plan` (was: `ios-plan`)
- Tests: `tests/test_gen_wrappers.py` (14 tests)

CI/CD (completed Dec 2024)
- Workflows: `.github/workflows/ci.yml` runs on push/PR
- Jobs: `qlty` (linting via ruff/bandit), `tests` (unittest + coverage)
- CODEOWNERS: `.github/CODEOWNERS` assigns @brian-sherwin as default owner
- Copilot Code Review: enabled via repository ruleset

Testing
- Keep tests lightweight; add only for new CLI surfaces or helpers touched

Notes
- A legacy file `.llm/MIGRAGION_PLAN.md` exists and is retained for reference
- This file is the canonical, up-to-date tracker
