# Agent Guidelines for desk-assistant

These instructions guide LLM agents working in this repository.

## Project Structure & Module Organization
- `desk_assistant/` — Core library and CLI entrypoints.
- `bin/` — Wrapper scripts (e.g., `bin/desk-assistant`).
- `tests/` — Minimal CLI smoke/unit tests.
- `_disasm/` — Reserved for references; do not modify.

## Build, Test, and Development Commands
- Setup venv: `python3 -m venv .venv && source .venv/bin/activate`
- Install package (editable): `make venv` or `pip install -e .[yaml]`
- CLI help: `./bin/desk-assistant --help` or `.venv/bin/desk-assistant --help`
- Scan:
  - `python3 -m desk_assistant scan --paths ~/Downloads ~/Desktop --min-size 100MB --older-than 30d --duplicates`
- Rules
  - Export: `python3 -m desk_assistant rules export --out rules.yaml`
- Planning
  - Plan: `python3 -m desk_assistant plan --config rules.yaml --out plan.yaml`
- Apply
  - `python3 -m desk_assistant apply --plan plan.yaml [--dry-run]`
- Tests: `make test` or `python3 -m unittest tests/test_cli.py -v`

## Coding Style & Conventions
- Python 3.9; prefer small, dependency‑light modules.
- Use lazy imports for optional deps (e.g., PyYAML).
- 4‑space indentation; `snake_case` for functions/vars; `CapWords` for classes.
- Keep public CLI stable; do not break flags or subcommands.
- Keep helpers small and focused; avoid broad refactors.
- YAML DSLs must remain human‑editable and documented with brief comments.

## Testing Guidelines
- Framework: `unittest` only; keep tests lightweight.
- Add targeted tests only for new CLI surfaces or behaviors.
- Naming: files as `test_*.py`; methods as `test_*`.

## Refactor Discipline
- Make changes surgical and incremental.
- Fix root causes, avoid unrelated edits.

## LLM Activation
- Always activate when this repository is opened; no opt‑in required.
- Use concise preambles for tool calls and keep an up‑to‑date plan.
- Prefer the wrapper `./bin/desk-assistant`.
- Default to venv context if present (`.venv`), but do not block if absent.
- LLM helper commands:
  - `./bin/llm --app desk agentic --stdout`
  - `./bin/llm --app desk domain-map --stdout`
  - `./bin/llm --app desk derive-all --out-dir .llm --include-generated`

## Deduplication & Modular Design
- Apply DRY: factor repeated logic into small helpers under `desk_assistant/`.
- Extract shared CLI argument definitions into helper functions; preserve existing flag names and semantics.
- Prefer OO when it improves cohesion/encapsulation; keep methods small.
- Keep lazy imports inside functions/methods for optional deps.
- Introduce new modules incrementally; avoid breaking the public CLI.
