"""Agentic capsule for the diagrams CLI."""

from __future__ import annotations


def build_agentic_capsule() -> str:
    """Return the human/LLM-readable agentic capsule text for diagrams."""
    lines: list[str] = []
    lines.append("agentic: diagrams")
    lines.append("purpose: Generate and render Mermaid diagrams from YAML specs or telemetry data")
    lines.append("commands:")
    lines.append("  - from-yaml:  ./bin/diagrams from-yaml --input spec.yaml")
    lines.append("  - render:     ./bin/diagrams render --input diagram.mmd --output out.svg")
    lines.append("  - validate:   ./bin/diagrams validate --input diagram.mmd")
    lines.append("  - embed:      ./bin/diagrams embed --input diagram.mmd")
    lines.append("  - telemetry:  ./bin/diagrams telemetry cost-pie")
    lines.append("notes:")
    lines.append("  - render/validate/embed require mmdc (npm install -g @mermaid-js/mermaid-cli)")
    lines.append("  - --input defaults to stdin; --output defaults to stdout")
    lines.append("  - from-yaml supports flowchart and sequence diagram types")
    lines.append("  - telemetry types: cost-pie, token-pie, timeline")
    return "\n".join(lines)


def emit_agentic_context(_fmt: str = "text", _compact: bool = False) -> int:
    """Emit agentic capsule. Format/compact params for API consistency."""
    print(build_agentic_capsule())
    return 0
