# Core Pipeline Modules

Shared scaffolding for all assistants as they migrate to the consumer → processor → producer
model. Modules:

- `pipeline.py` — protocol definitions plus the `ResultEnvelope` helper.
- `context.py` — lightweight `AppContext` used to pass args/config/root paths.
- `testing.py` — reusable stubs to exercise individual stages in unit tests.

Assistants should compose these pieces instead of rebuilding bespoke plumbing so that CLI
shims stay thin and domain logic stays easy to test.
