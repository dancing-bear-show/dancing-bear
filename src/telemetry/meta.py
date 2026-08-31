from __future__ import annotations

from core.meta_base import AppMeta

META = AppMeta(
    app_id="telemetry",
    purpose="Claude Code session telemetry: cost, tokens, TUI, and OTel queries",
    display_name="Telemetry",
    example_cmd="./bin/telemetry sessions --since 7d",
)
