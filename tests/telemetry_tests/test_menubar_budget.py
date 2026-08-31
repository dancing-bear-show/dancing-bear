"""Tests for telemetry/_menubar_budget.py — budget scoring and safe-coerce helpers."""
from __future__ import annotations

import unittest

from telemetry._menubar_budget import _budget_score, _safe_float, _safe_int, _to_int


class TestBudgetScore(unittest.TestCase):
    def test_zero_budget_returns_one(self) -> None:
        self.assertEqual(_budget_score(100.0, 0.0), 1)

    def test_negative_budget_returns_one(self) -> None:
        self.assertEqual(_budget_score(100.0, -50.0), 1)

    def test_no_spend_returns_one(self) -> None:
        self.assertEqual(_budget_score(0.0, 1000.0), 1)

    def test_half_budget_returns_five(self) -> None:
        self.assertEqual(_budget_score(500.0, 1000.0), 5)

    def test_full_budget_returns_ten(self) -> None:
        self.assertEqual(_budget_score(1000.0, 1000.0), 10)

    def test_over_budget_capped_at_ten(self) -> None:
        self.assertEqual(_budget_score(2000.0, 1000.0), 10)

    def test_minimum_clamped_to_one(self) -> None:
        self.assertEqual(_budget_score(0.001, 1000.0), 1)

    def test_rounding(self) -> None:
        # 350/1000*10 = 3.5 -> rounds to 4
        self.assertEqual(_budget_score(350.0, 1000.0), 4)

    def test_score_range_across_scale(self) -> None:
        budget = 100.0
        for spend, expected in [(10.0, 1), (20.0, 2), (50.0, 5), (80.0, 8), (100.0, 10)]:
            with self.subTest(spend=spend):
                score = _budget_score(spend, budget)
                self.assertEqual(score, expected)


class TestSafeFloat(unittest.TestCase):
    def test_float_passthrough(self) -> None:
        self.assertEqual(_safe_float(3.14, 0.0), 3.14)

    def test_int_converted(self) -> None:
        self.assertEqual(_safe_float(5, 0.0), 5.0)

    def test_string_number_converted(self) -> None:
        self.assertEqual(_safe_float("2.5", 0.0), 2.5)

    def test_bool_returns_default(self) -> None:
        self.assertEqual(_safe_float(True, 9.9), 9.9)
        self.assertEqual(_safe_float(False, 9.9), 9.9)

    def test_none_returns_default(self) -> None:
        self.assertEqual(_safe_float(None, 7.0), 7.0)

    def test_invalid_string_returns_default(self) -> None:
        self.assertEqual(_safe_float("not-a-number", 1.5), 1.5)

    def test_empty_string_returns_default(self) -> None:
        self.assertEqual(_safe_float("", 2.0), 2.0)

    def test_zero_float(self) -> None:
        self.assertEqual(_safe_float(0.0, 99.0), 0.0)


class TestSafeInt(unittest.TestCase):
    def test_int_passthrough(self) -> None:
        self.assertEqual(_safe_int(42, 0), 42)

    def test_float_truncated(self) -> None:
        self.assertEqual(_safe_int(3.9, 0), 3)

    def test_string_number_converted(self) -> None:
        self.assertEqual(_safe_int("7", 0), 7)

    def test_bool_returns_default(self) -> None:
        self.assertEqual(_safe_int(True, 9), 9)
        self.assertEqual(_safe_int(False, 9), 9)

    def test_none_returns_default(self) -> None:
        self.assertEqual(_safe_int(None, 99), 99)

    def test_invalid_string_returns_default(self) -> None:
        self.assertEqual(_safe_int("abc", 5), 5)

    def test_zero_int(self) -> None:
        self.assertEqual(_safe_int(0, 99), 0)


class TestToInt(unittest.TestCase):
    """_to_int must handle both precision requirements.

    Requirement 1: 19-digit nanosecond timestamps must be exact.
      int(float(1705320000123456789)) loses 21ns; only int passthrough is correct.
    Requirement 2: float values like 123.0 must round-trip.
      int("123.0") raises ValueError; only the float path handles it.
    Neither int(str(v)) nor int(float(v)) alone satisfies both — hence the
    three-branch form in _to_int.
    """

    _NS_EXACT = 1705320000123456789  # 19-digit ns timestamp

    def test_int_ns_timestamp_exact(self) -> None:
        """int passthrough preserves 19-digit precision; float would lose 21ns."""
        result = _to_int(self._NS_EXACT)
        self.assertEqual(result, self._NS_EXACT)

    def test_float_rounds_to_int(self) -> None:
        """float 123.0 must convert without ValueError."""
        self.assertEqual(_to_int(123.0), 123)

    def test_float_string_converts(self) -> None:
        """String '123.0' must convert; int('123.0') would raise ValueError."""
        self.assertEqual(_to_int("123.0"), 123)

    def test_int_string_converts(self) -> None:
        self.assertEqual(_to_int("456"), 456)

    def test_plain_int_passthrough(self) -> None:
        self.assertEqual(_to_int(42), 42)

    def test_zero_int(self) -> None:
        self.assertEqual(_to_int(0), 0)

    def test_bool_returns_zero(self) -> None:
        # bool is a subclass of int but must not be treated as a plain int
        self.assertEqual(_to_int(True), 0)
        self.assertEqual(_to_int(False), 0)

    def test_invalid_string_returns_zero(self) -> None:
        self.assertEqual(_to_int("not-a-number"), 0)

    def test_none_returns_zero(self) -> None:
        self.assertEqual(_to_int(None), 0)


if __name__ == "__main__":
    unittest.main()
