"""charts CLI — render time-series charts from JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from functools import lru_cache

from core.assistant import BaseAssistant
from core.cli_errors import CLIError, ExitCode, handle_error
from core.cli_framework import CLIApp
from core.cli_output import OutputWriter, OutputConfig, OutputFormat

from .meta import META

# add_common_args=False: charts has no --profile/--dry-run, and its own
# --output/-o means output *path* (not the CLIApp built-in output *format*
# flag), so the common args would collide with the per-command --output.
app = CLIApp(
    "charts",
    "charts — render time-series charts from JSON.",
    add_common_args=False,
)

assistant = BaseAssistant(META.app_id, META.agentic_fallback)


@lru_cache(maxsize=1)
def _lazy_agentic():
    from . import agentic as _agentic

    return _agentic.emit_agentic_context


def _require_matplotlib() -> None:
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        raise CLIError(
            "matplotlib is not installed. Run: pip install matplotlib",
            ExitCode.ERROR,
        )


def _apply_cli_overrides(cfg, output_path: str | None, theme: str | None, svg: bool):
    """Apply CLI output/theme/svg overrides to a GridConfig."""
    from charts.config import GridConfig

    effective_output: str = output_path or cfg.output
    effective_theme: str | None = theme or cfg.theme
    if svg and not effective_output.endswith(".svg"):
        effective_output = str(Path(effective_output).with_suffix(".svg"))

    if effective_output == cfg.output and effective_theme == cfg.theme:
        return cfg
    return GridConfig(
        title=cfg.title,
        output=effective_output,
        rows=cfg.rows,
        cols=cfg.cols,
        panels=cfg.panels,
        width_px=cfg.width_px,
        height_px=cfg.height_px,
        theme=effective_theme,
        dpi=cfg.dpi,
    )


def _read_text(input_path: str) -> str:
    if input_path == "-":
        return sys.stdin.read()
    try:
        with open(input_path) as f:
            return f.read()
    except OSError as exc:
        raise CLIError(f"error: {exc}", ExitCode.ERROR) from exc


def _parse_rows(raw_text: str) -> list[object]:
    try:
        rows = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON — {exc}", file=sys.stderr)
        raise SystemExit(1)
    if not isinstance(rows, list):
        print("error: input must be a JSON array of row objects", file=sys.stderr)
        raise SystemExit(1)
    return rows  # type: ignore[return-value]


def _validate_row(row: object, x_field: str, y_field: str) -> dict[str, object]:
    if not isinstance(row, dict):
        print("error: each row must be a JSON object", file=sys.stderr)
        raise SystemExit(1)
    if x_field not in row:
        print(f"error: row missing --x field {x_field!r}", file=sys.stderr)
        raise SystemExit(1)
    if y_field not in row:
        print(f"error: row missing --y field {y_field!r}", file=sys.stderr)
        raise SystemExit(1)
    return row  # type: ignore[return-value]


def _build_series_map(
    rows: list[object],
    x_field: str,
    y_field: str,
    group_by: str | None,
) -> dict[str, list[dict[str, object]]]:
    series_map: dict[str, list[dict[str, object]]] = {}
    for raw_row in rows:
        row = _validate_row(raw_row, x_field, y_field)
        if group_by:
            if group_by in row:
                series_name = str(row[group_by])
            else:
                print(
                    f"warning: row missing --group-by field {group_by!r}, grouped as '<missing>'",
                    file=sys.stderr,
                )
                series_name = "<missing>"
        else:
            series_name = "value"
        series_map.setdefault(series_name, []).append(
            {x_field: row[x_field], "value": row[y_field]}
        )
    return series_map


def _load_panel_specs(cfg, json_to_spec_fn):
    """Read and parse JSON for each panel; exit on the first I/O or parse error."""
    stdin_content: str | None = None
    if any(p.input == "-" for p in cfg.panels):
        stdin_content = sys.stdin.read()

    specs = []
    for idx, panel in enumerate(cfg.panels):
        if panel.input == "-":
            raw_text = stdin_content if stdin_content is not None else sys.stdin.read()
        else:
            try:
                with open(panel.input) as f:
                    raw_text = f.read()
            except OSError as exc:
                print(f"error: panel[{idx}]: {exc}", file=sys.stderr)
                raise SystemExit(1)
        try:
            specs.append(json_to_spec_fn(json.loads(raw_text)))
        except ValueError as exc:
            print(f"error: panel[{idx}]: {exc}", file=sys.stderr)
            raise SystemExit(1)
    return specs


@app.command("render", help="Render a single chart from a JSON spec.")
@app.argument("--input", "-i", dest="input_path", default="-",
              help="JSON input file (default: stdin).")
@app.argument("--output", "-o", dest="output_path", required=True,
              help="Output path (.png or .svg).")
@app.argument("--theme", choices=["dark", "light"], default="dark",
              help="Color theme (default: dark).")
@app.argument("--dpi", type=int, default=None,
              help="Override DPI (default: from spec).")
@app.argument("--svg", action="store_true", default=False,
              help="Force SVG output regardless of --output extension.")
def _handle_render(args: argparse.Namespace, writer: OutputWriter | None = None) -> int:
    _require_matplotlib()

    from charts.renderer import render_chart
    from charts.reshape import json_to_spec

    out = writer or OutputWriter()

    raw_text = _read_text(args.input_path)
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON — {exc}", file=sys.stderr)
        raise SystemExit(1)

    try:
        spec = json_to_spec(raw)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    effective_output = args.output_path
    if args.svg and not args.output_path.endswith(".svg"):
        effective_output = str(Path(args.output_path).with_suffix(".svg"))

    try:
        path = render_chart(spec, effective_output, theme=args.theme, dpi=args.dpi)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    out.print(str(path))
    return 0


@app.command("grid", help="Render a multi-panel grid from a YAML config.")
@app.argument("--config", "-c", dest="config_path", required=True,
              help="YAML grid config file.")
@app.argument("--output", "-o", dest="output_path", default=None,
              help="Override output path from config.")
@app.argument("--theme", choices=["dark", "light"], default=None,
              help="Override theme from config.")
@app.argument("--svg", action="store_true", default=False,
              help="Force SVG output.")
def _handle_grid(args: argparse.Namespace, writer: OutputWriter | None = None) -> int:
    _require_matplotlib()

    from charts.config import load_grid_config
    from charts.renderer import render_grid
    from charts.reshape import json_to_spec

    out = writer or OutputWriter()

    try:
        cfg = load_grid_config(args.config_path)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    cfg = _apply_cli_overrides(cfg, args.output_path, args.theme, args.svg)
    specs = _load_panel_specs(cfg, json_to_spec)

    try:
        path = render_grid(cfg, specs)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    out.print(str(path))
    return 0


@app.command(
    "reshape",
    help="Normalise arbitrary row data into the charts JSON contract, writes to stdout.",
)
@app.argument("--input", "-i", dest="input_path", default="-",
              help="Input file (default: stdin).")
@app.argument("--x", dest="x_field", required=True,
              help="Field to use as x-axis.")
@app.argument("--y", dest="y_field", required=True,
              help="Field to use as value (y-axis).")
@app.argument("--group-by", dest="group_by", default=None,
              help="Field to split into series.")
@app.argument("--title", default="Chart",
              help="Chart title (default: Chart).")
@app.argument("--format", dest="fmt", choices=["json", "yaml"], default="json",
              help="Output format (default: json).")
def _handle_reshape(args: argparse.Namespace, writer: OutputWriter | None = None) -> int:
    fmt = OutputFormat.YAML if args.fmt == "yaml" else OutputFormat.JSON
    out = writer or OutputWriter(OutputConfig(format=fmt))

    raw_text = _read_text(args.input_path)
    rows = _parse_rows(raw_text)
    series_map = _build_series_map(rows, args.x_field, args.y_field, args.group_by)

    data: dict[str, object] = {
        "title": args.title,
        "x_field": args.x_field,
        "series": [
            {"name": name, "data": series_data}
            for name, series_data in series_map.items()
        ],
    }

    out.print_data(data)
    return 0


def main(argv: list[str] | None = None) -> int:
    """charts CLI entry point."""
    parser = app.build_parser()
    assistant.add_agentic_flags(parser)
    _argv = app.normalize_argv(argv if argv is not None else sys.argv[1:])
    args = parser.parse_args(_argv)

    # Handled before the no-subcommand branch so `--agentic` alone exits 0
    # while a bare invocation keeps its legacy exit code of 1.
    rc = assistant.maybe_emit_agentic(args, _lazy_agentic(), parser=parser)
    if rc is not None:
        return rc

    cmd_func = getattr(args, "_cmd_func", None)
    if cmd_func is None:
        parser.print_help()
        return 1

    try:
        return cmd_func(args)
    except CLIError as exc:
        sys.exit(handle_error(exc))
