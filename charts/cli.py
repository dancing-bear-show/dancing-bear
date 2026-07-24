"""charts CLI — render time-series charts from JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _require_matplotlib() -> None:
    try:
        from charts.renderer import _require_matplotlib as _check
        _check()
    except ImportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)


def _apply_cli_overrides(cfg: object, output_path: str | None, theme: str | None, svg: bool) -> object:
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
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)


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


def _load_panel_specs(cfg: object, json_to_spec_fn: object) -> list[object]:
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


def _handle_render(args: argparse.Namespace) -> int:
    _require_matplotlib()

    from charts.renderer import render_chart
    from charts.reshape import json_to_spec

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

    print(str(path))
    return 0


def _handle_grid(args: argparse.Namespace) -> int:
    _require_matplotlib()

    from charts.config import load_grid_config
    from charts.renderer import render_grid
    from charts.reshape import json_to_spec

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

    print(str(path))
    return 0


def _handle_reshape(args: argparse.Namespace) -> int:
    raw_text = _read_text(args.input_path)
    rows = _parse_rows(raw_text)
    series_map = _build_series_map(rows, args.x_field, args.y_field, args.group_by)

    output: dict[str, object] = {
        "title": args.title,
        "x_field": args.x_field,
        "series": [
            {"name": name, "data": data}
            for name, data in series_map.items()
        ],
    }

    if args.fmt == "yaml":
        try:
            import yaml  # noqa: PLC0415
            print(yaml.dump(output, default_flow_style=False), end="")
        except ImportError:
            print(json.dumps(output, indent=2))
    else:
        print(json.dumps(output, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    """charts CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="charts",
        description="charts — render time-series charts from JSON.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # render
    p_render = subparsers.add_parser("render", help="Render a single chart from a JSON spec.")
    p_render.add_argument("--input", "-i", dest="input_path", default="-",
                          help="JSON input file (default: stdin).")
    p_render.add_argument("--output", "-o", dest="output_path", required=True,
                          help="Output path (.png or .svg).")
    p_render.add_argument("--theme", choices=["dark", "light"], default="dark",
                          help="Color theme (default: dark).")
    p_render.add_argument("--dpi", type=int, default=None,
                          help="Override DPI (default: from spec).")
    p_render.add_argument("--svg", action="store_true", default=False,
                          help="Force SVG output regardless of --output extension.")

    # grid
    p_grid = subparsers.add_parser("grid", help="Render a multi-panel grid from a YAML config.")
    p_grid.add_argument("--config", "-c", dest="config_path", required=True,
                        help="YAML grid config file.")
    p_grid.add_argument("--output", "-o", dest="output_path", default=None,
                        help="Override output path from config.")
    p_grid.add_argument("--theme", choices=["dark", "light"], default=None,
                        help="Override theme from config.")
    p_grid.add_argument("--svg", action="store_true", default=False,
                        help="Force SVG output.")

    # reshape
    p_reshape = subparsers.add_parser(
        "reshape",
        help="Normalise arbitrary row data into the charts JSON contract, writes to stdout.",
    )
    p_reshape.add_argument("--input", "-i", dest="input_path", default="-",
                           help="Input file (default: stdin).")
    p_reshape.add_argument("--x", dest="x_field", required=True,
                           help="Field to use as x-axis.")
    p_reshape.add_argument("--y", dest="y_field", required=True,
                           help="Field to use as value (y-axis).")
    p_reshape.add_argument("--group-by", dest="group_by", default=None,
                           help="Field to split into series.")
    p_reshape.add_argument("--title", default="Chart",
                           help="Chart title (default: Chart).")
    p_reshape.add_argument("--format", dest="fmt", choices=["json", "yaml"], default="json",
                           help="Output format (default: json).")

    args = parser.parse_args(argv)

    handlers = {
        "render": _handle_render,
        "grid": _handle_grid,
        "reshape": _handle_reshape,
    }
    handler = handlers.get(args.command)
    if handler:
        return handler(args)
    parser.print_help()
    return 1
