"""Tests for core.coerce."""
from __future__ import annotations

import unittest

from core.coerce import coerce_int


class TestCoerceInt(unittest.TestCase):
    def test_converts_like_int(self):
        cases = [("42", 42), ("-3", -3), (7, 7), (3.9, 3), (True, 1)]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(coerce_int(value, 99), expected)

    def test_falls_back_to_default_on_failure(self):
        for value in (None, "abc", "3.5", "", [1], float("inf")):
            with self.subTest(value=value):
                self.assertEqual(coerce_int(value, 99), 99)

    def test_default_defaults_to_zero(self):
        self.assertEqual(coerce_int("nope"), 0)


if __name__ == "__main__":
    unittest.main()
