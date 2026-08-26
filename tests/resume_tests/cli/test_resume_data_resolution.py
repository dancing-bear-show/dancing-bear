"""Tests for --data resolution from the profile config directory.

`--profile` previously affected only the OUTPUT filename, so every invocation
had to repeat an absolute path to data that already lives at a predictable
location. `_resolve_data` closes that gap, mirroring how mail resolves its
unified filter config.

Sad-path methods use the test_rejects_* / test_invalid_* naming contract.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.cli_errors import CLIError
from resume.cli.main import _resolve_data


def _args(**kw):
    ns = argparse.Namespace(data=None, profile=None)
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


class TestResolveData(unittest.TestCase):
    """--data wins when given; otherwise fall back to the profile directory."""

    def test_explicit_data_path_wins(self):
        """A caller who names a path means it — no config lookup at all."""
        self.assertEqual(
            _resolve_data(_args(data="/tmp/explicit.json", profile="brian")),
            "/tmp/explicit.json",
        )

    def test_explicit_data_wins_even_when_profile_file_exists(self):
        """The override must not be shadowed by a present profile file."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "resume" / "brian"
            base.mkdir(parents=True)
            (base / "data.json").write_text("{}")
            with patch("resume.cli.main.config_home", return_value=Path(tmp)):
                self.assertEqual(
                    _resolve_data(_args(data="/tmp/wins.json", profile="brian")),
                    "/tmp/wins.json",
                )

    def test_resolves_json_from_profile_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "resume" / "brian"
            base.mkdir(parents=True)
            target = base / "data.json"
            target.write_text(json.dumps({"name": "Test"}))
            with patch("resume.cli.main.config_home", return_value=Path(tmp)):
                self.assertEqual(_resolve_data(_args(profile="brian")), str(target))

    def test_resolves_yaml_variants(self):
        """data.yaml and data.yml are accepted, not just JSON."""
        for filename in ("data.yaml", "data.yml"):
            with self.subTest(filename=filename):
                with tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp) / "resume" / "p"
                    base.mkdir(parents=True)
                    target = base / filename
                    target.write_text("name: Test\n")
                    with patch("resume.cli.main.config_home", return_value=Path(tmp)):
                        self.assertEqual(
                            _resolve_data(_args(profile="p")), str(target)
                        )

    def test_prefers_json_over_yaml_when_both_exist(self):
        """Deterministic precedence, so the same command never flips sources."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "resume" / "p"
            base.mkdir(parents=True)
            (base / "data.json").write_text("{}")
            (base / "data.yaml").write_text("name: y\n")
            with patch("resume.cli.main.config_home", return_value=Path(tmp)):
                self.assertTrue(_resolve_data(_args(profile="p")).endswith("data.json"))

    def test_falls_back_to_default_profile(self):
        """No --profile means the default profile's directory."""
        from resume.cli.main import DEFAULT_PROFILE

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "resume" / DEFAULT_PROFILE
            base.mkdir(parents=True)
            target = base / "data.json"
            target.write_text("{}")
            with patch("resume.cli.main.config_home", return_value=Path(tmp)):
                self.assertEqual(_resolve_data(_args()), str(target))

    def test_rejects_missing_profile_directory(self):
        """A clear CLIError, not a traceback or a silent empty render."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch("resume.cli.main.config_home", return_value=Path(tmp)):
                with self.assertRaises(CLIError) as ctx:
                    _resolve_data(_args(profile="nonexistent"))
        msg = str(ctx.exception)
        self.assertIn("nonexistent", msg)
        self.assertIn("data.json", msg)
        self.assertIn("--data", msg)

    def test_rejects_profile_dir_without_a_data_file(self):
        """An existing but empty profile directory is still an error."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "resume" / "empty").mkdir(parents=True)
            with patch("resume.cli.main.config_home", return_value=Path(tmp)):
                with self.assertRaises(CLIError):
                    _resolve_data(_args(profile="empty"))

    def test_rejects_directory_named_data_json(self):
        """A directory named data.json must not satisfy the lookup.

        exists() is True for a directory, so the check uses is_file(); without
        it the caller gets an IsADirectoryError from deep inside the reader
        instead of the actionable message here.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "resume" / "p"
            (base / "data.json").mkdir(parents=True)
            with patch("resume.cli.main.config_home", return_value=Path(tmp)):
                with self.assertRaises(CLIError):
                    _resolve_data(_args(profile="p"))

    def test_skips_directory_and_finds_real_file(self):
        """A bogus data.json directory must not mask a valid data.yaml."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "resume" / "p"
            (base / "data.json").mkdir(parents=True)
            target = base / "data.yaml"
            target.write_text("name: Test\n")
            with patch("resume.cli.main.config_home", return_value=Path(tmp)):
                self.assertEqual(_resolve_data(_args(profile="p")), str(target))


if __name__ == "__main__":
    unittest.main()
