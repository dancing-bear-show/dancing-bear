"""Slides CLI -- generate PowerPoint from YAML deck definitions."""

from __future__ import annotations

import json
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING
from zipfile import ZipFile

from core.assistant import BaseAssistant
from core.cli_framework import CLIApp
from core.cli_output import emit_rows

from .meta import META

if TYPE_CHECKING:
    from .schema import SlideDeck

assistant = BaseAssistant(META.app_id, META.agentic_fallback)

app = CLIApp(
    "slides",
    "Generate PowerPoint slides from YAML definitions",
    # own -o/--output means an output PATH (generate) not a format enum, and
    # validate/templates have no top-level --output at all -- same rationale
    # as src/charts/cli.py and src/desk/cli.py.
    add_common_args=False,
)

_LAYOUT_NAME_RE = re.compile(rb'<p:cSld[^>]*\sname="([^"]+)"')


@lru_cache(maxsize=1)
def _lazy_agentic():
    from . import agentic as _agentic

    return _agentic.emit_agentic_context


def _parse_layout_map_entry(pair: str) -> tuple[str, int]:
    """Parse one ``name=index`` pair from a --layout-map value.

    Raises ValueError on a missing '=', an empty or reserved name, or an
    index that is not a non-negative integer.
    """
    from .constants import RESERVED_LAYOUT_KEY

    if "=" not in pair:
        raise ValueError(f"Invalid layout-map entry {pair!r}; expected name=index")

    name, _, index_str = pair.partition("=")
    name = name.strip()
    if not name:
        raise ValueError("Layout name cannot be empty in --layout-map")
    if name == RESERVED_LAYOUT_KEY:
        raise ValueError(f"Layout name {name!r} is reserved and cannot be used in --layout-map")

    index_str = index_str.strip()
    try:
        index = int(index_str)
    except ValueError as exc:
        raise ValueError(
            f"Invalid index {index_str!r} for layout {name!r}; must be an integer"
        ) from exc
    if index < 0:
        raise ValueError(f"Index for layout {name!r} must be non-negative, got {index}")
    return name, index


def _parse_layout_map_flag(raw: str | None) -> dict[str, int] | None:
    """Parse a --layout-map CLI flag value into a dict.

    Accepts comma-separated key=value pairs like ``section=0,bullet=1``.
    """
    if not raw:
        return None

    layout_map = dict(
        _parse_layout_map_entry(pair)
        for pair in (p.strip() for p in raw.split(","))
        if pair
    )
    return layout_map or None


def _resolve_template(template_flag: str | None, deck: "SlideDeck") -> str | None:
    """Resolve the effective template path: --template flag > deck.template_path."""
    return template_flag or deck.template_path


def _apply_layout_map(
    deck: "SlideDeck",
    cli_layout_map: dict[str, int] | None,
    exported_template: str | None = None,
) -> None:
    """Apply a CLI-supplied layout map to the deck, overriding any YAML value."""
    if cli_layout_map is not None:
        deck.metadata.layout_map = cli_layout_map
    if exported_template:
        deck.template_path = exported_template


def _list_pptx_layouts(pptx_path: str) -> list[dict[str, str]]:
    """List slide layouts in a .pptx template.

    Opens the .pptx as a ZIP and regexes ppt/slideLayouts/*.xml (excluding
    _rels/) for a name="..." attribute. Falls back to "(no name)".
    """
    layouts: list[dict[str, str]] = []
    with ZipFile(pptx_path) as zf:
        layout_names = sorted(
            n
            for n in zf.namelist()
            if n.startswith("ppt/slideLayouts/") and n.endswith(".xml") and "_rels" not in n
        )
        for rel in layout_names:
            data = zf.read(rel)
            match = _LAYOUT_NAME_RE.search(data)
            name = match.group(1).decode("utf-8") if match else "(no name)"
            layouts.append({"name": name, "rel": rel})
    return layouts


def _emit_templates(rows: list[dict[str, str]], fmt: str) -> int:
    """Emit template layout rows as json, real yaml, or a table.

    core.cli_output.emit_rows supports only json/csv/table -- its fallback
    for any other value renders a rich table with bare column headers, so
    routing "yaml" through it would silently produce table output under a
    yaml flag. This branches explicitly so --format yaml emits real YAML.
    """
    if fmt == "json":
        print(json.dumps(rows))
        return 0
    if fmt == "yaml":
        import yaml

        print(yaml.safe_dump(rows, sort_keys=False, default_flow_style=False))
        return 0
    return emit_rows(rows, fmt, headers=["name", "rel"])


@app.command("generate", help="Generate .pptx from YAML")
@app.argument("yaml_file", help="Path to YAML deck definition")
@app.argument("-o", "--output", help="Output .pptx path (default: same name as YAML)")
@app.argument("-t", "--template", help="Path to template .pptx file (overrides YAML setting)")
@app.argument("--layout-map", help="Layout name to template slide index mapping (e.g., section=0,bullet=1)")
def cmd_generate(args) -> int:
    """Generate a .pptx deck from a YAML deck definition."""
    yaml_path = Path(args.yaml_file)
    if not yaml_path.exists():
        print(f"Error: YAML file not found: {args.yaml_file}", file=sys.stderr)
        return 1

    try:
        deck = sys.modules[__name__].load_deck_from_yaml(args.yaml_file)
    except Exception as e:
        print(f"Error loading YAML: {e}", file=sys.stderr)
        return 1

    try:
        layout_map = _parse_layout_map_flag(args.layout_map)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    try:
        _apply_layout_map(deck, layout_map)
    except Exception as e:
        # Matches the ported source: layout-map application (including
        # auto-inference from a template) is best-effort. A failure here warns
        # but must not block generation of an otherwise-valid deck.
        print(f"Warning: layout_map auto-inference failed: {e}", file=sys.stderr)

    template = _resolve_template(args.template, deck)
    if not template:
        print(
            "Error: No template specified. Use --template or set template_path in YAML.",
            file=sys.stderr,
        )
        return 1
    deck.template_path = template

    # An explicit -o is honoured as given. The implicit default goes to the
    # shared data home, not next to the input: decks are generated FROM files
    # in the checkout, and defaulting beside them would write artifacts into
    # the repository. See core.paths.output_dir and CLAUDE.md.
    if args.output:
        output_path = args.output
    else:
        from core.paths import output_dir

        output_path = str(output_dir("slides") / f"{yaml_path.stem}.pptx")
    try:
        from .generator import SlideGenerator

        generator = SlideGenerator(template_path=deck.template_path)
        result = generator.generate(deck, output_path)
    except Exception as e:
        print(f"Error generating slides: {e}", file=sys.stderr)
        return 1

    print(f"Generated: {result}")
    return 0


@app.command("validate", help="Validate YAML deck definition")
@app.argument("yaml_file", help="Path to YAML deck definition")
def cmd_validate(args) -> int:
    """Validate a YAML deck definition and print a summary."""
    from .schema import TableSlide

    yaml_path = Path(args.yaml_file)
    if not yaml_path.exists():
        print(f"Error: YAML file not found: {args.yaml_file}", file=sys.stderr)
        return 1

    try:
        deck = sys.modules[__name__].load_deck_from_yaml(args.yaml_file)
    except Exception as e:
        print(f"Validation failed: {e}", file=sys.stderr)
        return 1

    from .constants import VALID_LAYOUTS

    errors: list[str] = []
    for i, slide in enumerate(deck.slides, start=1):
        if slide.layout not in VALID_LAYOUTS:
            errors.append(
                f"Slide {i} {slide.title!r}: unknown layout {slide.layout!r}; "
                f"expected one of {VALID_LAYOUTS}"
            )
        if isinstance(slide, TableSlide) and slide.rows and not slide.headers:
            errors.append(
                f"Slide {i} {slide.title!r}: table slide has rows but no headers"
            )

    if errors:
        for err in errors:
            print(f"Validation error: {err}", file=sys.stderr)
        return 1

    meta = deck.metadata
    print(f"Title: {meta.title}")
    print(f"Author: {meta.author or '(not set)'}")
    print(f"Date: {meta.date or '(not set)'}")
    print(f"Template slide index: {meta.template_slide_index}")
    print(f"Theme color: {meta.theme_color}")
    print(f"Template path: {deck.template_path or '(not set)'}")
    print(f"Slides: {len(deck.slides)}")
    for i, slide in enumerate(deck.slides, start=1):
        print(f"  {i}. {slide.title} ({len(slide.bullets)} bullets)")
    print()
    print("Validation: OK")
    return 0


@app.command("templates", help="List slide layouts in a PPTX template")
@app.argument("pptx", help="Path to a PPTX template file")
@app.argument("--format", choices=["table", "json", "yaml"], default="table", help="Output format")
def cmd_templates(args) -> int:
    """List the slide layouts present in a .pptx template file."""
    pptx_path = Path(args.pptx)
    if not pptx_path.exists():
        print(f"Error: File not found: {args.pptx}", file=sys.stderr)
        return 1

    try:
        layouts = _list_pptx_layouts(args.pptx)
    except Exception as e:
        print(f"Error reading template: {e}", file=sys.stderr)
        return 1

    return _emit_templates(layouts, args.format)


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the Slides CLI."""
    return app.run_with_assistant(
        assistant,
        emit_func=lambda fmt, compact: _lazy_agentic()(fmt, compact),
        argv=argv,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


def __getattr__(name: str) -> object:
    """Resolve generator helpers lazily on first access (PEP 562).

    Keeps `import slides.cli` free of pptx while exposing
    slides.cli.load_deck_from_yaml as a patchable module attribute — command
    bodies resolve it through sys.modules[__name__] so a patch takes effect.
    """
    if name == "load_deck_from_yaml":
        from .generator import load_deck_from_yaml

        return load_deck_from_yaml
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
