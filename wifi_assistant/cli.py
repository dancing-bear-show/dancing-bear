"""Wi-Fi diagnostics CLI using CLIApp framework."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from core.assistant import BaseAssistant
from core.cli_framework import CLIApp

from .diagnostics import DiagnoseConfig, run_diagnosis
from .meta import APP_ID, PURPOSE
from .pipeline import DiagnoseProcessor, DiagnoseProducer, DiagnoseRequest, DiagnoseRequestConsumer

assistant = BaseAssistant(
    APP_ID,
    f"agentic: {APP_ID}\npurpose: {PURPOSE}",
)

app = CLIApp(
    "wifi",
    "Wi-Fi + network diagnostic helper",
    add_common_args=False,  # We use our own args pattern
)


@lru_cache(maxsize=1)
def _lazy_agentic():
    from . import agentic as _agentic

    return _agentic.emit_agentic_context


# Note: @argument decorators must come BEFORE @command (decorators apply bottom-up)
@app.command("diagnose", help="Run Wi-Fi and network diagnostics")
@app.argument("--gateway", help="Override detected default gateway IP")
@app.argument("--targets", nargs="+", default=["1.1.1.1", "8.8.8.8", "google.com"], help="Ping targets (besides gateway)")
@app.argument("--ping-count", type=int, default=12, help="Packets per target")
@app.argument("--survey-count", type=int, default=4, help="Packets for quick ICMP survey (stage 1)")
@app.argument("--trace-target", help="Trace target (default: first non-gateway ping target)")
@app.argument("--dns-host", default="google.com", help="Host to resolve for DNS timing")
@app.argument("--http-url", default="https://speed.cloudflare.com/__down", help="URL for HTTPS smoke test")
@app.argument("--no-trace", action="store_true", help="Skip traceroute/tracepath")
@app.argument("--no-http", action="store_true", help="Skip HTTPS smoke check")
@app.argument("--no-wifi", action="store_true", help="Skip Wi-Fi metadata capture")
@app.argument("--no-survey", action="store_true", help="Skip quick ICMP survey stage")
@app.argument("--trace-hops", type=int, default=12, help="Max hops for traceroute")
@app.argument("--ping-timeout", type=float, default=15.0, help="Timeout per ping command")
@app.argument("--json", action="store_true", help="Emit JSON instead of pretty text")
@app.argument("--out", help="Write report to file")
def cmd_diagnose(args) -> int:
    """Run network diagnostics."""
    cfg = DiagnoseConfig(
        ping_targets=args.targets,
        ping_count=args.ping_count,
        gateway=args.gateway,
        trace_target=args.trace_target,
        dns_host=args.dns_host,
        http_url=None if args.no_http else args.http_url,
        include_trace=not args.no_trace,
        include_http=not args.no_http,
        include_wifi=not args.no_wifi,
        ping_timeout=args.ping_timeout,
        trace_max_hops=args.trace_hops,
        run_survey=not args.no_survey,
        survey_count=args.survey_count,
    )

    out_path = Path(args.out) if args.out else None
    request = DiagnoseRequest(config=cfg, emit_json=args.json, out_path=out_path)
    processor = DiagnoseProcessor(run_fn=run_diagnosis)
    envelope = processor.process(DiagnoseRequestConsumer(request).consume())
    DiagnoseProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point for the Wi-Fi CLI."""
    # Build parser and add agentic flags
    parser = app.build_parser()
    assistant.add_agentic_flags(parser)

    args = parser.parse_args(argv)

    # Handle agentic output if requested
    agentic_result = assistant.maybe_emit_agentic(
        args, emit_func=lambda fmt, compact: _lazy_agentic()(fmt, compact)
    )
    if agentic_result is not None:
        return agentic_result

    # Get the command function
    cmd_func = getattr(args, "_cmd_func", None)
    if cmd_func is None:
        parser.print_help()
        return 0

    return int(cmd_func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
