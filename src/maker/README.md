Maker

Overview
- Utility scripts and generators to produce derived configs or artifacts.

Usage
- Prefer invoking via `bin/` wrappers or package CLIs where possible.
- Keep outputs under `out/` and sources under `config/`.
- LLM helpers:
  - `./bin/llm --app maker agentic --stdout`
  - `./bin/llm --app maker domain-map --stdout`
  - `./bin/llm --app maker derive-all --out-dir .llm --include-generated`
