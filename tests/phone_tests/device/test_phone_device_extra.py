"""Additional tests for phone/device.py — covering previously uncovered lines."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from phone.device import (
    _extract_cert_pem,
    _extract_ecid_from_parts,
    _x509_field,
    export_from_device,
    extract_p12_cert_info,
    find_cfgutil_path,
    get_device_supervision_status,
    read_credentials_ini,
    resolve_udid_from_label,
)


class TestFindCfgutilPath(unittest.TestCase):
    def test_finds_cfgutil_on_path(self):
        with patch("phone.device.which", return_value="/usr/local/bin/cfgutil"):
            result = find_cfgutil_path()
            self.assertEqual(result, "/usr/local/bin/cfgutil")

    def test_finds_cfgutil_at_alt_path(self):
        alt = "/Applications/Apple Configurator.app/Contents/MacOS/cfgutil"
        with patch("phone.device.which", return_value=None), \
             patch.object(Path, "exists", return_value=True):
            result = find_cfgutil_path()
            self.assertEqual(result, alt)

    def test_raises_when_not_found(self):
        with patch("phone.device.which", return_value=None), \
             patch.object(Path, "exists", return_value=False):
            with self.assertRaises(FileNotFoundError):
                find_cfgutil_path()


class TestExtractEcidFromParts(unittest.TestCase):
    def test_inline_ecid(self):
        parts = ["Device", "UDID:ABC", "ECID:0x12345"]
        self.assertEqual(_extract_ecid_from_parts(parts), "0x12345")

    def test_ecid_with_space(self):
        parts = ["Device", "ECID:", "0xABCD"]
        self.assertEqual(_extract_ecid_from_parts(parts), "0xABCD")

    def test_ecid_at_end_no_value(self):
        parts = ["ECID:"]
        self.assertEqual(_extract_ecid_from_parts(parts), "")

    def test_no_ecid_returns_empty(self):
        parts = ["Device", "UDID:ABC123"]
        self.assertEqual(_extract_ecid_from_parts(parts), "")


class TestExportFromDevice(unittest.TestCase):
    def test_export_via_plist(self):
        import plistlib

        mock_layout = MagicMock()
        mock_layout.dock = ["com.dock"]
        mock_layout.pages = []

        plist_data = {"buttonBar": [], "iconLists": []}
        plist_bytes = plistlib.dumps(plist_data)

        with patch("phone.device.subprocess.check_output", return_value=plist_bytes), \
             patch("phone.device.normalize_iconstate", return_value=mock_layout), \
             patch("phone.device.to_yaml_export", return_value={"dock": ["com.dock"], "pages": []}):
            result = export_from_device("/usr/bin/cfgutil")
            self.assertIn("dock", result)

    def test_export_raises_on_subprocess_failure(self):
        with patch("phone.device.subprocess.check_output", side_effect=Exception("failed")):
            with self.assertRaises(RuntimeError):
                export_from_device("/usr/bin/cfgutil")

    def test_export_with_ecid(self):
        import plistlib

        mock_layout = MagicMock()
        mock_layout.dock = []
        mock_layout.pages = []
        plist_bytes = plistlib.dumps({})

        with patch("phone.device.subprocess.check_output", return_value=plist_bytes), \
             patch("phone.device.normalize_iconstate", return_value=mock_layout), \
             patch("phone.device.to_yaml_export", return_value={}):
            result = export_from_device("/usr/bin/cfgutil", ecid="0x12345")
            self.assertIsInstance(result, dict)

    def test_export_fallback_parse_on_normalize_failure(self):
        import plistlib

        plist_data = {"buttonBar": [{"bundleIdentifier": "com.app"}], "iconLists": []}
        plist_bytes = plistlib.dumps(plist_data)

        with patch("phone.device.subprocess.check_output", return_value=plist_bytes), \
             patch("phone.device.normalize_iconstate", side_effect=Exception("parse error")):
            result = export_from_device("/usr/bin/cfgutil")
            self.assertIsInstance(result, dict)

    def test_export_json_fallback(self):
        import json

        json_data = [["com.dock"], ["com.app1"]]
        json_bytes = json.dumps(json_data).encode()

        with patch("phone.device.subprocess.check_output", return_value=json_bytes):
            # plist parse fails → json parse succeeds → _fallback_parse on list
            result = export_from_device("/usr/bin/cfgutil")
            self.assertIsInstance(result, dict)


class TestReadCredentialsIni(unittest.TestCase):
    def test_reads_ini_from_explicit_path(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
            f.write("[phone.profile]\nmy_key = my_value\n")
            fname = f.name

        try:
            path, data = read_credentials_ini(explicit=fname)
            self.assertEqual(path, fname)
            self.assertIn("phone.profile", data)
            self.assertEqual(data["phone.profile"]["my_key"], "my_value")
        finally:
            os.unlink(fname)

    def test_returns_none_when_no_ini_found(self):
        with patch("phone.device.credential_ini_paths", return_value=[]):
            path, data = read_credentials_ini()
            self.assertIsNone(path)
            self.assertEqual(data, {})

    def test_skips_nonexistent_candidates(self):
        with patch("phone.device.credential_ini_paths", return_value=["/nonexistent/path.ini"]):
            path, _data = read_credentials_ini()
            self.assertIsNone(path)


class TestExtractCertPem(unittest.TestCase):
    def test_tries_legacy_then_standard(self):
        with patch("phone.device.subprocess.check_output", side_effect=[
            Exception("legacy failed"),
            b"-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n",
        ]):
            result = _extract_cert_pem("/fake/cert.p12", "password")
            self.assertIn(b"CERTIFICATE", result)

    def test_legacy_succeeds(self):
        with patch("phone.device.subprocess.check_output", return_value=b"cert_pem_data"):
            result = _extract_cert_pem("/fake/cert.p12", None)
            self.assertEqual(result, b"cert_pem_data")

    def test_raises_when_both_fail(self):
        with patch("phone.device.subprocess.check_output", side_effect=Exception("fail")):
            with self.assertRaises(RuntimeError) as ctx:
                _extract_cert_pem("/fake/cert.p12", "pass")
            self.assertIn("Failed to extract certificate", str(ctx.exception))


class TestX509Field(unittest.TestCase):
    def test_extracts_subject(self):
        with patch("phone.device.subprocess.check_output", return_value=b"subject=CN=Test\n"):
            result = _x509_field(b"fake_pem", "subject")
            self.assertEqual(result, "CN=Test")

    def test_returns_empty_on_failure(self):
        with patch("phone.device.subprocess.check_output", side_effect=Exception("fail")):
            result = _x509_field(b"fake_pem", "subject")
            self.assertEqual(result, "")


class TestExtractP12CertInfo(unittest.TestCase):
    def test_raises_when_file_missing(self):
        with self.assertRaises(FileNotFoundError):
            extract_p12_cert_info("/nonexistent/cert.p12")

    def test_extracts_cert_info(self):
        with tempfile.NamedTemporaryFile(suffix=".p12", delete=False) as f:
            f.write(b"fake p12 data")
            fname = f.name

        try:
            with patch("phone.device._extract_cert_pem", return_value=b"fake_pem"), \
                 patch("phone.device._x509_field", side_effect=["CN=Test", "CN=CA"]):
                info = extract_p12_cert_info(fname, "password")
                self.assertEqual(info.subject, "CN=Test")
                self.assertEqual(info.issuer, "CN=CA")
        finally:
            os.unlink(fname)


class TestGetDeviceSupervisionStatus(unittest.TestCase):
    def test_returns_none_when_cfgutil_not_found(self):
        with patch("phone.device.find_cfgutil_path", side_effect=FileNotFoundError):
            result = get_device_supervision_status()
            self.assertIsNone(result)

    def test_returns_status_when_found(self):
        with patch("phone.device.find_cfgutil_path", return_value="/usr/bin/cfgutil"), \
             patch("phone.device.subprocess.check_output", return_value="Supervised: true\n"):
            result = get_device_supervision_status()
            self.assertEqual(result, "true")

    def test_returns_none_on_subprocess_failure(self):
        with patch("phone.device.find_cfgutil_path", return_value="/usr/bin/cfgutil"), \
             patch("phone.device.subprocess.check_output", side_effect=Exception("fail")):
            result = get_device_supervision_status()
            self.assertIsNone(result)

    def test_uses_explicit_path(self):
        with patch("phone.device.subprocess.check_output", return_value="Supervised: false\n"):
            result = get_device_supervision_status("/custom/cfgutil")
            self.assertEqual(result, "false")


class TestResolveUdidFromLabel(unittest.TestCase):
    def test_returns_none_for_missing_inputs(self):
        result = resolve_udid_from_label("", None, {})
        self.assertIsNone(result)

    def test_returns_none_when_file_missing(self):
        result = resolve_udid_from_label("mydevice", "/nonexistent/creds.ini", {})
        self.assertIsNone(result)

    def test_reads_udid_from_ini(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
            f.write("[ios_devices]\nmydevice = UDID-12345\n")
            fname = f.name

        try:
            result = resolve_udid_from_label("mydevice", fname, {})
            self.assertEqual(result, "UDID-12345")
        finally:
            os.unlink(fname)

    def test_returns_none_for_unknown_label(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
            f.write("[ios_devices]\nknown_device = UDID-99999\n")
            fname = f.name

        try:
            result = resolve_udid_from_label("unknown_device", fname, {})
            self.assertIsNone(result)
        finally:
            os.unlink(fname)


if __name__ == "__main__":
    unittest.main()
