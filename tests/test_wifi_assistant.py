import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from wifi_assistant import cli
from wifi_assistant.diagnostics import (
    CommandResult,
    CommandRunner,
    DiagnoseConfig,
    DnsResult,
    HttpResult,
    Report,
    render_report,
    run_diagnosis,
)


class FakeRunner(CommandRunner):
    def __init__(self):
        self._results = {}

    def add(self, cmd, stdout="", stderr="", returncode=0):
        self._results[tuple(cmd)] = CommandResult(stdout=stdout, stderr=stderr, returncode=returncode)

    def run(self, cmd, timeout=None):
        return self._results.get(tuple(cmd), CommandResult(stdout="", stderr="missing", returncode=127))


class WifiAssistantTests(unittest.TestCase):
    def test_run_diagnosis_formats_report(self):
        runner = FakeRunner()
        runner.add(
            ["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-I"],
            stdout="     SSID: TestNet\n     BSSID: aa:bb:cc:dd:ee:ff\n     agrCtlRSSI: -60\n     agrCtlNoise: -95\n     lastTxRate: 300\n     channel: 36\n",
        )
        runner.add(["route", "-n", "get", "default"], stdout="route to: default\ngateway: 192.168.1.1\n")
        runner.add(
            ["ping", "-c", "5", "192.168.1.1"],
            stdout=(
                "PING 192.168.1.1 (192.168.1.1): 56 data bytes\n"
                "--- 192.168.1.1 ping statistics ---\n"
                "5 packets transmitted, 5 packets received, 0.0% packet loss\n"
                "round-trip min/avg/max/stddev = 2.0/3.0/5.0/0.5 ms\n"
            ),
        )
        runner.add(
            ["ping", "-c", "5", "1.1.1.1"],
            stdout=(
                "PING 1.1.1.1 (1.1.1.1): 56 data bytes\n"
                "--- 1.1.1.1 ping statistics ---\n"
                "5 packets transmitted, 4 packets received, 20.0% packet loss\n"
                "round-trip min/avg/max/stddev = 15.0/28.0/52.0/5.0 ms\n"
            ),
        )
        runner.add(
            ["ping", "-c", "5", "8.8.8.8"],
            stdout=(
                "PING 8.8.8.8 (8.8.8.8): 56 data bytes\n"
                "--- 8.8.8.8 ping statistics ---\n"
                "5 packets transmitted, 5 packets received, 0.0% packet loss\n"
                "round-trip min/avg/max/stddev = 30.0/40.0/55.0/5.0 ms\n"
            ),
        )
        runner.add(
            ["traceroute", "-m", "12", "-q", "1", "1.1.1.1"],
            stdout="traceroute to 1.1.1.1\n 1 192.168.1.1 2.0 ms\n 2 10.0.0.1 12.0 ms\n 3 1.1.1.1 20.0 ms\n",
        )

        resolver = lambda host: DnsResult(host=host, success=True, addresses=["142.0.0.1"], elapsed_ms=8.5)
        http_probe = lambda url: HttpResult(url=url, success=True, status=200, elapsed_ms=180.0, bytes_read=2048)
        cfg = DiagnoseConfig(
            ping_targets=["1.1.1.1", "8.8.8.8"],
            ping_count=5,
            dns_host="example.com",
            trace_max_hops=12,
        )
        report = run_diagnosis(cfg, runner=runner, resolver=resolver, http_probe_fn=http_probe)
        text = render_report(report)

        self.assertIn("Wi-Fi:", text)
        self.assertIn("Ping sweep", text)
        self.assertTrue(any("Backhaul" in finding for finding in report.findings))
        self.assertIn("gateway (192.168.1.1)", text)
        self.assertIn("example.com", text)

    def test_cli_json_output_and_write(self):
        report = Report(
            timestamp="now",
            gateway="192.168.0.1",
            wifi=None,
            ping_results=[],
            dns=DnsResult(host="example.com", success=True, addresses=["1.2.3.4"], elapsed_ms=5.0),
            trace=None,
            http=None,
            findings=["ok"],
        )
        with patch("wifi_assistant.cli.run_diagnosis", return_value=report):
            with tempfile.TemporaryDirectory() as tmpdir:
                out_path = Path(tmpdir) / "diag.json"
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = cli.main(["diagnose", "--json", "--out", str(out_path)])
                self.assertEqual(rc, 0)
                data = json.loads(out_path.read_text())
                self.assertEqual(data["gateway"], "192.168.0.1")
                self.assertIn('"gateway": "192.168.0.1"', buf.getvalue())

    def test_icmp_filtered_survey_surfaces_hint(self):
        runner = FakeRunner()
        runner.add(["route", "-n", "get", "default"], stdout="gateway: 10.0.0.1\n")
        loss_out = (
            "3 packets transmitted, 0 packets received, 100.0% packet loss\n"
        )
        # survey (4) and main ping (12) for gateway and target
        for count in ("4", "12"):
            runner.add(["ping", "-c", count, "10.0.0.1"], stdout=loss_out)
            runner.add(["ping", "-c", count, "1.1.1.1"], stdout=loss_out)
        runner.add(
            ["traceroute", "-m", "12", "-q", "1", "1.1.1.1"],
            stdout="traceroute to 1.1.1.1\n 1 10.0.0.1 2.0 ms\n 2 1.1.1.1 10.0 ms\n",
            returncode=0,
        )
        cfg = DiagnoseConfig(ping_targets=["1.1.1.1"], ping_count=12)
        resolver = lambda host: DnsResult(host=host, success=True, addresses=["1.2.3.4"], elapsed_ms=5.0)
        http_probe = lambda url: HttpResult(url=url, success=True, status=200, elapsed_ms=100.0, bytes_read=1024)
        report = run_diagnosis(cfg, runner=runner, resolver=resolver, http_probe_fn=http_probe)
        self.assertTrue(any("ICMP" in f and "filtered" in f for f in report.findings), report.findings)
        self.assertEqual(report.condition, "n/a (icmp filtered)")


if __name__ == "__main__":
    unittest.main()
