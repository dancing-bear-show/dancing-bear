"""Coverage uplift tests for mail.config_cli.pipeline_audit.

Focuses on the seven pure scoring helpers (Priority 1) and AuditFilters
pipeline edge cases (Priority 2).  EnvSetup paths that would create a real
venv, run pip, or write ~/.config/credentials.ini are intentionally skipped.
"""
from __future__ import annotations

import io
import os
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, cast
from unittest import TestCase
from unittest.mock import MagicMock, patch

from core.pipeline import ResultEnvelope
from mail.config_cli.pipeline_audit import (
    EnvSetupProducer,
    EnvSetupRequest,
    EnvSetupResult,
    _install_venv_packages,
    _make_bin_scripts_executable,
    _resolve_gmail_cred_paths,
    _setup_venv,
    # Pure helpers
    _build_dest_token_map,
    _dest_and_tokens_for_filter,
    _extract_filter_adds,
    _extract_filter_from_addr,
    _score_exported_filters,
    _score_one_filter,
    _token_matches,
    # Pipeline classes
    AuditFiltersProcessor,
    AuditFiltersProducer,
    AuditFiltersRequest,
    AuditFiltersResult,
)


# ---------------------------------------------------------------------------
# _dest_and_tokens_for_filter
# ---------------------------------------------------------------------------

class DestAndTokensForFilterTests(TestCase):
    """Tests for _dest_and_tokens_for_filter."""

    def test_non_dict_returns_none(self):
        self.assertIsNone(_dest_and_tokens_for_filter(cast(Any, "not a dict")))  # cast: exercises non-dict isinstance guard

    def test_empty_dict_returns_none(self):
        self.assertIsNone(_dest_and_tokens_for_filter({}))

    def test_missing_action_returns_none(self):
        self.assertIsNone(_dest_and_tokens_for_filter({"match": {"from": "a@b.com"}}))

    def test_empty_add_returns_none(self):
        f = {"match": {"from": "a@b.com"}, "action": {"add": []}}
        self.assertIsNone(_dest_and_tokens_for_filter(f))

    def test_no_from_address_returns_none(self):
        # action has add but from is empty string
        f = {"match": {"from": ""}, "action": {"add": ["L1"]}}
        self.assertIsNone(_dest_and_tokens_for_filter(f))

    def test_missing_from_key_returns_none(self):
        # match has no 'from' key
        f = {"match": {}, "action": {"add": ["L1"]}}
        self.assertIsNone(_dest_and_tokens_for_filter(f))

    def test_happy_path_single_from(self):
        f = {"match": {"from": "a@b.com"}, "action": {"add": ["L1"]}}
        dest, toks = _dest_and_tokens_for_filter(f)
        self.assertEqual("L1", dest)
        self.assertEqual({"a@b.com"}, toks)

    def test_or_delimited_from_produces_multiple_tokens(self):
        f = {"match": {"from": "a@b.com OR c@d.com"}, "action": {"add": ["L2"]}}
        dest, toks = _dest_and_tokens_for_filter(f)
        self.assertEqual("L2", dest)
        self.assertEqual({"a@b.com", "c@d.com"}, toks)

    def test_first_add_becomes_dest(self):
        f = {"match": {"from": "a@b.com"}, "action": {"add": ["First", "Second"]}}
        dest, _ = _dest_and_tokens_for_filter(f)
        self.assertEqual("First", dest)


# ---------------------------------------------------------------------------
# _build_dest_token_map
# ---------------------------------------------------------------------------

class BuildDestTokenMapTests(TestCase):
    """Tests for _build_dest_token_map."""

    def test_empty_list_returns_empty_dict(self):
        self.assertEqual({}, _build_dest_token_map([]))

    def test_non_dict_entries_are_skipped(self):
        result = _build_dest_token_map(["not a dict", 42, None])
        self.assertEqual({}, result)

    def test_entries_without_from_are_skipped(self):
        result = _build_dest_token_map([{"action": {"add": ["L1"]}}])
        self.assertEqual({}, result)

    def test_happy_path_single_filter(self):
        filters = [{"match": {"from": "a@b.com"}, "action": {"add": ["L1"]}}]
        result = _build_dest_token_map(filters)
        self.assertEqual({"L1": {"a@b.com"}}, result)

    def test_multiple_filters_merge_tokens_for_same_dest(self):
        filters = [
            {"match": {"from": "a@b.com"}, "action": {"add": ["L1"]}},
            {"match": {"from": "c@d.com"}, "action": {"add": ["L1"]}},
            {"match": {"from": "x@y.com"}, "action": {"add": ["L2"]}},
            "not a dict",
            {},
        ]
        result = _build_dest_token_map(filters)
        self.assertEqual({"a@b.com", "c@d.com"}, result["L1"])
        self.assertEqual({"x@y.com"}, result["L2"])


# ---------------------------------------------------------------------------
# _extract_filter_from_addr
# ---------------------------------------------------------------------------

class ExtractFilterFromAddrTests(TestCase):
    """Tests for _extract_filter_from_addr."""

    def test_no_criteria_or_match_key_returns_none(self):
        self.assertIsNone(_extract_filter_from_addr({}))

    def test_empty_match_dict_returns_none(self):
        self.assertIsNone(_extract_filter_from_addr({"match": {}}))

    def test_empty_criteria_dict_returns_none(self):
        self.assertIsNone(_extract_filter_from_addr({"criteria": {}}))

    def test_criteria_with_query_returns_none(self):
        self.assertIsNone(_extract_filter_from_addr({"criteria": {"query": "something"}}))

    def test_criteria_with_negated_query_returns_none(self):
        self.assertIsNone(_extract_filter_from_addr({"criteria": {"negatedQuery": "x"}}))

    def test_criteria_with_size_returns_none(self):
        self.assertIsNone(_extract_filter_from_addr({"criteria": {"size": 1000}}))

    def test_criteria_with_size_comparison_returns_none(self):
        self.assertIsNone(_extract_filter_from_addr({"criteria": {"sizeComparison": "larger"}}))

    def test_criteria_with_to_returns_none(self):
        self.assertIsNone(_extract_filter_from_addr({"criteria": {"to": "someone@x.com"}}))

    def test_match_with_subject_returns_none(self):
        self.assertIsNone(_extract_filter_from_addr({"match": {"subject": "hello"}}))

    def test_criteria_with_from_returns_lowercased_addr(self):
        result = _extract_filter_from_addr({"criteria": {"from": "A@B.COM"}})
        self.assertEqual("a@b.com", result)

    def test_match_with_from_returns_addr(self):
        result = _extract_filter_from_addr({"match": {"from": "a@b.com"}})
        self.assertEqual("a@b.com", result)

    def test_empty_from_returns_none(self):
        self.assertIsNone(_extract_filter_from_addr({"match": {"from": ""}}))


# ---------------------------------------------------------------------------
# _extract_filter_adds
# ---------------------------------------------------------------------------

class ExtractFilterAddsTests(TestCase):
    """Tests for _extract_filter_adds."""

    def test_empty_dict_returns_empty_list(self):
        self.assertEqual([], _extract_filter_adds({}))

    def test_no_action_key_returns_empty_list(self):
        self.assertEqual([], _extract_filter_adds({"criteria": {"from": "x"}}))

    def test_add_labels_returned(self):
        result = _extract_filter_adds({"action": {"addLabels": ["L1", "L2"]}})
        self.assertEqual(["L1", "L2"], result)

    def test_add_key_returned(self):
        result = _extract_filter_adds({"action": {"add": ["X"]}})
        self.assertEqual(["X"], result)

    def test_move_to_folder_returned_when_no_add_labels(self):
        result = _extract_filter_adds({"action": {"moveToFolder": "Inbox"}})
        self.assertEqual(["Inbox"], result)

    def test_add_labels_takes_priority_over_move_to_folder(self):
        result = _extract_filter_adds({"action": {"addLabels": ["L1"], "moveToFolder": "Inbox"}})
        self.assertEqual(["L1"], result)


# ---------------------------------------------------------------------------
# _token_matches
# ---------------------------------------------------------------------------

class TokenMatchesTests(TestCase):
    """Tests for _token_matches."""

    def test_empty_token_set_returns_false(self):
        self.assertFalse(_token_matches("a@b.com", set()))

    def test_exact_match_returns_true(self):
        self.assertTrue(_token_matches("a@b.com", {"a@b.com"}))

    def test_token_substring_of_frm_returns_true(self):
        # tok "b.com" is in frm "a@b.com"
        self.assertTrue(_token_matches("a@b.com", {"b.com"}))

    def test_frm_substring_of_token_returns_true(self):
        # frm "b.com" is in tok "a@b.com"
        self.assertTrue(_token_matches("b.com", {"a@b.com"}))

    def test_no_overlap_returns_false(self):
        self.assertFalse(_token_matches("x@y.com", {"a@b.com", "c@d.com"}))

    def test_any_token_match_sufficient(self):
        self.assertTrue(_token_matches("x@y.com", {"nope.com", "x@y.com"}))


# ---------------------------------------------------------------------------
# _score_one_filter
# ---------------------------------------------------------------------------

class ScoreOneFilterTests(TestCase):
    """Tests for _score_one_filter."""

    _DTM = {"L1": {"a@b.com", "c@d.com"}, "L2": {"x@y.com"}}

    def test_non_dict_returns_none(self):
        self.assertIsNone(_score_one_filter(cast(Any, "not a dict"), self._DTM))  # cast: exercises non-dict isinstance guard

    def test_no_from_addr_returns_none(self):
        self.assertIsNone(_score_one_filter({"criteria": {}}, self._DTM))

    def test_no_adds_returns_none(self):
        self.assertIsNone(_score_one_filter({"criteria": {"from": "a@b.com"}}, self._DTM))

    def test_covered_filter_is_marked_covered(self):
        f = {"criteria": {"from": "a@b.com"}, "action": {"addLabels": ["L1"]}}
        score = _score_one_filter(f, self._DTM)
        self.assertIsNotNone(score)
        self.assertEqual("L1", score.dest)
        self.assertEqual("a@b.com", score.frm)
        self.assertTrue(score.covered)

    def test_uncovered_filter_is_marked_not_covered(self):
        f = {"criteria": {"from": "z@z.com"}, "action": {"addLabels": ["L1"]}}
        score = _score_one_filter(f, self._DTM)
        self.assertIsNotNone(score)
        self.assertFalse(score.covered)

    def test_dest_not_in_token_map_is_not_covered(self):
        f = {"criteria": {"from": "a@b.com"}, "action": {"addLabels": ["NOTEXIST"]}}
        score = _score_one_filter(f, self._DTM)
        self.assertIsNotNone(score)
        self.assertEqual("NOTEXIST", score.dest)
        self.assertFalse(score.covered)


# ---------------------------------------------------------------------------
# _score_exported_filters
# ---------------------------------------------------------------------------

class ScoreExportedFiltersTests(TestCase):
    """Tests for _score_exported_filters."""

    def test_empty_exported_list(self):
        total, covered, missing = _score_exported_filters([], {})
        self.assertEqual(0, total)
        self.assertEqual(0, covered)
        self.assertEqual([], missing)

    def test_non_simple_filters_excluded_from_count(self):
        exported = [{"criteria": {"query": "has:attachment"}}]
        total, _, _ = _score_exported_filters(exported, {})
        self.assertEqual(0, total)

    def test_covered_and_uncovered_counted_correctly(self):
        dtm = {"L1": {"a@b.com"}}
        exported = [
            {"criteria": {"from": "a@b.com"}, "action": {"addLabels": ["L1"]}},
            {"criteria": {"from": "z@z.com"}, "action": {"addLabels": ["L1"]}},
        ]
        total, covered, missing = _score_exported_filters(exported, dtm)
        self.assertEqual(2, total)
        self.assertEqual(1, covered)
        self.assertEqual(1, len(missing))
        self.assertEqual(("L1", "z@z.com"), missing[0])

    def test_missing_samples_truncated_to_10_when_11_uncovered(self):
        # 11 uncovered entries — must return exactly 10 (line 124 truncation)
        exported = [
            {"criteria": {"from": f"z{i}@x.com"}, "action": {"addLabels": ["L_NOTEXIST"]}}
            for i in range(11)
        ]
        total, covered, missing = _score_exported_filters(exported, {})
        self.assertEqual(11, total)
        self.assertEqual(0, covered)
        self.assertEqual(10, len(missing))

    def test_all_covered_produces_empty_missing(self):
        dtm = {"L1": {"a@b.com"}, "L2": {"c@d.com"}}
        exported = [
            {"criteria": {"from": "a@b.com"}, "action": {"addLabels": ["L1"]}},
            {"criteria": {"from": "c@d.com"}, "action": {"addLabels": ["L2"]}},
        ]
        total, covered, missing = _score_exported_filters(exported, dtm)
        self.assertEqual(2, total)
        self.assertEqual(2, covered)
        self.assertEqual([], missing)


# ---------------------------------------------------------------------------
# AuditFiltersProcessor — edge cases
# ---------------------------------------------------------------------------

class AuditFiltersProcessorEdgeCaseTests(TestCase):
    """AuditFilters pipeline edge cases not covered by the existing test."""

    def _write_yaml(self, tmpdir: str, filename: str, text: str) -> str:
        p = Path(tmpdir) / filename
        p.write_text(text)
        return str(p)

    def test_empty_in_path_uses_empty_unified(self):
        """in_path='' means no unified config; all exported filters are uncovered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            export_path = self._write_yaml(
                tmpdir,
                "export.yaml",
                "filters:\n  - criteria:\n      from: a@b.com\n    action:\n      addLabels: [L1]\n",
            )
            req = AuditFiltersRequest(in_path="", export_path=export_path)
            result = AuditFiltersProcessor().process(req)
            self.assertTrue(result.ok())
            self.assertEqual(1, result.payload.simple_total)
            self.assertEqual(0, result.payload.covered)
            self.assertEqual(1, result.payload.not_covered)

    def test_empty_export_path_uses_empty_exported(self):
        """export_path='' means no exported filters; totals are all zero."""
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = self._write_yaml(
                tmpdir,
                "unified.yaml",
                "filters:\n  - match:\n      from: a@b.com\n    action:\n      add: [L1]\n",
            )
            req = AuditFiltersRequest(in_path=in_path, export_path="")
            result = AuditFiltersProcessor().process(req)
            self.assertTrue(result.ok())
            self.assertEqual(0, result.payload.simple_total)
            self.assertEqual(0.0, result.payload.percentage)

    def test_no_simple_filters_percentage_is_zero(self):
        """When simple_total is 0, percentage must be 0.0 (no division by zero)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = self._write_yaml(tmpdir, "unified.yaml", "filters: []\n")
            export_path = self._write_yaml(tmpdir, "export.yaml", "filters: []\n")
            req = AuditFiltersRequest(in_path=in_path, export_path=export_path)
            result = AuditFiltersProcessor().process(req)
            self.assertTrue(result.ok())
            self.assertEqual(0.0, result.payload.percentage)

    def test_percentage_reflects_uncovered_fraction(self):
        """Percentage is the uncovered fraction of simple filters, times 100."""
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = self._write_yaml(
                tmpdir,
                "unified.yaml",
                "filters:\n  - match:\n      from: a@b.com\n    action:\n      add: [L1]\n",
            )
            export_path = self._write_yaml(
                tmpdir,
                "export.yaml",
                "filters:\n"
                "  - criteria:\n      from: a@b.com\n    action:\n      addLabels: [L1]\n"
                "  - criteria:\n      from: z@z.com\n    action:\n      addLabels: [L1]\n",
            )
            req = AuditFiltersRequest(in_path=in_path, export_path=export_path)
            result = AuditFiltersProcessor().process(req)
            self.assertTrue(result.ok())
            self.assertEqual(2, result.payload.simple_total)
            self.assertEqual(1, result.payload.covered)
            self.assertEqual(1, result.payload.not_covered)
            self.assertAlmostEqual(50.0, result.payload.percentage)

    def test_non_simple_exported_filters_excluded(self):
        """Exported filters with 'query' criterion are not counted as simple."""
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = self._write_yaml(tmpdir, "unified.yaml", "filters: []\n")
            export_path = self._write_yaml(
                tmpdir,
                "export.yaml",
                "filters:\n  - criteria:\n      query: has:attachment\n    action:\n      addLabels: [L1]\n",
            )
            req = AuditFiltersRequest(in_path=in_path, export_path=export_path)
            result = AuditFiltersProcessor().process(req)
            self.assertTrue(result.ok())
            self.assertEqual(0, result.payload.simple_total)

    def test_missing_samples_appear_in_result(self):
        """missing_samples contains (dest, frm) tuples for uncovered filters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = self._write_yaml(tmpdir, "unified.yaml", "filters: []\n")
            export_path = self._write_yaml(
                tmpdir,
                "export.yaml",
                "filters:\n  - criteria:\n      from: z@z.com\n    action:\n      addLabels: [MISSING]\n",
            )
            req = AuditFiltersRequest(in_path=in_path, export_path=export_path)
            result = AuditFiltersProcessor().process(req)
            self.assertTrue(result.ok())
            self.assertEqual([("MISSING", "z@z.com")], result.payload.missing_samples)


# ---------------------------------------------------------------------------
# AuditFiltersProducer — output formatting
# ---------------------------------------------------------------------------

class AuditFiltersProducerOutputTests(TestCase):
    """Producer output tests beyond what already exists."""

    def _make_envelope(self, **kwargs) -> ResultEnvelope:
        # Annotated Any rather than inferred: dict(...) infers dict[str, object],
        # which loses the per-field types when splatted into AuditFiltersResult
        # and makes mypy reject every int/float/list argument.
        defaults: dict[str, Any] = dict(
            simple_total=5,
            covered=3,
            not_covered=2,
            percentage=40.0,
            missing_samples=[],
        )
        defaults.update(kwargs)
        return ResultEnvelope(
            status="success",
            payload=AuditFiltersResult(**defaults),
        )

    def test_producer_prints_totals(self):
        envelope = self._make_envelope()
        buf = io.StringIO()
        with redirect_stdout(buf):
            AuditFiltersProducer(preview_missing=False).produce(envelope)
        output = buf.getvalue()
        self.assertIn("5", output)
        self.assertIn("3", output)
        self.assertIn("2", output)
        self.assertIn("40.0", output)

    def test_producer_preview_missing_false_no_examples_printed(self):
        envelope = self._make_envelope(missing_samples=[("L1", "z@z.com")])
        buf = io.StringIO()
        with redirect_stdout(buf):
            AuditFiltersProducer(preview_missing=False).produce(envelope)
        self.assertNotIn("z@z.com", buf.getvalue())

    def test_producer_preview_missing_true_prints_samples(self):
        envelope = self._make_envelope(
            not_covered=1,
            missing_samples=[("L1", "z@z.com")],
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            AuditFiltersProducer(preview_missing=True).produce(envelope)
        output = buf.getvalue()
        self.assertIn("L1", output)
        self.assertIn("z@z.com", output)

    def test_producer_preview_missing_true_empty_samples_no_section(self):
        # preview_missing=True but no missing — section header must not appear
        envelope = self._make_envelope(missing_samples=[])
        buf = io.StringIO()
        with redirect_stdout(buf):
            AuditFiltersProducer(preview_missing=True).produce(envelope)
        self.assertNotIn("Missing examples", buf.getvalue())


# ---------------------------------------------------------------------------
# EnvSetup helpers — unit tests with mocks to avoid real subprocess / venv
# ---------------------------------------------------------------------------


class InstallVenvPackagesTests(TestCase):
    """Tests for _install_venv_packages (lines 201-209)."""

    def test_raises_file_not_found_when_python_absent(self):
        # Sad path: python binary not in venv
        with tempfile.TemporaryDirectory() as td:
            venv_dir = Path(td) / "venv"
            venv_dir.mkdir()
            with self.assertRaises(FileNotFoundError):
                _install_venv_packages(venv_dir)

    def test_raises_value_error_when_python_path_escapes_venv(self):
        # Sad path: python exists but resolves outside venv dir (symlink escape)
        with tempfile.TemporaryDirectory() as td:
            venv_dir = Path(td) / "venv"
            (venv_dir / "bin").mkdir(parents=True)
            py = venv_dir / "bin" / "python"
            # Make python a symlink pointing outside the venv
            py.symlink_to("/usr/bin/python3")
            with self.assertRaises(ValueError):
                _install_venv_packages(venv_dir)

    def test_happy_path_via_mock_calls_install(self):
        # Test that _install_venv_packages is called by _setup_venv when skip_install=False.
        with tempfile.TemporaryDirectory() as td:
            venv_dir = Path(td) / "venv"
            venv_dir.mkdir()
            with patch("mail.config_cli.pipeline_audit._install_venv_packages") as mock_install:
                with patch("mail.config_cli.pipeline_audit._make_bin_scripts_executable"):
                    _setup_venv(venv_dir, skip_install=False)
            mock_install.assert_called_once_with(venv_dir)

    def test_subprocess_run_called_for_valid_venv_python(self):
        # Lines 208-209: subprocess.run called when python exists and path is safe
        with tempfile.TemporaryDirectory() as td:
            venv_dir = Path(td) / "venv"
            bin_dir = venv_dir / "bin"
            bin_dir.mkdir(parents=True)
            # Create a python symlink pointing to a real interpreter inside the venv dir
            # We simulate by making a regular file (not symlink) — resolve() stays in venv_dir
            py = bin_dir / "python"
            py.touch()
            with patch("subprocess.run") as mock_run:
                # Patch Path.exists to return True for py, and Path.resolve to keep path inside venv
                def fake_resolve(self):
                    # Return self (so path stays in venv_dir tree)
                    import pathlib
                    return pathlib.Path(str(self))
                with patch.object(Path, "resolve", fake_resolve):
                    with patch.object(Path, "exists", return_value=True):
                        _install_venv_packages(venv_dir)
            self.assertEqual(2, mock_run.call_count)


class MakeBinScriptsExecutableTests(TestCase):
    """Tests for _make_bin_scripts_executable (lines 214-220)."""

    def test_no_error_when_bin_files_do_not_exist(self):
        # Happy path: files don't exist, nothing to chmod
        with patch.object(Path, "exists", return_value=False):
            _make_bin_scripts_executable()  # should not raise

    def test_chmod_called_when_bin_exists(self):
        # Happy path: file exists and is chmod-able
        with patch.object(Path, "exists", return_value=True):
            fake_stat = MagicMock()
            fake_stat.st_mode = 0o644
            with patch.object(Path, "stat", return_value=fake_stat):
                with patch("os.chmod") as mock_chmod:
                    _make_bin_scripts_executable()
        # chmod called at least once (for bin/mail which exists)
        self.assertGreater(mock_chmod.call_count, 0)

    def test_os_error_on_chmod_does_not_raise(self):
        # Sad path: OSError from chmod is swallowed
        with patch.object(Path, "exists", return_value=True):
            fake_stat = MagicMock()
            fake_stat.st_mode = 0o644
            with patch.object(Path, "stat", return_value=fake_stat):
                with patch("os.chmod", side_effect=OSError("permission denied")):
                    _make_bin_scripts_executable()  # must not propagate


class SetupVenvTests(TestCase):
    """Tests for _setup_venv (lines 225-233)."""

    def test_skips_creation_when_venv_already_exists(self):
        with tempfile.TemporaryDirectory() as td:
            venv_dir = Path(td) / "venv"
            venv_dir.mkdir()
            with patch("mail.config_cli.pipeline_audit._install_venv_packages") as mock_install:
                with patch("mail.config_cli.pipeline_audit._make_bin_scripts_executable"):
                    result = _setup_venv(venv_dir, skip_install=True)
            self.assertFalse(result)
            mock_install.assert_not_called()

    def test_creates_venv_when_dir_absent(self):
        with tempfile.TemporaryDirectory() as td:
            venv_dir = Path(td) / "newvenv"
            with patch("venv.EnvBuilder") as mock_builder:
                with patch("mail.config_cli.pipeline_audit._install_venv_packages"):
                    with patch("mail.config_cli.pipeline_audit._make_bin_scripts_executable"):
                        result = _setup_venv(venv_dir, skip_install=True)
            self.assertTrue(result)
            mock_builder.return_value.create.assert_called_once_with(str(venv_dir))

    def test_calls_install_when_skip_install_false(self):
        with tempfile.TemporaryDirectory() as td:
            venv_dir = Path(td) / "venv"
            venv_dir.mkdir()
            with patch("mail.config_cli.pipeline_audit._install_venv_packages") as mock_install:
                with patch("mail.config_cli.pipeline_audit._make_bin_scripts_executable"):
                    _setup_venv(venv_dir, skip_install=False)
            mock_install.assert_called_once_with(venv_dir)


class ResolveGmailCredPathsTests(TestCase):
    """Tests for _resolve_gmail_cred_paths (lines 241-253)."""

    def _make_payload(self, **kwargs):
        defaults = dict(
            credentials=None, token=None, copy_gmail_example=False,
            outlook_client_id=None, tenant=None, outlook_token=None,
        )
        defaults.update(kwargs)
        return MagicMock(**defaults)

    def test_no_credentials_no_copy_returns_none_none(self):
        # Happy path: no cred, no copy_gmail_example
        payload = self._make_payload()
        cred, tok = _resolve_gmail_cred_paths(
            payload, lambda x: x, lambda: "/default/cred.json", lambda: "/default/tok.json"
        )
        self.assertIsNone(cred)
        self.assertIsNone(tok)

    def test_cred_path_set_but_no_token_sets_default_tok(self):
        # Line 252: cred_path set, tok_path is None — default tok assigned
        payload = self._make_payload(credentials="/path/to/cred.json", token=None)
        cred, tok = _resolve_gmail_cred_paths(
            payload, lambda x: x, lambda: "/default/cred.json", lambda: "/default/tok.json"
        )
        self.assertEqual("/path/to/cred.json", cred)
        self.assertEqual("/default/tok.json", tok)

    def test_both_cred_and_token_set_returns_them_unchanged(self):
        # "/t.json" is a token-cache FILE PATH, not a password; B106 matches on
        # the kwarg name containing "token".
        payload = self._make_payload(credentials="/c.json", token="/t.json")  # nosec B106
        cred, tok = _resolve_gmail_cred_paths(
            payload, lambda x: x, lambda: "/dc.json", lambda: "/dt.json"
        )
        self.assertEqual("/c.json", cred)
        self.assertEqual("/t.json", tok)

    def test_copy_gmail_example_copies_when_example_exists_and_dest_absent(self):
        # Lines 244-250: copy_gmail_example=True, example exists, dest absent — file is copied
        with tempfile.TemporaryDirectory() as td:
            old_cwd = os.getcwd()
            try:
                # Create credentials.example.json in our temp CWD
                example = Path(td) / "credentials.example.json"
                example.write_text('{"example": true}', encoding="utf-8")
                os.chdir(td)

                dest = Path(td) / "creds" / "cred.json"
                payload = self._make_payload(copy_gmail_example=True, credentials=None, token=None)
                cred, _ = _resolve_gmail_cred_paths(
                    payload,
                    lambda x: x,
                    lambda: str(dest),
                    lambda: str(dest.parent / "tok.json"),
                )
                # dest was absent and example existed — should have been copied
                self.assertEqual(str(dest), cred)
                self.assertTrue(dest.exists())
            finally:
                os.chdir(old_cwd)

    def test_copy_gmail_example_os_error_prints_warning(self):
        # Lines 249-250: OSError during copy prints a warning and leaves cred_path None
        payload = self._make_payload(copy_gmail_example=True, credentials=None, token=None)
        with patch("mail.config_cli.pipeline_audit.Path") as MockPath:
            ex_mock = MagicMock()
            ex_mock.exists.return_value = True
            ex_mock.read_text.side_effect = OSError("read failed")
            dest_mock = MagicMock()
            dest_mock.exists.return_value = False
            dest_mock.parent.mkdir = MagicMock()
            dest_mock.write_text = MagicMock(side_effect=OSError("write failed"))
            str_dest_mock = MagicMock()
            str_dest_mock.__str__ = MagicMock(return_value="/dest.json")
            MockPath.side_effect = lambda s: ex_mock if "example" in str(s) else dest_mock
            import io as _io
            err_buf = _io.StringIO()
            import sys as _sys
            with patch.object(_sys, "stderr", err_buf):
                cred, _ = _resolve_gmail_cred_paths(
                    payload, lambda x: x, lambda: "/dest.json", lambda: "/tok.json"
                )
            # cred_path remains None since OSError was raised
            self.assertIsNone(cred)
            self.assertIn("Warning", err_buf.getvalue())

    def test_copy_gmail_example_skips_when_dest_already_exists(self):
        # Sad path for copy_gmail_example: dest exists, skip copy
        payload = self._make_payload(copy_gmail_example=True, credentials=None, token=None)
        with patch("mail.config_cli.pipeline_audit.Path") as MockPath:
            ex_mock = MagicMock()
            ex_mock.exists.return_value = True
            dest_mock = MagicMock()
            dest_mock.exists.return_value = True  # already exists
            MockPath.side_effect = lambda s: ex_mock if "example" in str(s) else dest_mock
            cred, _ = _resolve_gmail_cred_paths(
                payload, lambda x: x, lambda: "/dest.json", lambda: "/tok.json"
            )
            # cred should remain None since dest already exists
            self.assertIsNone(cred)


class EnvSetupProcessorTests(TestCase):
    """Tests for EnvSetupProcessor._process_safe (lines 257-297)."""

    def _run_processor(self, **kwargs):
        from mail.config_cli.pipeline_audit import EnvSetupProcessor
        req = EnvSetupRequest(**kwargs)
        return EnvSetupProcessor().process(req)

    def test_no_venv_skips_setup_venv(self):
        # Line 266-267: no_venv=True skips _setup_venv
        with patch("mail.config_cli.pipeline_audit._setup_venv") as mock_setup:
            with patch("mail.config_cli.pipeline_audit._resolve_gmail_cred_paths", return_value=(None, None)):
                result = self._run_processor(
                    no_venv=True,
                    skip_install=True,
                    profile=None,
                    credentials=None,
                    token=None,
                    outlook_client_id=None,
                    tenant=None,
                    outlook_token=None,
                    copy_gmail_example=False,
                )
        self.assertTrue(result.ok())
        mock_setup.assert_not_called()

    def test_with_venv_calls_setup_venv(self):
        # Line 267: no_venv=False calls _setup_venv
        with patch("mail.config_cli.pipeline_audit._setup_venv", return_value=True) as mock_setup:
            with patch("mail.config_cli.pipeline_audit._resolve_gmail_cred_paths", return_value=(None, None)):
                result = self._run_processor(
                    no_venv=False,
                    venv_dir="/tmp/testvenv",  # nosec B108 - test path, never accessed
                    skip_install=True,
                    profile=None,
                    credentials=None,
                    token=None,
                    outlook_client_id=None,
                    tenant=None,
                    outlook_token=None,
                    copy_gmail_example=False,
                )
        self.assertTrue(result.ok())
        mock_setup.assert_called_once()
        self.assertTrue(result.payload.venv_created)

    def test_profile_saved_when_credentials_provided(self):
        # Lines 277-278 and 281->293: non-None cred paths cause mkdir + persist_profile_settings
        with tempfile.TemporaryDirectory() as td:
            cred = os.path.join(td, "creds", "cred.json")
            tok = os.path.join(td, "tokens", "tok.json")
            with patch("mail.config_cli.pipeline_audit._setup_venv", return_value=False):
                with patch("mail.config_cli.pipeline_audit._resolve_gmail_cred_paths",
                           return_value=(cred, tok)):
                    with patch("mail.config_resolver.persist_profile_settings") as mock_persist:
                        result = self._run_processor(
                            no_venv=True,
                            skip_install=True,
                            profile="test_profile",
                            credentials=cred,
                            token=tok,
                            outlook_client_id=None,
                            tenant=None,
                            outlook_token=None,
                            copy_gmail_example=False,
                        )
        self.assertTrue(result.ok())
        self.assertTrue(result.payload.profile_saved)
        mock_persist.assert_called_once()

    def test_oserror_from_mkdir_is_swallowed(self):
        # Lines 277-278: OSError from mkdir is caught and ignored
        with tempfile.TemporaryDirectory() as td:
            cred = os.path.join(td, "creds", "cred.json")
            with patch("mail.config_cli.pipeline_audit._setup_venv", return_value=False):
                with patch("mail.config_cli.pipeline_audit._resolve_gmail_cred_paths",
                           return_value=(cred, None)):
                    with patch("mail.config_resolver.persist_profile_settings"):
                        with patch("pathlib.Path.mkdir", side_effect=OSError("permission denied")):
                            result = self._run_processor(
                                no_venv=True,
                                skip_install=True,
                                profile=None,
                                credentials=cred,
                                token=None,
                                outlook_client_id=None,
                                tenant=None,
                                outlook_token=None,
                                copy_gmail_example=False,
                            )
            # OSError is swallowed, processor still returns a result
            self.assertTrue(result.ok())

    def test_profile_not_saved_when_no_credentials(self):
        # Line 280: profile_saved=False when no credentials
        with patch("mail.config_cli.pipeline_audit._setup_venv", return_value=False):
            with patch("mail.config_cli.pipeline_audit._resolve_gmail_cred_paths", return_value=(None, None)):
                result = self._run_processor(
                    no_venv=True,
                    skip_install=True,
                    profile=None,
                    credentials=None,
                    token=None,
                    outlook_client_id=None,
                    tenant=None,
                    outlook_token=None,
                    copy_gmail_example=False,
                )
        self.assertTrue(result.ok())
        self.assertFalse(result.payload.profile_saved)


class EnvSetupProducerTests(TestCase):
    """Tests for EnvSetupProducer._produce_success (lines 302-306)."""

    def _make_envelope(self, profile_saved: bool) -> "ResultEnvelope":
        payload = EnvSetupResult(
            venv_created=False,
            profile_saved=profile_saved,
            message="Environment setup complete.",
        )
        return ResultEnvelope(status="success", payload=payload)

    def test_produce_success_with_profile_saved_prints_persisted(self):
        # Line 302-303: profile_saved=True
        envelope = self._make_envelope(profile_saved=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            EnvSetupProducer().produce(envelope)
        out = buf.getvalue()
        self.assertIn("Persisted settings", out)
        self.assertIn("Environment setup complete.", out)

    def test_produce_success_without_profile_saved_prints_skipped(self):
        # Line 305: profile_saved=False — else branch
        envelope = self._make_envelope(profile_saved=False)
        buf = io.StringIO()
        with redirect_stdout(buf):
            EnvSetupProducer().produce(envelope)
        out = buf.getvalue()
        self.assertIn("skipped INI write", out)
        self.assertIn("Environment setup complete.", out)
