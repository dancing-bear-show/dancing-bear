Scope
- Applies to scripts under `maker/`.

Guidelines
- Keep scripts idempotent and deterministic given the same inputs.
- No secrets in code or logs. Read credentials via profiles when necessary.
- Emit artifacts into `out/` and avoid modifying source YAML directly.
- LLM helpers:
  - `./bin/llm --app maker agentic --stdout`
  - `./bin/llm --app maker domain-map --stdout`
  - `./bin/llm --app maker derive-all --out-dir .llm --include-generated`
