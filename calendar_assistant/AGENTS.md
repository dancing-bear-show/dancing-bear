Scope
- This file governs the entire `calendar_assistant/` CLI module.

Guidelines
- Keep CLI flags stable; extend with additive options only (e.g., `--all-occurrences`).
- Reuse `mail_assistant.outlook_api.OutlookClient` for Graph calls.
- Keep address parsing dependency‑light; heuristics are acceptable with clear fallback to displayName.
- Ensure updates target series masters when present, else fall back to occurrences.

Testing
- Use `unittest` in `tests/` for matching/selection helpers and parser behavior.

