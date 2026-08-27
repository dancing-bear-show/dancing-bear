"""App metadata for the charts CLI."""

from __future__ import annotations

from core.meta_base import AppMeta

META = AppMeta(
    app_id="charts",
    purpose="Render time-series charts from JSON (line/bar/area/dual)",
    display_name="Charts",
    example_cmd="./bin/charts render --input spec.json --output chart.png",
)
