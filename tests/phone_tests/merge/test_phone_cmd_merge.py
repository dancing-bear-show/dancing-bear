"""Tests for phone CLI merge-folders and reorg commands.

Covers cmd_merge_folders, cmd_reorg, and their helpers. All subprocess/cfgutil
interactions are mocked — no real device or network is required. The 625
copy-then-tap success path (the macOS-26 install contract) is the key case.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from tests.phone_tests.cli.fixtures import make_args

# A minimal synthetic layout: dock + page-1 loose apps + page-2 folders
# including an "Other" dump folder and a loose page-2 app.
_LAYOUT = {
    "dock": ["com.dock.a", "com.dock.b"],
    "pages": [
        {"apps": ["com.apple.mobilesafari", "com.apple.Preferences"], "folders": []},
        {
            "apps": ["com.spothero.spothero"],
            "folders": [
                {"name": "Media", "apps": ["com.netflix.Netflix"]},
                {"name": "Travel", "apps": ["com.ubercab.UberClient"]},
                {"name": "Other", "apps": ["com.chase", "com.burbn.instagram"]},
            ],
        },
    ],
}


def _write_layout(dir_path: Path, layout: dict = None) -> Path:
    """Write a layout YAML into dir_path and return its path."""
    p = dir_path / "ios.IconState.yaml"
    p.write_text(yaml.safe_dump(layout if layout is not None else _LAYOUT))
    return p


def _cfg_result(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    """Build a fake subprocess.CompletedProcess-like object."""
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# cfgutil's real "profile copied, awaiting tap" message (exit code is 1).
_CFG_625 = (
    "cfgutil: error: User interaction on the device is required to install "
    "this profile.\n(Domain: ConfigurationUtilityKit.error Code: 625)\n"
)


class TestCmdMergeFolders(unittest.TestCase):
    """cmd_merge_folders: plan generation, conservation, error paths."""

    def test_writes_plan_and_returns_zero(self):
        from phone.cli.cmd_merge import cmd_merge_folders

        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            layout = _write_layout(dp)
            plan_out = dp / "plan.yaml"
            args = make_args(
                layout=str(layout), plan=str(plan_out), keep="", dump_folder_names=""
            )

            rc = cmd_merge_folders(args)

            self.assertEqual(rc, 0)
            self.assertTrue(plan_out.exists())
            plan = yaml.safe_load(plan_out.read_text())
            # Other dump folder eliminated; its apps redistributed.
            self.assertNotIn("Other", plan["folders"])

    def test_missing_layout_returns_two(self):
        from phone.cli.cmd_merge import cmd_merge_folders

        with tempfile.TemporaryDirectory() as d:
            args = make_args(
                layout=str(Path(d) / "nonexistent.yaml"),
                plan=str(Path(d) / "should-not-write.yaml"),
                keep="",
                dump_folder_names="",
            )

            rc = cmd_merge_folders(args)

        self.assertEqual(rc, 2)

    def test_conservation_failure_returns_one(self):
        from phone.cli.cmd_merge import cmd_merge_folders

        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            layout = _write_layout(dp)
            plan_out = dp / "plan.yaml"
            args = make_args(
                layout=str(layout), plan=str(plan_out), keep="", dump_folder_names=""
            )

            # Force a plan that drops an app so verify_conservation raises.
            bad_plan = MagicMock()
            bad_plan.to_dict.return_value = {"dock": [], "pins": [], "folders": {}}
            bad_plan.folders = {}
            with patch("phone.cli.cmd_merge.merge_folders", return_value=bad_plan):
                rc = cmd_merge_folders(args)

            self.assertEqual(rc, 1)

    def test_keep_and_dump_args_parsed(self):
        from phone.cli.cmd_merge import cmd_merge_folders

        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            layout = _write_layout(dp)
            plan_out = dp / "plan.yaml"
            args = make_args(
                layout=str(layout),
                plan=str(plan_out),
                keep="com.apple.mobilesafari, com.apple.Preferences",
                dump_folder_names="Other",
            )

            captured = {}
            real = __import__("phone.layout_merge", fromlist=["merge_folders"]).merge_folders

            def spy(layout_arg, keep=None, dump_folders=None):
                captured["keep"] = keep
                captured["dump_folders"] = dump_folders
                return real(layout_arg, keep=keep, dump_folders=dump_folders)

            with patch("phone.cli.cmd_merge.merge_folders", side_effect=spy):
                rc = cmd_merge_folders(args)

            self.assertEqual(rc, 0)
            self.assertEqual(
                captured["keep"], ["com.apple.mobilesafari", "com.apple.Preferences"]
            )
            self.assertEqual(captured["dump_folders"], ["Other"])


class TestReorgInstall625(unittest.TestCase):
    """_reorg_install: the macOS-26 copy-then-tap (625) contract."""

    def test_625_message_is_success(self):
        """cfgutil exits 1 with the 625 phrase → treated as SUCCESS (rc 0)."""
        from phone.cli.cmd_merge import _reorg_install

        with patch("phone.cli.cmd_merge.find_cfgutil_path", return_value="/usr/bin/cfgutil"), \
             patch("phone.cli.cmd_merge.map_udid_to_ecid", return_value=None), \
             patch(
                 "phone.cli.cmd_merge.subprocess.run",
                 return_value=_cfg_result(1, stderr=_CFG_625),
             ):
            rc = _reorg_install(
                dry_run=False, no_install=False,
                out_profile=Path("out/x.mobileconfig"), udid="",
            )

        self.assertEqual(rc, 0)

    def test_625_success_suppresses_raw_cfgutil_error(self):
        """On the 625 success path, cfgutil's raw 'error:' line is NOT printed."""
        import contextlib
        import io
        from phone.cli.cmd_merge import _reorg_install

        out, err = io.StringIO(), io.StringIO()
        with patch("phone.cli.cmd_merge.find_cfgutil_path", return_value="/usr/bin/cfgutil"), \
             patch("phone.cli.cmd_merge.map_udid_to_ecid", return_value=None), \
             patch(
                 "phone.cli.cmd_merge.subprocess.run",
                 return_value=_cfg_result(1, stderr=_CFG_625),
             ), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = _reorg_install(False, False, Path("out/x.mobileconfig"), "")

        self.assertEqual(rc, 0)
        combined = out.getvalue() + err.getvalue()
        self.assertNotIn("cfgutil: error:", combined)
        self.assertIn("Profile copied to device", out.getvalue())

    def test_clean_success_rc0(self):
        from phone.cli.cmd_merge import _reorg_install

        with patch("phone.cli.cmd_merge.find_cfgutil_path", return_value="/usr/bin/cfgutil"), \
             patch("phone.cli.cmd_merge.map_udid_to_ecid", return_value=None), \
             patch(
                 "phone.cli.cmd_merge.subprocess.run",
                 return_value=_cfg_result(0, stdout="ok"),
             ):
            rc = _reorg_install(False, False, Path("out/x.mobileconfig"), "")

        self.assertEqual(rc, 0)

    def test_device_locked_is_failure(self):
        """A genuine error (4009, no 625 phrase) must NOT be a success."""
        from phone.cli.cmd_merge import _reorg_install

        locked = (
            "cfgutil: error: The device is locked.\n"
            "(Domain: MCInstallationErrorDomain Code: 4009)\n"
        )
        with patch("phone.cli.cmd_merge.find_cfgutil_path", return_value="/usr/bin/cfgutil"), \
             patch("phone.cli.cmd_merge.map_udid_to_ecid", return_value=None), \
             patch(
                 "phone.cli.cmd_merge.subprocess.run",
                 return_value=_cfg_result(1, stderr=locked),
             ):
            rc = _reorg_install(False, False, Path("out/x.mobileconfig"), "")

        self.assertNotEqual(rc, 0)

    def test_no_devices_is_failure(self):
        from phone.cli.cmd_merge import _reorg_install

        with patch("phone.cli.cmd_merge.find_cfgutil_path", return_value="/usr/bin/cfgutil"), \
             patch("phone.cli.cmd_merge.map_udid_to_ecid", return_value=None), \
             patch(
                 "phone.cli.cmd_merge.subprocess.run",
                 return_value=_cfg_result(1, stderr="cfgutil: error: no devices found"),
             ):
            rc = _reorg_install(False, False, Path("out/x.mobileconfig"), "")

        self.assertNotEqual(rc, 0)

    def test_bare_625_substring_not_success(self):
        """Output containing '625' but not the cfgutil phrase is NOT success."""
        from phone.cli.cmd_merge import _reorg_install

        with patch("phone.cli.cmd_merge.find_cfgutil_path", return_value="/usr/bin/cfgutil"), \
             patch("phone.cli.cmd_merge.map_udid_to_ecid", return_value=None), \
             patch(
                 "phone.cli.cmd_merge.subprocess.run",
                 return_value=_cfg_result(1, stdout="installed 625 profiles earlier"),
             ):
            rc = _reorg_install(False, False, Path("out/x.mobileconfig"), "")

        self.assertNotEqual(rc, 0)

    def test_no_cfgutil_returns_error(self):
        from phone.cli.cmd_merge import _reorg_install

        with patch("phone.cli.cmd_merge.find_cfgutil_path", side_effect=FileNotFoundError):
            rc = _reorg_install(False, False, Path("out/x.mobileconfig"), "")

        self.assertNotEqual(rc, 0)

    def test_no_install_skips_cfgutil(self):
        from phone.cli.cmd_merge import _reorg_install

        with patch("phone.cli.cmd_merge.subprocess.run") as run:
            rc = _reorg_install(
                dry_run=False, no_install=True,
                out_profile=Path("out/x.mobileconfig"), udid="",
            )

        self.assertEqual(rc, 0)
        run.assert_not_called()


class TestCmdReorg(unittest.TestCase):
    """cmd_reorg: dry-run / no-install orchestration (subprocess mocked)."""

    def test_dry_run_skips_build_and_install(self):
        from phone.cli.cmd_merge import cmd_reorg

        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            # dry-run uses existing layout at the default path; patch output_dir
            # so the default resolves inside the temp directory.
            _write_layout(dp)
            with patch("phone.cli.cmd_merge.output_dir", return_value=dp), \
                 patch("phone.cli.cmd_merge.subprocess.run") as run:
                args = make_args(
                    device_label="bcsphone", udid=None, keep="",
                    out=None, no_install=False, dry_run=True,
                    install_only=False, profile_path=None,
                )
                rc = cmd_reorg(args)

            self.assertEqual(rc, 0)
            # No subprocess (export/build/install) runs in dry-run.
            run.assert_not_called()

    def test_no_install_builds_but_skips_device_copy(self):
        from phone.cli.cmd_merge import cmd_reorg

        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)

            # export + build run via subprocess; make them succeed and have the
            # export step produce the layout file reorg reads next.
            # Patch output_dir so default paths resolve inside the temp directory.
            layout_target = dp / "ios.IconState.yaml"

            def fake_run(cmd, *a, **k):
                if "export-device" in cmd:
                    layout_target.write_text(yaml.safe_dump(_LAYOUT))
                return _cfg_result(0)

            with patch("phone.cli.cmd_merge.output_dir", return_value=dp), \
                 patch("phone.cli.cmd_merge.subprocess.run", side_effect=fake_run), \
                 patch("phone.cli.cmd_merge.find_cfgutil_path", return_value="/usr/bin/cfgutil"):
                args = make_args(
                    device_label="bcsphone", udid="UDID-X", keep="",
                    out=None, no_install=True, dry_run=False,
                    install_only=False, profile_path=None,
                )
                rc = cmd_reorg(args)

            self.assertEqual(rc, 0)


class TestUdidForLabel(unittest.TestCase):
    """_udid_for_label: resolve device label → UDID from credentials.ini."""

    def _write_creds(self, dir_path: Path) -> Path:
        p = dir_path / "credentials.ini"
        p.write_text("[ios_devices]\nbcsphone = 00008150-ABCDEF\n")
        return p

    def test_known_label_resolves(self):
        from phone.cli.cmd_merge import _udid_for_label

        with tempfile.TemporaryDirectory() as d:
            creds = self._write_creds(Path(d))
            with patch.dict(os.environ, {"IOS_CREDS_FILE": str(creds)}):
                self.assertEqual(_udid_for_label("bcsphone"), "00008150-ABCDEF")

    def test_unknown_label_returns_none(self):
        from phone.cli.cmd_merge import _udid_for_label

        with tempfile.TemporaryDirectory() as d:
            creds = self._write_creds(Path(d))
            with patch.dict(os.environ, {"IOS_CREDS_FILE": str(creds)}):
                self.assertIsNone(_udid_for_label("nope"))

    def test_missing_file_returns_none(self):
        from phone.cli.cmd_merge import _udid_for_label

        with patch.dict(os.environ, {"IOS_CREDS_FILE": "/nonexistent/creds.ini"}):
            # Also ensure the ~/.config fallback doesn't accidentally match.
            self.assertIn(_udid_for_label("zzz-unlikely-label"), (None,))


class TestDefaultDeviceLabel(unittest.TestCase):
    """Configurable default device label ([ios_devices] default = <label>)."""

    def _creds(self, dir_path: Path, body: str) -> Path:
        p = dir_path / "credentials.ini"
        p.write_text(body)
        return p

    def test_default_label_read_from_config(self):
        from phone.cli import cmd_merge

        with tempfile.TemporaryDirectory() as d:
            creds = self._creds(
                Path(d), "[ios_devices]\ndefault = bcsphone\nbcsphone = 00008150-X\n"
            )
            with patch.dict(os.environ, {"IOS_CREDS_FILE": str(creds)}), \
                 patch("core.constants.credential_ini_paths", return_value=[str(creds)]):
                self.assertEqual(cmd_merge._default_device_label(), "bcsphone")

    def test_no_default_returns_none(self):
        from phone.cli import cmd_merge

        with tempfile.TemporaryDirectory() as d:
            creds = self._creds(Path(d), "[ios_devices]\nbcsphone = 00008150-X\n")
            with patch.dict(os.environ, {"IOS_CREDS_FILE": str(creds)}), \
                 patch("core.constants.credential_ini_paths", return_value=[str(creds)]):
                self.assertIsNone(cmd_merge._default_device_label())

    def test_reorg_uses_configured_default_when_no_flag(self):
        from phone.cli.cmd_merge import _resolve_reorg_udid

        with tempfile.TemporaryDirectory() as d:
            creds = self._creds(
                Path(d), "[ios_devices]\ndefault = bcsphone\nbcsphone = 00008150-X\n"
            )
            args = make_args(udid=None, device_label=None)
            with patch.dict(os.environ, {"IOS_CREDS_FILE": str(creds), "IOS_DEVICE_UDID": ""}), \
                 patch("core.constants.credential_ini_paths", return_value=[str(creds)]):
                udid, rc = _resolve_reorg_udid(args, dry_run=False)
            self.assertEqual(rc, 0)
            self.assertEqual(udid, "00008150-X")

    def test_reorg_no_default_falls_back_to_autodetect(self):
        """No flag + no configured default → empty udid (cfgutil auto-detects), rc 0."""
        from phone.cli.cmd_merge import _resolve_reorg_udid

        with tempfile.TemporaryDirectory() as d:
            creds = self._creds(Path(d), "[ios_devices]\nfoo = ABC\n")
            args = make_args(udid=None, device_label=None)
            with patch.dict(os.environ, {"IOS_CREDS_FILE": str(creds), "IOS_DEVICE_UDID": ""}), \
                 patch("core.constants.credential_ini_paths", return_value=[str(creds)]):
                udid, rc = _resolve_reorg_udid(args, dry_run=False)
            self.assertEqual(rc, 0)
            self.assertEqual(udid, "")

    def test_reorg_broken_default_fails_fast(self):
        """A CONFIGURED default label that has no UDID entry fails fast (not dry-run)."""
        from phone.cli.cmd_merge import _resolve_reorg_udid

        with tempfile.TemporaryDirectory() as d:
            creds = self._creds(
                Path(d), "[ios_devices]\ndefault = ghost\nbcsphone = 00008150-X\n"
            )
            args = make_args(udid=None, device_label=None)
            with patch.dict(os.environ, {"IOS_CREDS_FILE": str(creds), "IOS_DEVICE_UDID": ""}), \
                 patch("core.constants.credential_ini_paths", return_value=[str(creds)]):
                _, rc = _resolve_reorg_udid(args, dry_run=False)
            self.assertEqual(rc, 1)

    def test_reorg_broken_default_dry_run_is_lenient(self):
        """Under --dry-run, a broken configured default does not error."""
        from phone.cli.cmd_merge import _resolve_reorg_udid

        with tempfile.TemporaryDirectory() as d:
            creds = self._creds(
                Path(d), "[ios_devices]\ndefault = ghost\nbcsphone = 00008150-X\n"
            )
            args = make_args(udid=None, device_label=None)
            with patch.dict(os.environ, {"IOS_CREDS_FILE": str(creds), "IOS_DEVICE_UDID": ""}), \
                 patch("core.constants.credential_ini_paths", return_value=[str(creds)]):
                udid, rc = _resolve_reorg_udid(args, dry_run=True)
            self.assertEqual(rc, 0)
            self.assertEqual(udid, "")

    def test_reorg_explicit_unknown_label_fails_fast(self):
        """An EXPLICIT unresolvable label errors, even when a default exists."""
        from phone.cli.cmd_merge import _resolve_reorg_udid

        with tempfile.TemporaryDirectory() as d:
            creds = self._creds(
                Path(d), "[ios_devices]\ndefault = bcsphone\nbcsphone = 00008150-X\n"
            )
            args = make_args(udid=None, device_label="no-such-device")
            with patch.dict(os.environ, {"IOS_CREDS_FILE": str(creds), "IOS_DEVICE_UDID": ""}), \
                 patch("core.constants.credential_ini_paths", return_value=[str(creds)]):
                _, rc = _resolve_reorg_udid(args, dry_run=False)
            self.assertEqual(rc, 1)


class TestResolveEcid(unittest.TestCase):
    """map_udid_to_ecid: parse cfgutil list output for a UDID's ECID."""

    def test_matches_udid_line(self):
        from phone.device import map_udid_to_ecid

        listing = (
            "Type: iPhone18,2\tECID: 0x578D421D8401C\t"
            "UDID: 00008150-000578D421D8401C Name: Brian Phone\n"
        )
        with patch("phone.device.subprocess.check_output", return_value=listing):
            ecid = map_udid_to_ecid("/usr/bin/cfgutil", "00008150-000578D421D8401C")

        self.assertEqual(ecid, "0x578D421D8401C")

    def test_absent_udid_returns_empty(self):
        from phone.device import map_udid_to_ecid

        with patch("phone.device.subprocess.check_output",
                   return_value="Type: iPhone\tECID: 0xAAA\tUDID: other\n"):
            ecid = map_udid_to_ecid("/usr/bin/cfgutil", "00008150-NOTHERE")

        self.assertEqual(ecid, "")


class TestKeepConservation(unittest.TestCase):
    def test_keep_app_in_preserved_folder(self):
        """Fix 1: --keep strips app from its folder and adds it to pins; conservation PASS."""
        from phone.cli.cmd_merge import cmd_merge_folders

        layout = {
            "dock": ["com.dock.a"],
            "pages": [
                {"apps": ["com.apple.mobilesafari"], "folders": []},
                {
                    "apps": [],
                    "folders": [
                        {"name": "Work", "apps": ["com.microsoft.Office.Word", "com.slack"]},
                        {"name": "Media", "apps": ["com.netflix.Netflix"]},
                        {"name": "Other", "apps": ["com.burbn.instagram"]},
                    ],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            layout_path = dp / "layout.yaml"
            layout_path.write_text(yaml.safe_dump(layout))
            plan_out = dp / "plan.yaml"
            args = make_args(
                layout=str(layout_path),
                plan=str(plan_out),
                keep="com.microsoft.Office.Word",
                dump_folder_names="Other",
            )
            rc = cmd_merge_folders(args)
            self.assertEqual(rc, 0)
            plan = yaml.safe_load(plan_out.read_text())
            # App must be in pins
            self.assertIn("com.microsoft.Office.Word", plan["pins"])
            # App must NOT be in Work folder
            self.assertNotIn("com.microsoft.Office.Word", plan["folders"].get("Work", []))

    def test_keep_absent_bundle_warns_no_error(self):
        """Fix 1: --keep with bundle ID not in layout → warned, conservation PASS."""
        from phone.cli.cmd_merge import cmd_merge_folders

        layout = {
            "dock": [],
            "pages": [
                {"apps": ["com.apple.mobilesafari"], "folders": []},
                {
                    "apps": [],
                    "folders": [
                        {"name": "Work", "apps": ["com.slack"]},
                        {"name": "Other", "apps": ["com.burbn.instagram"]},
                    ],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            layout_path = dp / "layout.yaml"
            layout_path.write_text(yaml.safe_dump(layout))
            plan_out = dp / "plan.yaml"
            args = make_args(
                layout=str(layout_path),
                plan=str(plan_out),
                keep="com.nonexistent.app",
                dump_folder_names="Other",
            )
            rc = cmd_merge_folders(args)
        self.assertEqual(rc, 0)  # must NOT raise / return error


class TestCmdReorgFailFast(unittest.TestCase):
    def test_unresolvable_label_no_udid_returns_nonzero(self):
        """Fix 3: unresolvable device_label without --udid and not --dry-run → non-zero."""
        from phone.cli.cmd_merge import cmd_reorg

        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            (dp / "out").mkdir()
            with _chdir(dp), \
                 patch.dict(os.environ, {"IOS_DEVICE_UDID": "", "IOS_CREDS_FILE": "/nonexistent"}), \
                 patch("phone.cli.cmd_merge.subprocess.run") as run:
                args = make_args(
                    device_label="no-such-device",
                    udid=None,
                    keep="",
                    out=None,
                    no_install=False,
                    dry_run=False,
                )
                rc = cmd_reorg(args)

        self.assertNotEqual(rc, 0)
        run.assert_not_called()


class TestReorgMergeMissingLayout(unittest.TestCase):
    def test_missing_layout_returns_none_tuple(self):
        """Fix 7: _reorg_merge with missing layout → returns (None, False, 0), no exception."""
        from phone.cli.cmd_merge import _reorg_merge

        with tempfile.TemporaryDirectory() as d:
            result = _reorg_merge(
                Path(d) / "nonexistent.yaml",
                Path(d) / "plan.yaml",
                [],
            )

        plan_obj, dump_elim, loose = result
        self.assertIsNone(plan_obj)
        self.assertFalse(dump_elim)
        self.assertEqual(loose, 0)


class TestReorgInstallOnly(unittest.TestCase):
    """reorg --install-only: skip export/merge/build, install an existing profile."""

    def test_install_only_success_with_625(self):
        """--install-only with existing profile + cfgutil 625 → rc 0, no export/merge/build."""
        from phone.cli.cmd_merge import cmd_reorg

        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            (dp / "out").mkdir()
            profile = dp / "out" / "ios.merged.mobileconfig"
            profile.write_bytes(b"fake-profile")

            with _chdir(dp), \
                 patch("phone.cli.cmd_merge.find_cfgutil_path", return_value="/usr/bin/cfgutil"), \
                 patch("phone.cli.cmd_merge.map_udid_to_ecid", return_value=None), \
                 patch(
                     "phone.cli.cmd_merge.subprocess.run",
                     return_value=_cfg_result(1, stderr=_CFG_625),
                 ) as run:
                args = make_args(
                    device_label="bcsphone",
                    udid="UDID-X",
                    install_only=True,
                    no_install=False,
                    dry_run=False,
                    profile_path=str(profile),
                    out=None,
                    keep="",
                )
                rc = cmd_reorg(args)

        self.assertEqual(rc, 0)
        # subprocess.run must have been called once (cfgutil install-profile only)
        run.assert_called_once()
        call_cmd = run.call_args[0][0]
        self.assertIn("install-profile", call_cmd)
        # export-device must NOT have been called
        self.assertNotIn("export-device", call_cmd)

    def test_install_only_profile_not_found(self):
        """--install-only with nonexistent profile → nonzero, no cfgutil call."""
        from phone.cli.cmd_merge import cmd_reorg

        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            (dp / "out").mkdir()
            with _chdir(dp), \
                 patch("phone.cli.cmd_merge.subprocess.run") as run:
                args = make_args(
                    device_label="bcsphone",
                    udid="UDID-X",
                    install_only=True,
                    no_install=False,
                    dry_run=False,
                    profile_path=str(dp / "out" / "nonexistent.mobileconfig"),
                    out=None,
                    keep="",
                )
                rc = cmd_reorg(args)

        self.assertNotEqual(rc, 0)
        run.assert_not_called()

    def test_install_only_and_no_install_are_mutually_exclusive(self):
        """--install-only + --no-install → error, nonzero."""
        from phone.cli.cmd_merge import cmd_reorg

        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            with _chdir(dp), \
                 patch("phone.cli.cmd_merge.subprocess.run") as run:
                args = make_args(
                    device_label="bcsphone",
                    udid="UDID-X",
                    install_only=True,
                    no_install=True,
                    dry_run=False,
                    profile_path=None,
                    out=None,
                    keep="",
                )
                rc = cmd_reorg(args)

        self.assertNotEqual(rc, 0)
        run.assert_not_called()

    def test_install_only_dry_run_no_subprocess(self):
        """--install-only --dry-run → prints, rc 0, no subprocess.run."""
        from phone.cli.cmd_merge import cmd_reorg

        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            (dp / "out").mkdir()
            profile = dp / "out" / "ios.merged.mobileconfig"
            profile.write_bytes(b"fake-profile")

            with _chdir(dp), \
                 patch("phone.cli.cmd_merge.subprocess.run") as run:
                args = make_args(
                    device_label="bcsphone",
                    udid="UDID-X",
                    install_only=True,
                    no_install=False,
                    dry_run=True,
                    profile_path=str(profile),
                    out=None,
                    keep="",
                )
                rc = cmd_reorg(args)

        self.assertEqual(rc, 0)
        run.assert_not_called()


class _chdir:
    """Context manager to temporarily change the working directory."""

    def __init__(self, path: Path):
        self._path = str(path)
        self._prev = None

    def __enter__(self):
        self._prev = os.getcwd()
        os.chdir(self._path)
        return self

    def __exit__(self, *exc):
        os.chdir(self._prev)
        return False


if __name__ == "__main__":
    unittest.main()
