Scope
- Applies to files under `schedule/`.

Guidelines
- Follow repo conventions: small helpers, stable CLI, YAML inputs.
- Use `core.cli_args` for Outlook auth flags and `core.auth` service builders in CLI wiring.
- Add tests for new behaviors under `tests/`.
- Use the assistant-specific LLM tooling to refresh capsules:
  - `./bin/llm --app schedule agentic --stdout`
  - `./bin/llm --app schedule domain-map --stdout`
  - `./bin/llm --app schedule derive-all --out-dir .llm --include-generated`
