"""Tests for worker.queue_ops.effective_job_timeout."""
from __future__ import annotations

import unittest

from worker.queue_ops import effective_job_timeout


class TestEffectiveJobTimeout(unittest.TestCase):
    def test_positive_override_wins(self):
        for raw, expected in ((30, 30), ("45", 45), (12.9, 12)):
            with self.subTest(raw=raw):
                self.assertEqual(effective_job_timeout({"timeout_sec": raw}, 600), expected)

    def test_missing_zero_or_negative_uses_default(self):
        for data in ({}, {"timeout_sec": None}, {"timeout_sec": 0}, {"timeout_sec": -5}):
            with self.subTest(data=data):
                self.assertEqual(effective_job_timeout(data, 600), 600)

    def test_unconvertible_values_use_default(self):
        for raw in ("abc", "1.5", [30], {"s": 30}):
            with self.subTest(raw=raw):
                self.assertEqual(effective_job_timeout({"timeout_sec": raw}, 600), 600)

    def test_non_finite_floats_use_default(self):
        """json decodes Infinity/NaN; int() raises OverflowError/ValueError on them."""
        for raw in (float("inf"), float("-inf"), float("nan")):
            with self.subTest(raw=raw):
                self.assertEqual(effective_job_timeout({"timeout_sec": raw}, 600), 600)


if __name__ == "__main__":
    unittest.main()
