"""Wifi diagnostic report derivation and rendering."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .diagnostics_probes import (
    DnsResult,
    HttpResult,
    PingResult,
    TraceResult,
    WifiInfo,
)


@dataclass
class DiagnoseConfig:
    ping_targets: List[str]
    ping_count: int = 12
    gateway: Optional[str] = None
    trace_target: Optional[str] = None
    dns_host: str = "google.com"
    http_url: Optional[str] = "https://speed.cloudflare.com/__down"
    include_trace: bool = True
    include_http: bool = True
    include_wifi: bool = True
    ping_timeout: float = 15.0
    trace_max_hops: int = 12
    run_survey: bool = True
    survey_count: int = 4


@dataclass
class Report:
    timestamp: str
    gateway: Optional[str]
    wifi: Optional[WifiInfo]
    ping_results: List[PingResult]
    dns: DnsResult
    trace: Optional[TraceResult]
    http: Optional[HttpResult]
    survey_results: List[PingResult] = dataclasses.field(default_factory=list)
    findings: List[str] = dataclasses.field(default_factory=list)
    condition: str = "unknown"


@dataclass
class DiagnoseResults:
    """Collected results from a diagnostic run for deriving findings."""

    gateway: Optional[str]
    ping_results: List[PingResult]
    icmp_filtered: bool
    dns: DnsResult
    trace: Optional[TraceResult]
    http: Optional[HttpResult]


def _check_gateway_health(gateway_ping: Optional[PingResult], icmp_filtered: bool) -> List[str]:
    """Check gateway ping health, return findings."""
    if icmp_filtered:
        return []
    if gateway_ping is None:
        return ["Gateway not detected; verify you are connected to Wi-Fi."]
    if gateway_ping.loss_pct is None or gateway_ping.loss_pct >= 20:
        return [f"Wi-Fi link looks unstable ({gateway_ping.loss_pct or 100:.1f}% loss to gateway). Check interference or move closer."]
    if gateway_ping.avg_ms and gateway_ping.avg_ms > 50:
        return [f"Wi-Fi link latency is high (avg {gateway_ping.avg_ms:.1f} ms to gateway)."]
    return []


def _check_upstream_health(upstream: List[PingResult], gateway_ping: Optional[PingResult]) -> List[str]:
    """Check upstream ping health, return findings."""
    if not upstream:
        return []
    worst = max(upstream, key=lambda p: p.loss_pct or -1)
    gateway_ok = gateway_ping and (gateway_ping.loss_pct or 0) < 5
    if worst.loss_pct is not None and worst.loss_pct >= 10 and gateway_ok:
        return [f"Backhaul/ISP loss detected ({worst.loss_pct:.1f}% to {worst.label}). Gateway looks fine, so upstream is suspect."]
    gateway_latency_ok = not gateway_ping or not gateway_ping.avg_ms or gateway_ping.avg_ms < 50
    if worst.avg_ms and worst.avg_ms > 120 and gateway_latency_ok:
        return [f"High internet latency (avg {worst.avg_ms:.1f} ms to {worst.label})."]
    return []


def _check_dns_health(dns: DnsResult) -> List[str]:
    """Check DNS health, return findings."""
    if dns.error:
        return [f"DNS lookup failed for {dns.host}: {dns.error}"]
    if not dns.success or (dns.elapsed_ms and dns.elapsed_ms > 200):
        return [f"DNS responses feel slow ({dns.elapsed_ms:.1f} ms). Consider switching resolvers."]
    return []


def _check_http_health(http: Optional[HttpResult]) -> List[str]:
    """Check HTTP health, return findings."""
    if not http:
        return []
    if not http.success:
        return [f"HTTPS fetch failed ({http.error or 'unknown error'})."]
    if http.elapsed_ms and http.elapsed_ms > 1200:
        return [f"HTTPS handshake/TTFB is slow ({http.elapsed_ms:.0f} ms)."]
    return []


def derive_findings(results: DiagnoseResults) -> List[str]:
    """Derive human-readable findings from diagnostic results."""
    gateway_ping = next((p for p in results.ping_results if p.label == "gateway"), None)
    upstream = [p for p in results.ping_results if p.label != "gateway"]

    findings: List[str] = []
    if results.icmp_filtered:
        findings.append("Gateway ICMP likely filtered; judging health via trace/HTTP instead of ping loss.")

    findings.extend(_check_gateway_health(gateway_ping, results.icmp_filtered))
    findings.extend(_check_upstream_health(upstream, gateway_ping))
    findings.extend(_check_dns_health(results.dns))
    findings.extend(_check_http_health(results.http))

    if not findings:
        findings.append("Link looks healthy: low loss to gateway and upstream targets.")

    return findings


def _append_trace_section(lines: List[str], trace: TraceResult) -> None:
    lines.append("")
    lines.append(f"Trace → {trace.target}:")
    if trace.lines:
        lines.extend([f"  {ln}" for ln in trace.lines[:16]])
    elif trace.error:
        lines.append(f"  error: {trace.error}")


def render_report(report: Report) -> str:
    lines: List[str] = []
    header = f"Wi-Fi Doctor @ {report.timestamp}"
    box = "+" + "-" * (len(header) + 2) + "+"
    lines.extend([box, f"| {header} |", box])
    lines.append(f"Gateway: {report.gateway or 'unknown'}")
    lines.append(f"Condition: {report.condition}")
    if report.wifi:
        lines.append(format_wifi(report.wifi))
    lines.append("")
    if report.survey_results:
        lines.append("ICMP survey (quick):")
        lines.extend(format_ping(p) for p in report.survey_results)
        lines.append("")
    lines.append("Findings:")
    lines.extend(f"- {f}" for f in report.findings)
    lines.append("")
    lines.append("Ping sweep:")
    lines.extend(format_ping(p) for p in report.ping_results)
    lines.append("")
    lines.append(f"DNS: {format_dns(report.dns)}")
    if report.trace:
        _append_trace_section(lines, report.trace)
    if report.http:
        lines.append("")
        lines.append(f"HTTPS smoke: {format_http(report.http)}")
    return "\n".join(lines) + "\n"


# Alias for callers that prefer the verb "format" over "render"
format_report = render_report


def _detect_icmp_filtered(survey_results: List[PingResult], trace: Optional[TraceResult]) -> bool:
    if not survey_results:
        return False
    survey_gateway = next((p for p in survey_results if p.label.startswith("survey-gateway")), None)
    survey_upstream = [p for p in survey_results if not p.label.startswith("survey-gateway")]
    gateway_loss = survey_gateway.loss_pct if survey_gateway else None
    upstream_any_ok = any((p.loss_pct is None or p.loss_pct < 80) for p in survey_upstream)
    if gateway_loss is not None and gateway_loss >= 90 and (upstream_any_ok or (trace and trace.success)):
        return True
    return False


def _score_ping(p: PingResult) -> int:
    """Score a ping result: 0=good, 1=poor, 2=bad."""
    if p.loss_pct is None or p.loss_pct >= 30:
        return 2
    if p.loss_pct >= 10 or (p.avg_ms and p.avg_ms > 200):
        return 1
    return 0


def compute_condition(
    *,
    ping_results: List[PingResult],
    icmp_filtered: bool,
    http: Optional[HttpResult],
    dns: DnsResult,
) -> str:
    if icmp_filtered:
        return "n/a (icmp filtered)"

    gateway_ping = next((p for p in ping_results if p.label == "gateway"), None)
    upstream = [p for p in ping_results if p.label != "gateway"]

    scores = [_score_ping(gateway_ping)] if gateway_ping else []
    scores.extend(_score_ping(p) for p in upstream)

    dns_bad = (not dns.success) or (dns.elapsed_ms and dns.elapsed_ms > 400)
    http_bad = http and (not http.success or (http.elapsed_ms and http.elapsed_ms > 1500))

    worst = max(scores) if scores else 0
    if dns_bad or http_bad:
        worst = max(worst, 1)

    if worst == 0:
        return "good"
    if worst == 1:
        return "poor"
    return "bad"


def report_to_dict(report: Report) -> Dict[str, Any]:
    def _clean(value: Any) -> Any:
        if dataclasses.is_dataclass(value):
            return {k: _clean(v) for k, v in dataclasses.asdict(value).items()}
        if isinstance(value, list):
            return [_clean(v) for v in value]
        return value

    return _clean(report)


def format_wifi(info: WifiInfo) -> str:
    bits = []
    if info.ssid:
        bits.append(f"SSID={info.ssid}")
    if info.bssid:
        bits.append(f"BSSID={info.bssid}")
    if info.rssi is not None:
        bits.append(f"RSSI={info.rssi} dBm")
    if info.noise is not None:
        bits.append(f"Noise={info.noise} dBm")
    if info.tx_rate is not None:
        bits.append(f"Rate={info.tx_rate:.0f} Mbps")
    if info.channel:
        bits.append(f"Channel={info.channel}")
    bits.append(f"source={info.source}")
    return "Wi-Fi: " + ", ".join(bits)


def format_ping(result: PingResult) -> str:
    bar = _loss_bar(result.loss_pct)
    loss = "loss ?:??%" if result.loss_pct is None else f"loss {result.loss_pct:.1f}%"
    latency = ""
    if result.avg_ms is not None:
        latency = f"avg {result.avg_ms:.1f} ms (min {result.min_ms or 0:.1f} / max {result.max_ms or 0:.1f})"
    suffix = f" [{result.error}]" if result.error else ""
    label = f"{result.label} ({result.target})"
    return f"  {label:<24} {bar} {loss:<14} {latency}{suffix}"


def format_dns(result: DnsResult) -> str:
    if result.success:
        targets = ", ".join(result.addresses) if result.addresses else "n/a"
        return f"{result.host} -> {targets} ({result.elapsed_ms:.1f} ms)"
    return f"{result.host} FAILED ({result.error or 'dns error'})"


def format_http(result: HttpResult) -> str:
    if result.success:
        status = f"{result.status} OK" if result.status else "ok"
        ttfb = f"{result.elapsed_ms:.0f} ms" if result.elapsed_ms is not None else "n/a"
        size = f"{result.bytes_read or 0} bytes"
        return f"{status} in {ttfb} ({size})"
    return f"failed: {result.error or 'http error'}"


def _loss_bar(loss_pct: Optional[float], width: int = 18) -> str:
    if loss_pct is None:
        return "[" + "?" * width + "]"
    success_pct = max(0.0, min(100.0, 100.0 - loss_pct))
    fill = int(round((success_pct / 100.0) * width))
    return "[" + "#" * fill + "." * (width - fill) + "]"
