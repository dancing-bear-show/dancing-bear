"""WiFi diagnostics test fixtures.

Factories for creating test data for wifi diagnostics commands and reports.
"""

from __future__ import annotations

from typing import List, Optional

from wifi.diagnostics import (
    CommandResult,
    CommandRunner,
    DnsResult,
    HttpResult,
    PingResult,
    Report,
    TraceResult,
    WifiInfo,
)


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

DEFAULT_DNS_HOST = "example.com"
DEFAULT_HTTP_URL = "https://example.com"


# -----------------------------------------------------------------------------
# CommandRunner mock
# -----------------------------------------------------------------------------


class FakeRunner(CommandRunner):
    """Fake CommandRunner for testing without subprocess calls."""

    def __init__(self):
        self._results = {}

    def add(self, cmd, stdout="", stderr="", returncode=0):
        """Register a command result for run() to return."""
        self._results[tuple(cmd)] = CommandResult(stdout=stdout, stderr=stderr, returncode=returncode)

    def run(self, cmd, timeout=None):
        """Return pre-registered result or default missing command result."""
        return self._results.get(tuple(cmd), CommandResult(stdout="", stderr="missing", returncode=127))


# -----------------------------------------------------------------------------
# PingResult factories
# -----------------------------------------------------------------------------


def ping_result_ok(
    label: str = "gateway",
    target: str = "192.168.1.1",
    transmitted: int = 10,
    received: int = 10,
    loss_pct: float = 0.0,
    min_ms: float = 1.0,
    avg_ms: float = 2.0,
    max_ms: float = 3.0,
) -> PingResult:
    """Create a healthy ping result (0% loss, low latency)."""
    return PingResult(
        label=label,
        target=target,
        transmitted=transmitted,
        received=received,
        loss_pct=loss_pct,
        min_ms=min_ms,
        avg_ms=avg_ms,
        max_ms=max_ms,
    )


def ping_result_bad(
    label: str = "gateway",
    target: str = "192.168.1.1",
    transmitted: int = 10,
    received: int = 5,
    loss_pct: float = 50.0,
    min_ms: Optional[float] = 1.0,
    avg_ms: Optional[float] = 2.0,
    max_ms: Optional[float] = 3.0,
) -> PingResult:
    """Create a bad ping result (high packet loss)."""
    return PingResult(
        label=label,
        target=target,
        transmitted=transmitted,
        received=received,
        loss_pct=loss_pct,
        min_ms=min_ms,
        avg_ms=avg_ms,
        max_ms=max_ms,
    )


def ping_result_survey(
    label: str = "survey-gateway",
    target: str = "192.168.1.1",
    transmitted: int = 4,
    received: int = 0,
    loss_pct: float = 100.0,
) -> PingResult:
    """Create a survey ping result (100% loss for ICMP filtering detection)."""
    return PingResult(
        label=label,
        target=target,
        transmitted=transmitted,
        received=received,
        loss_pct=loss_pct,
        min_ms=None,
        avg_ms=None,
        max_ms=None,
    )


def ping_result_high_latency(
    label: str = "gateway",
    target: str = "192.168.1.1",
    transmitted: int = 10,
    received: int = 10,
    loss_pct: float = 0.0,
    min_ms: float = 40.0,
    avg_ms: float = 60.0,
    max_ms: float = 80.0,
) -> PingResult:
    """Create a ping result with high latency but no packet loss."""
    return PingResult(
        label=label,
        target=target,
        transmitted=transmitted,
        received=received,
        loss_pct=loss_pct,
        min_ms=min_ms,
        avg_ms=avg_ms,
        max_ms=max_ms,
    )


def ping_result_unstable(
    label: str = "gateway",
    target: str = "192.168.1.1",
    transmitted: int = 10,
    received: int = 5,
    loss_pct: float = 50.0,
    min_ms: float = 1.0,
    avg_ms: float = 2.0,
    max_ms: float = 3.0,
) -> PingResult:
    """Create an unstable ping result (moderate packet loss)."""
    return PingResult(
        label=label,
        target=target,
        transmitted=transmitted,
        received=received,
        loss_pct=loss_pct,
        min_ms=min_ms,
        avg_ms=avg_ms,
        max_ms=max_ms,
    )


# -----------------------------------------------------------------------------
# DnsResult factories
# -----------------------------------------------------------------------------


def dns_result_success(
    host: str = DEFAULT_DNS_HOST,
    addresses: Optional[List[str]] = None,
    elapsed_ms: float = 5.0,
) -> DnsResult:
    """Create a successful DNS result (fast resolution)."""
    return DnsResult(
        host=host,
        success=True,
        addresses=addresses or ["1.2.3.4"],
        elapsed_ms=elapsed_ms,
    )


def dns_result_slow(
    host: str = DEFAULT_DNS_HOST,
    addresses: Optional[List[str]] = None,
    elapsed_ms: float = 250.0,
) -> DnsResult:
    """Create a slow DNS result (high latency)."""
    return DnsResult(
        host=host,
        success=True,
        addresses=addresses or ["1.2.3.4"],
        elapsed_ms=elapsed_ms,
    )


def dns_result_failed(
    host: str = DEFAULT_DNS_HOST,
    error: str = "timeout",
) -> DnsResult:
    """Create a failed DNS result."""
    return DnsResult(
        host=host,
        success=False,
        addresses=[],
        elapsed_ms=None,
        error=error,
    )


# -----------------------------------------------------------------------------
# HttpResult factories
# -----------------------------------------------------------------------------


def http_result_ok(
    url: str = DEFAULT_HTTP_URL,
    status: int = 200,
    elapsed_ms: float = 100.0,
    bytes_read: int = 1024,
) -> HttpResult:
    """Create a successful HTTP result (fast response)."""
    return HttpResult(
        url=url,
        success=True,
        status=status,
        elapsed_ms=elapsed_ms,
        bytes_read=bytes_read,
    )


def http_result_slow(
    url: str = DEFAULT_HTTP_URL,
    status: int = 200,
    elapsed_ms: float = 1500.0,
    bytes_read: int = 1024,
) -> HttpResult:
    """Create a slow HTTP result (high latency)."""
    return HttpResult(
        url=url,
        success=True,
        status=status,
        elapsed_ms=elapsed_ms,
        bytes_read=bytes_read,
    )


def http_result_failed(
    url: str = DEFAULT_HTTP_URL,
    error: str = "timeout",
) -> HttpResult:
    """Create a failed HTTP result."""
    return HttpResult(
        url=url,
        success=False,
        status=None,
        elapsed_ms=None,
        bytes_read=None,
        error=error,
    )


# -----------------------------------------------------------------------------
# TraceResult factories
# -----------------------------------------------------------------------------


def trace_result_success(
    target: str = "1.1.1.1",
    lines: Optional[List[str]] = None,
) -> TraceResult:
    """Create a successful traceroute result."""
    return TraceResult(
        target=target,
        success=True,
        lines=lines or ["hop1", "hop2", "hop3"],
    )


def trace_result_failed(
    target: str = "1.1.1.1",
    error: str = "timeout",
) -> TraceResult:
    """Create a failed traceroute result."""
    return TraceResult(
        target=target,
        success=False,
        lines=[],
        error=error,
    )


# -----------------------------------------------------------------------------
# WifiInfo factories
# -----------------------------------------------------------------------------


def wifi_info_airport(
    ssid: str = "TestNet",
    bssid: str = "aa:bb:cc:dd:ee:ff",
    rssi: int = -60,
    noise: int = -90,
    tx_rate: float = 300.0,
    channel: str = "36",
) -> WifiInfo:
    """Create a WifiInfo from airport command format."""
    return WifiInfo(
        ssid=ssid,
        bssid=bssid,
        rssi=rssi,
        noise=noise,
        tx_rate=tx_rate,
        channel=channel,
        source="airport",
    )


def wifi_info_weak(
    ssid: str = "WeakNet",
    bssid: str = "aa:bb:cc:dd:ee:ff",
    rssi: int = -80,
    noise: int = -90,
    tx_rate: float = 50.0,
    channel: str = "1",
) -> WifiInfo:
    """Create a WifiInfo with weak signal."""
    return WifiInfo(
        ssid=ssid,
        bssid=bssid,
        rssi=rssi,
        noise=noise,
        tx_rate=tx_rate,
        channel=channel,
        source="airport",
    )


# -----------------------------------------------------------------------------
# Report factory
# -----------------------------------------------------------------------------


def make_report(
    timestamp: str = "2024-01-01 00:00:00",
    gateway: str = "192.168.1.1",
    wifi: Optional[WifiInfo] = None,
    ping_results: Optional[List[PingResult]] = None,
    dns: Optional[DnsResult] = None,
    trace: Optional[TraceResult] = None,
    http: Optional[HttpResult] = None,
    survey_results: Optional[List[PingResult]] = None,
    findings: Optional[List[str]] = None,
    condition: str = "good",
) -> Report:
    """Create a diagnostic report with sensible defaults.

    Args:
        timestamp: Report timestamp
        gateway: Gateway IP
        wifi: WifiInfo (None for no wifi)
        ping_results: List of ping results (defaults to single ok gateway ping)
        dns: DNS result (defaults to success)
        trace: Traceroute result (None by default)
        http: HTTP result (None by default)
        survey_results: Survey ping results (empty by default)
        findings: List of findings (defaults to ["all good"])
        condition: Overall condition (good/poor/bad/n/a)

    Returns:
        Report instance
    """
    return Report(
        timestamp=timestamp,
        gateway=gateway,
        wifi=wifi,
        ping_results=ping_results or [ping_result_ok()],
        dns=dns or dns_result_success(),
        trace=trace,
        http=http,
        survey_results=survey_results or [],
        findings=findings or ["all good"],
        condition=condition,
    )


# -----------------------------------------------------------------------------
# Common test constants
# -----------------------------------------------------------------------------

SAMPLE_GATEWAY_OK = ping_result_ok(label="gateway", target="192.168.1.1")
SAMPLE_GATEWAY_BAD = ping_result_bad(label="gateway", target="192.168.1.1")
SAMPLE_UPSTREAM_OK = ping_result_ok(label="1.1.1.1", target="1.1.1.1", min_ms=10.0, avg_ms=20.0, max_ms=30.0)
SAMPLE_UPSTREAM_BAD = ping_result_bad(label="8.8.8.8", target="8.8.8.8", min_ms=10.0, avg_ms=20.0, max_ms=30.0)

SAMPLE_DNS_OK = dns_result_success()
SAMPLE_DNS_SLOW = dns_result_slow()
SAMPLE_DNS_FAILED = dns_result_failed()

SAMPLE_HTTP_OK = http_result_ok()
SAMPLE_HTTP_SLOW = http_result_slow()
SAMPLE_HTTP_FAILED = http_result_failed()

SAMPLE_WIFI_GOOD = wifi_info_airport(ssid="GoodNet", rssi=-50)
SAMPLE_WIFI_WEAK = wifi_info_weak(ssid="WeakNet", rssi=-80)

SAMPLE_TRACE_OK = trace_result_success()
SAMPLE_TRACE_FAILED = trace_result_failed()
