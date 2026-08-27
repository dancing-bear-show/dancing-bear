"""Agentic capsule for the charts CLI."""

from __future__ import annotations


def build_agentic_capsule() -> str:
    """Return the human/LLM-readable agentic capsule text for charts."""
    lines: list[str] = []
    lines.append("agentic: charts")
    lines.append("purpose: Render time-series charts from JSON (line/bar/area/dual)")
    lines.append("commands:")
    lines.append("  - render single chart: ./bin/charts render --input spec.json --output chart.png")
    lines.append("  - render grid:         ./bin/charts grid --config grid.yaml --output grid.png")
    lines.append("  - reshape row data:    ./bin/charts reshape --x ts --y val --input rows.json")
    lines.append("notes:")
    lines.append("  - render/grid require matplotlib (pip install matplotlib)")
    lines.append("  - --input defaults to stdin; --output is required for render")
    lines.append("  - reshape writes the charts JSON contract to stdout (--format json|yaml)")
    lines.append("  - grid config is YAML; --theme and --output on the CLI override the config")
    return "\n".join(lines)


def emit_agentic_context(_fmt: str = "text", _compact: bool = False) -> int:
    """Emit agentic capsule. Format/compact params for API consistency."""
    print(build_agentic_capsule())
    return 0
