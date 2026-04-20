"""Tests for core/collections.py uncovered branches."""

from __future__ import annotations

import unittest

from core.collections import dedupe


class TestDedupe(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(dedupe([]), [])

    def test_no_duplicates(self):
        self.assertEqual(dedupe([1, 2, 3]), [1, 2, 3])

    def test_removes_duplicates_preserves_order(self):
        self.assertEqual(dedupe([1, 2, 2, 3, 1]), [1, 2, 3])

    def test_all_duplicates(self):
        self.assertEqual(dedupe([5, 5, 5]), [5])

    def test_strings(self):
        result = dedupe(["a", "b", "a", "c", "b"])
        self.assertEqual(result, ["a", "b", "c"])

    def test_with_key_fn_dicts(self):
        items = [{"a": 1, "b": "x"}, {"a": 1, "b": "y"}, {"a": 2, "b": "z"}]
        result = dedupe(items, key_fn=lambda x: x["a"])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], {"a": 1, "b": "x"})
        self.assertEqual(result[1], {"a": 2, "b": "z"})

    def test_with_key_fn_strings(self):
        items = ["Apple", "apple", "APPLE", "Banana"]
        result = dedupe(items, key_fn=str.lower)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], "Apple")
        self.assertEqual(result[1], "Banana")

    def test_identity_key_fn_is_default(self):
        items = [1, 2, 1, 3]
        result_default = dedupe(items)
        result_explicit = dedupe(items, key_fn=lambda x: x)
        self.assertEqual(result_default, result_explicit)

    def test_preserves_first_occurrence(self):
        items = [{"id": 1, "v": "first"}, {"id": 1, "v": "second"}]
        result = dedupe(items, key_fn=lambda x: x["id"])
        self.assertEqual(result[0]["v"], "first")

    def test_single_item(self):
        self.assertEqual(dedupe([42]), [42])

    def test_none_key_fn_uses_identity(self):
        result = dedupe([3, 1, 2, 1, 3], key_fn=None)
        self.assertEqual(result, [3, 1, 2])


if __name__ == "__main__":
    unittest.main()
