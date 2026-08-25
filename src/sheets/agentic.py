"""Agentic capsule for the sheets CLI."""

from __future__ import annotations


def build_agentic_capsule() -> str:
    """Return the human/LLM-readable agentic capsule text for sheets."""
    lines: list[str] = []
    lines.append("agentic: sheets")
    lines.append("purpose: Generate styled .xlsx spreadsheets from YAML workbook definitions")
    lines.append("commands:")
    lines.append("  - generate: ./bin/sheets generate workbook.yaml -o out.xlsx")
    lines.append("  - validate: ./bin/sheets validate workbook.yaml")
    lines.append(
        "Notes:\n"
        "  - Without -o, output goes to output_dir('sheets') (~/.local/share/dancing-bear/sheets/).\n"
        "  - openpyxl is a required dependency; install the package before use."
    )
    return "\n".join(lines)


def emit_agentic_context(_fmt: str = "text", _compact: bool = False) -> int:
    """Emit agentic capsule. Format/compact params for API consistency."""
    print(build_agentic_capsule())
    return 0
