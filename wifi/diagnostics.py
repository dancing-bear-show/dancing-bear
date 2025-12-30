from __future__ import annotations

import dataclasses
import re
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


class CommandRunner:
    """Simple abstraction to allow faking subprocess calls in tests."""

    def run(self, cmd: Sequence[str], timeout: Optional[float] = None) -> CommandResult:  # pragma: no cover - interface
        raise NotImplementedError


class SubprocessRunner(CommandRunner):
    def run(self, cmd: Sequence[str], timeout: Optional[float] = None) -> CommandResult:
        try:
            proc = subprocess.run(  # noqa: S603 - cmd is controlled by caller
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return CommandResult(stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode(errors="ignore") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode(errors="ignore") if isinstance(exc.stderr, bytes) else (exc.stderr or "timeout")
            return CommandResult(stdout=stdout, stderr=stderr or "timeout", returncode=124)
        except FileNotFoundError:
            return CommandResult(stdout="", stderr=f"{cmd[0]}: not found", returncode=127)


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


def _select_trace_target(config: DiagnoseConfig, ping_targets: List[Tuple[str, str]]) -> str:
    """Select target for traceroute."""
    if config.trace_target:
        return config.trace_target
    if len(ping_targets) > 1:
        return ping_targets[1][1]
    if ping_targets:
        return ping_targets[0][1]
    return config.dns_host


def run_diagnosis(
    config: DiagnoseConfig,
    runner: Optional[CommandRunner] = None,
    resolver: Optional[Callable[[str], DnsResult]] = None,
    http_probe_fn: Optional[Callable[[str], HttpResult]] = None,
) -> Report:
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

    findings = derive_findings(
        gateway=gateway,
        ping_results=ping_results,
        icmp_filtered=icmp_filtered,
        dns=dns_result,
        trace=trace_result,
        http=http_result,
    )

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
        active, ssid, bssid, signal, rate = parts[:5]
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
    start = time.perf_counter()
    try:
        import requests

        resp = requests.get(url, stream=True, timeout=5)
        elapsed_ms = (time.perf_counter() - start) * 1000
        chunk = next(resp.iter_content(chunk_size=2048), b"")
        bytes_read = len(chunk)
        resp.close()
        return HttpResult(url=url, success=True, status=resp.status_code, elapsed_ms=elapsed_ms, bytes_read=bytes_read)
    except Exception as exc:  # pragma: no cover - error path exercised indirectly
        elapsed_ms = (time.perf_counter() - start) * 1000
        return HttpResult(url=url, success=False, status=None, elapsed_ms=elapsed_ms, bytes_read=None, error=str(exc))


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


def derive_findings(
    *,
    gateway: Optional[str],
    ping_results: List[PingResult],
    icmp_filtered: bool,
    dns: DnsResult,
    trace: Optional[TraceResult],
    http: Optional[HttpResult],
) -> List[str]:
    gateway_ping = next((p for p in ping_results if p.label == "gateway"), None)
    upstream = [p for p in ping_results if p.label != "gateway"]

    findings: List[str] = []
    if icmp_filtered:
        findings.append("Gateway ICMP likely filtered; judging health via trace/HTTP instead of ping loss.")

    findings.extend(_check_gateway_health(gateway_ping, icmp_filtered))
    findings.extend(_check_upstream_health(upstream, gateway_ping))
    findings.extend(_check_dns_health(dns))
    findings.extend(_check_http_health(http))

    if not findings:
        findings.append("Link looks healthy: low loss to gateway and upstream targets.")

    return findings


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
        for p in report.survey_results:
            lines.append(format_ping(p))
        lines.append("")
    lines.append("Findings:")
    for f in report.findings:
        lines.append(f"- {f}")
    lines.append("")
    lines.append("Ping sweep:")
    for p in report.ping_results:
        lines.append(format_ping(p))
    lines.append("")
    lines.append(f"DNS: {format_dns(report.dns)}")
    if report.trace:
        lines.append("")
        lines.append(f"Trace → {report.trace.target}:")
        if report.trace.lines:
            lines.extend([f"  {ln}" for ln in report.trace.lines[:16]])
        elif report.trace.error:
            lines.append(f"  error: {report.trace.error}")
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
