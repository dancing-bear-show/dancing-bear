import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from core.pipeline import ResultEnvelope
from phone.layout import NormalizedLayout
from phone.helpers import LayoutLoadError
from phone.pipeline import (
    AnalyzeProducer,
    AnalyzeProcessor,
    AnalyzeResult,
    AnalyzeRequest,
    AnalyzeRequestConsumer,
    ChecklistProducer,
    ChecklistProcessor,
    ChecklistResult,
    ChecklistRequest,
    ChecklistRequestConsumer,
    ExportDeviceProducer,
    ExportDeviceProcessor,
    ExportDeviceResult,
    ExportDeviceRequest,
    ExportDeviceRequestConsumer,
    ExportProducer,
    ExportProcessor,
    ExportResult,
    ExportRequest,
    ExportRequestConsumer,
    IconmapProducer,
    IconmapProcessor,
    IconmapResult,
    IconmapRequest,
    IconmapRequestConsumer,
    IdentityVerifyProducer,
    IdentityVerifyProcessor,
    IdentityVerifyResult,
    IdentityVerifyRequest,
    IdentityVerifyRequestConsumer,
    ManifestFromDeviceProcessor,
    ManifestFromDeviceRequest,
    ManifestFromDeviceRequestConsumer,
    ManifestFromExportProducer,
    ManifestFromExportProcessor,
    ManifestFromExportResult,
    ManifestFromExportRequest,
    ManifestFromExportRequestConsumer,
    PlanProducer,
    PlanProcessor,
    PlanResult,
    PlanRequest,
    PlanRequestConsumer,
    PruneProducer,
    PruneProcessor,
    PruneResult,
    PruneRequest,
    PruneRequestConsumer,
    UnusedProducer,
    UnusedProcessor,
    UnusedResult,
    UnusedRequest,
    UnusedRequestConsumer,
)


class PhonePipelineTests(TestCase):
    def setUp(self):
        self.layout = NormalizedLayout(dock=["app1"], pages=[[{"kind": "app", "id": "app2"}]])

    def test_export_processor_success(self):
        with patch("phone.pipeline.load_layout", return_value=self.layout):
            request = ExportRequest(backup=None, out_path=Path("out.yaml"))
            env = ExportProcessor().process(ExportRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertIn("dock", env.payload.document)  # type: ignore[union-attr]

    def test_export_processor_failure(self):
        err = LayoutLoadError(code=2, message="no backup")
        with patch("phone.pipeline.load_layout", side_effect=err):
            request = ExportRequest(backup=None, out_path=Path("out.yaml"))
            env = ExportProcessor().process(ExportRequestConsumer(request).consume())
        self.assertFalse(env.ok())
        self.assertEqual(env.diagnostics["code"], 2)

    def test_export_producer_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "export.yaml"
            payload = ExportResult(document={"dock": []}, out_path=path)
            result = ResultEnvelope(status="success", payload=payload)
            buf = io.StringIO()
            with redirect_stdout(buf):
                ExportProducer().produce(result)
            self.assertTrue(path.exists())
            self.assertIn("Wrote layout export", buf.getvalue())

    def test_plan_processor_generates_plan(self):
        with patch("phone.pipeline.load_layout", return_value=self.layout):
            request = PlanRequest(layout=None, backup=None, out_path=Path("plan.yaml"))
            env = PlanProcessor().process(PlanRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertIn("pins", env.payload.document)  # type: ignore[union-attr]

    def test_plan_producer_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.yaml"
            payload = PlanResult(document={"pins": []}, out_path=path)
            result = ResultEnvelope(status="success", payload=payload)
            PlanProducer().produce(result)
            self.assertTrue(path.exists())

    def test_checklist_processor(self):
        plan_data = {"pins": [], "folders": {"Work": ["app2"]}}
        with patch("phone.pipeline.load_layout", return_value=self.layout), patch(
            "phone.pipeline.read_yaml", return_value=plan_data
        ):
            req = ChecklistRequest(
                plan_path=Path("plan.yaml"),
                layout=None,
                backup=None,
                out_path=Path("checklist.txt"),
            )
            env = ChecklistProcessor().process(ChecklistRequestConsumer(req).consume())
        self.assertTrue(env.ok())
        self.assertGreater(len(env.payload.steps), 0)  # type: ignore[union-attr]

    def test_checklist_producer_writes_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checklist.txt"
            payload = ChecklistResult(steps=["step1"], out_path=path)
            env = ResultEnvelope(status="success", payload=payload)
            ChecklistProducer().produce(env)
            self.assertTrue(path.exists())
            self.assertIn("step1", path.read_text())

    # -------------------------------------------------------------------------
    # Unused pipeline tests
    # -------------------------------------------------------------------------

    def test_unused_processor_success(self):
        with patch("phone.pipeline.load_layout", return_value=self.layout):
            request = UnusedRequest(
                layout=None,
                backup=None,
                recent_path=None,
                keep_path=None,
                limit=10,
                threshold=0.0,
                format="text",
            )
            env = UnusedProcessor().process(UnusedRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertIsInstance(env.payload.rows, list)  # type: ignore[union-attr]

    def test_unused_processor_failure(self):
        err = LayoutLoadError(code=2, message="no backup")
        with patch("phone.pipeline.load_layout", side_effect=err):
            request = UnusedRequest(
                layout=None,
                backup=None,
                recent_path=None,
                keep_path=None,
                limit=10,
                threshold=0.0,
                format="text",
            )
            env = UnusedProcessor().process(UnusedRequestConsumer(request).consume())
        self.assertFalse(env.ok())
        self.assertEqual(env.diagnostics["code"], 2)

    def test_unused_producer_text_output(self):
        payload = UnusedResult(rows=[("com.test.app", 0.9, "Page 1")], format="text")
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            UnusedProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("com.test.app", output)
        self.assertIn("Likely unused", output)

    def test_unused_producer_csv_output(self):
        payload = UnusedResult(rows=[("com.test.app", 0.9, "Page 1")], format="csv")
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            UnusedProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("app,score,location", output)
        self.assertIn("com.test.app,0.90,Page 1", output)

    # -------------------------------------------------------------------------
    # Prune pipeline tests
    # -------------------------------------------------------------------------

    def test_prune_processor_success(self):
        with patch("phone.pipeline.load_layout", return_value=self.layout):
            request = PruneRequest(
                layout=None,
                backup=None,
                recent_path=None,
                keep_path=None,
                limit=10,
                threshold=0.0,
                mode="offload",
                out_path=Path("prune.txt"),
            )
            env = PruneProcessor().process(PruneRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertIsInstance(env.payload.lines, list)  # type: ignore[union-attr]
        self.assertIn("OFFLOAD", env.payload.lines[0])  # type: ignore[union-attr]

    def test_prune_processor_delete_mode(self):
        with patch("phone.pipeline.load_layout", return_value=self.layout):
            request = PruneRequest(
                layout=None,
                backup=None,
                recent_path=None,
                keep_path=None,
                limit=10,
                threshold=0.0,
                mode="delete",
                out_path=Path("prune.txt"),
            )
            env = PruneProcessor().process(PruneRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertIn("DELETE", env.payload.lines[0])  # type: ignore[union-attr]

    def test_prune_producer_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prune.txt"
            payload = PruneResult(lines=["line1", "line2"], out_path=path)
            env = ResultEnvelope(status="success", payload=payload)
            buf = io.StringIO()
            with redirect_stdout(buf):
                PruneProducer().produce(env)
            self.assertTrue(path.exists())
            self.assertIn("line1", path.read_text())
            self.assertIn("Wrote", buf.getvalue())

    # -------------------------------------------------------------------------
    # Analyze pipeline tests
    # -------------------------------------------------------------------------

    def test_analyze_processor_success(self):
        with patch("phone.pipeline.load_layout", return_value=self.layout):
            request = AnalyzeRequest(
                layout=None,
                backup=None,
                plan_path=None,
                format="text",
            )
            env = AnalyzeProcessor().process(AnalyzeRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertIn("dock_count", env.payload.metrics)  # type: ignore[union-attr]
        self.assertIn("pages_count", env.payload.metrics)  # type: ignore[union-attr]

    def test_analyze_processor_failure(self):
        err = LayoutLoadError(code=2, message="no backup")
        with patch("phone.pipeline.load_layout", side_effect=err):
            request = AnalyzeRequest(
                layout=None,
                backup=None,
                plan_path=None,
                format="text",
            )
            env = AnalyzeProcessor().process(AnalyzeRequestConsumer(request).consume())
        self.assertFalse(env.ok())
        self.assertEqual(env.diagnostics["code"], 2)

    def test_analyze_producer_text_output(self):
        payload = AnalyzeResult(
            metrics={"dock_count": 4, "pages_count": 2, "totals": {"folders": 5}},
            format="text",
        )
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            AnalyzeProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("Layout Summary", output)
        self.assertIn("Dock: 4 apps", output)

    def test_analyze_producer_json_output(self):
        payload = AnalyzeResult(
            metrics={"dock_count": 4, "pages_count": 2, "totals": {"folders": 5}},
            format="json",
        )
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            AnalyzeProducer().produce(env)
        output = buf.getvalue()
        self.assertIn('"dock_count": 4', output)

    # -------------------------------------------------------------------------
    # Device I/O pipeline tests (export-device, iconmap)
    # -------------------------------------------------------------------------

    def test_export_device_processor_success(self):
        mock_export = {"dock": ["app1"], "pages": []}
        with patch("phone.device.find_cfgutil_path", return_value="/usr/bin/cfgutil"), \
             patch("phone.device.map_udid_to_ecid", return_value="0x123"), \
             patch("phone.device.export_from_device", return_value=mock_export):
            request = ExportDeviceRequest(udid="test-udid", ecid=None, out_path=Path("out.yaml"))
            env = ExportDeviceProcessor().process(ExportDeviceRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertEqual(env.payload.document, mock_export)  # type: ignore[union-attr]

    def test_export_device_processor_cfgutil_not_found(self):
        with patch("phone.device.find_cfgutil_path", side_effect=FileNotFoundError("cfgutil not found")):
            request = ExportDeviceRequest(udid=None, ecid=None, out_path=Path("out.yaml"))
            env = ExportDeviceProcessor().process(ExportDeviceRequestConsumer(request).consume())
        self.assertFalse(env.ok())
        self.assertEqual(env.diagnostics["code"], 127)

    def test_export_device_processor_empty_export(self):
        with patch("phone.device.find_cfgutil_path", return_value="/usr/bin/cfgutil"), \
             patch("phone.device.map_udid_to_ecid", return_value=""), \
             patch("phone.device.export_from_device", return_value={}):
            request = ExportDeviceRequest(udid=None, ecid=None, out_path=Path("out.yaml"))
            env = ExportDeviceProcessor().process(ExportDeviceRequestConsumer(request).consume())
        self.assertFalse(env.ok())
        self.assertEqual(env.diagnostics["code"], 3)

    def test_export_device_producer_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "export.yaml"
            payload = ExportDeviceResult(document={"dock": ["app1"]}, out_path=path)
            result = ResultEnvelope(status="success", payload=payload)
            buf = io.StringIO()
            with redirect_stdout(buf):
                ExportDeviceProducer().produce(result)
            self.assertTrue(path.exists())
            self.assertIn("Wrote layout export", buf.getvalue())

    def test_iconmap_processor_success(self):
        with patch("phone.device.find_cfgutil_path", return_value="/usr/bin/cfgutil"), \
             patch("phone.device.map_udid_to_ecid", return_value=""), \
             patch("subprocess.check_output", return_value=b'{"dock": []}'):
            request = IconmapRequest(udid=None, ecid=None, format="json", out_path=Path("out.json"))
            env = IconmapProcessor().process(IconmapRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertEqual(env.payload.data, b'{"dock": []}')  # type: ignore[union-attr]

    def test_iconmap_processor_cfgutil_not_found(self):
        with patch("phone.device.find_cfgutil_path", side_effect=FileNotFoundError("cfgutil not found")):
            request = IconmapRequest(udid=None, ecid=None, format="json", out_path=Path("out.json"))
            env = IconmapProcessor().process(IconmapRequestConsumer(request).consume())
        self.assertFalse(env.ok())
        self.assertEqual(env.diagnostics["code"], 127)

    def test_iconmap_producer_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "iconmap.json"
            payload = IconmapResult(data=b'{"test": true}', out_path=path)
            result = ResultEnvelope(status="success", payload=payload)
            buf = io.StringIO()
            with redirect_stdout(buf):
                IconmapProducer().produce(result)
            self.assertTrue(path.exists())
            self.assertEqual(path.read_bytes(), b'{"test": true}')
            self.assertIn("Wrote icon map", buf.getvalue())

    # -------------------------------------------------------------------------
    # Manifest pipeline tests
    # -------------------------------------------------------------------------

    def test_manifest_from_export_processor_success(self):
        export_data = {"dock": ["app1"], "pages": [{"apps": ["app2"], "folders": []}]}
        with tempfile.TemporaryDirectory() as tmp:
            export_path = Path(tmp) / "export.yaml"
            import yaml
            with open(export_path, "w") as f:
                yaml.safe_dump(export_data, f)
            request = ManifestFromExportRequest(export_path=export_path, out_path=Path(tmp) / "manifest.yaml")
            env = ManifestFromExportProcessor().process(ManifestFromExportRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertIn("layout", env.payload.manifest)  # type: ignore[union-attr]
        self.assertEqual(env.payload.manifest["layout"]["dock"], ["app1"])  # type: ignore[union-attr]

    def test_manifest_from_export_processor_file_not_found(self):
        request = ManifestFromExportRequest(export_path=Path("/nonexistent.yaml"), out_path=Path("out.yaml"))
        env = ManifestFromExportProcessor().process(ManifestFromExportRequestConsumer(request).consume())
        self.assertFalse(env.ok())
        self.assertEqual(env.diagnostics["code"], 2)

    def test_manifest_from_export_producer_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.yaml"
            manifest = {"meta": {"name": "test"}, "layout": {"dock": []}}
            payload = ManifestFromExportResult(manifest=manifest, out_path=path)
            result = ResultEnvelope(status="success", payload=payload)
            buf = io.StringIO()
            with redirect_stdout(buf):
                ManifestFromExportProducer().produce(result)
            self.assertTrue(path.exists())
            self.assertIn("Wrote device layout manifest", buf.getvalue())

    def test_manifest_from_device_processor_success(self):
        mock_export = {"dock": ["app1"], "pages": [{"apps": ["app2"], "folders": []}]}
        with patch("phone.device.find_cfgutil_path", return_value="/usr/bin/cfgutil"), \
             patch("phone.device.map_udid_to_ecid", return_value="0x123"), \
             patch("phone.device.export_from_device", return_value=mock_export):
            request = ManifestFromDeviceRequest(udid="test-udid", export_out=None, out_path=Path("out.yaml"))
            env = ManifestFromDeviceProcessor().process(ManifestFromDeviceRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertIn("layout", env.payload.manifest)  # type: ignore[union-attr]

    def test_manifest_from_device_processor_cfgutil_not_found(self):
        with patch("phone.device.find_cfgutil_path", side_effect=FileNotFoundError("cfgutil not found")):
            request = ManifestFromDeviceRequest(udid=None, export_out=None, out_path=Path("out.yaml"))
            env = ManifestFromDeviceProcessor().process(ManifestFromDeviceRequestConsumer(request).consume())
        self.assertFalse(env.ok())
        self.assertEqual(env.diagnostics["code"], 127)

    # -------------------------------------------------------------------------
    # Identity verify pipeline tests
    # -------------------------------------------------------------------------

    def test_identity_verify_processor_success(self):
        from phone.device import CertInfo

        mock_cert = CertInfo(subject="CN=TestOrg", issuer="CN=TestIssuer")
        with (
            patch("phone.device.read_credentials_ini", return_value=(None, {})),
            patch("phone.device.resolve_p12_path", return_value=("/path/to/cert.p12", "pass")),  # nosec B106
            patch("phone.device.extract_p12_cert_info", return_value=mock_cert),
            patch("phone.device.get_device_supervision_status", return_value="true"),
        ):
            request = IdentityVerifyRequest(  # nosec B106
                p12_path="/path/to/cert.p12",
                p12_pass="pass",
                creds_profile=None,
                config=None,
                device_label=None,
                udid="test-udid",
                expected_org="TestOrg",
            )
            env = IdentityVerifyProcessor().process(IdentityVerifyRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertEqual(env.payload.cert_subject, "CN=TestOrg")  # type: ignore[union-attr]
        self.assertEqual(env.payload.org_match, True)  # type: ignore[union-attr]

    def test_identity_verify_processor_no_p12(self):
        with patch("phone.device.read_credentials_ini", return_value=(None, {})), \
             patch("phone.device.resolve_p12_path", return_value=(None, None)):
            request = IdentityVerifyRequest(
                p12_path=None,
                p12_pass=None,
                creds_profile=None,
                config=None,
                device_label=None,
                udid=None,
                expected_org=None,
            )
            env = IdentityVerifyProcessor().process(IdentityVerifyRequestConsumer(request).consume())
        self.assertFalse(env.ok())
        self.assertEqual(env.diagnostics["code"], 2)

    def test_identity_verify_processor_p12_not_found(self):
        with patch("phone.device.read_credentials_ini", return_value=(None, {})), \
             patch("phone.device.resolve_p12_path", return_value=("/missing.p12", None)), \
             patch("phone.device.extract_p12_cert_info", side_effect=FileNotFoundError("/missing.p12")):
            request = IdentityVerifyRequest(
                p12_path="/missing.p12",
                p12_pass=None,
                creds_profile=None,
                config=None,
                device_label=None,
                udid=None,
                expected_org=None,
            )
            env = IdentityVerifyProcessor().process(IdentityVerifyRequestConsumer(request).consume())
        self.assertFalse(env.ok())
        self.assertEqual(env.diagnostics["code"], 2)

    def test_identity_verify_producer_output(self):
        payload = IdentityVerifyResult(
            p12_path="/path/to/cert.p12",
            cert_subject="CN=TestOrg",
            cert_issuer="CN=TestIssuer",
            udid="test-udid",
            supervised="true",
            expected_org="TestOrg",
            org_match=True,
        )
        result = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            IdentityVerifyProducer().produce(result)
        output = buf.getvalue()
        self.assertIn("Identity Verification Summary", output)
        self.assertIn("CN=TestOrg", output)
        self.assertIn("MATCH", output)
