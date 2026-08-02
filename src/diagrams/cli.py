"""Mermaid diagram CLI — generate .mmd from telemetry and repo data."""

from __future__ import annotations

import sys

from core.cli_framework import CLIApp
from core.cli_output import OutputWriter

from .cli_telemetry import (  # noqa: F401
    _format_tokens,
    _load_telemetry,
    _render_cost_pie,
    _render_timeline,
    _render_token_pie,
    _session_cost,
)
from .cli_yaml import (  # noqa: F401
    _build_flowchart_from_spec,
    _build_sequence_from_spec,
    _convert_yaml_spec,
    _load_yaml,
)

DAYS_HELP = "Lookback days (default: 7)"
NO_SESSIONS = "No sessions found."
_DEFAULT_MMD_LABEL = "diagram.mmd"

# add_common_args=False: diagrams' own --output/-o (dest="output") means an
# output *file path*, not CLIApp's built-in output *format* flag of the same
# name. CLIApp.run() now guards its OutputFormat(args.output) parsing behind
# add_common_args (core/cli_framework.py), so calling app.run() here would no
# longer crash on that specifically — but main() still dispatches via
# _cmd_func directly (not app.run()) to preserve this CLI's legacy
# no-subcommand exit code (0, not CLIApp's default ExitCode.USAGE).
app = CLIApp("diagrams", "Mermaid diagram generation", add_common_args=False)


# ── Shared I/O helpers ────────────────────────────────────────────────────────


def _read_input(input_path: str | None, label: str = _DEFAULT_MMD_LABEL) -> str | None:
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
            print("Error: No input file specified and stdin is empty", file=sys.stderr)
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
        _writer = OutputWriter()
        _writer.print_data(content)
    return 0


def _validate_non_empty(content: str) -> bool:
    if not content.strip():
        print("Error: Empty input", file=sys.stderr)
        return False
    return True


# ── Commands ──────────────────────────────────────────────────────────────────


@app.command("telemetry", help="Telemetry diagrams (cost, tokens, timeline)")
@app.argument("type", choices=["cost-pie", "token-pie", "timeline"], help="Diagram type")
@app.argument("-d", "--days", type=int, default=7, help=DAYS_HELP)
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
    _writer = OutputWriter()
    _writer.print_data(renderer())
    return 0


@app.command("render", help="Render .mmd to PNG/SVG/PDF via mmdc")
@app.argument("--input", "-i", type=str, help="Input .mmd file (stdin if omitted)")
@app.argument("--output", "-o", type=str, required=True, help="Output file (.svg, .png, or .pdf)")
@app.argument("--format", "-f", choices=["svg", "png", "pdf"], help="Output format (inferred from path if omitted)")
@app.argument("--timeout", type=int, default=60, help="Timeout in seconds")
@app.argument("--theme", choices=["default", "forest", "dark", "neutral"], help="Mermaid theme")
@app.argument("--background", "-b", type=str, help="Background color (e.g. 'white', 'transparent')")
@app.argument("--width", "-w", type=int, help="Width in pixels (PNG only)")
@app.argument("--height", type=int, help="Height in pixels (PNG only)")
def cmd_render(args) -> int:
    """Render a .mmd file to PNG/SVG/PDF via mmdc."""
    mermaid_text = _read_input(args.input, _DEFAULT_MMD_LABEL)
    if mermaid_text is None:
        return 1
    if not _validate_non_empty(mermaid_text):
        return 1

    from core.pipeline import run_pipeline

    from .renderers import RenderDiagramProcessor, RenderDiagramProducer, RenderRequest

    request = RenderRequest(
        source=mermaid_text,
        output=args.output,
        output_format=getattr(args, "format", None),
        background=getattr(args, "background", None),
        theme=getattr(args, "theme", None),
        width=getattr(args, "width", None),
        height=getattr(args, "height", None),
        timeout=args.timeout,
    )
    return run_pipeline(request, RenderDiagramProcessor, RenderDiagramProducer)


@app.command("validate", help="Validate mermaid syntax via mmdc")
@app.argument("--input", "-i", type=str, help="Input .mmd file (stdin if omitted)")
@app.argument("--timeout", type=int, default=60, help="Timeout in seconds")
def cmd_validate(args) -> int:
    """Validate mermaid syntax via mmdc."""
    import tempfile

    mermaid_text = _read_input(args.input, _DEFAULT_MMD_LABEL)
    if mermaid_text is None:
        return 1
    if not _validate_non_empty(mermaid_text):
        return 1

    from .renderers import RenderDiagramProcessor, RenderRequest

    with tempfile.TemporaryDirectory() as tmpdir:
        import os
        tmp_out = os.path.join(tmpdir, "validate_out.svg")
        request = RenderRequest(
            source=mermaid_text,
            output=tmp_out,
            output_format="svg",
            timeout=args.timeout,
        )
        envelope = RenderDiagramProcessor().process(request)
    if envelope.ok():
        print("Valid: Mermaid syntax is correct", file=sys.stderr)
        return 0
    msg = (envelope.diagnostics or {}).get("message", "Validation failed")
    print(f"Invalid: {msg}", file=sys.stderr)
    return 1


@app.command("embed", help="Output mermaid wrapped in ```mermaid code fence")
@app.argument("--input", "-i", type=str, help="Input file (stdin if omitted)")
@app.argument("--output", "-o", type=str, help="Output file (stdout if omitted)")
@app.argument("--from-yaml", action="store_true", help="Treat input as YAML spec")
def cmd_embed(args) -> int:
    """Output mermaid wrapped in a ```mermaid code fence."""
    content = _read_input(args.input, _DEFAULT_MMD_LABEL)
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


@app.command("health", help="Check mmdc is installed and working")
@app.argument("--skip-render", action="store_true", help="Skip local mmdc render check")
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
        from .renderers import RenderOptions
        svg_bytes = renderer.render("flowchart LR\n    A-->B", RenderOptions(output_format="svg"))
        if not svg_bytes or b"<svg" not in svg_bytes:
            raise RuntimeError("Local renderer returned invalid SVG")
        print("local renderer ok", file=sys.stderr)
    except Exception as e:
        print(f"local renderer FAILED: {e}", file=sys.stderr)
        return 1

    return 0


@app.command("from-yaml", help="Generate .mmd from a YAML spec")
@app.argument("--input", "-i", type=str, help="Input YAML spec file (stdin if omitted)")
@app.argument("--output", "-o", type=str, help="Output .mmd file (stdout if omitted)")
@app.argument("--embedded", action="store_true", help="Wrap output in ```mermaid code fence")
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
    parser = app.build_parser()
    _argv = app.normalize_argv(argv if argv is not None else sys.argv[1:])
    args = parser.parse_args(_argv)

    cmd_func = getattr(args, "_cmd_func", None)
    if cmd_func is None:
        # Preserve legacy behavior: no subcommand prints help and exits 0
        # (not CLIApp's default ExitCode.USAGE), per
        # tests/diagrams_tests/test_diagrams_cli_commands.py::test_no_command_prints_help.
        parser.print_help()
        return 0
    return cmd_func(args)
