Telemetry Assistant

Overview
- Claude Code session telemetry: cost tracking, token usage, session browsing, and transcript parsing.
- Entry point: `./bin/telemetry`

Key Commands
- Cost breakdown: `./bin/telemetry cost --days 7`
- Session browser: `./bin/telemetry sessions --limit 20`
- Compare sessions: `./bin/telemetry otel compare <session_a> <session_b>`
- OTLP collector (standalone script, not routed through the telemetry CLI):
  `python3 -m telemetry.otel.collector --daemon` / `--stop` / `--status`

Key Modules
- `otel/cli/cost.py` — cost summary output via `CostScanProcessor`/`CostScanProducer`
- `otel/cli/sessions.py` — session listing
- `otel/cli/compare.py` — cross-session comparison
- `otel/collector.py` — OTEL collector management via `CollectorReadProcessor`/`CollectorProducer`
- `parse_transcripts.py` — transcript ingestion via `TranscriptParseProcessor`/`TranscriptParseProducer`
- `otel/health.py` — infrastructure readiness check
- `menubar.py` — macOS menu bar status helper

Pipeline Pattern
- Commands route through `SafeProcessor`/`BaseProducer` — see `core/pipeline.py`.
- All output routes through `OutputWriter`; bare `print()` eliminated.
- `sys.exit()` replaced with `raise CLIError(...)` at all non-POSIX boundaries.

Tests
- `tests/telemetry_tests/`
