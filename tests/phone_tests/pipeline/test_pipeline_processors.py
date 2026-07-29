"""Tests for phone pipeline processor classes and helper functions."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch



class TestProcessPage(unittest.TestCase):
    """Tests for page/folder helper function branches."""

    def test_folder_without_name_defaults_to_folder(self):
        from phone.pipeline import _process_pages
        p = {"apps": ["app1"], "folders": [{"apps": ["app2"]}]}  # no name key
        pages_out, folders_total = _process_pages([p], set(), [])
        self.assertEqual(folders_total, 1)
        self.assertEqual(pages_out[0]["folders"][0]["name"], "Folder")

    def test_folder_with_none_name_defaults_to_folder(self):
        from phone.pipeline import _process_pages
        p = {"apps": [], "folders": [{"name": None, "apps": ["app1"]}]}
        pages_out, _folders_total = _process_pages([p], set(), [])
        self.assertEqual(pages_out[0]["folders"][0]["name"], "Folder")

    def test_collect_unique_skips_empty_strings(self):
        from phone.pipeline import _collect_unique_app
        seen = set()
        all_apps: list = []
        for app in ["app1", "", "app2", "app1"]:
            _collect_unique_app(app, seen, all_apps)
        self.assertEqual(all_apps, ["app1", "app2"])


class TestChecklistProcessorFileNotFound(unittest.TestCase):
    def test_checklist_plan_not_found(self):
        from phone.pipeline import ChecklistProcessor, ChecklistRequest, ChecklistRequestConsumer
        from phone.layout import NormalizedLayout
        layout = NormalizedLayout(dock=[], pages=[])
        with patch("phone.pipeline_export.load_layout", return_value=layout), \
             patch("phone.pipeline_export.read_yaml", side_effect=FileNotFoundError("/missing.yaml")):
            req = ChecklistRequest(
                plan_path=Path("/missing.yaml"),
                layout=None,
                backup=None,
                out_path=Path("checklist.txt"),
            )
            env = ChecklistProcessor().process(ChecklistRequestConsumer(req).consume())
        self.assertFalse(env.ok())
        self.assertIn("not found", (env.diagnostics or {}).get("message", "").lower())


class TestBuildInstallCmd(unittest.TestCase):
    def test_with_udid(self):
        from phone.pipeline import _build_install_command, ManifestInstallRequest
        payload = ManifestInstallRequest(
            manifest_path=Path("manifest.yaml"),
            out_path=None,
            dry_run=False,
            udid="test-udid",
            device_label=None,
            creds_profile=None,
            config=None,
        )
        man = {"device": {}}
        out_path = Path("test.mobileconfig")  # sentinel path, never written to disk in this test
        cmd = _build_install_command(payload, man, out_path)
        self.assertIn("--udid", cmd)
        self.assertIn("test-udid", cmd)

    def test_with_label_only(self):
        from phone.pipeline import _build_install_command, ManifestInstallRequest
        payload = ManifestInstallRequest(
            manifest_path=Path("manifest.yaml"),
            out_path=None,
            dry_run=False,
            udid=None,
            device_label="my-device",
            creds_profile=None,
            config=None,
        )
        man = {"device": {}}
        out_path = Path("test.mobileconfig")  # sentinel path, never written to disk in this test
        cmd = _build_install_command(payload, man, out_path)
        self.assertIn("--device-label", cmd)
        self.assertIn("my-device", cmd)

    def test_with_creds_profile_and_config(self):
        from phone.pipeline import _build_install_command, ManifestInstallRequest
        payload = ManifestInstallRequest(
            manifest_path=Path("manifest.yaml"),
            out_path=None,
            dry_run=False,
            udid=None,
            device_label=None,
            creds_profile="ios_layout",
            config="/etc/config.yaml",
        )
        man = {"device": {}}
        out_path = Path("test.mobileconfig")  # sentinel path, never written to disk in this test
        cmd = _build_install_command(payload, man, out_path)
        self.assertIn("--creds-profile", cmd)
        self.assertIn("ios_layout", cmd)
        self.assertIn("--config", cmd)
        self.assertIn("/etc/config.yaml", cmd)

    def test_with_device_section_in_manifest(self):
        from phone.pipeline import _build_install_command, ManifestInstallRequest
        payload = ManifestInstallRequest(
            manifest_path=Path("manifest.yaml"),
            out_path=None,
            dry_run=False,
            udid=None,
            device_label=None,
            creds_profile=None,
            config=None,
        )
        man = {"device": {"udid": "from-manifest-udid"}}
        out_path = Path("test.mobileconfig")  # sentinel path, never written to disk in this test
        cmd = _build_install_command(payload, man, out_path)
        self.assertIn("--udid", cmd)
        self.assertIn("from-manifest-udid", cmd)


class TestManifestInstallProcessor(unittest.TestCase):
    def _make_manifest_yaml(self, tmp: str, data: dict) -> Path:
        import yaml
        p = Path(tmp) / "manifest.yaml"
        with open(p, "w") as f:
            yaml.safe_dump(data, f)
        return p

    def test_file_not_found(self):
        from phone.pipeline import ManifestInstallProcessor, ManifestInstallRequest, ManifestInstallRequestConsumer
        req = ManifestInstallRequest(
            manifest_path=Path("/nonexistent.yaml"),
            out_path=None,
            dry_run=True,
            udid=None,
            device_label=None,
            creds_profile=None,
            config=None,
        )
        env = ManifestInstallProcessor().process(ManifestInstallRequestConsumer(req).consume())
        self.assertFalse(env.ok())
        self.assertIn("not found", (env.diagnostics or {}).get("message", "").lower())

    def test_invalid_manifest_not_dict(self):
        from phone.pipeline import ManifestInstallProcessor, ManifestInstallRequest, ManifestInstallRequestConsumer
        with tempfile.TemporaryDirectory() as tmp:  # nosec B108 - test-only temp file, not a security concern
            p = Path(tmp) / "manifest.yaml"
            p.write_text("- item1\n- item2\n")
            req = ManifestInstallRequest(
                manifest_path=p,
                out_path=None,
                dry_run=True,
                udid=None,
                device_label=None,
                creds_profile=None,
                config=None,
            )
            env = ManifestInstallProcessor().process(ManifestInstallRequestConsumer(req).consume())
        self.assertFalse(env.ok())

    def test_manifest_missing_plan_section(self):
        from phone.pipeline import ManifestInstallProcessor, ManifestInstallRequest, ManifestInstallRequestConsumer
        with tempfile.TemporaryDirectory() as tmp:  # nosec B108 - test-only temp file, not a security concern
            p = self._make_manifest_yaml(tmp, {"meta": {"name": "test"}})
            req = ManifestInstallRequest(
                manifest_path=p,
                out_path=None,
                dry_run=True,
                udid=None,
                device_label=None,
                creds_profile=None,
                config=None,
            )
            env = ManifestInstallProcessor().process(ManifestInstallRequestConsumer(req).consume())
        self.assertFalse(env.ok())

    def test_manifest_with_layout_section(self):
        from phone.pipeline import ManifestInstallProcessor, ManifestInstallRequest, ManifestInstallRequestConsumer
        with tempfile.TemporaryDirectory() as tmp:  # nosec B108 - test-only temp file, not a security concern
            manifest = {
                "layout": {"dock": ["app1"], "pages": []},
                "device": {"label": "mydevice"},
            }
            p = self._make_manifest_yaml(tmp, manifest)
            out_path = Path(tmp) / "test.mobileconfig"
            req = ManifestInstallRequest(
                manifest_path=p,
                out_path=out_path,
                dry_run=True,
                udid=None,
                device_label=None,
                creds_profile=None,
                config=None,
            )
            mock_profile = {"PayloadContent": [], "PayloadType": "Configuration"}
            with patch("phone.profile.build_mobileconfig", return_value=mock_profile):
                env = ManifestInstallProcessor().process(ManifestInstallRequestConsumer(req).consume())
        self.assertTrue(env.ok())
        self.assertTrue(env.payload.dry_run)  # type: ignore[union-attr]

    def test_manifest_with_plan_auto_path(self):
        """Test that auto path is generated from device label when out_path is None."""
        from phone.pipeline import ManifestInstallProcessor, ManifestInstallRequest, ManifestInstallRequestConsumer
        with tempfile.TemporaryDirectory() as tmp:  # nosec B108 - test-only temp file, not a security concern
            manifest = {
                "plan": {"dock": ["app1"], "pages": {}},
                "device": {"label": "mydevice"},
            }
            p = self._make_manifest_yaml(tmp, manifest)
            req = ManifestInstallRequest(
                manifest_path=p,
                out_path=None,  # auto-generate
                dry_run=True,
                udid=None,
                device_label=None,
                creds_profile=None,
                config=None,
            )
            mock_profile = {"PayloadContent": [], "PayloadType": "Configuration"}
            with patch("phone.profile.build_mobileconfig", return_value=mock_profile):
                env = ManifestInstallProcessor().process(ManifestInstallRequestConsumer(req).consume())
        self.assertTrue(env.ok())
        # Auto-generated path should include 'mydevice'
        self.assertIn("mydevice", str(env.payload.profile_path))  # type: ignore[union-attr]


class TestPlanFromLayout(unittest.TestCase):
    def test_basic_conversion(self):
        from phone.pipeline import _plan_from_layout
        layout_obj = {
            "dock": ["app1", "app2"],
            "pages": [
                {"apps": ["app3"], "folders": [{"name": "Work", "apps": ["app4"]}]},
            ],
        }
        plan = _plan_from_layout(layout_obj)
        self.assertEqual(plan["dock"], ["app1", "app2"])
        self.assertIn(1, plan["pages"])
        self.assertEqual(plan["pages"][1]["apps"], ["app3"])
        self.assertIn("Work", plan["folders"])
        self.assertEqual(plan["folders"]["Work"], ["app4"])

    def test_empty_layout(self):
        from phone.pipeline import _plan_from_layout
        plan = _plan_from_layout({})
        self.assertEqual(plan["dock"], [])
        self.assertEqual(plan["pages"], {})
        self.assertEqual(plan["folders"], {})

    def test_page_folder_without_name(self):
        from phone.pipeline import _plan_from_layout
        layout_obj = {
            "dock": [],
            "pages": [
                {"apps": [], "folders": [{"apps": ["app1"]}]},  # no name
            ],
        }
        plan = _plan_from_layout(layout_obj)
        self.assertIn("Folder", plan["folders"])


class TestIdentityVerifyProcessorBranches(unittest.TestCase):
    def test_verify_with_label_resolves_udid(self):
        from phone.pipeline import IdentityVerifyProcessor, IdentityVerifyRequest, IdentityVerifyRequestConsumer
        from phone.device import CertInfo
        mock_cert = CertInfo(subject="CN=TestOrg", issuer="CN=TestIssuer")
        with (
            patch("phone.device.read_credentials_ini", return_value=(Path("creds.ini"), {})),  # sentinel path, never accessed in this test
            patch("phone.device.resolve_p12_path", return_value=("/path/to/cert.p12", "pass")),  # nosec B106
            patch("phone.device.extract_p12_cert_info", return_value=mock_cert),
            patch("phone.device.get_device_supervision_status", return_value="true"),
            patch("phone.device.resolve_udid_from_label", return_value="resolved-udid"),
        ):
            request = IdentityVerifyRequest(
                p12_path="/path/to/cert.p12",
                p12_pass="pass",  # nosec B106
                creds_profile=None,
                config=None,
                device_label="my-device",
                udid=None,
                expected_org=None,
            )
            env = IdentityVerifyProcessor().process(IdentityVerifyRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertEqual(env.payload.udid, "resolved-udid")  # type: ignore[union-attr]

    def test_verify_runtime_error_from_p12(self):
        from phone.pipeline import IdentityVerifyProcessor, IdentityVerifyRequest, IdentityVerifyRequestConsumer
        with (
            patch("phone.device.read_credentials_ini", return_value=(None, {})),
            patch("phone.device.resolve_p12_path", return_value=("/path/to/cert.p12", "pass")),  # nosec B106
            patch("phone.device.extract_p12_cert_info", side_effect=RuntimeError("bad password")),
        ):
            request = IdentityVerifyRequest(
                p12_path="/path/to/cert.p12",
                p12_pass="pass",  # nosec B106
                creds_profile=None,
                config=None,
                device_label=None,
                udid=None,
                expected_org=None,
            )
            env = IdentityVerifyProcessor().process(IdentityVerifyRequestConsumer(request).consume())
        self.assertFalse(env.ok())


class TestIconmapProcessorEcidResolution(unittest.TestCase):
    def test_iconmap_with_udid_resolves_ecid(self):
        from phone.pipeline import IconmapProcessor, IconmapRequest, IconmapRequestConsumer
        with patch("phone.device.find_cfgutil_path", return_value="/usr/bin/cfgutil"), \
             patch("phone.device.map_udid_to_ecid", return_value="0xECID"), \
             patch("subprocess.check_output", return_value=b'{}'):
            request = IconmapRequest(udid="test-udid", ecid=None, format="json", out_path=Path("out.json"))
            env = IconmapProcessor().process(IconmapRequestConsumer(request).consume())
        self.assertTrue(env.ok())

    def test_iconmap_processor_called_process_error(self):
        import subprocess as sp
        from phone.pipeline import IconmapProcessor, IconmapRequest, IconmapRequestConsumer
        with patch("phone.device.find_cfgutil_path", return_value="/usr/bin/cfgutil"), \
             patch("phone.device.map_udid_to_ecid", return_value=""), \
             patch("subprocess.check_output", side_effect=sp.CalledProcessError(1, "cfgutil")):
            request = IconmapRequest(udid=None, ecid=None, format="json", out_path=Path("out.json"))
            env = IconmapProcessor().process(IconmapRequestConsumer(request).consume())
        self.assertFalse(env.ok())

    def test_iconmap_processor_generic_exception(self):
        from phone.pipeline import IconmapProcessor, IconmapRequest, IconmapRequestConsumer
        with patch("phone.device.find_cfgutil_path", return_value="/usr/bin/cfgutil"), \
             patch("phone.device.map_udid_to_ecid", return_value=""), \
             patch("subprocess.check_output", side_effect=OSError("device not found")):
            request = IconmapRequest(udid=None, ecid=None, format="json", out_path=Path("out.json"))
            env = IconmapProcessor().process(IconmapRequestConsumer(request).consume())
        self.assertFalse(env.ok())


class TestManifestFromExportValidation(unittest.TestCase):
    def test_invalid_export_missing_required_keys(self):
        from phone.pipeline import ManifestFromExportProcessor, ManifestFromExportRequest, ManifestFromExportRequestConsumer
        with tempfile.TemporaryDirectory() as tmp:  # nosec B108 - test-only temp file, not a security concern
            p = Path(tmp) / "bad_export.yaml"
            import yaml
            with open(p, "w") as f:
                yaml.safe_dump({"only_key": "no_dock_or_pages"}, f)
            request = ManifestFromExportRequest(export_path=p, out_path=Path(tmp) / "manifest.yaml")
            env = ManifestFromExportProcessor().process(ManifestFromExportRequestConsumer(request).consume())
        self.assertFalse(env.ok())
        self.assertIn("dock", (env.diagnostics or {}).get("message", "").lower())


class TestManifestFromDeviceProcessorEmptyExport(unittest.TestCase):
    def test_empty_export_raises_error(self):
        from phone.pipeline import ManifestFromDeviceProcessor, ManifestFromDeviceRequest, ManifestFromDeviceRequestConsumer
        with patch("phone.device.find_cfgutil_path", return_value="/usr/bin/cfgutil"), \
             patch("phone.device.map_udid_to_ecid", return_value=None), \
             patch("phone.device.export_from_device", return_value=None):
            request = ManifestFromDeviceRequest(udid=None, export_out=None, out_path=Path("out.yaml"))
            env = ManifestFromDeviceProcessor().process(ManifestFromDeviceRequestConsumer(request).consume())
        self.assertFalse(env.ok())
        self.assertIn("export", (env.diagnostics or {}).get("message", "").lower())


class TestPruneProcessorCandidateLine(unittest.TestCase):
    def test_candidates_in_output(self):
        from phone.pipeline import PruneProcessor, PruneRequest, PruneRequestConsumer
        from phone.layout import NormalizedLayout
        layout = NormalizedLayout(dock=[], pages=[])
        rows = [("com.example.app", 1.5, "Page 1")]
        with patch("phone.pipeline_export.load_layout", return_value=layout), \
             patch("phone.layout.rank_unused_candidates", return_value=rows):
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
        self.assertTrue(any("com.example.app" in line for line in env.payload.lines))  # type: ignore[union-attr]


class TestAnalyzeProcessorWithPlanPath(unittest.TestCase):
    def test_analyze_with_missing_plan_path(self):
        from phone.pipeline import AnalyzeProcessor, AnalyzeRequest, AnalyzeRequestConsumer
        from phone.layout import NormalizedLayout
        layout = NormalizedLayout(dock=[], pages=[])
        with patch("phone.pipeline_export.load_layout", return_value=layout), \
             patch("phone.pipeline_export.read_yaml", side_effect=FileNotFoundError("/missing.yaml")):
            request = AnalyzeRequest(
                layout=None,
                backup=None,
                plan_path="/missing.yaml",
                format="text",
            )
            env = AnalyzeProcessor().process(AnalyzeRequestConsumer(request).consume())
        self.assertFalse(env.ok())
        self.assertIn("not found", (env.diagnostics or {}).get("message", "").lower())


class TestIdentityVerifyNoLabelNoUdid(unittest.TestCase):
    def test_verify_no_label_no_udid_skips_resolve(self):
        from phone.pipeline import IdentityVerifyProcessor, IdentityVerifyRequest, IdentityVerifyRequestConsumer
        from phone.device import CertInfo
        mock_cert = CertInfo(subject="CN=TestOrg", issuer="CN=TestIssuer")
        with (
            patch("phone.device.read_credentials_ini", return_value=(None, {})),
            patch("phone.device.resolve_p12_path", return_value=("/path/to/cert.p12", "pass")),  # nosec B106
            patch("phone.device.extract_p12_cert_info", return_value=mock_cert),
            patch("phone.device.get_device_supervision_status", return_value="true"),
        ):
            request = IdentityVerifyRequest(
                p12_path="/path/to/cert.p12",
                p12_pass="pass",  # nosec B106
                creds_profile=None,
                config=None,
                device_label=None,  # no label
                udid=None,          # no udid
                expected_org=None,
            )
            env = IdentityVerifyProcessor().process(IdentityVerifyRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertIsNone(env.payload.udid)  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
