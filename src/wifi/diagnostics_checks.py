"""Thin re-export shim for wifi diagnostic checks.

Split into:
  - diagnostics_probes.py  — probe execution and data classes
  - diagnostics_report.py  — report derivation and rendering
"""
from .diagnostics_probes import (  # noqa: F401
    DnsResult,
    HttpResult,
    PingResult,
    TraceResult,
    WifiInfo,
    _build_ping_targets,
    _extract_gateway_line,
    _extract_iwconfig_field,
    _parse_airport,
    _parse_gateway_from_line,
    _parse_iwconfig,
    _parse_nmcli,
    _parse_ping,
    _safe_float,
    _safe_int,
    collect_wifi_info,
    detect_gateway,
    dns_lookup,
    http_probe,
    ping_target,
    run_diagnosis,
    trace_route,
)
from .diagnostics_report import (  # noqa: F401
    DiagnoseConfig,
    DiagnoseResults,
    Report,
    _check_dns_health,
    _check_gateway_health,
    _check_http_health,
    _check_upstream_health,
    _detect_icmp_filtered,
    _loss_bar,
    _score_ping,
    compute_condition,
    derive_findings,
    format_dns,
    format_http,
    format_ping,
    format_report,
    format_wifi,
    render_report,
    report_to_dict,
)
from .diagnostics_probes import _select_trace_target  # noqa: F401
