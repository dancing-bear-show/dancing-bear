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

        with patch("phone.cli.cmd_merge._resolve_cfgutil", return_value="/usr/bin/cfgutil"), \
             patch("phone.cli.cmd_merge._resolve_ecid", return_value=None), \
             patch(
                 "phone.cli.cmd_merge.subprocess.run",
                 return_value=_cfg_result(1, stderr=_CFG_625),
             ):
            rc = _reorg_install(
                dry_run=False, no_install=False,
                out_profile=Path("out/x.mobileconfig"), udid="",
            )

        self.assertEqual(rc, 0)

    def test_clean_success_rc0(self):
        from phone.cli.cmd_merge import _reorg_install

        with patch("phone.cli.cmd_merge._resolve_cfgutil", return_value="/usr/bin/cfgutil"), \
             patch("phone.cli.cmd_merge._resolve_ecid", return_value=None), \
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
        with patch("phone.cli.cmd_merge._resolve_cfgutil", return_value="/usr/bin/cfgutil"), \
             patch("phone.cli.cmd_merge._resolve_ecid", return_value=None), \
             patch(
                 "phone.cli.cmd_merge.subprocess.run",
                 return_value=_cfg_result(1, stderr=locked),
             ):
            rc = _reorg_install(False, False, Path("out/x.mobileconfig"), "")

        self.assertNotEqual(rc, 0)

    def test_no_devices_is_failure(self):
        from phone.cli.cmd_merge import _reorg_install

        with patch("phone.cli.cmd_merge._resolve_cfgutil", return_value="/usr/bin/cfgutil"), \
             patch("phone.cli.cmd_merge._resolve_ecid", return_value=None), \
             patch(
                 "phone.cli.cmd_merge.subprocess.run",
                 return_value=_cfg_result(1, stderr="cfgutil: error: no devices found"),
             ):
            rc = _reorg_install(False, False, Path("out/x.mobileconfig"), "")

        self.assertNotEqual(rc, 0)

    def test_bare_625_substring_not_success(self):
        """Output containing '625' but not the cfgutil phrase is NOT success."""
        from phone.cli.cmd_merge import _reorg_install

        with patch("phone.cli.cmd_merge._resolve_cfgutil", return_value="/usr/bin/cfgutil"), \
             patch("phone.cli.cmd_merge._resolve_ecid", return_value=None), \
             patch(
                 "phone.cli.cmd_merge.subprocess.run",
                 return_value=_cfg_result(1, stdout="installed 625 profiles earlier"),
             ):
            rc = _reorg_install(False, False, Path("out/x.mobileconfig"), "")

        self.assertNotEqual(rc, 0)

    def test_no_cfgutil_returns_error(self):
        from phone.cli.cmd_merge import _reorg_install

        with patch("phone.cli.cmd_merge._resolve_cfgutil", return_value=None):
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
            # dry-run uses existing layout at the fixed default path; patch cwd
            # by writing the layout where reorg looks and chdir into temp.
            (dp / "out").mkdir()
            _write_layout(dp / "out")
            with _chdir(dp), patch("phone.cli.cmd_merge.subprocess.run") as run:
                args = make_args(
                    device_label="bcsphone", udid=None, keep="",
                    out=None, no_install=False, dry_run=True,
                )
                rc = cmd_reorg(args)

            self.assertEqual(rc, 0)
            # No subprocess (export/build/install) runs in dry-run.
            run.assert_not_called()

    def test_no_install_builds_but_skips_device_copy(self):
        from phone.cli.cmd_merge import cmd_reorg

        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            (dp / "out").mkdir()

            # export + build run via subprocess; make them succeed and have the
            # export step produce the layout file reorg reads next.
            layout_target = dp / "out" / "ios.IconState.yaml"

            def fake_run(cmd, *a, **k):
                if "export-device" in cmd:
                    layout_target.write_text(yaml.safe_dump(_LAYOUT))
                return _cfg_result(0)

            with _chdir(dp), \
                 patch("phone.cli.cmd_merge.subprocess.run", side_effect=fake_run), \
                 patch("phone.cli.cmd_merge._resolve_cfgutil", return_value="/usr/bin/cfgutil"):
                args = make_args(
                    device_label="bcsphone", udid="UDID-X", keep="",
                    out=None, no_install=True, dry_run=False,
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


class TestResolveEcid(unittest.TestCase):
    """_resolve_ecid: parse cfgutil list output for a UDID's ECID."""

    def test_matches_udid_line(self):
        from phone.cli.cmd_merge import _resolve_ecid

        listing = (
            "Type: iPhone18,2\tECID: 0x578D421D8401C\t"
            "UDID: 00008150-000578D421D8401C Name: Brian Phone\n"
        )
        with patch(
            "phone.cli.cmd_merge.subprocess.run",
            return_value=_cfg_result(0, stdout=listing),
        ):
            ecid = _resolve_ecid("/usr/bin/cfgutil", "00008150-000578D421D8401C")

        self.assertEqual(ecid, "0x578D421D8401C")

    def test_absent_udid_returns_none(self):
        from phone.cli.cmd_merge import _resolve_ecid

        with patch(
            "phone.cli.cmd_merge.subprocess.run",
            return_value=_cfg_result(0, stdout="Type: iPhone\tECID: 0xAAA\tUDID: other\n"),
        ):
            ecid = _resolve_ecid("/usr/bin/cfgutil", "00008150-NOTHERE")

        self.assertIsNone(ecid)


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
