"""Coverage uplift tests for mail.config_cli.pipeline_audit.

Focuses on the seven pure scoring helpers (Priority 1) and AuditFilters
pipeline edge cases (Priority 2).  EnvSetup paths that would create a real
venv, run pip, or write ~/.config/credentials.ini are intentionally skipped.
"""
from __future__ import annotations

import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest import TestCase

from core.pipeline import ResultEnvelope
from mail.config_cli.pipeline_audit import (
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
        self.assertIsNone(_dest_and_tokens_for_filter("not a dict"))

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
        self.assertIsNone(_score_one_filter("not a dict", self._DTM))

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
