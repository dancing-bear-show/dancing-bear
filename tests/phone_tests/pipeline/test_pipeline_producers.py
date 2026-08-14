"""Tests for phone pipeline producer classes and standalone helper functions."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from core.pipeline import ResultEnvelope


class TestBaseProducer(unittest.TestCase):
    """Tests for BaseProducer.produce() error handling branches."""

    def test_produce_error_with_message(self):
        from phone.pipeline_export import ExportProducer
        env = ResultEnvelope(status="error", payload=None, diagnostics={"message": "something went wrong"})
        io.StringIO()
        with patch("sys.stderr", new_callable=io.StringIO):
            ExportProducer().produce(env)
        # message should go to stderr - we can't easily capture it but ensure no exception

    def test_produce_error_without_message(self):
        from phone.pipeline_export import ExportProducer
        env = ResultEnvelope(status="error", payload=None, diagnostics={})
        # Should not raise
        ExportProducer().produce(env)

    def test_produce_error_no_diagnostics(self):
        from phone.pipeline_export import ExportProducer
        env = ResultEnvelope(status="error", payload=None, diagnostics=None)
        # Should not raise
        ExportProducer().produce(env)

    def test_produce_success_none_payload(self):
        from phone.pipeline_export import ExportProducer
        env = ResultEnvelope(status="success", payload=None, diagnostics=None)
        # Should not call _produce_success since payload is None
        ExportProducer().produce(env)


class TestAnalyzeProducerBranches(unittest.TestCase):
    """Test AnalyzeProducer output branches for dock, pages, folders, duplicates, observations."""

    def test_analyze_producer_with_dock_apps(self):
        from phone.pipeline_export import AnalyzeProducer, AnalyzeResult
        metrics = {
            "dock_count": 2,
            "dock": ["app1", "app2"],
            "pages_count": 1,
            "pages": [{"page": 1, "root_apps": 3, "folders": 1, "items_total": 7}],
            "totals": {"folders": 1},
            "folders": [{"name": "Work", "page": 1, "app_count": 3}],
            "duplicates": ["app1"],
            "observations": ["App count looks good"],
        }
        payload = AnalyzeResult(metrics=metrics, format="text")
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            AnalyzeProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("app1, app2", output)
        self.assertIn("Page 1:", output)
        self.assertIn("Work", output)
        self.assertIn("Duplicates", output)
        self.assertIn("app1", output)
        self.assertIn("Observations", output)
        self.assertIn("App count looks good", output)


class TestManifestFromDeviceProducer(unittest.TestCase):
    def test_produce_success_with_export_document_and_out(self):
        from phone.pipeline_plan import ManifestFromDeviceProducer, ManifestFromDeviceResult
        with tempfile.TemporaryDirectory() as tmp:  # nosec B108 - test-only temp file, not a security concern
            export_path = Path(tmp) / "export.yaml"
            manifest_path = Path(tmp) / "manifest.yaml"
            payload = ManifestFromDeviceResult(
                manifest={"meta": {"name": "test"}},
                out_path=manifest_path,
                export_out=export_path,
                export_document={"dock": [], "pages": []},
            )
            env = ResultEnvelope(status="success", payload=payload)
            buf = io.StringIO()
            with redirect_stdout(buf):
                ManifestFromDeviceProducer().produce(env)
            self.assertTrue(manifest_path.exists())
            self.assertTrue(export_path.exists())
            self.assertIn("manifest", buf.getvalue().lower())

    def test_produce_success_no_export_document(self):
        from phone.pipeline_plan import ManifestFromDeviceProducer, ManifestFromDeviceResult
        with tempfile.TemporaryDirectory() as tmp:  # nosec B108 - test-only temp file, not a security concern
            manifest_path = Path(tmp) / "manifest.yaml"
            payload = ManifestFromDeviceResult(
                manifest={"meta": {"name": "test"}},
                out_path=manifest_path,
                export_out=None,
                export_document=None,
            )
            env = ResultEnvelope(status="success", payload=payload)
            buf = io.StringIO()
            with redirect_stdout(buf):
                ManifestFromDeviceProducer().produce(env)
            self.assertTrue(manifest_path.exists())


class TestManifestInstallProducer(unittest.TestCase):
    def test_dry_run_skips_install(self):
        from phone.pipeline_plan import ManifestInstallProducer, ManifestInstallResult
        with tempfile.TemporaryDirectory() as tmp:  # nosec B108 - test-only temp file, not a security concern
            profile_path = Path(tmp) / "test.mobileconfig"
            payload = ManifestInstallResult(
                profile_path=profile_path,
                profile_bytes=b"fake-profile-data",
                dry_run=True,
                install_cmd=None,
            )
            env = ResultEnvelope(status="success", payload=payload)
            buf = io.StringIO()
            with redirect_stdout(buf):
                ManifestInstallProducer().produce(env)
            self.assertTrue(profile_path.exists())
            self.assertIn("Dry-run", buf.getvalue())

    def test_install_with_cmd(self):
        from phone.pipeline_plan import ManifestInstallProducer, ManifestInstallResult
        with tempfile.TemporaryDirectory() as tmp:  # nosec B108 - test-only temp file, not a security concern
            profile_path = Path(tmp) / "test.mobileconfig"
            payload = ManifestInstallResult(
                profile_path=profile_path,
                profile_bytes=b"fake-profile-data",
                dry_run=False,
                install_cmd=["echo", "installing"],
            )
            env = ResultEnvelope(status="success", payload=payload)
            buf = io.StringIO()
            with redirect_stdout(buf):
                with patch("subprocess.call", return_value=0) as mock_call:
                    ManifestInstallProducer().produce(env)
            mock_call.assert_called_once()
            self.assertIn("Installing via", buf.getvalue())

    def test_install_cmd_not_found(self):
        from phone.pipeline_plan import ManifestInstallProducer, ManifestInstallResult
        with tempfile.TemporaryDirectory() as tmp:  # nosec B108 - test-only temp file, not a security concern
            profile_path = Path(tmp) / "test.mobileconfig"
            payload = ManifestInstallResult(
                profile_path=profile_path,
                profile_bytes=b"fake-profile-data",
                dry_run=False,
                install_cmd=["/nonexistent/ios-install-profile", "--profile", str(profile_path)],
            )
            env = ResultEnvelope(status="success", payload=payload)
            with patch("subprocess.call", side_effect=FileNotFoundError("not found")):
                with patch("sys.stderr", new_callable=io.StringIO):
                    ManifestInstallProducer().produce(env)

    def test_no_install_cmd(self):
        from phone.pipeline_plan import ManifestInstallProducer, ManifestInstallResult
        with tempfile.TemporaryDirectory() as tmp:  # nosec B108 - test-only temp file, not a security concern
            profile_path = Path(tmp) / "test.mobileconfig"
            payload = ManifestInstallResult(
                profile_path=profile_path,
                profile_bytes=b"fake-profile-data",
                dry_run=False,
                install_cmd=None,
            )
            env = ResultEnvelope(status="success", payload=payload)
            buf = io.StringIO()
            with redirect_stdout(buf):
                ManifestInstallProducer().produce(env)
            self.assertIn("Built profile", buf.getvalue())
            self.assertNotIn("Installing", buf.getvalue())


class TestIdentityVerifyProducerBranches(unittest.TestCase):
    def test_verify_producer_no_match(self):
        from phone.pipeline_plan import IdentityVerifyProducer, IdentityVerifyResult
        payload = IdentityVerifyResult(
            p12_path="/path/to/cert.p12",
            cert_subject="CN=OtherOrg",
            cert_issuer="CN=SomeIssuer",
            udid=None,
            supervised=None,
            expected_org="TestOrg",
            org_match=False,
        )
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            IdentityVerifyProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("NO MATCH", output)
        self.assertIn("(not provided)", output)
        self.assertIn("(unknown)", output)

    def test_verify_producer_no_expected_org(self):
        from phone.pipeline_plan import IdentityVerifyProducer, IdentityVerifyResult
        payload = IdentityVerifyResult(
            p12_path="/path/to/cert.p12",
            cert_subject="CN=TestOrg",
            cert_issuer="CN=TestIssuer",
            udid="test-udid",
            supervised="true",
            expected_org=None,
            org_match=None,
        )
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            IdentityVerifyProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("Identity Verification Summary", output)
        self.assertNotIn("expected org", output.lower())


class TestReadLinesFile(unittest.TestCase):
    def test_reads_non_empty_non_comment_lines(self):
        from phone.helpers import read_lines_file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:  # nosec B108 - test-only temp file, not a security concern
            f.write("# comment\n")
            f.write("app1\n")
            f.write("\n")
            f.write("app2\n")
            f.write("# another comment\n")
            path = f.name
        result = read_lines_file(path)
        self.assertEqual(result, ["app1", "app2"])

    def test_returns_empty_for_none(self):
        from phone.helpers import read_lines_file
        self.assertEqual(read_lines_file(None), [])

    def test_returns_empty_for_nonexistent_file(self):
        from phone.helpers import read_lines_file
        self.assertEqual(read_lines_file("/nonexistent/path.txt"), [])

    def test_empty_file_returns_empty(self):
        from phone.helpers import read_lines_file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:  # nosec B108 - test-only temp file, not a security concern
            path = f.name
        result = read_lines_file(path)
        self.assertEqual(result, [])


class TestReadLinesFileError(unittest.TestCase):
    def test_read_error_returns_empty(self):
        from phone.helpers import read_lines_file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:  # nosec B108 - test-only temp file, not a security concern
            path = f.name
        with patch("pathlib.Path.read_text", side_effect=PermissionError("denied")):
            result = read_lines_file(path)
        self.assertEqual(result, [])


class TestParsePingRttLine(unittest.TestCase):
    def test_parses_rtt_stats(self):
        from wifi.diagnostics_probes import _parse_ping
        text = "5 packets transmitted, 5 packets received, 0.0% packet loss\nround-trip min/avg/max/stddev = 1.2/2.3/3.4/0.5 ms"
        _tx, _rx, _loss, mn, avg, mx = _parse_ping(text)
        self.assertAlmostEqual(mn, 1.2)
        self.assertAlmostEqual(avg, 2.3)
        self.assertAlmostEqual(mx, 3.4)


if __name__ == "__main__":
    unittest.main()
