"""Wifi diagnostic probe execution: data classes and probe runners."""
from __future__ import annotations

import re
import socket
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Tuple

from .diagnostics_runners import CommandRunner, SubprocessRunner

if TYPE_CHECKING:
    from .diagnostics_report import DiagnoseConfig, Report


@dataclass
class WifiInfo:
    ssid: Optional[str]
    bssid: Optional[str]
    rssi: Optional[int]
    noise: Optional[int]
    tx_rate: Optional[float]
    channel: Optional[str]
    source: str
    raw: Optional[str] = None


@dataclass
class PingResult:
    label: str
    target: str
    transmitted: int
    received: int
    loss_pct: Optional[float]
    min_ms: Optional[float]
    avg_ms: Optional[float]
    max_ms: Optional[float]
    error: Optional[str] = None
    raw: Optional[str] = None

    def ok(self) -> bool:
        if self.loss_pct is None:
            return False
        return self.loss_pct < 50


@dataclass
class DnsResult:
    host: str
    success: bool
    addresses: List[str]
    elapsed_ms: Optional[float]
    error: Optional[str] = None


@dataclass
class TraceResult:
    target: str
    success: bool
    lines: List[str]
    error: Optional[str] = None


@dataclass
class HttpResult:
    url: str
    success: bool
    status: Optional[int]
    elapsed_ms: Optional[float]
    bytes_read: Optional[int]
    error: Optional[str] = None


def _build_ping_targets(gateway: Optional[str], targets: List[str]) -> List[Tuple[str, str]]:
    """Build deduplicated list of (label, target) pairs for pinging."""
    result: List[Tuple[str, str]] = []
    seen: set = set()
    if gateway:
        result.append(("gateway", gateway))
        seen.add(("gateway", gateway))
    for tgt in targets:
        if gateway and tgt == gateway:
            continue
        key = (tgt, tgt)
        if key not in seen:
            seen.add(key)
            result.append(key)
    return result


def _select_trace_target(config: "DiagnoseConfig", ping_targets: List[Tuple[str, str]]) -> str:
    """Select target for traceroute."""
    if config.trace_target:
        return config.trace_target
    if len(ping_targets) > 1:
        return ping_targets[1][1]
    if ping_targets:
        return ping_targets[0][1]
    return config.dns_host


def run_diagnosis(
    config: "DiagnoseConfig",
    runner: Optional[CommandRunner] = None,
    resolver: Optional[Callable[[str], DnsResult]] = None,
    http_probe_fn: Optional[Callable[[str], HttpResult]] = None,
) -> "Report":
    from .diagnostics_report import (  # noqa: PLC0415 - local import to avoid circular dependency
        DiagnoseResults,
        Report,
        _detect_icmp_filtered,
        compute_condition,
        derive_findings,
    )

    runner = runner or SubprocessRunner()
    resolver = resolver or dns_lookup
    http_probe_fn = http_probe_fn or http_probe
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    gateway = config.gateway or detect_gateway(runner)
    wifi_info = collect_wifi_info(runner) if config.include_wifi else None
    ping_targets = _build_ping_targets(gateway, config.ping_targets)

    survey_results: List[PingResult] = []
    if config.run_survey:
        survey_count = max(1, config.survey_count)
        survey_results = [
            ping_target(f"survey-{label}", target, count=survey_count, runner=runner, timeout=min(config.ping_timeout, 6))
            for label, target in ping_targets
        ]

    ping_results = [
        ping_target(label, target, count=config.ping_count, runner=runner, timeout=config.ping_timeout)
        for label, target in ping_targets
    ]

    dns_result = resolver(config.dns_host)

    trace_result: Optional[TraceResult] = None
    if config.include_trace:
        trace_target = _select_trace_target(config, ping_targets)
        trace_result = trace_route(trace_target, runner=runner, max_hops=config.trace_max_hops)

    http_result: Optional[HttpResult] = None
    if config.include_http and config.http_url:
        http_result = http_probe_fn(config.http_url)

    icmp_filtered = _detect_icmp_filtered(survey_results, trace_result)

    findings = derive_findings(DiagnoseResults(
        gateway=gateway,
        ping_results=ping_results,
        icmp_filtered=icmp_filtered,
        dns=dns_result,
        trace=trace_result,
        http=http_result,
    ))

    condition = compute_condition(
        ping_results=ping_results,
        icmp_filtered=icmp_filtered,
        http=http_result,
        dns=dns_result,
    )

    return Report(
        timestamp=timestamp,
        gateway=gateway,
        wifi=wifi_info,
        ping_results=ping_results,
        dns=dns_result,
        trace=trace_result,
        http=http_result,
        survey_results=survey_results,
        findings=findings,
        condition=condition,
    )


def detect_gateway(runner: CommandRunner) -> Optional[str]:
    cmds = [
        ["route", "-n", "get", "default"],
        ["ip", "route", "get", "8.8.8.8"],
    ]
    for cmd in cmds:
        result = runner.run(cmd, timeout=3)
        line = _extract_gateway_line(result.stdout)
        if line:
            return line
    return None


def _parse_gateway_from_line(line: str) -> Optional[str]:
    """Extract gateway IP from a single line."""
    parts = line.strip().split()
    # macOS: "gateway: 192.168.1.1"
    if len(parts) >= 2 and parts[0] in ("gateway:", "gateway"):
        return parts[1]
    # Linux: "default via 192.168.1.1 dev eth0"
    m = re.search(r"via ([0-9a-fA-F:.]+)", line)
    return m.group(1) if m else None


def _extract_gateway_line(text: str) -> Optional[str]:
    for line in text.splitlines():
        if "gateway" in line or "via" in line:
            result = _parse_gateway_from_line(line)
            if result:
                return result
    return None


def collect_wifi_info(runner: CommandRunner) -> Optional[WifiInfo]:
    # macOS: airport -I
    airport_cmd = ["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-I"]
    res = runner.run(airport_cmd, timeout=3)
    if res.returncode == 0 and res.stdout:
        return _parse_airport(res.stdout)

    # Linux: nmcli
    nmcli_cmd = ["nmcli", "-t", "-f", "ACTIVE,SSID,BSSID,SIGNAL,RATE", "dev", "wifi"]
    res = runner.run(nmcli_cmd, timeout=3)
    if res.returncode == 0 and res.stdout:
        info = _parse_nmcli(res.stdout)
        if info:
            return info

    # Linux fallback: iwconfig
    iw_cmd = ["iwconfig"]
    res = runner.run(iw_cmd, timeout=3)
    if res.returncode == 0 and res.stdout:
        info = _parse_iwconfig(res.stdout)
        if info:
            return info

    return None


def _parse_airport(text: str) -> WifiInfo:
    data: Dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        data[key.strip()] = val.strip()
    ssid = data.get("SSID")
    bssid = data.get("BSSID")
    rssi = _safe_int(data.get("agrCtlRSSI"))
    noise = _safe_int(data.get("agrCtlNoise"))
    tx_rate = _safe_float(data.get("lastTxRate"))
    channel = data.get("channel")
    return WifiInfo(ssid=ssid, bssid=bssid, rssi=rssi, noise=noise, tx_rate=tx_rate, channel=channel, source="airport", raw=text.strip())


def _parse_nmcli(text: str) -> Optional[WifiInfo]:
    for line in text.splitlines():
        parts = line.split(":")
        if len(parts) < 5:
            continue
        active, ssid, bssid, _, rate = parts[:5]
        if active.lower() not in {"yes", "true", "*"}:
            continue
        return WifiInfo(
            ssid=ssid or None,
            bssid=bssid or None,
            rssi=None,
            noise=None,
            tx_rate=_safe_float(rate.replace("Mbit/s", "").strip()),
            channel=None,
            source="nmcli",
            raw=text.strip(),
        )
    return None


def _extract_iwconfig_field(text: str, pattern: str) -> Optional[str]:
    """Extract a field from iwconfig output using regex."""
    m = re.search(pattern, text)
    return m.group(1) if m else None


def _parse_iwconfig(text: str) -> Optional[WifiInfo]:
    ssid = _extract_iwconfig_field(text, r'ESSID:"([^"]+)"')
    bssid = _extract_iwconfig_field(text, r"Access Point: ([0-9A-Fa-f:]{17})")
    level_str = _extract_iwconfig_field(text, r"Signal level[=\:]-?(\d+)")
    level = _safe_int(level_str)
    rssi = -abs(level) if level is not None else None
    if ssid or bssid or rssi:
        return WifiInfo(ssid=ssid, bssid=bssid, rssi=rssi, noise=None, tx_rate=None, channel=None, source="iwconfig", raw=text.strip())
    return None


def ping_target(label: str, target: str, *, count: int, runner: CommandRunner, timeout: float) -> PingResult:
    cmd = ["ping", "-c", str(count), target]
    res = runner.run(cmd, timeout=timeout)
    transmitted, received, loss_pct, min_ms, avg_ms, max_ms = _parse_ping(res.stdout)
    error = None
    if res.returncode != 0:
        error = res.stderr.strip() or "ping failed"
    return PingResult(
        label=label,
        target=target,
        transmitted=transmitted,
        received=received,
        loss_pct=loss_pct,
        min_ms=min_ms,
        avg_ms=avg_ms,
        max_ms=max_ms,
        error=error,
        raw=res.stdout.strip() or None,
    )


def _parse_ping(text: str) -> Tuple[int, int, Optional[float], Optional[float], Optional[float], Optional[float]]:
    if isinstance(text, (bytes, bytearray)):
        text = text.decode(errors="ignore")
    transmitted = received = 0
    loss_pct: Optional[float] = None
    min_ms = avg_ms = max_ms = None
    for line in text.splitlines():
        if "packets transmitted" in line and "packet loss" in line:
            m = re.search(r"(\d+) packets transmitted, (\d+) (?:packets )?received, ([0-9.]+)% packet loss", line)
            if m:
                transmitted = int(m.group(1))
                received = int(m.group(2))
                loss_pct = float(m.group(3))
        if "min/avg/max" in line:
            m = re.search(r"=\s*([0-9.]+)/([0-9.]+)/([0-9.]+)/", line)
            if m:
                min_ms = float(m.group(1))
                avg_ms = float(m.group(2))
                max_ms = float(m.group(3))
    return transmitted, received, loss_pct, min_ms, avg_ms, max_ms


def dns_lookup(host: str) -> DnsResult:
    start = time.perf_counter()
    addresses: List[str] = []
    try:
        infos = socket.getaddrinfo(host, None)
        for family, _type, _proto, _canon, sockaddr in infos:
            if family in (socket.AF_INET, socket.AF_INET6):
                ip = sockaddr[0]
                if ip not in addresses:
                    addresses.append(ip)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return DnsResult(host=host, success=True, addresses=addresses, elapsed_ms=elapsed_ms)
    except Exception as exc:  # pragma: no cover - exercised indirectly
        elapsed_ms = (time.perf_counter() - start) * 1000
        return DnsResult(host=host, success=False, addresses=[], elapsed_ms=elapsed_ms, error=str(exc))


def trace_route(target: str, *, runner: CommandRunner, max_hops: int = 12) -> TraceResult:
    cmd = ["traceroute", "-m", str(max_hops), "-q", "1", target]
    res = runner.run(cmd, timeout=15)
    if res.returncode != 0 and (res.returncode == 127 or "not found" in res.stderr.lower()):
        cmd = ["tracepath", target]
        res = runner.run(cmd, timeout=15)
    success = res.returncode == 0
    lines = res.stdout.splitlines()
    error = res.stderr.strip() or None
    return TraceResult(target=target, success=success, lines=lines, error=error)


def http_probe(url: str) -> HttpResult:
    from core.http import HttpClient

    start = time.perf_counter()
    try:
        resp = HttpClient("", timeout=5.0, retries=1).get(url, stream=True)
        elapsed_ms = (time.perf_counter() - start) * 1000
        chunk = next(resp.iter_content(chunk_size=2048), b"")
        bytes_read = len(chunk)
        resp.close()
        return HttpResult(url=url, success=True, status=resp.status_code, elapsed_ms=elapsed_ms, bytes_read=bytes_read)
    except Exception as exc:  # pragma: no cover - error path exercised indirectly
        elapsed_ms = (time.perf_counter() - start) * 1000
        return HttpResult(url=url, success=False, status=None, elapsed_ms=elapsed_ms, bytes_read=None, error=str(exc))


def _safe_int(val: Optional[str]) -> Optional[int]:
    try:
        return int(val) if val is not None else None
    except ValueError:
        return None


def _safe_float(val: Optional[str]) -> Optional[float]:
    try:
        return float(val) if val is not None else None
    except ValueError:
        return None
