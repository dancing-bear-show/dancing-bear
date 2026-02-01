import unittest
from unittest.mock import patch

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
    _extract_iwconfig_field,
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
    dns_lookup,
    format_dns,
    format_http,
    format_ping,
    format_wifi,
    http_probe,
    ping_target,
    render_report,
    report_to_dict,
    run_diagnosis,
    trace_route,
)


class FakeRunner(CommandRunner):
    def __init__(self):
        self._results = {}

    def add(self, cmd, stdout="", stderr="", returncode=0):
        self._results[tuple(cmd)] = CommandResult(stdout=stdout, stderr=stderr, returncode=returncode)

    def run(self, cmd, timeout=None):
        return self._results.get(tuple(cmd), CommandResult(stdout="", stderr="missing", returncode=127))


class SubprocessRunnerTests(unittest.TestCase):
    def test_subprocess_runner_success(self):
        runner = SubprocessRunner()
        result = runner.run(["echo", "hello"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("hello", result.stdout)

    def test_subprocess_runner_timeout(self):
        runner = SubprocessRunner()
        result = runner.run(["sleep", "10"], timeout=0.1)
        self.assertEqual(result.returncode, 124)
        self.assertIn("timeout", result.stderr)

    def test_subprocess_runner_file_not_found(self):
        runner = SubprocessRunner()
        result = runner.run(["nonexistent-command-xyz"])
        self.assertEqual(result.returncode, 127)
        self.assertIn("not found", result.stderr)


class PingResultTests(unittest.TestCase):
    def test_ping_result_ok_when_low_loss(self):
        pr = PingResult(label="test", target="1.1.1.1", transmitted=10, received=9, loss_pct=10.0,
                        min_ms=1.0, avg_ms=2.0, max_ms=3.0)
        self.assertTrue(pr.ok())

    def test_ping_result_not_ok_when_high_loss(self):
        pr = PingResult(label="test", target="1.1.1.1", transmitted=10, received=3, loss_pct=70.0,
                        min_ms=1.0, avg_ms=2.0, max_ms=3.0)
        self.assertFalse(pr.ok())

    def test_ping_result_not_ok_when_loss_none(self):
        pr = PingResult(label="test", target="1.1.1.1", transmitted=0, received=0, loss_pct=None,
                        min_ms=None, avg_ms=None, max_ms=None)
        self.assertFalse(pr.ok())


class BuildPingTargetsTests(unittest.TestCase):
    def test_build_ping_targets_no_gateway(self):
        targets = _build_ping_targets(None, ["1.1.1.1", "8.8.8.8"])
        self.assertEqual(targets, [("1.1.1.1", "1.1.1.1"), ("8.8.8.8", "8.8.8.8")])

    def test_build_ping_targets_with_gateway(self):
        targets = _build_ping_targets("192.168.1.1", ["1.1.1.1", "8.8.8.8"])
        self.assertEqual(targets, [("gateway", "192.168.1.1"), ("1.1.1.1", "1.1.1.1"), ("8.8.8.8", "8.8.8.8")])

    def test_build_ping_targets_dedup_gateway(self):
        targets = _build_ping_targets("192.168.1.1", ["192.168.1.1", "1.1.1.1"])
        self.assertEqual(targets, [("gateway", "192.168.1.1"), ("1.1.1.1", "1.1.1.1")])

    def test_build_ping_targets_dedup_duplicates(self):
        targets = _build_ping_targets(None, ["1.1.1.1", "1.1.1.1", "8.8.8.8"])
        self.assertEqual(targets, [("1.1.1.1", "1.1.1.1"), ("8.8.8.8", "8.8.8.8")])


class SelectTraceTargetTests(unittest.TestCase):
    def test_select_trace_target_explicit(self):
        config = DiagnoseConfig(ping_targets=[], trace_target="custom.target")
        target = _select_trace_target(config, [])
        self.assertEqual(target, "custom.target")

    def test_select_trace_target_second_ping_target(self):
        config = DiagnoseConfig(ping_targets=[])
        targets = [("gateway", "192.168.1.1"), ("1.1.1.1", "1.1.1.1")]
        target = _select_trace_target(config, targets)
        self.assertEqual(target, "1.1.1.1")

    def test_select_trace_target_first_when_only_one(self):
        config = DiagnoseConfig(ping_targets=[])
        targets = [("gateway", "192.168.1.1")]
        target = _select_trace_target(config, targets)
        self.assertEqual(target, "192.168.1.1")

    def test_select_trace_target_fallback_dns_host(self):
        config = DiagnoseConfig(ping_targets=[], dns_host="google.com")
        target = _select_trace_target(config, [])
        self.assertEqual(target, "google.com")


class GatewayDetectionTests(unittest.TestCase):
    def test_detect_gateway_macos_format(self):
        runner = FakeRunner()
        runner.add(["route", "-n", "get", "default"], stdout="gateway: 192.168.1.1\n")
        gw = detect_gateway(runner)
        self.assertEqual(gw, "192.168.1.1")

    def test_detect_gateway_linux_format(self):
        runner = FakeRunner()
        runner.add(["route", "-n", "get", "default"], stdout="", returncode=1)
        runner.add(["ip", "route", "get", "8.8.8.8"], stdout="8.8.8.8 via 10.0.0.1 dev eth0\n")
        gw = detect_gateway(runner)
        self.assertEqual(gw, "10.0.0.1")

    def test_detect_gateway_none_when_not_found(self):
        runner = FakeRunner()
        runner.add(["route", "-n", "get", "default"], stdout="no gateway here\n")
        runner.add(["ip", "route", "get", "8.8.8.8"], stdout="no via\n")
        gw = detect_gateway(runner)
        self.assertIsNone(gw)

    def test_parse_gateway_from_line_macos(self):
        self.assertEqual(_parse_gateway_from_line("gateway: 192.168.1.1"), "192.168.1.1")
        self.assertEqual(_parse_gateway_from_line("   gateway 10.0.0.1"), "10.0.0.1")

    def test_parse_gateway_from_line_linux(self):
        self.assertEqual(_parse_gateway_from_line("default via 192.168.1.1 dev eth0"), "192.168.1.1")
        self.assertEqual(_parse_gateway_from_line("10.0.0.1 via 172.16.0.1 src 10.0.0.5"), "172.16.0.1")

    def test_parse_gateway_from_line_ipv6(self):
        self.assertEqual(_parse_gateway_from_line("via fe80::1 dev eth0"), "fe80::1")

    def test_extract_gateway_line_finds_gateway(self):
        text = "route to: default\ngateway: 192.168.1.1\ninterface: en0\n"
        self.assertEqual(_extract_gateway_line(text), "192.168.1.1")

    def test_extract_gateway_line_finds_via(self):
        text = "10.0.0.1 via 172.16.0.1 dev eth0\n"
        self.assertEqual(_extract_gateway_line(text), "172.16.0.1")

    def test_extract_gateway_line_none_when_no_match(self):
        text = "no relevant data\n"
        self.assertIsNone(_extract_gateway_line(text))


class WifiInfoTests(unittest.TestCase):
    def test_collect_wifi_info_airport(self):
        runner = FakeRunner()
        airport_out = "     SSID: MyNetwork\n     BSSID: aa:bb:cc:dd:ee:ff\n     agrCtlRSSI: -50\n     agrCtlNoise: -90\n     lastTxRate: 866\n     channel: 36\n"
        runner.add(
            ["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-I"],
            stdout=airport_out
        )
        info = collect_wifi_info(runner)
        self.assertIsNotNone(info)
        self.assertEqual(info.ssid, "MyNetwork")  # type: ignore[union-attr]
        self.assertEqual(info.bssid, "aa:bb:cc:dd:ee:ff")  # type: ignore[union-attr]
        self.assertEqual(info.rssi, -50)  # type: ignore[union-attr]
        self.assertEqual(info.noise, -90)  # type: ignore[union-attr]
        self.assertEqual(info.tx_rate, 866.0)  # type: ignore[union-attr]
        self.assertEqual(info.channel, "36")  # type: ignore[union-attr]
        self.assertEqual(info.source, "airport")  # type: ignore[union-attr]

    def test_collect_wifi_info_nmcli(self):
        runner = FakeRunner()
        runner.add(
            ["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-I"],
            stdout="", returncode=1
        )
        # nmcli format: ACTIVE:SSID:BSSID:SIGNAL:RATE
        # The parser splits on ":" which will split the BSSID MAC address
        # Use a test format without MAC colons or use different field
        nmcli_out = "yes:TestSSID:aabbccddeeff:75:300 Mbit/s\n"
        runner.add(["nmcli", "-t", "-f", "ACTIVE,SSID,BSSID,SIGNAL,RATE", "dev", "wifi"], stdout=nmcli_out)
        info = collect_wifi_info(runner)
        self.assertIsNotNone(info)
        self.assertEqual(info.ssid, "TestSSID")  # type: ignore[union-attr]
        self.assertEqual(info.bssid, "aabbccddeeff")  # type: ignore[union-attr]
        self.assertEqual(info.tx_rate, 300.0)  # type: ignore[union-attr]
        self.assertEqual(info.source, "nmcli")  # type: ignore[union-attr]

    def test_collect_wifi_info_iwconfig(self):
        runner = FakeRunner()
        runner.add(
            ["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-I"],
            stdout="", returncode=1
        )
        runner.add(["nmcli", "-t", "-f", "ACTIVE,SSID,BSSID,SIGNAL,RATE", "dev", "wifi"], stdout="", returncode=1)
        iwconfig_out = 'wlan0     ESSID:"MyWiFi"\n          Access Point: aa:bb:cc:dd:ee:ff\n          Signal level:-65 dBm\n'
        runner.add(["iwconfig"], stdout=iwconfig_out)
        info = collect_wifi_info(runner)
        self.assertIsNotNone(info)
        self.assertEqual(info.ssid, "MyWiFi")  # type: ignore[union-attr]
        self.assertEqual(info.bssid, "aa:bb:cc:dd:ee:ff")  # type: ignore[union-attr]
        self.assertEqual(info.rssi, -65)  # type: ignore[union-attr]
        self.assertEqual(info.source, "iwconfig")  # type: ignore[union-attr]

    def test_collect_wifi_info_none_when_all_fail(self):
        runner = FakeRunner()
        runner.add(
            ["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-I"],
            stdout="", returncode=1
        )
        runner.add(["nmcli", "-t", "-f", "ACTIVE,SSID,BSSID,SIGNAL,RATE", "dev", "wifi"], stdout="", returncode=1)
        runner.add(["iwconfig"], stdout="no wireless extensions", returncode=1)
        info = collect_wifi_info(runner)
        self.assertIsNone(info)

    def test_parse_nmcli_inactive(self):
        text = "no:InactiveNet:aa:bb:cc:dd:ee:ff:50:100 Mbit/s\n"
        info = _parse_nmcli(text)
        self.assertIsNone(info)

    def test_parse_nmcli_malformed(self):
        text = "yes:incomplete\n"
        info = _parse_nmcli(text)
        self.assertIsNone(info)

    def test_parse_iwconfig_no_match(self):
        info = _parse_iwconfig("no wireless data\n")
        self.assertIsNone(info)

    def test_extract_iwconfig_field(self):
        text = 'ESSID:"TestNet" other fields'
        result = _extract_iwconfig_field(text, r'ESSID:"([^"]+)"')
        self.assertEqual(result, "TestNet")

    def test_extract_iwconfig_field_no_match(self):
        result = _extract_iwconfig_field("no match", r'ESSID:"([^"]+)"')
        self.assertIsNone(result)


class PingTests(unittest.TestCase):
    def test_ping_target_success(self):
        runner = FakeRunner()
        ping_out = (
            "PING 1.1.1.1 (1.1.1.1): 56 data bytes\n"
            "--- 1.1.1.1 ping statistics ---\n"
            "10 packets transmitted, 9 packets received, 10.0% packet loss\n"
            "round-trip min/avg/max/stddev = 5.0/10.0/20.0/3.0 ms\n"
        )
        runner.add(["ping", "-c", "10", "1.1.1.1"], stdout=ping_out)
        result = ping_target("test", "1.1.1.1", count=10, runner=runner, timeout=10.0)
        self.assertEqual(result.transmitted, 10)
        self.assertEqual(result.received, 9)
        self.assertEqual(result.loss_pct, 10.0)
        self.assertEqual(result.min_ms, 5.0)
        self.assertEqual(result.avg_ms, 10.0)
        self.assertEqual(result.max_ms, 20.0)
        self.assertIsNone(result.error)

    def test_ping_target_error(self):
        runner = FakeRunner()
        runner.add(["ping", "-c", "5", "invalid.host"], stdout="", stderr="cannot resolve", returncode=2)
        result = ping_target("test", "invalid.host", count=5, runner=runner, timeout=5.0)
        self.assertIsNotNone(result.error)
        self.assertIn("cannot resolve", result.error)

    def test_parse_ping_bytes_input(self):
        ping_bytes = b"10 packets transmitted, 8 packets received, 20.0% packet loss\n"
        transmitted, received, loss_pct, _, _, _ = _parse_ping(ping_bytes)
        self.assertEqual(transmitted, 10)
        self.assertEqual(received, 8)
        self.assertEqual(loss_pct, 20.0)


class DnsTests(unittest.TestCase):
    def test_dns_lookup_success(self):
        result = dns_lookup("google.com")
        self.assertTrue(result.success)
        self.assertGreater(len(result.addresses), 0)
        self.assertIsNotNone(result.elapsed_ms)

    def test_dns_lookup_invalid_host(self):
        result = dns_lookup("invalid-nonexistent-host-xyz-12345.com")
        self.assertFalse(result.success)
        self.assertEqual(len(result.addresses), 0)
        self.assertIsNotNone(result.error)


class TraceRouteTests(unittest.TestCase):
    def test_trace_route_success(self):
        runner = FakeRunner()
        trace_out = "traceroute to 1.1.1.1\n 1  192.168.1.1  2.0 ms\n 2  1.1.1.1  10.0 ms\n"
        runner.add(["traceroute", "-m", "12", "-q", "1", "1.1.1.1"], stdout=trace_out, returncode=0)
        result = trace_route("1.1.1.1", runner=runner, max_hops=12)
        self.assertTrue(result.success)
        self.assertEqual(len(result.lines), 3)

    def test_trace_route_fallback_tracepath(self):
        runner = FakeRunner()
        runner.add(["traceroute", "-m", "10", "-q", "1", "8.8.8.8"], stdout="", stderr="not found", returncode=127)
        tracepath_out = " 1:  192.168.1.1\n 2:  8.8.8.8\n"
        runner.add(["tracepath", "8.8.8.8"], stdout=tracepath_out, returncode=0)
        result = trace_route("8.8.8.8", runner=runner, max_hops=10)
        self.assertTrue(result.success)
        self.assertGreater(len(result.lines), 0)


class HttpProbeTests(unittest.TestCase):
    def test_http_probe_success(self):
        # http_probe uses lazy import, so we mock at the module level after import
        import sys
        mock_requests = unittest.mock.Mock()
        mock_resp = unittest.mock.Mock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = iter([b"x" * 1024])
        mock_resp.close = unittest.mock.Mock()
        mock_requests.get.return_value = mock_resp

        with patch.dict(sys.modules, {"requests": mock_requests}):
            result = http_probe("https://example.com")

        self.assertTrue(result.success)
        self.assertEqual(result.status, 200)
        self.assertIsNotNone(result.elapsed_ms)
        self.assertEqual(result.bytes_read, 1024)
        mock_resp.close.assert_called_once()

    def test_http_probe_failure(self):
        # Test the error handling path by mocking requests to raise an exception
        import sys
        mock_requests = unittest.mock.Mock()
        mock_requests.get.side_effect = Exception("Network error")

        with patch.dict(sys.modules, {"requests": mock_requests}):
            result = http_probe("https://example.com")

        self.assertFalse(result.success)
        self.assertIsNone(result.status)
        self.assertIsNotNone(result.error)


class CheckHealthTests(unittest.TestCase):
    def test_check_gateway_health_icmp_filtered(self):
        findings = _check_gateway_health(None, icmp_filtered=True)
        self.assertEqual(findings, [])

    def test_check_gateway_health_no_gateway(self):
        findings = _check_gateway_health(None, icmp_filtered=False)
        self.assertEqual(len(findings), 1)
        self.assertIn("not detected", findings[0])

    def test_check_gateway_health_high_loss(self):
        ping = PingResult(label="gateway", target="192.168.1.1", transmitted=10, received=5, loss_pct=50.0,
                          min_ms=1.0, avg_ms=2.0, max_ms=3.0)
        findings = _check_gateway_health(ping, icmp_filtered=False)
        self.assertEqual(len(findings), 1)
        self.assertIn("unstable", findings[0])

    def test_check_gateway_health_high_latency(self):
        ping = PingResult(label="gateway", target="192.168.1.1", transmitted=10, received=10, loss_pct=0.0,
                          min_ms=40.0, avg_ms=60.0, max_ms=80.0)
        findings = _check_gateway_health(ping, icmp_filtered=False)
        self.assertEqual(len(findings), 1)
        self.assertIn("latency is high", findings[0])

    def test_check_gateway_health_ok(self):
        ping = PingResult(label="gateway", target="192.168.1.1", transmitted=10, received=10, loss_pct=0.0,
                          min_ms=1.0, avg_ms=2.0, max_ms=3.0)
        findings = _check_gateway_health(ping, icmp_filtered=False)
        self.assertEqual(findings, [])

    def test_check_upstream_health_no_upstream(self):
        findings = _check_upstream_health([], None)
        self.assertEqual(findings, [])

    def test_check_upstream_health_high_loss_gateway_ok(self):
        gateway = PingResult(label="gateway", target="192.168.1.1", transmitted=10, received=10, loss_pct=2.0,
                             min_ms=1.0, avg_ms=2.0, max_ms=3.0)
        upstream = [PingResult(label="1.1.1.1", target="1.1.1.1", transmitted=10, received=5, loss_pct=50.0,
                               min_ms=10.0, avg_ms=20.0, max_ms=30.0)]
        findings = _check_upstream_health(upstream, gateway)
        self.assertEqual(len(findings), 1)
        self.assertIn("Backhaul", findings[0])

    def test_check_upstream_health_high_latency_gateway_ok(self):
        gateway = PingResult(label="gateway", target="192.168.1.1", transmitted=10, received=10, loss_pct=0.0,
                             min_ms=1.0, avg_ms=2.0, max_ms=3.0)
        upstream = [PingResult(label="8.8.8.8", target="8.8.8.8", transmitted=10, received=10, loss_pct=0.0,
                               min_ms=100.0, avg_ms=150.0, max_ms=200.0)]
        findings = _check_upstream_health(upstream, gateway)
        self.assertEqual(len(findings), 1)
        self.assertIn("High internet latency", findings[0])

    def test_check_dns_health_error(self):
        dns = DnsResult(host="example.com", success=False, addresses=[], elapsed_ms=None, error="timeout")
        findings = _check_dns_health(dns)
        self.assertEqual(len(findings), 1)
        self.assertIn("failed", findings[0])

    def test_check_dns_health_slow(self):
        dns = DnsResult(host="example.com", success=True, addresses=["1.2.3.4"], elapsed_ms=250.0)
        findings = _check_dns_health(dns)
        self.assertEqual(len(findings), 1)
        self.assertIn("slow", findings[0])

    def test_check_dns_health_ok(self):
        dns = DnsResult(host="example.com", success=True, addresses=["1.2.3.4"], elapsed_ms=5.0)
        findings = _check_dns_health(dns)
        self.assertEqual(findings, [])

    def test_check_http_health_none(self):
        findings = _check_http_health(None)
        self.assertEqual(findings, [])

    def test_check_http_health_failure(self):
        http = HttpResult(url="https://example.com", success=False, status=None, elapsed_ms=None, bytes_read=None, error="timeout")
        findings = _check_http_health(http)
        self.assertEqual(len(findings), 1)
        self.assertIn("failed", findings[0])

    def test_check_http_health_slow(self):
        http = HttpResult(url="https://example.com", success=True, status=200, elapsed_ms=1500.0, bytes_read=1024)
        findings = _check_http_health(http)
        self.assertEqual(len(findings), 1)
        self.assertIn("slow", findings[0])

    def test_check_http_health_ok(self):
        http = HttpResult(url="https://example.com", success=True, status=200, elapsed_ms=100.0, bytes_read=1024)
        findings = _check_http_health(http)
        self.assertEqual(findings, [])


class DeriveFindingsTests(unittest.TestCase):
    def test_derive_findings_icmp_filtered(self):
        findings = derive_findings(
            gateway="192.168.1.1",
            ping_results=[],
            icmp_filtered=True,
            dns=DnsResult(host="example.com", success=True, addresses=["1.2.3.4"], elapsed_ms=5.0),
            trace=None,
            http=None,
        )
        self.assertTrue(any("ICMP" in f and "filtered" in f for f in findings))

    def test_derive_findings_all_ok(self):
        gateway_ping = PingResult(label="gateway", target="192.168.1.1", transmitted=10, received=10, loss_pct=0.0,
                                   min_ms=1.0, avg_ms=2.0, max_ms=3.0)
        findings = derive_findings(
            gateway="192.168.1.1",
            ping_results=[gateway_ping],
            icmp_filtered=False,
            dns=DnsResult(host="example.com", success=True, addresses=["1.2.3.4"], elapsed_ms=5.0),
            trace=None,
            http=None,
        )
        self.assertTrue(any("healthy" in f for f in findings))


class DetectIcmpFilteredTests(unittest.TestCase):
    def test_detect_icmp_filtered_no_survey(self):
        result = _detect_icmp_filtered([], None)
        self.assertFalse(result)

    def test_detect_icmp_filtered_gateway_high_loss_upstream_ok(self):
        survey = [
            PingResult(label="survey-gateway", target="192.168.1.1", transmitted=4, received=0, loss_pct=100.0,
                       min_ms=None, avg_ms=None, max_ms=None),
            PingResult(label="survey-1.1.1.1", target="1.1.1.1", transmitted=4, received=3, loss_pct=25.0,
                       min_ms=10.0, avg_ms=20.0, max_ms=30.0),
        ]
        result = _detect_icmp_filtered(survey, None)
        self.assertTrue(result)

    def test_detect_icmp_filtered_gateway_high_loss_trace_success(self):
        survey = [
            PingResult(label="survey-gateway", target="192.168.1.1", transmitted=4, received=0, loss_pct=100.0,
                       min_ms=None, avg_ms=None, max_ms=None),
        ]
        trace = TraceResult(target="1.1.1.1", success=True, lines=["hop1", "hop2"])
        result = _detect_icmp_filtered(survey, trace)
        self.assertTrue(result)

    def test_detect_icmp_filtered_not_filtered(self):
        survey = [
            PingResult(label="survey-gateway", target="192.168.1.1", transmitted=4, received=4, loss_pct=0.0,
                       min_ms=1.0, avg_ms=2.0, max_ms=3.0),
        ]
        result = _detect_icmp_filtered(survey, None)
        self.assertFalse(result)


class ScorePingTests(unittest.TestCase):
    def test_score_ping_good(self):
        ping = PingResult(label="test", target="1.1.1.1", transmitted=10, received=10, loss_pct=0.0,
                          min_ms=5.0, avg_ms=10.0, max_ms=15.0)
        self.assertEqual(_score_ping(ping), 0)

    def test_score_ping_poor_loss(self):
        ping = PingResult(label="test", target="1.1.1.1", transmitted=10, received=8, loss_pct=20.0,
                          min_ms=5.0, avg_ms=10.0, max_ms=15.0)
        self.assertEqual(_score_ping(ping), 1)

    def test_score_ping_poor_latency(self):
        ping = PingResult(label="test", target="1.1.1.1", transmitted=10, received=10, loss_pct=5.0,
                          min_ms=150.0, avg_ms=220.0, max_ms=300.0)
        self.assertEqual(_score_ping(ping), 1)

    def test_score_ping_bad(self):
        ping = PingResult(label="test", target="1.1.1.1", transmitted=10, received=5, loss_pct=50.0,
                          min_ms=None, avg_ms=None, max_ms=None)
        self.assertEqual(_score_ping(ping), 2)

    def test_score_ping_bad_none_loss(self):
        ping = PingResult(label="test", target="1.1.1.1", transmitted=0, received=0, loss_pct=None,
                          min_ms=None, avg_ms=None, max_ms=None)
        self.assertEqual(_score_ping(ping), 2)


class ComputeConditionTests(unittest.TestCase):
    def test_compute_condition_icmp_filtered(self):
        condition = compute_condition(ping_results=[], icmp_filtered=True, http=None,
                                       dns=DnsResult(host="example.com", success=True, addresses=["1.2.3.4"], elapsed_ms=5.0))
        self.assertEqual(condition, "n/a (icmp filtered)")

    def test_compute_condition_good(self):
        ping = PingResult(label="gateway", target="192.168.1.1", transmitted=10, received=10, loss_pct=0.0,
                          min_ms=1.0, avg_ms=2.0, max_ms=3.0)
        condition = compute_condition(ping_results=[ping], icmp_filtered=False, http=None,
                                       dns=DnsResult(host="example.com", success=True, addresses=["1.2.3.4"], elapsed_ms=5.0))
        self.assertEqual(condition, "good")

    def test_compute_condition_poor_dns(self):
        ping = PingResult(label="gateway", target="192.168.1.1", transmitted=10, received=10, loss_pct=0.0,
                          min_ms=1.0, avg_ms=2.0, max_ms=3.0)
        dns = DnsResult(host="example.com", success=True, addresses=["1.2.3.4"], elapsed_ms=500.0)
        condition = compute_condition(ping_results=[ping], icmp_filtered=False, http=None, dns=dns)
        self.assertEqual(condition, "poor")

    def test_compute_condition_poor_http(self):
        ping = PingResult(label="gateway", target="192.168.1.1", transmitted=10, received=10, loss_pct=0.0,
                          min_ms=1.0, avg_ms=2.0, max_ms=3.0)
        http = HttpResult(url="https://example.com", success=True, status=200, elapsed_ms=1600.0, bytes_read=1024)
        condition = compute_condition(ping_results=[ping], icmp_filtered=False, http=http,
                                       dns=DnsResult(host="example.com", success=True, addresses=["1.2.3.4"], elapsed_ms=5.0))
        self.assertEqual(condition, "poor")

    def test_compute_condition_bad(self):
        ping = PingResult(label="gateway", target="192.168.1.1", transmitted=10, received=3, loss_pct=70.0,
                          min_ms=1.0, avg_ms=2.0, max_ms=3.0)
        condition = compute_condition(ping_results=[ping], icmp_filtered=False, http=None,
                                       dns=DnsResult(host="example.com", success=True, addresses=["1.2.3.4"], elapsed_ms=5.0))
        self.assertEqual(condition, "bad")


class ReportToDictTests(unittest.TestCase):
    def test_report_to_dict(self):
        report = Report(
            timestamp="2024-01-01 00:00:00",
            gateway="192.168.1.1",
            wifi=None,
            ping_results=[],
            dns=DnsResult(host="example.com", success=True, addresses=["1.2.3.4"], elapsed_ms=5.0),
            trace=None,
            http=None,
            findings=["all good"],
            condition="good",
        )
        result = report_to_dict(report)
        self.assertEqual(result["timestamp"], "2024-01-01 00:00:00")
        self.assertEqual(result["gateway"], "192.168.1.1")
        self.assertEqual(result["condition"], "good")
        self.assertEqual(result["dns"]["host"], "example.com")


class FormatTests(unittest.TestCase):
    def test_format_wifi(self):
        info = WifiInfo(ssid="TestNet", bssid="aa:bb:cc:dd:ee:ff", rssi=-60, noise=-90, tx_rate=300.0, channel="36", source="airport")
        text = format_wifi(info)
        self.assertIn("TestNet", text)
        self.assertIn("aa:bb:cc:dd:ee:ff", text)
        self.assertIn("-60", text)
        self.assertIn("300", text)

    def test_format_ping(self):
        ping = PingResult(label="test", target="1.1.1.1", transmitted=10, received=9, loss_pct=10.0,
                          min_ms=5.0, avg_ms=10.0, max_ms=15.0)
        text = format_ping(ping)
        self.assertIn("test", text)
        self.assertIn("1.1.1.1", text)
        self.assertIn("10.0%", text)
        self.assertIn("10.0", text)

    def test_format_ping_with_error(self):
        ping = PingResult(label="test", target="1.1.1.1", transmitted=0, received=0, loss_pct=None,
                          min_ms=None, avg_ms=None, max_ms=None, error="timeout")
        text = format_ping(ping)
        self.assertIn("timeout", text)

    def test_format_dns_success(self):
        dns = DnsResult(host="example.com", success=True, addresses=["1.2.3.4", "5.6.7.8"], elapsed_ms=5.0)
        text = format_dns(dns)
        self.assertIn("example.com", text)
        self.assertIn("1.2.3.4", text)
        self.assertIn("5.0", text)

    def test_format_dns_failure(self):
        dns = DnsResult(host="example.com", success=False, addresses=[], elapsed_ms=None, error="timeout")
        text = format_dns(dns)
        self.assertIn("FAILED", text)
        self.assertIn("timeout", text)

    def test_format_http_success(self):
        http = HttpResult(url="https://example.com", success=True, status=200, elapsed_ms=100.0, bytes_read=2048)
        text = format_http(http)
        self.assertIn("200", text)
        self.assertIn("100", text)
        self.assertIn("2048", text)

    def test_format_http_failure(self):
        http = HttpResult(url="https://example.com", success=False, status=None, elapsed_ms=None, bytes_read=None, error="connection refused")
        text = format_http(http)
        self.assertIn("failed", text)
        self.assertIn("connection refused", text)


class RenderReportTests(unittest.TestCase):
    def test_render_report_basic(self):
        report = Report(
            timestamp="2024-01-01 00:00:00",
            gateway="192.168.1.1",
            wifi=None,
            ping_results=[],
            dns=DnsResult(host="example.com", success=True, addresses=["1.2.3.4"], elapsed_ms=5.0),
            trace=None,
            http=None,
            findings=["all good"],
            condition="good",
        )
        text = render_report(report)
        self.assertIn("Wi-Fi Doctor", text)
        self.assertIn("192.168.1.1", text)
        self.assertIn("good", text)
        self.assertIn("Findings:", text)

    def test_render_report_with_wifi(self):
        wifi = WifiInfo(ssid="TestNet", bssid="aa:bb:cc:dd:ee:ff", rssi=-60, noise=-90, tx_rate=300.0, channel="36", source="airport")
        report = Report(
            timestamp="2024-01-01 00:00:00",
            gateway="192.168.1.1",
            wifi=wifi,
            ping_results=[],
            dns=DnsResult(host="example.com", success=True, addresses=["1.2.3.4"], elapsed_ms=5.0),
            trace=None,
            http=None,
            findings=["all good"],
            condition="good",
        )
        text = render_report(report)
        self.assertIn("Wi-Fi:", text)
        self.assertIn("TestNet", text)

    def test_render_report_with_trace(self):
        trace = TraceResult(target="1.1.1.1", success=True, lines=["hop1", "hop2", "hop3"])
        report = Report(
            timestamp="2024-01-01 00:00:00",
            gateway="192.168.1.1",
            wifi=None,
            ping_results=[],
            dns=DnsResult(host="example.com", success=True, addresses=["1.2.3.4"], elapsed_ms=5.0),
            trace=trace,
            http=None,
            findings=["all good"],
            condition="good",
        )
        text = render_report(report)
        self.assertIn("Trace", text)
        self.assertIn("1.1.1.1", text)
        self.assertIn("hop1", text)

    def test_render_report_with_http(self):
        http = HttpResult(url="https://example.com", success=True, status=200, elapsed_ms=100.0, bytes_read=2048)
        report = Report(
            timestamp="2024-01-01 00:00:00",
            gateway="192.168.1.1",
            wifi=None,
            ping_results=[],
            dns=DnsResult(host="example.com", success=True, addresses=["1.2.3.4"], elapsed_ms=5.0),
            trace=None,
            http=http,
            findings=["all good"],
            condition="good",
        )
        text = render_report(report)
        self.assertIn("HTTPS smoke", text)


class UtilityTests(unittest.TestCase):
    def test_safe_int_valid(self):
        self.assertEqual(_safe_int("42"), 42)
        self.assertEqual(_safe_int("-10"), -10)

    def test_safe_int_invalid(self):
        self.assertIsNone(_safe_int("not_a_number"))
        self.assertIsNone(_safe_int(None))

    def test_safe_float_valid(self):
        self.assertEqual(_safe_float("3.14"), 3.14)
        self.assertEqual(_safe_float("-2.5"), -2.5)

    def test_safe_float_invalid(self):
        self.assertIsNone(_safe_float("not_a_number"))
        self.assertIsNone(_safe_float(None))


class RunDiagnosisIntegrationTests(unittest.TestCase):
    def test_run_diagnosis_with_defaults(self):
        # Test run_diagnosis with minimal config, using default runner/resolver/http_probe
        runner = FakeRunner()
        runner.add(["route", "-n", "get", "default"], stdout="gateway: 192.168.1.1\n")
        runner.add(
            ["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-I"],
            stdout=""
        )
        runner.add(["nmcli", "-t", "-f", "ACTIVE,SSID,BSSID,SIGNAL,RATE", "dev", "wifi"], stdout="")
        runner.add(["iwconfig"], stdout="")

        # Survey pings (count=4)
        for label in ["survey-gateway", "survey-1.1.1.1"]:
            target = "192.168.1.1" if label == "survey-gateway" else "1.1.1.1"
            runner.add(["ping", "-c", "4", target], stdout="4 packets transmitted, 4 packets received, 0.0% packet loss\n")

        # Main pings (count=12)
        for target in ["192.168.1.1", "1.1.1.1"]:
            runner.add(["ping", "-c", "12", target], stdout="12 packets transmitted, 12 packets received, 0.0% packet loss\nround-trip min/avg/max/stddev = 1.0/2.0/3.0/0.5 ms\n")

        runner.add(["traceroute", "-m", "12", "-q", "1", "1.1.1.1"], stdout="traceroute to 1.1.1.1\n")

        def mock_resolver(host):
            return DnsResult(host=host, success=True, addresses=["1.2.3.4"], elapsed_ms=5.0)

        def mock_http_probe(url):
            return HttpResult(url=url, success=True, status=200, elapsed_ms=100.0, bytes_read=1024)

        config = DiagnoseConfig(ping_targets=["1.1.1.1"], ping_count=12, run_survey=True, survey_count=4)
        report = run_diagnosis(config, runner=runner, resolver=mock_resolver, http_probe_fn=mock_http_probe)

        self.assertIsNotNone(report)
        self.assertEqual(report.gateway, "192.168.1.1")
        self.assertGreaterEqual(len(report.ping_results), 1)
        self.assertIsNotNone(report.dns)
        self.assertTrue(report.dns.success)

    def test_run_diagnosis_without_wifi(self):
        runner = FakeRunner()
        runner.add(["route", "-n", "get", "default"], stdout="gateway: 192.168.1.1\n")
        runner.add(["ping", "-c", "5", "192.168.1.1"], stdout="5 packets transmitted, 5 packets received, 0.0% packet loss\n")

        def mock_resolver(host):
            return DnsResult(host=host, success=True, addresses=["1.2.3.4"], elapsed_ms=5.0)

        config = DiagnoseConfig(ping_targets=[], ping_count=5, include_wifi=False, include_trace=False, include_http=False, run_survey=False)
        report = run_diagnosis(config, runner=runner, resolver=mock_resolver)

        self.assertIsNone(report.wifi)
        self.assertIsNone(report.trace)
        self.assertIsNone(report.http)

    def test_run_diagnosis_without_http_url(self):
        runner = FakeRunner()
        runner.add(["route", "-n", "get", "default"], stdout="gateway: 192.168.1.1\n")
        runner.add(["ping", "-c", "5", "192.168.1.1"], stdout="5 packets transmitted, 5 packets received, 0.0% packet loss\n")

        def mock_resolver(host):
            return DnsResult(host=host, success=True, addresses=["1.2.3.4"], elapsed_ms=5.0)

        config = DiagnoseConfig(ping_targets=[], ping_count=5, include_wifi=False, include_trace=False, include_http=True, http_url=None, run_survey=False)
        report = run_diagnosis(config, runner=runner, resolver=mock_resolver)

        self.assertIsNone(report.http)


if __name__ == "__main__":
    unittest.main()
