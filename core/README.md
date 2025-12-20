# Core Modules

Shared scaffolding for all assistants plus lightweight utilities used across CLIs.
Modules:

- `pipeline.py` — protocol definitions plus the `ResultEnvelope` helper.
- `context.py` — lightweight `AppContext` used to pass args/config/root paths.
- `testing.py` — reusable stubs to exercise individual stages in unit tests.
- `agentic.py` — agentic capsule helpers (CLI tree, section building).
- `textio.py` — UTF-8 read/write helpers.
- `yamlio.py` — YAML read/write helpers.
- `auth.py` — shared Gmail/Outlook auth resolution and service builders (including `*_from_args` helpers).
- `cli_args.py` — shared argparse builders for Gmail/Outlook auth flags.
- `assistant.py` — base assistant flags + capsule emit helper.
- `assistant_cli.py` — assistant dispatcher entry point.
- `llm_cli.py` — LLM CLI helpers (inventory, familiar, flows, policies).

Assistants should compose these pieces instead of rebuilding bespoke plumbing so that CLI
shims stay thin and domain logic stays easy to test.
