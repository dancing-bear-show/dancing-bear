from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from .diagnostics import DiagnoseConfig, SubprocessRunner, render_report, report_to_dict, run_diagnosis


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wifi-assistant", description="Wi-Fi + network diagnostic helper")
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

    report = run_diagnosis(cfg, runner=SubprocessRunner())
    if args.json:
        content = json.dumps(report_to_dict(report), indent=2)
    else:
        content = render_report(report)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
    print(content, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
