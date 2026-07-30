Diagrams

Overview
- Mermaid diagram generation from YAML specs or telemetry data.
- Entry point: `./bin/diagrams`

Key Commands
- Render from YAML: `./bin/diagrams from-yaml --input spec.yaml --output out/diagram.png`
- Validate a rendered .mmd file: `./bin/diagrams validate --input diagram.mmd`
- Embed in Markdown: `./bin/diagrams embed --input spec.yaml --from-yaml`
- Telemetry pie charts: `./bin/diagrams telemetry cost-pie --days 7`

Key Modules
- `cli.py` — command dispatch; `cmd_render` uses `run_pipeline(request, RenderDiagramProcessor, RenderDiagramProducer)`
- `renderers.py` — `LocalRenderer` wraps mmdc; `RenderDiagramProcessor(SafeProcessor)` / `RenderDiagramProducer(BaseProducer)`; `LocalRendererError` subclasses `CLIError`

Pipeline Pattern
- `cmd_render` routes through `SafeProcessor`/`BaseProducer` — see `core/pipeline.py`.
- Request/result: `RenderRequest` / `RenderResult` (frozen dataclasses).
- `cmd_validate` calls `RenderDiagramProcessor().process(request)` directly (suppresses success output).
- Output routes through `OutputWriter`.

Tests
- `tests/diagrams_tests/`
