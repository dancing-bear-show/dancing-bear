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

Testing
- Keep tests lightweight; add only for new CLI surfaces or helpers touched

Notes
- A legacy file `.llm/MIGRAGION_PLAN.md` exists and is retained for reference
- This file is the canonical, up-to-date tracker

