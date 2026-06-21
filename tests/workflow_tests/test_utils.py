"""Tests for workflow.utils."""

import unittest

from workflow.utils import dedupe_preserving_order


class TestDedupePreservingOrder(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(dedupe_preserving_order(["a", "b", "a", "c", "b"]), ["a", "b", "c"])

    def test_empty(self):
        self.assertEqual(dedupe_preserving_order([]), [])

    def test_no_duplicates(self):
        self.assertEqual(dedupe_preserving_order(["a", "b", "c"]), ["a", "b", "c"])

    def test_all_duplicates(self):
        self.assertEqual(dedupe_preserving_order(["x", "x", "x"]), ["x"])

    def test_tuple_input(self):
        self.assertEqual(dedupe_preserving_order(("x", "y", "x")), ["x", "y"])

    def test_int_values(self):
        self.assertEqual(dedupe_preserving_order([1, 2, 1, 3, 2]), [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
