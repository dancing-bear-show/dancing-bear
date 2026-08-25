"""Tests for core.preflight — invariant-check framework."""

from __future__ import annotations

import json
import unittest

from core.preflight import (
    InvariantViolation,
    PreflightReport,
    evaluate_invariants,
)


# ---------------------------------------------------------------------------
# Helper check functions used across test cases
# ---------------------------------------------------------------------------

def _always_pass(changes, baseline):
    return "always_pass", []


def _always_fail(changes, baseline):
    return "always_fail", [{"item": c} for c in changes]


def _raises(changes, baseline):
    raise ValueError("boom")


def _deletes_more_than_half(changes, baseline):
    total = baseline.get("total", len(changes))
    bad = [c for c in changes if c.get("op") == "delete"]
    if total and len(bad) > total / 2:
        return "deletes_more_than_half", bad
    return "deletes_more_than_half", []


def _no_new_labels(changes, baseline):
    bad = [c for c in changes if c.get("op") == "add_label"]
    return "no_new_labels", bad


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAllChecksPass(unittest.TestCase):
    def test_passed_true_when_all_clear(self):
        changes = [{"op": "modify", "id": "1"}]
        report = evaluate_invariants(changes, {}, [_always_pass])
        self.assertTrue(report.passed)

    def test_no_violations_when_all_clear(self):
        report = evaluate_invariants([{"op": "x"}], {}, [_always_pass])
        self.assertEqual(report.violations, [])

    def test_tallies_include_total_and_violation_count(self):
        changes = [{"op": "a"}, {"op": "b"}, {"op": "c"}]
        report = evaluate_invariants(changes, {}, [_always_pass])
        self.assertEqual(report.tallies["total_changes"], 3)
        self.assertEqual(report.tallies["violation_count"], 0)


class TestOneFailingCheck(unittest.TestCase):
    def _make_changes(self, n=5):
        return [{"op": "delete", "id": str(i)} for i in range(n)]

    def test_passed_false_on_violation(self):
        changes = self._make_changes()
        report = evaluate_invariants(changes, {"total": 6}, [_deletes_more_than_half])
        self.assertFalse(report.passed)

    def test_correct_code(self):
        changes = self._make_changes()
        report = evaluate_invariants(changes, {"total": 6}, [_deletes_more_than_half])
        self.assertEqual(len(report.violations), 1)
        self.assertEqual(report.violations[0].code, "deletes_more_than_half")

    def test_correct_samples(self):
        changes = self._make_changes(3)
        report = evaluate_invariants(changes, {"total": 4}, [_deletes_more_than_half])
        self.assertEqual(len(report.violations[0].samples), 3)

    def test_default_message_derived_from_code(self):
        changes = self._make_changes()
        report = evaluate_invariants(changes, {"total": 6}, [_deletes_more_than_half])
        self.assertEqual(report.violations[0].message, "deletes more than half")

    def test_custom_message_used_when_provided(self):
        changes = self._make_changes()
        report = evaluate_invariants(
            changes,
            {"total": 6},
            [_deletes_more_than_half],
            messages={"deletes_more_than_half": "Too many deletes — check your plan."},
        )
        self.assertEqual(
            report.violations[0].message, "Too many deletes — check your plan."
        )

    def test_tallies_violation_count(self):
        changes = self._make_changes()
        report = evaluate_invariants(changes, {"total": 6}, [_deletes_more_than_half])
        self.assertEqual(report.tallies["violation_count"], 1)


class TestMultipleFailingChecksAreAllCollected(unittest.TestCase):
    """Proves evaluate_invariants does NOT short-circuit on first failure."""

    def test_both_violations_collected(self):
        changes = [
            {"op": "delete", "id": "1"},
            {"op": "delete", "id": "2"},
            {"op": "add_label", "id": "3"},
        ]
        report = evaluate_invariants(
            changes,
            {"total": 3},
            [_deletes_more_than_half, _no_new_labels],
        )
        self.assertFalse(report.passed)
        codes = {v.code for v in report.violations}
        self.assertIn("deletes_more_than_half", codes)
        self.assertIn("no_new_labels", codes)
        self.assertEqual(len(report.violations), 2)

    def test_tallies_reflect_all_violations(self):
        changes = [
            {"op": "delete", "id": "x"},
            {"op": "delete", "id": "y"},
            {"op": "add_label", "id": "z"},
        ]
        report = evaluate_invariants(
            changes, {"total": 3}, [_deletes_more_than_half, _no_new_labels]
        )
        self.assertEqual(report.tallies["violation_count"], 2)


class TestMaxSamplesTruncation(unittest.TestCase):
    def test_samples_capped_at_max_samples(self):
        changes = [{"op": "add_label", "id": str(i)} for i in range(20)]
        report = evaluate_invariants(changes, {}, [_no_new_labels], max_samples=5)
        self.assertEqual(len(report.violations[0].samples), 5)

    def test_samples_not_truncated_below_cap(self):
        changes = [{"op": "add_label", "id": str(i)} for i in range(3)]
        report = evaluate_invariants(changes, {}, [_no_new_labels], max_samples=10)
        self.assertEqual(len(report.violations[0].samples), 3)

    def test_violation_still_recorded_when_truncated(self):
        changes = [{"op": "add_label", "id": str(i)} for i in range(20)]
        report = evaluate_invariants(changes, {}, [_no_new_labels], max_samples=5)
        self.assertFalse(report.passed)
        self.assertEqual(len(report.violations), 1)


class TestRaisingCheckBehavior(unittest.TestCase):
    def test_raising_check_produces_violation(self):
        report = evaluate_invariants([{"op": "x"}], {}, [_raises])
        self.assertFalse(report.passed)
        self.assertEqual(len(report.violations), 1)

    def test_raising_check_code_is_check_error(self):
        report = evaluate_invariants([{"op": "x"}], {}, [_raises])
        self.assertEqual(report.violations[0].code, "check_error")

    def test_raising_check_sample_contains_error_text(self):
        report = evaluate_invariants([{"op": "x"}], {}, [_raises])
        sample = report.violations[0].samples[0]
        self.assertIn("boom", sample["error"])

    def test_raising_check_sample_contains_check_name(self):
        report = evaluate_invariants([{"op": "x"}], {}, [_raises])
        sample = report.violations[0].samples[0]
        self.assertIn("_raises", sample["check"])

    def test_other_checks_still_run_after_raising_check(self):
        """A raising check must not abort the run — subsequent checks still execute."""
        changes = [{"op": "add_label", "id": "1"}]
        report = evaluate_invariants(changes, {}, [_raises, _no_new_labels])
        codes = {v.code for v in report.violations}
        self.assertIn("check_error", codes)
        self.assertIn("no_new_labels", codes)

    def test_raising_check_custom_message(self):
        report = evaluate_invariants(
            [{"op": "x"}],
            {},
            [_raises],
            messages={"check_error": "A check threw an exception."},
        )
        self.assertEqual(report.violations[0].message, "A check threw an exception.")


class TestToDict(unittest.TestCase):
    def _round_trip(self, obj):
        return json.loads(json.dumps(obj))

    def test_evaluate_invariants_returns_preflight_report(self):
        report = evaluate_invariants([], {}, [])
        self.assertIsInstance(report, PreflightReport)

    def test_violation_to_dict_round_trips(self):
        v = InvariantViolation(
            code="my_code",
            message="my message",
            samples=[{"id": "1", "op": "delete"}],
        )
        d = self._round_trip(v.to_dict())
        self.assertEqual(d["code"], "my_code")
        self.assertEqual(d["message"], "my message")
        self.assertEqual(d["samples"], [{"id": "1", "op": "delete"}])

    def test_report_to_dict_round_trips(self):
        changes = [{"op": "delete", "id": "1"}, {"op": "delete", "id": "2"}]
        report = evaluate_invariants(changes, {"total": 2}, [_deletes_more_than_half])
        d = self._round_trip(report.to_dict())
        self.assertIn("passed", d)
        self.assertIn("violations", d)
        self.assertIn("tallies", d)
        self.assertIsInstance(d["violations"], list)

    def test_passing_report_to_dict_round_trips(self):
        report = evaluate_invariants([{"op": "x"}], {}, [_always_pass])
        d = self._round_trip(report.to_dict())
        self.assertTrue(d["passed"])
        self.assertEqual(d["violations"], [])

    def test_to_dict_is_json_serializable_with_samples(self):
        changes = [{"op": "add_label", "id": str(i)} for i in range(5)]
        report = evaluate_invariants(changes, {}, [_no_new_labels])
        # must not raise
        encoded = json.dumps(report.to_dict())
        self.assertIn("no_new_labels", encoded)


class TestSummary(unittest.TestCase):
    def test_passing_summary_starts_with_passed(self):
        report = evaluate_invariants([{"op": "x"}, {"op": "y"}], {}, [_always_pass])
        s = report.summary()
        self.assertTrue(s.startswith("PASSED"))
        self.assertIn("2 changes", s)
        self.assertIn("0 violations", s)

    def test_failing_summary_starts_with_failed(self):
        changes = [{"op": "add_label", "id": "1"}]
        report = evaluate_invariants(changes, {}, [_no_new_labels])
        s = report.summary()
        self.assertTrue(s.startswith("FAILED"))
        # Singular at a count of one — this is user-facing CLI output.
        self.assertEqual(s.splitlines()[0], "FAILED: 1 change, 1 violation")

    def test_failing_summary_lists_violation_codes(self):
        changes = [{"op": "add_label", "id": "1"}]
        report = evaluate_invariants(changes, {}, [_no_new_labels])
        s = report.summary()
        self.assertIn("no_new_labels", s)

    def test_multiple_violations_each_get_a_line(self):
        changes = [
            {"op": "delete", "id": "1"},
            {"op": "delete", "id": "2"},
            {"op": "add_label", "id": "3"},
        ]
        report = evaluate_invariants(
            changes, {"total": 3}, [_deletes_more_than_half, _no_new_labels]
        )
        s = report.summary()
        self.assertIn("deletes_more_than_half", s)
        self.assertIn("no_new_labels", s)


class TestMessageDerivation(unittest.TestCase):
    def test_underscores_become_spaces(self):
        changes = [{"op": "add_label"}]
        report = evaluate_invariants(changes, {}, [_no_new_labels])
        self.assertEqual(report.violations[0].message, "no new labels")

    def test_messages_mapping_takes_priority(self):
        changes = [{"op": "add_label"}]
        report = evaluate_invariants(
            changes, {}, [_no_new_labels], messages={"no_new_labels": "Custom text"}
        )
        self.assertEqual(report.violations[0].message, "Custom text")

    def test_missing_key_in_messages_falls_back_to_derivation(self):
        changes = [{"op": "add_label"}]
        report = evaluate_invariants(
            changes, {}, [_no_new_labels], messages={"other_code": "irrelevant"}
        )
        self.assertEqual(report.violations[0].message, "no new labels")


class TestSummaryPluralization(unittest.TestCase):
    """summary() is user-facing CLI output, so counts read naturally."""

    @staticmethod
    def _fail_check(changes, baseline):
        return "bad_thing", list(changes)

    def test_singular_forms_at_count_one(self):
        report = evaluate_invariants([{"id": "1"}], {}, [self._fail_check])
        first = report.summary().splitlines()[0]
        self.assertEqual(first, "FAILED: 1 change, 1 violation")

    def test_plural_forms_above_one(self):
        changes = [{"id": "1"}, {"id": "2"}]
        report = evaluate_invariants(changes, {}, [self._fail_check])
        self.assertIn("2 changes", report.summary().splitlines()[0])

    def test_plural_forms_at_zero(self):
        report = evaluate_invariants([], {}, [])
        first = report.summary().splitlines()[0]
        self.assertEqual(first, "PASSED: 0 changes, 0 violations")

    def test_sample_count_is_pluralized(self):
        one = evaluate_invariants([{"id": "1"}], {}, [self._fail_check])
        self.assertIn("(1 sample)", one.summary())
        two = evaluate_invariants(
            [{"id": "1"}, {"id": "2"}], {}, [self._fail_check]
        )
        self.assertIn("(2 samples)", two.summary())


if __name__ == "__main__":
    unittest.main()
