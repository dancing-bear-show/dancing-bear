"""Tests for --data resolution from the profile config directory.

`--profile` previously affected only the OUTPUT filename, so every invocation
had to repeat an absolute path to data that already lives at a predictable
location. `_resolve_data` closes that gap, mirroring how mail resolves its
unified filter config.

Sad-path methods use the test_rejects_* / test_invalid_* naming contract.
"""

from __future__ import annotations

import argparse
import ast
import inspect
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


def _direct_args_data_calls(source: str | None = None) -> list[int]:
    """Return line numbers of ``read_yaml_or_json(args.data)`` call nodes.

    Walks the AST rather than scanning text: a call split across lines is
    invisible to a substring search, and the same characters inside a comment
    or docstring are not a call at all. ``source`` defaults to the resume CLI
    module.
    """
    if source is None:
        from resume.cli import main as cli_main

        source = inspect.getsource(cli_main)

    offenders: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != "read_yaml_or_json" or not node.args:
            continue
        first = node.args[0]
        if (
            isinstance(first, ast.Attribute)
            and first.attr == "data"
            and isinstance(first.value, ast.Name)
            and first.value.id == "args"
        ):
            offenders.append(node.lineno)
    return offenders


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


class TestEveryDataCommandUsesTheResolver(unittest.TestCase):
    """No command may read args.data directly.

    cmd_align declared --data optional but still called
    read_yaml_or_json(args.data), so omitting the flag raised an opaque
    TypeError ("expected str, bytes or os.PathLike object, not NoneType")
    instead of reaching the resolver's actionable message. This pins the
    invariant across all commands rather than re-checking them one by one.
    """

    def test_rejects_direct_args_data_reads(self):
        """Match real call nodes via ast, not a source substring.

        A substring scan gets this wrong in both directions: a call split
        across lines is missed entirely, and the same text inside a comment or
        docstring (this docstring, for instance) reads as a violation.
        """
        offenders = _direct_args_data_calls()
        self.assertEqual(
            offenders,
            [],
            "read args.data directly instead of _resolve_data(args) at "
            f"line(s) {offenders}",
        )

    def test_guard_detects_a_multiline_violation(self):
        """The guard itself must catch a call the substring scan missed.

        Without this, a green guard proves nothing — the earlier version passed
        while being blind to exactly the shape a reformatter would produce.
        """
        source = (
            "def cmd(args):\n"
            "    return read_yaml_or_json(\n"
            "        args.data\n"
            "    )\n"
        )
        self.assertEqual(_direct_args_data_calls(source), [2])

    def test_guard_ignores_the_pattern_in_a_comment(self):
        """A mention in prose is not a call."""
        source = (
            "# read_yaml_or_json(args.data) is what this replaced\n"
            "def cmd(args):\n"
            '    """Also mentions read_yaml_or_json(args.data)."""\n'
            "    return read_yaml_or_json(_resolve_data(args))\n"
        )
        self.assertEqual(_direct_args_data_calls(source), [])

    def test_data_consuming_commands_declare_optional_data(self):
        """--data must not be required anywhere the resolver provides a default."""
        from resume.cli.main import app

        parser = app.build_parser()
        checked = 0
        for action in parser._subparsers._group_actions[0].choices.values():  # noqa: SLF001
            for opt in action._actions:  # noqa: SLF001
                if "--data" in getattr(opt, "option_strings", []):
                    self.assertFalse(
                        opt.required,
                        "--data should be optional so the profile fallback applies",
                    )
                    checked += 1
        self.assertGreater(checked, 0, "no --data arguments found to check")


if __name__ == "__main__":
    unittest.main()
