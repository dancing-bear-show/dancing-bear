"""Additional tests for wifi/diagnostics.py covering previously uncovered branches."""
from __future__ import annotations

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from wifi.diagnostics import (
    CommandResult,
    CommandRunner,
    DiagnoseConfig,
    DnsResult,
    HttpResult,
    PingResult,
    Report,
    SubprocessRunner,
    TraceResult,
    WifiInfo,
    _build_ping_targets,
    _check_dns_health,
    _check_gateway_health,
    _check_http_health,
    _check_upstream_health,
    _detect_icmp_filtered,
    _extract_gateway_line,
    _loss_bar,
    _parse_airport,
    _parse_gateway_from_line,
    _parse_iwconfig,
    _parse_nmcli,
    _parse_ping,
    _safe_float,
    _safe_int,
    _score_ping,
    _select_trace_target,
    collect_wifi_info,
    compute_condition,
    derive_findings,
    detect_gateway,
    format_dns,
    format_http,
    format_ping,
    format_report,
    format_wifi,
    ping_target,
    render_report,
    report_to_dict,
    run_diagnosis,
    trace_route,
)


class FakeRunner(CommandRunner):
    """Fake runner for tests."""
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def run(self, cmd, timeout=None):
        self.calls.append(cmd)
        key = cmd[0]
        if key in self.responses:
            return self.responses[key]
        return CommandResult(stdout="", stderr="not found", returncode=127)


class TestSubprocessRunner(unittest.TestCase):
    def test_timeout_expired_bytes_stdout(self):
        runner = SubprocessRunner()
        exc = subprocess.TimeoutExpired(cmd=["ping"], timeout=1)
        exc.stdout = b"partial output"
        exc.stderr = b"timeout error"
        with patch("subprocess.run", side_effect=exc):
            result = runner.run(["ping", "localhost"], timeout=1)
        self.assertEqual(result.returncode, 124)
        self.assertEqual(result.stdout, "partial output")
        self.assertEqual(result.stderr, "timeout error")

    def test_timeout_expired_str_stdout(self):
        runner = SubprocessRunner()
        exc = subprocess.TimeoutExpired(cmd=["ping"], timeout=1)
        exc.stdout = "partial str"
        exc.stderr = None
        with patch("subprocess.run", side_effect=exc):
            result = runner.run(["ping", "localhost"], timeout=1)
        self.assertEqual(result.returncode, 124)
        self.assertEqual(result.stdout, "partial str")
        self.assertEqual(result.stderr, "timeout")

    def test_file_not_found(self):
        runner = SubprocessRunner()
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            result = runner.run(["nonexistent-cmd"], timeout=5)
        self.assertEqual(result.returncode, 127)
        self.assertIn("not found", result.stderr)


class TestParseGatewayFromLine(unittest.TestCase):
    def test_macos_gateway_colon(self):
        result = _parse_gateway_from_line("    gateway: 192.168.1.1")
        self.assertEqual(result, "192.168.1.1")

    def test_macos_gateway_no_colon(self):
        result = _parse_gateway_from_line("    gateway 192.168.1.1")
        self.assertEqual(result, "192.168.1.1")

    def test_linux_via_format(self):
        result = _parse_gateway_from_line("default via 192.168.0.1 dev eth0")
        self.assertEqual(result, "192.168.0.1")

    def test_no_gateway(self):
        result = _parse_gateway_from_line("some random line without gateway")
        self.assertIsNone(result)


class TestExtractGatewayLine(unittest.TestCase):
    def test_finds_gateway_line(self):
        text = "  interface: en0\n  gateway: 10.0.0.1\n  expire: 1200"
        result = _extract_gateway_line(text)
        self.assertEqual(result, "10.0.0.1")

    def test_finds_via_line(self):
        text = "10.0.0.0/24 dev eth0 proto kernel\ndefault via 10.0.0.1 dev eth0"
        result = _extract_gateway_line(text)
        self.assertEqual(result, "10.0.0.1")

    def test_returns_none_for_empty(self):
        result = _extract_gateway_line("")
        self.assertIsNone(result)

    def test_returns_none_for_no_match(self):
        result = _extract_gateway_line("interface: en0\nsome data")
        self.assertIsNone(result)


class TestDetectGateway(unittest.TestCase):
    def test_detects_gateway_from_route(self):
        runner = FakeRunner({
            "route": CommandResult(stdout="  gateway: 192.168.1.1\n  interface: en0", stderr="", returncode=0)
        })
        result = detect_gateway(runner)
        self.assertEqual(result, "192.168.1.1")

    def test_falls_back_to_ip_route(self):
        runner = FakeRunner({
            "route": CommandResult(stdout="no gateway info", stderr="", returncode=1),
            "ip": CommandResult(stdout="default via 10.0.0.1 dev eth0", stderr="", returncode=0),
        })
        result = detect_gateway(runner)
        self.assertEqual(result, "10.0.0.1")

    def test_returns_none_when_no_gateway(self):
        runner = FakeRunner({
            "route": CommandResult(stdout="", stderr="error", returncode=1),
            "ip": CommandResult(stdout="", stderr="error", returncode=1),
        })
        result = detect_gateway(runner)
        self.assertIsNone(result)


class TestCollectWifiInfo(unittest.TestCase):
    def test_uses_airport(self):
        airport_output = "     SSID: MyNetwork\n     BSSID: aa:bb:cc:dd:ee:ff\n     channel: 6\n     agrCtlRSSI: -55\n     agrCtlNoise: -95\n     lastTxRate: 144"
        runner = FakeRunner()
        runner.responses["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"] = \
            CommandResult(stdout=airport_output, stderr="", returncode=0)
        result = collect_wifi_info(runner)
        self.assertIsNotNone(result)
        self.assertEqual(result.ssid, "MyNetwork")
        self.assertEqual(result.source, "airport")

    def test_falls_back_to_nmcli(self):
        nmcli_output = "yes:HomeNetwork:aa:bb:cc:dd:ee:ff:80:130 Mbit/s"
        runner = FakeRunner({
            "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport": CommandResult(stdout="", stderr="", returncode=1),
            "nmcli": CommandResult(stdout=nmcli_output, stderr="", returncode=0),
        })
        result = collect_wifi_info(runner)
        self.assertIsNotNone(result)
        self.assertEqual(result.source, "nmcli")

    def test_falls_back_to_iwconfig(self):
        iwconfig_output = 'wlan0 ESSID:"MyNet" Access Point: 11:22:33:44:55:66 Signal level=-60 dBm'
        runner = FakeRunner({
            "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport": CommandResult(stdout="", stderr="", returncode=1),
            "nmcli": CommandResult(stdout="inactive:none:::", stderr="", returncode=0),
            "iwconfig": CommandResult(stdout=iwconfig_output, stderr="", returncode=0),
        })
        result = collect_wifi_info(runner)
        self.assertIsNotNone(result)
        self.assertEqual(result.source, "iwconfig")

    def test_returns_none_when_all_fail(self):
        runner = FakeRunner({
            "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport": CommandResult(stdout="", stderr="", returncode=1),
            "nmcli": CommandResult(stdout="inactive:none:::", stderr="", returncode=0),
            "iwconfig": CommandResult(stdout="no wireless extensions", stderr="", returncode=0),
        })
        result = collect_wifi_info(runner)
        self.assertIsNone(result)


class TestParseAirport(unittest.TestCase):
    def test_parses_airport_output(self):
        text = "     SSID: TestNet\n     BSSID: 11:22:33:44:55:66\n     agrCtlRSSI: -65\n     agrCtlNoise: -90\n     lastTxRate: 200\n     channel: 6,1"
        info = _parse_airport(text)
        self.assertEqual(info.ssid, "TestNet")
        self.assertEqual(info.bssid, "11:22:33:44:55:66")
        self.assertEqual(info.rssi, -65)
        self.assertEqual(info.noise, -90)
        self.assertEqual(info.tx_rate, 200.0)
        self.assertEqual(info.channel, "6,1")
        self.assertEqual(info.source, "airport")


class TestParseNmcli(unittest.TestCase):
    def test_parses_active_connection(self):
        text = "yes:HomeNet:aa:bb:cc:dd:ee:ff:70:130 Mbit/s"
        result = _parse_nmcli(text)
        self.assertIsNotNone(result)
        self.assertEqual(result.ssid, "HomeNet")
        self.assertEqual(result.source, "nmcli")

    def test_skips_inactive(self):
        text = "no:InactiveNet:aa:bb:cc:dd:ee:ff:60:100 Mbit/s"
        result = _parse_nmcli(text)
        self.assertIsNone(result)

    def test_returns_none_when_short_line(self):
        text = "yes:only"
        result = _parse_nmcli(text)
        self.assertIsNone(result)


class TestParseIwconfig(unittest.TestCase):
    def test_parses_iwconfig_output(self):
        text = 'wlan0  ESSID:"TestNet"\n       Access Point: 11:22:33:44:55:66\n       Bit Rate=54 Mb/s   Signal level=-60 dBm'
        result = _parse_iwconfig(text)
        self.assertIsNotNone(result)
        self.assertEqual(result.ssid, "TestNet")
        self.assertEqual(result.bssid, "11:22:33:44:55:66")
        self.assertEqual(result.rssi, -60)

    def test_returns_none_for_no_info(self):
        result = _parse_iwconfig("no wireless extensions")
        self.assertIsNone(result)


class TestParsePing(unittest.TestCase):
    def test_parses_standard_ping_output(self):
        text = "5 packets transmitted, 5 packets received, 0.0% packet loss\nround-trip min/avg/max/stddev = 1.234/2.345/3.456/0.123 ms"
        tx, rx, loss, mn, avg, mx = _parse_ping(text)
        self.assertEqual(tx, 5)
        self.assertEqual(rx, 5)
        self.assertAlmostEqual(loss, 0.0)
        self.assertAlmostEqual(mn, 1.234)
        self.assertAlmostEqual(avg, 2.345)
        self.assertAlmostEqual(mx, 3.456)

    def test_parses_with_packet_loss(self):
        text = "10 packets transmitted, 7 received, 30.0% packet loss\nrtt min/avg/max/mdev = 10.0/20.0/30.0/5.0 ms"
        tx, rx, loss, _mn, _avg, _mx = _parse_ping(text)
        self.assertEqual(tx, 10)
        self.assertEqual(rx, 7)
        self.assertAlmostEqual(loss, 30.0)

    def test_parses_bytes_input(self):
        text = b"5 packets transmitted, 5 packets received, 0.0% packet loss"
        tx, rx, _loss, _mn, _avg, _mx = _parse_ping(text)
        self.assertEqual(tx, 5)
        self.assertEqual(rx, 5)

    def test_empty_returns_zeros(self):
        tx, rx, loss, _mn, _avg, _mx = _parse_ping("")
        self.assertEqual(tx, 0)
        self.assertEqual(rx, 0)
        self.assertIsNone(loss)


class TestPingTarget(unittest.TestCase):
    def test_successful_ping(self):
        output = "5 packets transmitted, 5 packets received, 0.0% packet loss\nround-trip min/avg/max/stddev = 1.0/2.0/3.0/0.5 ms"
        runner = FakeRunner({"ping": CommandResult(stdout=output, stderr="", returncode=0)})
        result = ping_target("gateway", "192.168.1.1", count=5, runner=runner, timeout=10)
        self.assertEqual(result.label, "gateway")
        self.assertEqual(result.target, "192.168.1.1")
        self.assertAlmostEqual(result.loss_pct, 0.0)
        self.assertIsNone(result.error)

    def test_failed_ping_sets_error(self):
        runner = FakeRunner({"ping": CommandResult(stdout="", stderr="host unreachable", returncode=1)})
        result = ping_target("target", "10.0.0.1", count=3, runner=runner, timeout=5)
        self.assertIsNotNone(result.error)
        self.assertEqual(result.error, "host unreachable")


class TestBuildPingTargets(unittest.TestCase):
    def test_no_gateway(self):
        result = _build_ping_targets(None, ["8.8.8.8", "1.1.1.1"])
        self.assertEqual(len(result), 2)
        self.assertNotIn("gateway", [r[0] for r in result])

    def test_with_gateway(self):
        result = _build_ping_targets("192.168.1.1", ["8.8.8.8"])
        self.assertEqual(result[0], ("gateway", "192.168.1.1"))
        self.assertEqual(len(result), 2)

    def test_gateway_in_targets_deduplicated(self):
        result = _build_ping_targets("192.168.1.1", ["192.168.1.1", "8.8.8.8"])
        labels = [r[0] for r in result]
        self.assertIn("gateway", labels)
        self.assertNotIn("192.168.1.1", labels)


class TestSelectTraceTarget(unittest.TestCase):
    def test_uses_explicit_target(self):
        config = DiagnoseConfig(ping_targets=["8.8.8.8"], trace_target="1.1.1.1")
        result = _select_trace_target(config, [("gateway", "192.168.1.1")])
        self.assertEqual(result, "1.1.1.1")

    def test_uses_second_target(self):
        config = DiagnoseConfig(ping_targets=["8.8.8.8"])
        ping_targets = [("gateway", "192.168.1.1"), ("8.8.8.8", "8.8.8.8")]
        result = _select_trace_target(config, ping_targets)
        self.assertEqual(result, "8.8.8.8")

    def test_uses_first_target_when_only_one(self):
        config = DiagnoseConfig(ping_targets=["8.8.8.8"])
        ping_targets = [("gateway", "192.168.1.1")]
        result = _select_trace_target(config, ping_targets)
        self.assertEqual(result, "192.168.1.1")

    def test_uses_dns_host_when_no_targets(self):
        config = DiagnoseConfig(ping_targets=[], dns_host="google.com")
        result = _select_trace_target(config, [])
        self.assertEqual(result, "google.com")


class TestCheckGatewayHealth(unittest.TestCase):
    def test_no_gateway(self):
        result = _check_gateway_health(None, False)
        self.assertTrue(any("not detected" in f for f in result))

    def test_icmp_filtered_skips_check(self):
        result = _check_gateway_health(None, True)
        self.assertEqual(result, [])

    def test_high_loss(self):
        p = PingResult(label="gateway", target="192.168.1.1", transmitted=10, received=0,
                       loss_pct=100.0, min_ms=None, avg_ms=None, max_ms=None)
        result = _check_gateway_health(p, False)
        self.assertTrue(any("unstable" in f.lower() for f in result))

    def test_high_latency(self):
        p = PingResult(label="gateway", target="192.168.1.1", transmitted=10, received=10,
                       loss_pct=0.0, min_ms=45.0, avg_ms=60.0, max_ms=80.0)
        result = _check_gateway_health(p, False)
        self.assertTrue(any("latency" in f.lower() for f in result))

    def test_healthy(self):
        p = PingResult(label="gateway", target="192.168.1.1", transmitted=10, received=10,
                       loss_pct=0.0, min_ms=1.0, avg_ms=2.0, max_ms=5.0)
        result = _check_gateway_health(p, False)
        self.assertEqual(result, [])


class TestCheckUpstreamHealth(unittest.TestCase):
    def test_no_upstream_returns_empty(self):
        result = _check_upstream_health([], None)
        self.assertEqual(result, [])

    def test_backhaul_loss(self):
        upstream = [PingResult(label="8.8.8.8", target="8.8.8.8", transmitted=10, received=9,
                               loss_pct=10.0, min_ms=20.0, avg_ms=25.0, max_ms=30.0)]
        gateway = PingResult(label="gateway", target="192.168.1.1", transmitted=10, received=10,
                             loss_pct=0.0, min_ms=1.0, avg_ms=2.0, max_ms=3.0)
        result = _check_upstream_health(upstream, gateway)
        self.assertTrue(any("backhaul" in f.lower() or "isp" in f.lower() for f in result))

    def test_high_internet_latency(self):
        upstream = [PingResult(label="8.8.8.8", target="8.8.8.8", transmitted=10, received=10,
                               loss_pct=0.0, min_ms=100.0, avg_ms=150.0, max_ms=200.0)]
        result = _check_upstream_health(upstream, None)
        self.assertTrue(any("latency" in f.lower() for f in result))


class TestCheckDnsHealth(unittest.TestCase):
    def test_dns_error(self):
        dns = DnsResult(host="google.com", success=False, addresses=[], elapsed_ms=None, error="SERVFAIL")
        result = _check_dns_health(dns)
        self.assertTrue(any("SERVFAIL" in f for f in result))

    def test_slow_dns(self):
        dns = DnsResult(host="google.com", success=True, addresses=["8.8.8.8"], elapsed_ms=250.0)
        result = _check_dns_health(dns)
        self.assertTrue(any("slow" in f.lower() for f in result))

    def test_healthy_dns(self):
        dns = DnsResult(host="google.com", success=True, addresses=["8.8.8.8"], elapsed_ms=10.0)
        result = _check_dns_health(dns)
        self.assertEqual(result, [])


class TestCheckHttpHealth(unittest.TestCase):
    def test_no_http(self):
        result = _check_http_health(None)
        self.assertEqual(result, [])

    def test_http_failure(self):
        http = HttpResult(url="https://test.com", success=False, status=None, elapsed_ms=None, bytes_read=None, error="Connection refused")
        result = _check_http_health(http)
        self.assertTrue(any("failed" in f.lower() for f in result))

    def test_slow_http(self):
        http = HttpResult(url="https://test.com", success=True, status=200, elapsed_ms=1500.0, bytes_read=100)
        result = _check_http_health(http)
        self.assertTrue(any("slow" in f.lower() for f in result))

    def test_healthy_http(self):
        http = HttpResult(url="https://test.com", success=True, status=200, elapsed_ms=200.0, bytes_read=1024)
        result = _check_http_health(http)
        self.assertEqual(result, [])


class TestDeriveFindingsEdgeCases(unittest.TestCase):
    def test_derive_findings_no_issues(self):
        ping_results = [
            PingResult(label="gateway", target="192.168.1.1", transmitted=10, received=10,
                       loss_pct=0.0, min_ms=1.0, avg_ms=2.0, max_ms=5.0),
            PingResult(label="8.8.8.8", target="8.8.8.8", transmitted=10, received=10,
                       loss_pct=0.0, min_ms=20.0, avg_ms=25.0, max_ms=30.0),
        ]
        dns = DnsResult(host="google.com", success=True, addresses=["8.8.8.8"], elapsed_ms=10.0)
        findings = derive_findings(gateway="192.168.1.1", ping_results=ping_results,
                                   icmp_filtered=False, dns=dns, _trace=None, http=None)
        self.assertTrue(any("healthy" in f.lower() for f in findings))

    def test_derive_findings_icmp_filtered_note(self):
        dns = DnsResult(host="google.com", success=True, addresses=["8.8.8.8"], elapsed_ms=10.0)
        findings = derive_findings(gateway="192.168.1.1", ping_results=[],
                                   icmp_filtered=True, dns=dns, _trace=None, http=None)
        self.assertTrue(any("icmp" in f.lower() for f in findings))


class TestComputeCondition(unittest.TestCase):
    def test_good_condition(self):
        ping = [PingResult(label="gateway", target="192.168.1.1", transmitted=10, received=10,
                           loss_pct=0.0, min_ms=1.0, avg_ms=5.0, max_ms=10.0)]
        dns = DnsResult(host="google.com", success=True, addresses=["8.8.8.8"], elapsed_ms=10.0)
        result = compute_condition(ping_results=ping, icmp_filtered=False, http=None, dns=dns)
        self.assertEqual(result, "good")

    def test_poor_condition_with_dns_slow(self):
        ping = []
        dns = DnsResult(host="google.com", success=True, addresses=[], elapsed_ms=450.0)
        result = compute_condition(ping_results=ping, icmp_filtered=False, http=None, dns=dns)
        self.assertEqual(result, "poor")

    def test_bad_condition_with_packet_loss(self):
        ping = [PingResult(label="gateway", target="192.168.1.1", transmitted=10, received=3,
                           loss_pct=70.0, min_ms=None, avg_ms=None, max_ms=None)]
        dns = DnsResult(host="google.com", success=True, addresses=["8.8.8.8"], elapsed_ms=10.0)
        result = compute_condition(ping_results=ping, icmp_filtered=False, http=None, dns=dns)
        self.assertEqual(result, "bad")

    def test_icmp_filtered_condition(self):
        dns = DnsResult(host="google.com", success=True, addresses=["8.8.8.8"], elapsed_ms=10.0)
        result = compute_condition(ping_results=[], icmp_filtered=True, http=None, dns=dns)
        self.assertIn("icmp", result.lower())

    def test_http_bad_degrades_condition(self):
        ping = []
        dns = DnsResult(host="google.com", success=True, addresses=["8.8.8.8"], elapsed_ms=10.0)
        http = HttpResult(url="https://test.com", success=False, status=None, elapsed_ms=None, bytes_read=None, error="timeout")
        result = compute_condition(ping_results=ping, icmp_filtered=False, http=http, dns=dns)
        self.assertIn(result, ("poor", "bad"))


class TestDetectIcmpFiltered(unittest.TestCase):
    def test_empty_survey_returns_false(self):
        result = _detect_icmp_filtered([], None)
        self.assertFalse(result)

    def test_high_gateway_loss_with_upstream_ok(self):
        survey = [
            PingResult(label="survey-gateway", target="192.168.1.1", transmitted=4, received=0,
                       loss_pct=100.0, min_ms=None, avg_ms=None, max_ms=None),
            PingResult(label="survey-8.8.8.8", target="8.8.8.8", transmitted=4, received=4,
                       loss_pct=0.0, min_ms=20.0, avg_ms=25.0, max_ms=30.0),
        ]
        result = _detect_icmp_filtered(survey, None)
        self.assertTrue(result)

    def test_low_gateway_loss_not_filtered(self):
        survey = [
            PingResult(label="survey-gateway", target="192.168.1.1", transmitted=4, received=4,
                       loss_pct=0.0, min_ms=1.0, avg_ms=2.0, max_ms=3.0),
        ]
        result = _detect_icmp_filtered(survey, None)
        self.assertFalse(result)


class TestScorePing(unittest.TestCase):
    def test_good_ping(self):
        p = PingResult(label="x", target="1.1.1.1", transmitted=5, received=5,
                       loss_pct=0.0, min_ms=1.0, avg_ms=10.0, max_ms=20.0)
        self.assertEqual(_score_ping(p), 0)

    def test_poor_ping(self):
        p = PingResult(label="x", target="1.1.1.1", transmitted=5, received=4,
                       loss_pct=20.0, min_ms=10.0, avg_ms=50.0, max_ms=100.0)
        self.assertEqual(_score_ping(p), 1)

    def test_bad_ping_no_loss_data(self):
        p = PingResult(label="x", target="1.1.1.1", transmitted=5, received=0,
                       loss_pct=None, min_ms=None, avg_ms=None, max_ms=None)
        self.assertEqual(_score_ping(p), 2)

    def test_bad_ping_high_latency(self):
        p = PingResult(label="x", target="1.1.1.1", transmitted=5, received=5,
                       loss_pct=5.0, min_ms=100.0, avg_ms=250.0, max_ms=400.0)
        self.assertEqual(_score_ping(p), 1)


class TestLossBar(unittest.TestCase):
    def test_zero_loss_full_bar(self):
        result = _loss_bar(0.0)
        self.assertTrue(result.startswith("["))
        self.assertIn("#", result)

    def test_100_loss_empty_bar(self):
        result = _loss_bar(100.0)
        self.assertIn(".", result)
        self.assertNotIn("#", result)

    def test_none_loss_question_marks(self):
        result = _loss_bar(None)
        self.assertIn("?", result)


class TestFormatWifi(unittest.TestCase):
    def test_full_wifi_info(self):
        info = WifiInfo(ssid="TestNet", bssid="aa:bb:cc:dd:ee:ff", rssi=-60, noise=-90, tx_rate=150.0, channel="6", source="airport")
        result = format_wifi(info)
        self.assertIn("TestNet", result)
        self.assertIn("-60 dBm", result)
        self.assertIn("150 Mbps", result)
        self.assertIn("Channel=6", result)

    def test_minimal_wifi_info(self):
        info = WifiInfo(ssid=None, bssid=None, rssi=None, noise=None, tx_rate=None, channel=None, source="test")
        result = format_wifi(info)
        self.assertIn("source=test", result)


class TestFormatDns(unittest.TestCase):
    def test_success(self):
        dns = DnsResult(host="google.com", success=True, addresses=["8.8.8.8", "8.8.4.4"], elapsed_ms=5.0)
        result = format_dns(dns)
        self.assertIn("google.com", result)
        self.assertIn("8.8.8.8", result)
        self.assertIn("5.0 ms", result)

    def test_failure(self):
        dns = DnsResult(host="google.com", success=False, addresses=[], elapsed_ms=10.0, error="NXDOMAIN")
        result = format_dns(dns)
        self.assertIn("FAILED", result)
        self.assertIn("NXDOMAIN", result)

    def test_success_no_addresses(self):
        dns = DnsResult(host="google.com", success=True, addresses=[], elapsed_ms=5.0)
        result = format_dns(dns)
        self.assertIn("n/a", result)


class TestFormatHttp(unittest.TestCase):
    def test_success(self):
        http = HttpResult(url="https://test.com", success=True, status=200, elapsed_ms=150.0, bytes_read=1024)
        result = format_http(http)
        self.assertIn("200 OK", result)
        self.assertIn("150 ms", result)
        self.assertIn("1024 bytes", result)

    def test_success_no_status(self):
        http = HttpResult(url="https://test.com", success=True, status=None, elapsed_ms=None, bytes_read=None)
        result = format_http(http)
        self.assertIn("ok", result)

    def test_failure(self):
        http = HttpResult(url="https://test.com", success=False, status=None, elapsed_ms=None, bytes_read=None, error="timeout")
        result = format_http(http)
        self.assertIn("failed", result)
        self.assertIn("timeout", result)


class TestFormatPing(unittest.TestCase):
    def test_with_stats(self):
        p = PingResult(label="gateway", target="192.168.1.1", transmitted=5, received=5,
                       loss_pct=0.0, min_ms=1.0, avg_ms=2.5, max_ms=4.0)
        result = format_ping(p)
        self.assertIn("gateway", result)
        self.assertIn("0.0%", result)
        self.assertIn("2.5 ms", result)

    def test_with_error(self):
        p = PingResult(label="target", target="1.1.1.1", transmitted=5, received=0,
                       loss_pct=100.0, min_ms=None, avg_ms=None, max_ms=None, error="host unreachable")
        result = format_ping(p)
        self.assertIn("host unreachable", result)

    def test_none_loss(self):
        p = PingResult(label="target", target="1.1.1.1", transmitted=0, received=0,
                       loss_pct=None, min_ms=None, avg_ms=None, max_ms=None)
        result = format_ping(p)
        self.assertIn("loss ?:??%", result)


class TestRenderReport(unittest.TestCase):
    def test_renders_full_report(self):
        ping = PingResult(label="gateway", target="192.168.1.1", transmitted=5, received=5,
                          loss_pct=0.0, min_ms=1.0, avg_ms=2.0, max_ms=5.0)
        dns = DnsResult(host="google.com", success=True, addresses=["8.8.8.8"], elapsed_ms=5.0)
        wifi = WifiInfo(ssid="TestNet", bssid=None, rssi=-55, noise=None, tx_rate=None, channel=None, source="airport")
        survey = [PingResult(label="survey-gateway", target="192.168.1.1", transmitted=4, received=4,
                             loss_pct=0.0, min_ms=1.0, avg_ms=2.0, max_ms=3.0)]
        trace = TraceResult(target="8.8.8.8", success=True, lines=["1 192.168.1.1 1ms"])
        http = HttpResult(url="https://test.com", success=True, status=200, elapsed_ms=100.0, bytes_read=512)
        report = Report(
            timestamp="2025-01-01 12:00:00",
            gateway="192.168.1.1",
            wifi=wifi,
            ping_results=[ping],
            dns=dns,
            trace=trace,
            http=http,
            survey_results=survey,
            findings=["Link looks healthy"],
            condition="good",
        )
        result = render_report(report)
        self.assertIn("Wi-Fi Doctor", result)
        self.assertIn("good", result)
        self.assertIn("TestNet", result)
        self.assertIn("ICMP survey", result)
        self.assertIn("Trace →", result)
        self.assertIn("HTTPS smoke", result)

    def test_format_report_alias(self):
        dns = DnsResult(host="google.com", success=True, addresses=["8.8.8.8"], elapsed_ms=5.0)
        report = Report(
            timestamp="2025-01-01", gateway=None, wifi=None,
            ping_results=[], dns=dns, trace=None, http=None,
            survey_results=[], findings=[], condition="unknown"
        )
        result = format_report(report)
        self.assertIsInstance(result, str)

    def test_trace_with_error_no_lines(self):
        dns = DnsResult(host="google.com", success=True, addresses=["8.8.8.8"], elapsed_ms=5.0)
        trace = TraceResult(target="8.8.8.8", success=False, lines=[], error="traceroute not found")
        report = Report(
            timestamp="2025-01-01", gateway=None, wifi=None,
            ping_results=[], dns=dns, trace=trace, http=None,
            survey_results=[], findings=["test"], condition="unknown"
        )
        result = render_report(report)
        self.assertIn("traceroute not found", result)


class TestReportToDict(unittest.TestCase):
    def test_converts_report(self):
        dns = DnsResult(host="google.com", success=True, addresses=["8.8.8.8"], elapsed_ms=5.0)
        report = Report(
            timestamp="2025-01-01", gateway="192.168.1.1", wifi=None,
            ping_results=[], dns=dns, trace=None, http=None,
            survey_results=[], findings=["healthy"], condition="good"
        )
        d = report_to_dict(report)
        self.assertIsInstance(d, dict)
        self.assertEqual(d["gateway"], "192.168.1.1")
        self.assertEqual(d["condition"], "good")


class TestSafeIntFloat(unittest.TestCase):
    def test_safe_int_valid(self):
        self.assertEqual(_safe_int("42"), 42)
        self.assertEqual(_safe_int("-10"), -10)

    def test_safe_int_invalid(self):
        self.assertIsNone(_safe_int("abc"))
        self.assertIsNone(_safe_int(None))

    def test_safe_float_valid(self):
        self.assertAlmostEqual(_safe_float("3.14"), 3.14)

    def test_safe_float_invalid(self):
        self.assertIsNone(_safe_float("abc"))
        self.assertIsNone(_safe_float(None))


class TestRunDiagnosis(unittest.TestCase):
    def test_full_run_without_wifi_trace_http(self):
        ping_result = PingResult(label="gateway", target="192.168.1.1", transmitted=4, received=4,
                                 loss_pct=0.0, min_ms=1.0, avg_ms=2.0, max_ms=3.0)
        dns_result = DnsResult(host="google.com", success=True, addresses=["8.8.8.8"], elapsed_ms=5.0)

        mock_runner = MagicMock()
        mock_runner.run.return_value = CommandResult(stdout="", stderr="", returncode=1)

        config = DiagnoseConfig(
            ping_targets=["8.8.8.8"],
            gateway="192.168.1.1",
            include_wifi=False,
            include_trace=False,
            include_http=False,
            run_survey=False,
        )

        def fake_ping(label, target, count, runner, timeout):
            return ping_result

        def fake_dns(host):
            return dns_result

        with patch("wifi.diagnostics.ping_target", side_effect=fake_ping), \
             patch("wifi.diagnostics.detect_gateway", return_value="192.168.1.1"):
            report = run_diagnosis(config, runner=mock_runner, resolver=fake_dns)

        self.assertEqual(report.gateway, "192.168.1.1")
        self.assertIsNone(report.wifi)
        self.assertIsNone(report.trace)
        self.assertIsNone(report.http)


class TestTraceRoute(unittest.TestCase):
    def test_traceroute_success(self):
        runner = FakeRunner({
            "traceroute": CommandResult(stdout="traceroute output\n1 192.168.1.1", stderr="", returncode=0)
        })
        result = trace_route("8.8.8.8", runner=runner)
        self.assertTrue(result.success)
        self.assertIn("traceroute output", result.lines)

    def test_traceroute_falls_back_to_tracepath(self):
        runner = FakeRunner({
            "traceroute": CommandResult(stdout="", stderr="traceroute: not found", returncode=127),
            "tracepath": CommandResult(stdout="tracepath output", stderr="", returncode=0),
        })
        result = trace_route("8.8.8.8", runner=runner)
        self.assertTrue(result.success)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
