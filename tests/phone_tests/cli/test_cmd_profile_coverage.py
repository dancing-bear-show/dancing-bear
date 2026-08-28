"""Coverage tests for phone/cli/cmd_profile.py.

Targets missing lines and branches:
  - _sign_mobileconfig: subprocess calls, legacy flag detection (lines 96-154)
  - _extract_manifest_profile_config: exception handler when layout file missing (lines 231-232)
  - _build_all_apps_folder_config: all_apps_folder_page branch (branch 66->68)
  - cmd_profile_build: layout FileNotFoundError path (lines 242-243)
  - cmd_profile_build: ValueError from _build_all_apps_folder_config (lines 247-250, 254-255)
  - cmd_profile_build: layout arg provided branch (branch 246->247)
  - cmd_profile_build: signing path (lines 280-287, branch 279->280)
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.phone_tests.cli.fixtures import make_profile_build_args
from tests.phone_tests.fixtures import make_mock_manifest, make_mock_plan

# Dummy p12 passphrase for signing tests. Never reaches a real keystore — the
# subprocess layer is mocked, and cmd_profile passes it via the _IOS_P12_PASS
# env var rather than argv.
FAKE_P12_PASS = "pw-placeholder"  # nosec B105 - test fixture, not a credential


class TestBuildAllAppsFolderConfig(unittest.TestCase):
    """Tests for _build_all_apps_folder_config helper."""

    def setUp(self):
        from phone.cli.cmd_profile import _build_all_apps_folder_config

        self._fn = _build_all_apps_folder_config

    def test_folder_page_included_when_all_apps_folder_page_is_set(self):
        """Branch 66->68: folder dict includes 'page' when all_apps_folder_page is not None."""
        args = MagicMock()
        args.all_apps_folder_name = "All Apps"
        args.all_apps_folder_page = 7

        result = self._fn(args, layout_export={"dock": [], "pages": {}})

        self.assertEqual(result["name"], "All Apps")
        self.assertEqual(result["page"], 7)

    def test_folder_page_absent_when_all_apps_folder_page_is_none(self):
        """Folder dict does not include 'page' when all_apps_folder_page is None."""
        args = MagicMock()
        args.all_apps_folder_name = "All Apps"
        args.all_apps_folder_page = None

        result = self._fn(args, layout_export={"dock": [], "pages": {}})

        self.assertEqual(result["name"], "All Apps")
        self.assertNotIn("page", result)

    def test_folder_name_defaults_to_all_apps_when_name_is_none(self):
        """Folder name defaults to 'All Apps' when all_apps_folder_name is None."""
        args = MagicMock()
        args.all_apps_folder_name = None
        args.all_apps_folder_page = 3

        result = self._fn(args, layout_export={"dock": [], "pages": {}})

        self.assertEqual(result["name"], "All Apps")
        self.assertEqual(result["page"], 3)


class TestExtractManifestProfileConfigLayoutError(unittest.TestCase):
    """Tests for _extract_manifest_profile_config layout file error handling."""

    def test_layout_set_to_none_when_file_read_fails(self):
        """Lines 231-232: layout_export is None when read_yaml raises for layout_export_path."""
        from phone.cli.cmd_profile import _extract_manifest_profile_config

        manifest = make_mock_manifest(layout_export_path="nonexistent/export.yaml")

        with patch("phone.cli.cmd_profile.read_yaml", side_effect=FileNotFoundError("no file")):
            plan, layout_export, _profile = _extract_manifest_profile_config(manifest)

        self.assertIsNone(layout_export)
        self.assertEqual(plan, manifest["plan"])

    def test_layout_loads_when_file_exists(self):
        """Happy path: layout_export is populated when read_yaml succeeds."""
        from phone.cli.cmd_profile import _extract_manifest_profile_config

        manifest = make_mock_manifest(layout_export_path="export.yaml")
        fake_layout = {"dock": ["com.apple.safari"], "pages": {}}

        with patch("phone.cli.cmd_profile.read_yaml", return_value=fake_layout):
            _plan, layout_export, _profile = _extract_manifest_profile_config(manifest)

        self.assertEqual(layout_export, fake_layout)


class TestCmdProfileBuildLayoutPath(unittest.TestCase):
    """Tests for cmd_profile_build layout loading branch and error paths."""

    @patch("phone.cli.cmd_profile._write_mobileconfig")
    @patch("phone.cli.cmd_profile.build_mobileconfig", return_value={"payload": "data"})
    @patch("phone.cli.cmd_profile._build_all_apps_folder_config", return_value=None)
    @patch("phone.cli.cmd_profile.read_yaml")
    def test_layout_loaded_when_layout_arg_provided(
        self, mock_read, mock_folder, mock_build, mock_write
    ):
        """Branch 246->247: layout is read when args.layout is set."""
        from phone.cli.cmd_profile import cmd_profile_build

        plan_data = make_mock_plan()
        layout_data = {"dock": [], "pages": {}}
        mock_read.side_effect = [plan_data, layout_data]
        args = make_profile_build_args(plan="plan.yaml", layout="export.yaml")

        result = cmd_profile_build(args)

        self.assertEqual(result, 0)
        self.assertEqual(mock_read.call_count, 2)
        # Second read_yaml call should be for the layout file
        self.assertIn(Path("export.yaml"), mock_read.call_args_list[1][0])

    @patch("phone.cli.cmd_profile.read_yaml")
    def test_layout_filenot_found_raises_cli_error(self, mock_read):
        """Lines 242-243: CLIError raised when layout file not found."""
        from core.cli_errors import CLIError
        from phone.cli.cmd_profile import cmd_profile_build

        plan_data = make_mock_plan()
        mock_read.side_effect = [plan_data, FileNotFoundError("no layout")]
        args = make_profile_build_args(plan="plan.yaml", layout="missing.yaml")

        with self.assertRaises(CLIError) as ctx:
            cmd_profile_build(args)

        self.assertIn("no layout", str(ctx.exception))

    @patch("phone.cli.cmd_profile.read_yaml")
    def test_plan_filenot_found_raises_cli_error(self, mock_read):
        """Happy-path pair: CLIError raised when plan file not found."""
        from core.cli_errors import CLIError
        from phone.cli.cmd_profile import cmd_profile_build

        mock_read.side_effect = FileNotFoundError("no plan")
        args = make_profile_build_args(plan="missing_plan.yaml")

        with self.assertRaises(CLIError) as ctx:
            cmd_profile_build(args)

        self.assertIn("no plan", str(ctx.exception))

    @patch("phone.cli.cmd_profile._write_mobileconfig")
    @patch("phone.cli.cmd_profile.build_mobileconfig", return_value={"payload": "data"})
    @patch("phone.cli.cmd_profile._build_all_apps_folder_config")
    @patch("phone.cli.cmd_profile.read_yaml")
    def test_valueerror_from_all_apps_folder_raises_cli_error(
        self, mock_read, mock_folder, mock_build, mock_write
    ):
        """Lines 247-255: CLIError raised when _build_all_apps_folder_config raises ValueError."""
        from core.cli_errors import CLIError
        from phone.cli.cmd_profile import cmd_profile_build

        mock_read.return_value = make_mock_plan()
        mock_folder.side_effect = ValueError("--all-apps-folder-* requires --layout")
        args = make_profile_build_args(
            plan="plan.yaml",
            all_apps_folder_name="All Apps",
            layout=None,
        )

        with self.assertRaises(CLIError) as ctx:
            cmd_profile_build(args)

        self.assertIn("--all-apps-folder-*", str(ctx.exception))

    @patch("phone.cli.cmd_profile._write_mobileconfig")
    @patch("phone.cli.cmd_profile.build_mobileconfig", return_value={"payload": "data"})
    @patch("phone.cli.cmd_profile._build_all_apps_folder_config", return_value=None)
    @patch("phone.cli.cmd_profile.read_yaml")
    def test_no_signing_when_sign_p12_not_set(
        self, mock_read, mock_folder, mock_build, mock_write
    ):
        """Happy path: no signing occurs when sign_p12 is None (branch 279 not taken)."""
        from phone.cli.cmd_profile import cmd_profile_build

        mock_read.return_value = make_mock_plan()
        args = make_profile_build_args(plan="plan.yaml", sign_p12=None)

        with patch("phone.cli.cmd_profile._sign_mobileconfig") as mock_sign:
            result = cmd_profile_build(args)

        self.assertEqual(result, 0)
        mock_sign.assert_not_called()


class TestCmdProfileBuildSigning(unittest.TestCase):
    """Tests for cmd_profile_build signing path."""

    @patch("phone.cli.cmd_profile._sign_mobileconfig")
    @patch("phone.cli.cmd_profile._write_mobileconfig")
    @patch("phone.cli.cmd_profile.build_mobileconfig", return_value={"payload": "data"})
    @patch("phone.cli.cmd_profile._build_all_apps_folder_config", return_value=None)
    @patch("phone.cli.cmd_profile.read_yaml")
    def test_signing_invoked_when_sign_p12_set(
        self, mock_read, mock_folder, mock_build, mock_write, mock_sign
    ):
        """Lines 280-287, branch 279->280: _sign_mobileconfig called when sign_p12 is set."""
        from phone.cli.cmd_profile import cmd_profile_build

        mock_read.return_value = make_mock_plan()
        args = make_profile_build_args(
            plan="plan.yaml",
            out="out/test.mobileconfig",
            sign_p12="cert.p12",
            sign_pass=FAKE_P12_PASS,
        )

        result = cmd_profile_build(args)

        self.assertEqual(result, 0)
        mock_sign.assert_called_once()
        call_args = mock_sign.call_args[0]
        # Third positional arg should be the p12 path
        self.assertEqual(call_args[2], Path("cert.p12"))
        # Fourth positional arg should be the password
        self.assertEqual(call_args[3], FAKE_P12_PASS)

    @patch("phone.cli.cmd_profile._write_mobileconfig")
    @patch("phone.cli.cmd_profile.build_mobileconfig", return_value={"payload": "data"})
    @patch("phone.cli.cmd_profile._build_all_apps_folder_config", return_value=None)
    @patch("phone.cli.cmd_profile.read_yaml")
    def test_signing_uses_env_var_when_sign_pass_not_provided(
        self, mock_read, mock_folder, mock_build, mock_write
    ):
        """Lines 280-281: sign_pass falls back to IOS_SIGN_PASS env var."""
        from phone.cli.cmd_profile import cmd_profile_build

        mock_read.return_value = make_mock_plan()
        args = make_profile_build_args(
            plan="plan.yaml",
            sign_p12="cert.p12",
            sign_pass=None,
        )

        with patch("phone.cli.cmd_profile._sign_mobileconfig") as mock_sign:
            with patch.dict("os.environ", {"IOS_SIGN_PASS": "env_secret"}):
                cmd_profile_build(args)

        mock_sign.assert_called_once()
        call_args = mock_sign.call_args[0]
        self.assertEqual(call_args[3], "env_secret")

    @patch("phone.cli.cmd_profile._write_mobileconfig")
    @patch("phone.cli.cmd_profile.build_mobileconfig", return_value={"payload": "data"})
    @patch("phone.cli.cmd_profile._build_all_apps_folder_config", return_value=None)
    @patch("phone.cli.cmd_profile.read_yaml")
    def test_signing_failure_raises_cli_error(
        self, mock_read, mock_folder, mock_build, mock_write
    ):
        """Lines 285-286: CLIError raised on CalledProcessError during signing."""
        from core.cli_errors import CLIError
        from phone.cli.cmd_profile import cmd_profile_build

        mock_read.return_value = make_mock_plan()
        args = make_profile_build_args(
            plan="plan.yaml",
            sign_p12="cert.p12",
            sign_pass=FAKE_P12_PASS,
        )

        with patch(
            "phone.cli.cmd_profile._sign_mobileconfig",
            side_effect=subprocess.CalledProcessError(1, "openssl"),
        ):
            with self.assertRaises(CLIError) as ctx:
                cmd_profile_build(args)

        self.assertIn("signing", str(ctx.exception).lower())


class TestSignMobileconfig(unittest.TestCase):
    """Tests for _sign_mobileconfig subprocess orchestration."""

    def _paths(self, tmpdir: str):
        d = Path(tmpdir)
        return d / "unsigned.mobileconfig", d / "signed.mobileconfig", d / "cert.p12"

    @patch("phone.cli.cmd_profile.subprocess.run")
    def test_makes_four_subprocess_calls(self, mock_run):
        """Lines 104-173: four subprocess.run calls: help, cert extract, key extract, sign."""
        from phone.cli.cmd_profile import _sign_mobileconfig

        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            in_path, out_path, p12_path = self._paths(tmpdir)
            _sign_mobileconfig(in_path, out_path, p12_path, "test_pass")

        self.assertEqual(mock_run.call_count, 4)

    @patch("phone.cli.cmd_profile.subprocess.run")
    def test_adds_legacy_flag_when_supported(self, mock_run):
        """Line 107: -legacy flag is added when openssl pkcs12 --help mentions -legacy."""
        from phone.cli.cmd_profile import _sign_mobileconfig

        help_result = MagicMock(stdout="-legacy", stderr="", returncode=0)
        normal_result = MagicMock(stdout="", stderr="", returncode=0)
        mock_run.side_effect = [help_result, normal_result, normal_result, normal_result]

        with tempfile.TemporaryDirectory() as tmpdir:
            in_path, out_path, p12_path = self._paths(tmpdir)
            _sign_mobileconfig(in_path, out_path, p12_path, "test_pass")

        # Second call (cert extraction) should include -legacy
        cert_cmd = mock_run.call_args_list[1][0][0]
        self.assertIn("-legacy", cert_cmd)

    @patch("phone.cli.cmd_profile.subprocess.run")
    def test_no_legacy_flag_when_not_supported(self, mock_run):
        """Line 107: -legacy flag omitted when openssl output does not mention it."""
        from phone.cli.cmd_profile import _sign_mobileconfig

        help_result = MagicMock(stdout="standard openssl help", stderr="", returncode=0)
        normal_result = MagicMock(stdout="", stderr="", returncode=0)
        mock_run.side_effect = [help_result, normal_result, normal_result, normal_result]

        with tempfile.TemporaryDirectory() as tmpdir:
            in_path, out_path, p12_path = self._paths(tmpdir)
            _sign_mobileconfig(in_path, out_path, p12_path, "pass")

        cert_cmd = mock_run.call_args_list[1][0][0]
        self.assertNotIn("-legacy", cert_cmd)

    @patch("phone.cli.cmd_profile.subprocess.run")
    def test_passes_password_via_env_var(self, mock_run):
        """Lines 111, 114-131: password passed as _IOS_P12_PASS env var, not as argv."""
        from phone.cli.cmd_profile import _sign_mobileconfig

        help_result = MagicMock(stdout="", stderr="", returncode=0)
        normal_result = MagicMock(stdout="", stderr="", returncode=0)
        mock_run.side_effect = [help_result, normal_result, normal_result, normal_result]

        with tempfile.TemporaryDirectory() as tmpdir:
            in_path, out_path, p12_path = self._paths(tmpdir)
            _sign_mobileconfig(in_path, out_path, p12_path, "my_secret")

        # Cert extraction call (index 1): env must contain the password
        cert_call_kwargs = mock_run.call_args_list[1][1]
        self.assertIn("env", cert_call_kwargs)
        self.assertEqual(cert_call_kwargs["env"]["_IOS_P12_PASS"], "my_secret")

        # Password must not appear as a command-line argument
        cert_cmd = mock_run.call_args_list[1][0][0]
        self.assertNotIn("my_secret", cert_cmd)

    @patch("phone.cli.cmd_profile.subprocess.run")
    def test_uses_passin_env_flag(self, mock_run):
        """Lines 114-131: subprocess call uses -passin env:_IOS_P12_PASS."""
        from phone.cli.cmd_profile import _sign_mobileconfig

        help_result = MagicMock(stdout="", stderr="", returncode=0)
        normal_result = MagicMock(stdout="", stderr="", returncode=0)
        mock_run.side_effect = [help_result, normal_result, normal_result, normal_result]

        with tempfile.TemporaryDirectory() as tmpdir:
            in_path, out_path, p12_path = self._paths(tmpdir)
            _sign_mobileconfig(in_path, out_path, p12_path, "pass")

        cert_cmd = mock_run.call_args_list[1][0][0]
        self.assertIn("-passin", cert_cmd)
        passin_idx = cert_cmd.index("-passin")
        self.assertEqual(cert_cmd[passin_idx + 1], "env:_IOS_P12_PASS")

    @patch("phone.cli.cmd_profile.subprocess.run")
    def test_raises_on_subprocess_failure(self, mock_run):
        """Signing step propagates CalledProcessError when openssl fails."""
        from phone.cli.cmd_profile import _sign_mobileconfig

        help_result = MagicMock(stdout="", stderr="", returncode=0)
        mock_run.side_effect = [
            help_result,
            subprocess.CalledProcessError(1, "openssl"),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            in_path, out_path, p12_path = self._paths(tmpdir)
            with self.assertRaises(subprocess.CalledProcessError):
                _sign_mobileconfig(in_path, out_path, p12_path, "pass")


if __name__ == "__main__":
    unittest.main()
