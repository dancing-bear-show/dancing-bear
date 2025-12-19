Scope
- Applies to files under `schedule_assistant/`.

Guidelines
- Follow repo conventions: small helpers, stable CLI, YAML inputs.
- Add tests for new behaviors under `tests/`.
- Use the assistant-specific LLM tooling to refresh capsules:
  - `./bin/llm --app schedule agentic --stdout`
  - `./bin/llm --app schedule domain-map --stdout`
  - `./bin/llm --app schedule derive-all --out-dir .llm --include-generated`
