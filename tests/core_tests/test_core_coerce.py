"""Tests for core.coerce."""

from __future__ import annotations

import unittest

from core.coerce import coerce_bool, coerce_int, parse_bool


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


class TestParseBool(unittest.TestCase):
    def test_true_spellings(self):
        for value in (True, 1, "1", "true", "TRUE", "yes", "on", "  On  "):
            with self.subTest(value=value):
                self.assertIs(parse_bool(value), True)

    def test_false_spellings(self):
        for value in (False, 0, "0", "false", "False", "no", "off", " OFF "):
            with self.subTest(value=value):
                self.assertIs(parse_bool(value), False)

    def test_unrecognised_is_none(self):
        for value in (None, "", "maybe", "none", 2, -1, 1.0, [], {}):
            with self.subTest(value=value):
                self.assertIsNone(parse_bool(value))

    def test_extra_false_spellings(self):
        extra = frozenset({"none"})
        self.assertIs(parse_bool("None", extra_false=extra), False)
        self.assertIs(parse_bool("on", extra_false=extra), True)
        self.assertIsNone(parse_bool("maybe", extra_false=extra))


class TestCoerceBool(unittest.TestCase):
    def test_recognised_values_ignore_default(self):
        self.assertIs(coerce_bool("off", True), False)
        self.assertIs(coerce_bool("on", False), True)
        self.assertIs(coerce_bool(0, True), False)

    def test_unrecognised_uses_default(self):
        for default in (True, False):
            for value in (None, "maybe", 2):
                with self.subTest(value=value, default=default):
                    self.assertIs(coerce_bool(value, default), default)


if __name__ == "__main__":
    unittest.main()
