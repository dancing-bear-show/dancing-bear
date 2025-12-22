from __future__ import annotations

import argparse
from functools import lru_cache
from pathlib import Path
import sys
from typing import Optional

from core.assistant import BaseAssistant

from .diagnostics import DiagnoseConfig, run_diagnosis
from .pipeline import DiagnoseProcessor, DiagnoseProducer, DiagnoseRequest, DiagnoseRequestConsumer

APP_ID = "wifi"
PURPOSE = "Wi-Fi and LAN diagnostics (gateway vs upstream vs DNS)"

assistant = BaseAssistant(
    APP_ID,
    f"agentic: {APP_ID}\npurpose: {PURPOSE}",
)


@lru_cache(maxsize=1)
def _lazy_agentic():
    from . import agentic as _agentic

    return _agentic.emit_agentic_context


def build_parser() -> argparse.ArgumentParser:
    prog = Path(sys.argv[0]).name or "wifi"
    parser = argparse.ArgumentParser(prog=prog, description="Wi-Fi + network diagnostic helper")
    assistant.add_agentic_flags(parser)
    parser.add_argument("--gateway", help="Override detected default gateway IP")
    parser.add_argument("--targets", nargs="+", default=["1.1.1.1", "8.8.8.8", "google.com"], help="Ping targets (besides gateway)")
    parser.add_argument("--ping-count", type=int, default=12, help="Packets per target")
    parser.add_argument("--survey-count", type=int, default=4, help="Packets for quick ICMP survey (stage 1)")
    parser.add_argument("--trace-target", help="Trace target (default: first non-gateway ping target)")
    parser.add_argument("--dns-host", default="google.com", help="Host to resolve for DNS timing")
    parser.add_argument("--http-url", default="https://speed.cloudflare.com/__down", help="URL for HTTPS smoke test")
    parser.add_argument("--no-trace", action="store_true", help="Skip traceroute/tracepath")
    parser.add_argument("--no-http", action="store_true", help="Skip HTTPS smoke check")
    parser.add_argument("--no-wifi", action="store_true", help="Skip Wi-Fi metadata capture")
    parser.add_argument("--no-survey", action="store_true", help="Skip quick ICMP survey stage")
    parser.add_argument("--trace-hops", type=int, default=12, help="Max hops for traceroute")
    parser.add_argument("--ping-timeout", type=float, default=15.0, help="Timeout per ping command")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of pretty text")
    parser.add_argument("--out", help="Write report to file")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    agentic_result = assistant.maybe_emit_agentic(
        args, emit_func=lambda fmt, compact: _lazy_agentic()(fmt, compact)
    )
    if agentic_result is not None:
        return agentic_result

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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
