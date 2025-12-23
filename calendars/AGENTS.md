Scope
- This file governs the entire `calendars/` CLI module.

Guidelines
- Keep CLI flags stable; extend with additive options only (e.g., `--all-occurrences`).
- Use `core.cli_args` for Gmail/Outlook auth flags and `core.auth` service builders in CLI wiring.
- Reuse `mail.outlook_api.OutlookClient` for Graph calls.
- Keep address parsing dependency‑light; heuristics are acceptable with clear fallback to displayName.
- Ensure updates target series masters when present, else fall back to occurrences.

Testing
- Use `unittest` in `tests/` for matching/selection helpers and parser behavior.
