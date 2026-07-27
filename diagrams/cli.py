"""Mermaid diagram CLI — generate .mmd from telemetry and repo data."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .mermaid import GanttBuilder, PieBuilder

DAYS_HELP = "Lookback days (default: 7)"
NO_SESSIONS = "No sessions found."


def _format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _load_telemetry(days: int):
    """Load session stats and helpers from the telemetry module."""
    from datetime import datetime, timezone

    from telemetry.parser import iter_session_files, parse_session
    from telemetry.pricing import compute_cost, model_tier

    sessions = []
    for path in iter_session_files(days=days):
        s = parse_session(path)
        if s.events > 0:
            sessions.append(s)
    sessions.sort(
        key=lambda s: s.start_time or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return sessions, compute_cost, model_tier


def _session_cost(s, compute_cost) -> float:
    if not s.model:
        return 0.0
    return compute_cost(
        s.input_tokens, s.output_tokens,
        s.cache_read_tokens, s.cache_create_tokens, s.model,
    )


# ── Telemetry diagram renderers ───────────────────────────────────────────────


def _render_cost_pie(sessions, days, compute_cost, model_tier) -> str:
    tier_cost: dict[str, float] = {"opus": 0.0, "sonnet": 0.0, "haiku": 0.0}
    for s in sessions:
        if s.model:
            tier = model_tier(s.model)
            tier_cost[tier] = tier_cost.get(tier, 0.0) + _session_cost(s, compute_cost)
    pie = PieBuilder(f"Cost by Model (last {days}d)")
    for tier, cost in tier_cost.items():
        if cost > 0:
            pie.slice(f"{tier.title()} ${cost:.2f}", round(cost, 2))
    return pie.render()


def _render_token_pie(sessions, days, model_tier) -> str:
    tier_tokens: dict[str, int] = {"opus": 0, "sonnet": 0, "haiku": 0}
    for s in sessions:
        if s.model:
            tier = model_tier(s.model)
            tier_tokens[tier] = tier_tokens.get(tier, 0) + s.total_tokens
    pie = PieBuilder(f"Tokens by Model (last {days}d)")
    for tier, tok in tier_tokens.items():
        if tok > 0:
            pie.slice(f"{tier.title()} {_format_tokens(tok)}", tok)
    return pie.render()


def _render_timeline(sessions, days, compute_cost, model_tier) -> str:
    gantt = GanttBuilder(f"Sessions (last {days}d)", date_format="YYYY-MM-DD")
    by_date: dict[str, list] = {}
    for s in sessions:
        if s.start_time:
            key = s.start_time.strftime("%Y-%m-%d")
            by_date.setdefault(key, []).append(s)
    for date_key in sorted(by_date.keys()):
        tasks = []
        for s in by_date[date_key]:
            sid = s.session_id[:12]
            tier = model_tier(s.model) if s.model else "?"
            cost = _session_cost(s, compute_cost)
            start = s.start_time.strftime("%Y-%m-%d") if s.start_time else date_key
            dur_days = max(1, round(s.duration_seconds / 86400))
            safe_id = "".join(c for c in sid if c.isalnum() or c == "_")[:8]
            tasks.append(f"{sid} ({tier} ${cost:.0f}) :t{safe_id}, {start}, {dur_days}d")
        gantt.section(date_key, tasks)
    return gantt.render()


# ── Shared I/O helpers ────────────────────────────────────────────────────────


def _read_input(input_path: str | None, label: str = "diagram.mmd") -> str | None:
    """Read content from a file or stdin. Returns None and prints to stderr on error."""
    if input_path:
        try:
            with open(input_path) as f:
                return f.read()
        except FileNotFoundError:
            print(f"Error: Input file not found: {input_path}", file=sys.stderr)
            return None
        except OSError as e:
            print(f"Error reading {input_path}: {e}", file=sys.stderr)
            return None
    else:
        if sys.stdin.isatty():
            print(f"Error: No input file specified and stdin is empty", file=sys.stderr)
            print(f"Usage: diagrams <command> --input {label}", file=sys.stderr)
            return None
        return sys.stdin.read()


def _write_output(content: str, output_path: str | None, success_msg: str = "") -> int:
    """Write content to a file or stdout. Returns 0 on success, 1 on error."""
    if output_path:
        try:
            with open(output_path, "w") as f:
                f.write(content)
                f.write("\n")
            if success_msg:
                print(success_msg, file=sys.stderr)
        except OSError as e:
            print(f"Error writing {output_path}: {e}", file=sys.stderr)
            return 1
    else:
        print(content)
    return 0


def _validate_non_empty(content: str) -> bool:
    if not content.strip():
        print("Error: Empty input", file=sys.stderr)
        return False
    return True


def _load_yaml(content: str) -> dict | None:
    try:
        import yaml  # noqa: PLC0415
        return yaml.safe_load(content)
    except ImportError:
        import json
        try:
            return json.loads(content)
        except Exception as e:
            print(f"Error parsing input: {e}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"Error parsing YAML: {e}", file=sys.stderr)
        return None


# ── YAML → Mermaid conversion helpers ────────────────────────────────────────


def _build_flowchart_from_spec(spec: dict) -> str:
    from .mermaid import FlowchartBuilder

    builder = FlowchartBuilder()
    if "direction" in spec:
        builder.with_direction(spec["direction"])
    if "title" in spec:
        builder.with_title(spec["title"])
    for node_spec in spec.get("nodes", []):
        builder.node(
            node_id=node_spec["id"],
            label=node_spec.get("label"),
            shape=node_spec.get("shape", "rect"),
        )
    for edge_spec in spec.get("edges", []):
        builder.edge(
            src=edge_spec["source"],
            dst=edge_spec["target"],
            label=edge_spec.get("label", ""),
            style=edge_spec.get("style", "-->"),
        )
    return builder.render()


def _build_sequence_from_spec(spec: dict) -> str:
    from .mermaid import SequenceDiagramBuilder

    builder = SequenceDiagramBuilder()
    if "title" in spec:
        builder.with_title(spec["title"])
    if spec.get("autonumber"):
        builder.autonumber()
    for p_spec in spec.get("participants", []):
        builder.participant(
            name=p_spec["id"],
            alias=p_spec.get("label", ""),
            actor=p_spec.get("actor", False),
        )
    for m_spec in spec.get("messages", []):
        builder.message(
            src=m_spec["sender"],
            dst=m_spec["receiver"],
            text=m_spec["text"],
            arrow=m_spec.get("arrow_type", "->>"),
            activate=m_spec.get("activate", False),
            deactivate=m_spec.get("deactivate", False),
        )
    return builder.render()


def _convert_yaml_spec(spec: dict) -> tuple[str | None, int]:
    """Convert a YAML spec dict to mermaid text. Returns (text, exit_code)."""
    if not isinstance(spec, dict):
        print("Error: YAML spec must be a dictionary", file=sys.stderr)
        return None, 1

    diagram_type = spec.get("type", "flowchart").lower()
    try:
        if diagram_type in ("flowchart", "graph"):
            return _build_flowchart_from_spec(spec), 0
        elif diagram_type in ("sequence", "sequencediagram"):
            return _build_sequence_from_spec(spec), 0
        else:
            print(f"Error: Unsupported diagram type {diagram_type!r}", file=sys.stderr)
            print("Supported types: flowchart, sequence", file=sys.stderr)
            return None, 1
    except KeyError as e:
        print(f"Error: Missing required field {e} in spec", file=sys.stderr)
        return None, 1
    except Exception as e:
        print(f"Error building diagram: {e}", file=sys.stderr)
        return None, 1


# ── Commands ──────────────────────────────────────────────────────────────────


def cmd_telemetry(args) -> int:
    sessions, compute_cost, model_tier = _load_telemetry(args.days)
    if not sessions:
        print(NO_SESSIONS, file=sys.stderr)
        return 1

    renderers = {
        "cost-pie": lambda: _render_cost_pie(sessions, args.days, compute_cost, model_tier),
        "token-pie": lambda: _render_token_pie(sessions, args.days, model_tier),
        "timeline": lambda: _render_timeline(sessions, args.days, compute_cost, model_tier),
    }
    renderer = renderers.get(args.type)
    if not renderer:
        print(f"Unknown diagram type: {args.type}", file=sys.stderr)
        return 1
    print(renderer())
    return 0


def cmd_render(args) -> int:
    """Render a .mmd file to PNG/SVG/PDF via mmdc."""
    mermaid_text = _read_input(args.input, "diagram.mmd")
    if mermaid_text is None:
        return 1
    if not _validate_non_empty(mermaid_text):
        return 1

    from .renderers import LocalRenderer, LocalRendererError

    try:
        renderer = LocalRenderer(timeout=args.timeout)
    except LocalRendererError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        output_path = renderer.render_to_file(
            mermaid_text,
            args.output,
            output_format=getattr(args, "format", None),
            background=getattr(args, "background", None),
            theme=getattr(args, "theme", None),
            width=getattr(args, "width", None),
            height=getattr(args, "height", None),
        )
        print(f"Rendered to: {output_path}", file=sys.stderr)
        return 0
    except LocalRendererError as e:
        print(f"Render error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_validate(args) -> int:
    """Validate mermaid syntax via mmdc."""
    mermaid_text = _read_input(args.input, "diagram.mmd")
    if mermaid_text is None:
        return 1
    if not _validate_non_empty(mermaid_text):
        return 1

    from .renderers import LocalRenderer, LocalRendererError

    try:
        renderer = LocalRenderer(timeout=args.timeout)
    except LocalRendererError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    is_valid, error = renderer.validate_syntax(mermaid_text)
    if is_valid:
        print("Valid: Mermaid syntax is correct", file=sys.stderr)
        return 0
    else:
        print(f"Invalid: {error}", file=sys.stderr)
        return 1


def cmd_embed(args) -> int:
    """Output mermaid wrapped in a ```mermaid code fence."""
    content = _read_input(args.input, "diagram.mmd")
    if content is None:
        return 1
    if not _validate_non_empty(content):
        return 1

    if getattr(args, "from_yaml", False):
        spec = _load_yaml(content)
        if spec is None:
            return 1
        mermaid_text, err = _convert_yaml_spec(spec)
        if err:
            return err
    else:
        mermaid_text = content

    from .renderers import TextRenderer
    renderer = TextRenderer()
    embedded = renderer.render_embedded(mermaid_text)

    output_path = getattr(args, "output", None)
    success_msg = f"Written to: {output_path}" if output_path else ""
    return _write_output(embedded, output_path, success_msg)


def cmd_health(args) -> int:
    """Check mmdc is installed and working."""
    skip_render = getattr(args, "skip_render", False)

    # Check builder
    try:
        from .mermaid import FlowchartBuilder
        diagram = FlowchartBuilder().node("A", "Start").node("B", "End").edge("A", "B").render()
        if "flowchart" not in diagram:
            raise RuntimeError("Builder produced invalid output")
        print("builder ok", file=sys.stderr)
    except Exception as e:
        print(f"builder FAILED: {e}", file=sys.stderr)
        return 1

    # Check text renderer
    try:
        from .mermaid import FlowchartBuilder
        from .renderers import TextRenderer
        builder = FlowchartBuilder().node("A", "Test")
        text = TextRenderer().render(builder)
        if not text:
            raise RuntimeError("Text renderer returned empty output")
        print("text renderer ok", file=sys.stderr)
    except Exception as e:
        print(f"text renderer FAILED: {e}", file=sys.stderr)
        return 1

    if skip_render:
        print("local renderer: skipped", file=sys.stderr)
        return 0

    # Check local renderer
    try:
        from .renderers import LocalRenderer, LocalRendererError
        if not LocalRenderer.is_available():
            raise LocalRendererError(
                "mmdc not installed. Run: npm install -g @mermaid-js/mermaid-cli"
            )
        renderer = LocalRenderer(timeout=30)
        svg_bytes = renderer.render("flowchart LR\n    A-->B", "svg")
        if not svg_bytes or b"<svg" not in svg_bytes:
            raise RuntimeError("Local renderer returned invalid SVG")
        print("local renderer ok", file=sys.stderr)
    except Exception as e:
        print(f"local renderer FAILED: {e}", file=sys.stderr)
        return 1

    return 0


def cmd_from_yaml(args) -> int:
    """Generate .mmd from a YAML spec (flowchart and sequence types)."""
    yaml_content = _read_input(args.input, "spec.yaml")
    if yaml_content is None:
        return 1
    if not _validate_non_empty(yaml_content):
        return 1

    spec = _load_yaml(yaml_content)
    if spec is None:
        return 1

    mermaid_text, err = _convert_yaml_spec(spec)
    if err:
        return err

    if getattr(args, "embedded", False):
        mermaid_text = f"```mermaid\n{mermaid_text}\n```"

    output_path = getattr(args, "output", None)
    success_msg = f"Generated: {output_path}" if output_path else ""
    return _write_output(mermaid_text, output_path, success_msg)


# ── Entry point ───────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="diagrams",
        description="Mermaid diagram generation",
    )
    sub = parser.add_subparsers(dest="command")

    # telemetry
    p_tel = sub.add_parser("telemetry", help="Telemetry diagrams (cost, tokens, timeline)")
    p_tel.add_argument("type", choices=["cost-pie", "token-pie", "timeline"],
                       help="Diagram type")
    p_tel.add_argument("-d", "--days", type=int, default=7, help=DAYS_HELP)

    # render
    p_render = sub.add_parser("render", help="Render .mmd to PNG/SVG/PDF via mmdc")
    p_render.add_argument("--input", "-i", type=str, help="Input .mmd file (stdin if omitted)")
    p_render.add_argument("--output", "-o", type=str, required=True,
                          help="Output file (.svg, .png, or .pdf)")
    p_render.add_argument("--format", "-f", choices=["svg", "png", "pdf"],
                          help="Output format (inferred from path if omitted)")
    p_render.add_argument("--timeout", type=int, default=60, help="Timeout in seconds")
    p_render.add_argument("--theme", choices=["default", "forest", "dark", "neutral"],
                          help="Mermaid theme")
    p_render.add_argument("--background", "-b", type=str,
                          help="Background color (e.g. 'white', 'transparent')")
    p_render.add_argument("--width", "-w", type=int, help="Width in pixels (PNG only)")
    p_render.add_argument("--height", type=int, help="Height in pixels (PNG only)")

    # validate
    p_val = sub.add_parser("validate", help="Validate mermaid syntax via mmdc")
    p_val.add_argument("--input", "-i", type=str, help="Input .mmd file (stdin if omitted)")
    p_val.add_argument("--timeout", type=int, default=60, help="Timeout in seconds")

    # embed
    p_embed = sub.add_parser("embed", help="Output mermaid wrapped in ```mermaid code fence")
    p_embed.add_argument("--input", "-i", type=str, help="Input file (stdin if omitted)")
    p_embed.add_argument("--output", "-o", type=str, help="Output file (stdout if omitted)")
    p_embed.add_argument("--from-yaml", action="store_true",
                         help="Treat input as YAML spec")

    # health
    p_health = sub.add_parser("health", help="Check mmdc is installed and working")
    p_health.add_argument("--skip-render", action="store_true",
                          help="Skip local mmdc render check")

    # from-yaml
    p_yaml = sub.add_parser("from-yaml", help="Generate .mmd from a YAML spec")
    p_yaml.add_argument("--input", "-i", type=str,
                        help="Input YAML spec file (stdin if omitted)")
    p_yaml.add_argument("--output", "-o", type=str,
                        help="Output .mmd file (stdout if omitted)")
    p_yaml.add_argument("--embedded", action="store_true",
                        help="Wrap output in ```mermaid code fence")

    args = parser.parse_args(argv)

    commands = {
        "telemetry": cmd_telemetry,
        "render": cmd_render,
        "validate": cmd_validate,
        "embed": cmd_embed,
        "health": cmd_health,
        "from-yaml": cmd_from_yaml,
    }
    handler = commands.get(args.command)
    if handler:
        return handler(args)
    parser.print_help()
    return 0
