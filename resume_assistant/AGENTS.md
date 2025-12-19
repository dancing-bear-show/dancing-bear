Scope
- Applies to files under `resume_assistant/`.

Guidelines
- Keep modules small and avoid heavy formatting dependencies.
- Document any CLI entry points or scripts in a local README.
- Do not include private data or secrets.
- LLM helpers exist for this assistant:
  - `./bin/llm --app resume agentic --stdout` (capsule preview)
  - `./bin/llm --app resume domain-map --stdout`
  - `./bin/llm --app resume derive-all --out-dir .llm --include-generated`
