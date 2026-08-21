"""Agentic capsule for the slides CLI."""

from __future__ import annotations


def build_agentic_capsule() -> str:
    """Return the human/LLM-readable agentic capsule text for slides."""
    lines: list[str] = []
    lines.append("agentic: slides")
    lines.append("purpose: Generate PowerPoint slides from YAML deck definitions")
    lines.append("commands:")
    lines.append("  - generate: ./bin/slides generate deck.yaml --template template.pptx -o out.pptx")
    lines.append("  - validate: ./bin/slides validate deck.yaml")
    lines.append("  - list layouts: ./bin/slides templates template.pptx --format json")
    lines.append(
        "Notes:\n"
        "  - A template .pptx is REQUIRED (--template flag or template_path in YAML);\n"
        "    generate fails with a clear error if absent -- no bundled default template.\n"
        "  - mermaid: fields in a deck YAML shell out to the `mmdc` binary (npm-installed,\n"
        "    not a Python dependency) and are rendered to PNG before insertion."
    )
    return "\n".join(lines)


def emit_agentic_context(_fmt: str = "text", _compact: bool = False) -> int:
    """Emit agentic capsule. Format/compact params for API consistency."""
    print(build_agentic_capsule())
    return 0
