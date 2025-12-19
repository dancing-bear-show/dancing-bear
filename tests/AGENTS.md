Scope
- Applies to tests under `tests/`.

Guidelines
- Use `unittest` only; no external runners required.
- Target specific helpers and CLI argument parsing. Avoid broad end‑to‑end unless necessary.
- Skip network interactions; mock where appropriate.

