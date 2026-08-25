"""Sheets CLI -- generate styled .xlsx files from YAML workbook definitions."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from core.assistant import BaseAssistant
from core.cli_framework import CLIApp

from .meta import META

assistant = BaseAssistant(META.app_id, META.agentic_fallback)

app = CLIApp(
    "sheets",
    "Generate styled .xlsx spreadsheets from YAML definitions",
    # own -o/--output means an output PATH (generate) not a format enum, and
    # validate has no top-level --output at all -- same rationale as
    # src/slides/cli.py and src/charts/cli.py.
    add_common_args=False,
)


@lru_cache(maxsize=1)
def _lazy_agentic():
    from . import agentic as _agentic
    return _agentic.emit_agentic_context


@app.command("generate", help="Generate .xlsx from YAML")
@app.argument("yaml_file", help="Path to YAML workbook definition")
@app.argument("-o", "--output", help="Output .xlsx path (default: output_dir('sheets')/<name>.xlsx)")
def cmd_generate(args) -> int:
    """Generate a .xlsx workbook from a YAML workbook definition."""
    yaml_path = Path(args.yaml_file)
    if not yaml_path.exists():
        print(f"Error: YAML file not found: {args.yaml_file}", file=sys.stderr)
        return 1

    try:
        from .generator import load_workbook_from_yaml
        workbook = load_workbook_from_yaml(args.yaml_file)
    except Exception as e:
        print(f"Error loading YAML: {e}", file=sys.stderr)
        return 1

    if args.output:
        output_path = args.output
    else:
        from core.paths import output_dir
        output_path = str(output_dir("sheets") / f"{yaml_path.stem}.xlsx")

    try:
        from .generator import SheetGenerator
        generator = SheetGenerator()
        result = generator.generate(workbook, output_path)
    except Exception as e:
        # Broad catch is intentional: openpyxl raises a range of types
        # (ValueError, OSError, ...) and every one of them is a user-facing
        # failure. The error is reported and surfaced as exit 1, never swallowed.
        print(f"Error generating spreadsheet: {e}", file=sys.stderr)
        return 1

    print(f"Generated: {result}")
    return 0


@app.command("validate", help="Validate YAML workbook definition")
@app.argument("yaml_file", help="Path to YAML workbook definition")
def cmd_validate(args) -> int:
    """Validate a YAML workbook definition and print a summary."""
    yaml_path = Path(args.yaml_file)
    if not yaml_path.exists():
        print(f"Error: YAML file not found: {args.yaml_file}", file=sys.stderr)
        return 1

    try:
        from .generator import load_workbook_from_yaml, validate_workbook
        workbook = load_workbook_from_yaml(args.yaml_file)
    except Exception as e:
        print(f"Validation failed: {e}", file=sys.stderr)
        return 1

    problems = validate_workbook(workbook)

    meta = workbook.metadata
    print(f"Title: {meta.title}")
    print(f"Author: {meta.author or '(not set)'}")
    print(f"Date: {meta.date or '(not set)'}")
    print(f"Sheets: {len(workbook.sheets)}")
    for i, sheet in enumerate(workbook.sheets, start=1):
        print(f"  {i}. {sheet.name} ({len(sheet.headers)} columns, {len(sheet.rows)} rows)")
    print()
    if problems:
        print(f"Validation: FAILED ({len(problems)} problem(s))", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("Validation: OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the Sheets CLI."""
    return app.run_with_assistant(
        assistant,
        emit_func=lambda fmt, compact: _lazy_agentic()(fmt, compact),
        argv=argv,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
