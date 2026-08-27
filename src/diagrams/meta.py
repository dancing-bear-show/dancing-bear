"""App metadata for the diagrams CLI."""

from __future__ import annotations

from core.meta_base import AppMeta

META = AppMeta(
    app_id="diagrams",
    purpose="Generate and render Mermaid diagrams from YAML specs or telemetry data",
    display_name="Diagrams",
    example_cmd="./bin/diagrams from-yaml --input spec.yaml",
)
