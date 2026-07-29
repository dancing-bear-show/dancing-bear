"""Wifi diagnostics — re-export shim.

Implementation lives in:
  - wifi.diagnostics_runners: CommandResult, CommandRunner, SubprocessRunner
  - wifi.diagnostics_checks: everything else (data classes, checks, formatting, run_diagnosis)
"""
from __future__ import annotations

from .diagnostics_runners import (  # noqa: F401
    CommandResult,
    CommandRunner,
    SubprocessRunner,
)
from .diagnostics_checks import (  # noqa: F401
    WifiInfo,
    PingResult,
    DnsResult,
    TraceResult,
    HttpResult,
    DiagnoseConfig,
    Report,
    DiagnoseResults,
    _build_ping_targets,
    _select_trace_target,
    run_diagnosis,
    detect_gateway,
    _parse_gateway_from_line,
    _extract_gateway_line,
    _extract_iwconfig_field,
    _parse_iwconfig,
    _parse_nmcli,
    _parse_airport,
    _parse_ping,
    _safe_float,
    _safe_int,
    _score_ping,
    _loss_bar,
    _detect_icmp_filtered,
    _check_gateway_health,
    _check_upstream_health,
    _check_dns_health,
    _check_http_health,
    collect_wifi_info,
    ping_target,
    dns_lookup,
    trace_route,
    http_probe,
    compute_condition,
    derive_findings,
    render_report,
    format_report,
    report_to_dict,
    format_wifi,
    format_ping,
    format_dns,
    format_http,
)
