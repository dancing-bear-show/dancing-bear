Architecture State
Canonical reference for the current provider-based architecture

Provider Abstraction
- Base provider abstraction present; Gmail and Outlook paths implemented where applicable
- Profile-aware credentials via `~/.config/credentials.ini`
- Outlook device-code auth: `outlook auth.device-code` then `outlook auth.poll`
- YAML read/write helpers centralized in `core.yamlio`; optional JSON cache helpers available

Remaining (targeted)
- Migrate any direct `yaml.safe_*` calls to `yamlio` helpers in non-export paths
- Ensure capability gating for features not supported by a provider (e.g., Outlook signatures)
- Consider aligning Outlook rules caching with JSON cache helpers for parity

Completed Migrations
- `personal_core/` → `core/`: all imports use `core.*`; no shims
- CLI rename: `-assistant` suffix dropped; short wrappers (`mail`, `calendar`, etc.) in place; legacy aliases retained
- `bin/` wrappers: config-driven via `bin/_wrappers.yaml`; regenerate with `make bin-wrappers`
- SafeProcessor/BaseProducer/RequestConsumer: all domains migrated (mail, calendars, desk, phone, schedule, wifi, whatsapp, maker); resume uses custom FilterPipeline
- CI/CD: `.github/workflows/ci.yml` on push/PR (qlty + tests + coverage)
- Pipeline migration complete; `PIPELINE_MIGRATION.md` removed

Testing
- Keep tests lightweight; add only for new CLI surfaces or helpers touched
