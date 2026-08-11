Scope
- Applies to tests under `tests/`.

Guidelines
- Use `unittest` only; no external runners required.
- Target specific helpers and CLI argument parsing. Avoid broad end-to-end unless necessary.
- Skip network interactions; mock where appropriate.
- **Never run bare `python3 -m unittest` in a worktree.** An inherited `PYTHONPATH` silently resolves imports to the main checkout and produces false greens. Use `make test` or `PYTHONPATH="$PWD/src" python3 -m unittest discover -s tests`. Run `make check-env` to verify.

