"""SAD-PATH tests for workflow error/edge branches.

Covers the silent-fallback ``except`` handlers in:
- workflow.compiler._load_file_content  (FileNotFoundError → None)
- workflow.persistence.read_stage_result  (FileNotFoundError on glob → None)
- workflow.cli_compile._fragment_bytes  (OSError on read_bytes → skip)
- workflow.cli_compile._try_read_cached_compile  (OSError → None)
- workflow.cli_dispatch._stage_names_from_plan  (OSError → [])
- workflow.cli_dispatch._stage_names_from_manifest  (OSError → [])
- workflow.include.extract_include_entries  (yaml.YAMLError → [])
- workflow.output_checks._read_json  (OSError → error message)
- workflow._fileutil.write_once  (success → True; file-exists → False)
"""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow._fileutil import write_once
from workflow.cli_compile import _fragment_bytes, _try_read_cached_compile
from workflow.cli_dispatch import _stage_names_from_manifest, _stage_names_from_plan
from workflow.compiler import _load_file_content
from workflow.include import extract_include_entries
from workflow.models import OutputCheck
from workflow.output_checks import run_output_checks
from workflow.persistence import read_stage_result


# ---------------------------------------------------------------------------
# workflow.compiler._load_file_content  (compiler.py line 380)
# ---------------------------------------------------------------------------


class TestLoadFileContent(unittest.TestCase):
    """_load_file_content returns file text on success, None on missing file."""

    def test_returns_text_for_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir) / "file.txt"
            p.write_text("hello world", encoding="utf-8")
            result = _load_file_content(p)
        self.assertEqual(result, "hello world")

    def test_returns_none_for_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir) / "nonexistent.txt"
            result = _load_file_content(p)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# workflow.persistence.read_stage_result  (persistence.py line 90)
# Path.glob() does NOT raise FileNotFoundError on Python 3.11 (the pinned
# runtime) -- it returns an empty iterator for a missing directory, so the
# `except FileNotFoundError` guard there is unreachable. It is harmless
# because both paths return None.
#
# The test below therefore has to patch glob to reach the branch at all. It
# documents intent and would catch the guard being replaced by something that
# swallows a real error; it does NOT prove behaviour reachable in production.
# It is the one mocked test in this file -- every other test drives a real
# file, directory, or permission error.
# ---------------------------------------------------------------------------


class TestReadStageResultGlobFileNotFound(unittest.TestCase):
    """read_stage_result returns None when the stages glob raises FileNotFoundError."""

    def test_glob_file_not_found_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            stages_dir = workspace / "stages"
            stages_dir.mkdir()
            with patch.object(
                Path,
                "glob",
                side_effect=FileNotFoundError("stages dir vanished"),
            ):
                result = read_stage_result(workspace, "my-stage")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# workflow.cli_compile._fragment_bytes  (cli_compile.py line 42)
# ---------------------------------------------------------------------------


class TestFragmentBytesOSError(unittest.TestCase):
    """_fragment_bytes silently skips a fragment file that raises OSError."""

    _YAML_WITH_INCLUDE = """\
name: wf
version: "0.1"
description: test
trigger:
  source: manual
include:
  - path: frag.yaml
stages:
  - name: gather
    kind: gather
    description: g
    agent:
      role: researcher
"""

    def test_unreadable_fragment_is_skipped_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            frag = tmp_path / "frag.yaml"
            frag.write_text("fragment: true\nstages: []\n", encoding="utf-8")
            with patch.object(Path, "read_bytes", side_effect=OSError("disk error")):
                result = _fragment_bytes(
                    self._YAML_WITH_INCLUDE.encode(), tmp_path / "wf.yaml"
                )
        self.assertIsInstance(result, bytes)
        self.assertEqual(result, b"")

    def test_readable_fragment_returns_bytes(self) -> None:
        """Happy path: a readable fragment returns its bytes."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            frag = tmp_path / "frag.yaml"
            frag.write_text("fragment: true\nstages: []\n", encoding="utf-8")
            result = _fragment_bytes(
                self._YAML_WITH_INCLUDE.encode(), tmp_path / "wf.yaml"
            )
        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 0)


# ---------------------------------------------------------------------------
# workflow.cli_compile._try_read_cached_compile  (cli_compile.py line 96)
# ---------------------------------------------------------------------------


class TestTryReadCachedCompileOSError(unittest.TestCase):
    """_try_read_cached_compile returns None when the file raises OSError on read."""

    def test_oserror_on_read_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_path = Path(tmp_dir) / "cache.json"
            cache_path.write_bytes(b"dummy")
            with patch.object(Path, "read_text", side_effect=OSError("I/O error")):
                result = _try_read_cached_compile(cache_path)
        self.assertIsNone(result)

    def test_valid_cache_returns_dict(self) -> None:
        """Happy path: a well-formed cache file returns a dict."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_path = Path(tmp_dir) / "cache.json"
            cache_path.write_text('{"name": "wf", "total_stages": 2}', encoding="utf-8")
            result = _try_read_cached_compile(cache_path)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["name"], "wf")


# ---------------------------------------------------------------------------
# workflow.cli_dispatch._stage_names_from_plan  (cli_dispatch.py line 136)
# ---------------------------------------------------------------------------


class TestStageNamesFromPlanOSError(unittest.TestCase):
    """_stage_names_from_plan returns [] when the plan file raises OSError on read."""

    def test_oserror_on_read_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            plan_path = workspace / "plan.json"
            plan_path.write_bytes(b"dummy")
            with patch.object(Path, "read_text", side_effect=OSError("disk error")):
                result = _stage_names_from_plan(workspace)
        self.assertEqual(result, [])

    def test_valid_plan_returns_stage_names(self) -> None:
        """Happy path: a well-formed plan.json returns ordered stage names."""
        import json

        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            plan = {
                "parallel_groups": [
                    {"stages": ["gather"]},
                    {"stages": ["propose", "validate"]},
                ]
            }
            (workspace / "plan.json").write_text(
                json.dumps(plan), encoding="utf-8"
            )
            result = _stage_names_from_plan(workspace)
        self.assertEqual(result, ["gather", "propose", "validate"])


# ---------------------------------------------------------------------------
# workflow.cli_dispatch._stage_names_from_manifest  (cli_dispatch.py line 150)
# ---------------------------------------------------------------------------


class TestStageNamesFromManifestOSError(unittest.TestCase):
    """_stage_names_from_manifest returns [] when manifest.json raises OSError on read."""

    def test_oserror_on_read_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            manifest_path = workspace / "manifest.json"
            manifest_path.write_bytes(b"dummy")
            with patch.object(Path, "read_text", side_effect=OSError("disk error")):
                result = _stage_names_from_manifest(workspace)
        self.assertEqual(result, [])

    def test_missing_manifest_returns_empty_list(self) -> None:
        """Missing manifest.json triggers OSError (FileNotFoundError subclass) → []."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            result = _stage_names_from_manifest(workspace)
        self.assertEqual(result, [])

    def test_valid_manifest_returns_stage_names(self) -> None:
        """Happy path: a well-formed manifest.json returns stage names."""
        import json

        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            manifest = {"parallel_groups": [["gather"], ["propose"]]}
            (workspace / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            result = _stage_names_from_manifest(workspace)
        self.assertEqual(result, ["gather", "propose"])


# ---------------------------------------------------------------------------
# workflow.include.extract_include_entries  (include.py line 66)
# ---------------------------------------------------------------------------


class TestExtractIncludeEntriesYAMLError(unittest.TestCase):
    """extract_include_entries returns [] when YAML parsing raises yaml.YAMLError."""

    def test_invalid_yaml_returns_empty_list(self) -> None:
        """Tab indentation triggers a YAMLError scanner error."""
        bad_yaml = b"key:\n\tinvalid_tab_indentation\n"
        result = extract_include_entries(bad_yaml)
        self.assertEqual(result, [])

    def test_valid_yaml_without_include_returns_empty_list(self) -> None:
        """Happy path: valid YAML with no include key returns []."""
        good_yaml = b"name: wf\nversion: '1.0'\n"
        result = extract_include_entries(good_yaml)
        self.assertEqual(result, [])

    def test_valid_yaml_with_include_returns_list(self) -> None:
        """Happy path: valid YAML with an include list returns the list."""
        yaml_with_include = b"include:\n  - path: frag.yaml\n    prefix: vc\n"
        result = extract_include_entries(yaml_with_include)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# workflow.output_checks._read_json (via run_output_checks)  (output_checks.py line 84)
# ---------------------------------------------------------------------------


@unittest.skipIf(os.geteuid() == 0, "root bypasses file permissions")
class TestReadJsonOSError(unittest.TestCase):
    """_read_json propagates OSError (permission denied) as a failed CheckResult."""

    def test_unreadable_file_produces_failed_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = tmp_dir
            target = os.path.join(tmp_dir, "locked.json")
            with open(target, "w", encoding="utf-8") as fh:
                fh.write('{"key": "value"}')
            os.chmod(target, stat.S_IWRITE)
            try:
                results = run_output_checks(
                    workspace,
                    [OutputCheck(path="locked.json", checks=["is_dict"])],
                )
            finally:
                # Restore inside the with-block: TemporaryDirectory cleanup runs
                # at block exit, so an addCleanup chmod would fire too late and
                # fail on an already-deleted path.
                os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].passed)
        self.assertIn("cannot read file", results[0].message)

    def test_readable_file_produces_passed_result(self) -> None:
        """Happy path: a readable valid JSON file passes is_dict."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = tmp_dir
            target = os.path.join(tmp_dir, "data.json")
            with open(target, "w", encoding="utf-8") as fh:
                fh.write('{"status": "ok"}')

            results = run_output_checks(
                workspace,
                [OutputCheck(path="data.json", checks=["is_dict"])],
            )

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].passed)


# ---------------------------------------------------------------------------
# workflow._fileutil.write_once
# ---------------------------------------------------------------------------


class TestFileUtilWriteOnce(unittest.TestCase):
    """write_once returns True on success and False when file already exists."""

    def test_returns_true_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir) / "new.bin"
            result = write_once(p, b"hello")
        self.assertTrue(result)

    def test_file_is_written_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir) / "new.bin"
            write_once(p, b"content")
            self.assertEqual(p.read_bytes(), b"content")

    def test_returns_false_when_file_already_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir) / "existing.bin"
            p.write_bytes(b"original")
            result = write_once(p, b"new-content")
        self.assertFalse(result)

    def test_existing_file_content_unchanged_after_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir) / "existing.bin"
            p.write_bytes(b"original")
            write_once(p, b"new-content")
            self.assertEqual(p.read_bytes(), b"original")

    def test_second_call_returns_false(self) -> None:
        """Second call on same path returns False (O_EXCL prevents overwrite)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir) / "once.bin"
            first = write_once(p, b"first")
            second = write_once(p, b"second")
        self.assertTrue(first)
        self.assertFalse(second)


if __name__ == "__main__":
    unittest.main()
