"""Tests for core.parallel — chunked and parallel_map."""

from __future__ import annotations

import unittest

from core.parallel import chunked, parallel_map


class TestChunked(unittest.TestCase):
    def test_empty_sequence(self) -> None:
        result = list(chunked([], 3))
        self.assertEqual(result, [])

    def test_exact_multiple(self) -> None:
        result = list(chunked([1, 2, 3, 4, 5, 6], 3))
        self.assertEqual(result, [[1, 2, 3], [4, 5, 6]])

    def test_remainder(self) -> None:
        result = list(chunked([1, 2, 3, 4, 5], 3))
        self.assertEqual(result, [[1, 2, 3], [4, 5]])

    def test_size_one(self) -> None:
        result = list(chunked([1, 2, 3], 1))
        self.assertEqual(result, [[1], [2], [3]])

    def test_size_greater_than_len(self) -> None:
        result = list(chunked([1, 2], 10))
        self.assertEqual(result, [[1, 2]])

    def test_size_zero_clamped_to_one(self) -> None:
        result = list(chunked([1, 2, 3], 0))
        self.assertEqual(result, [[1], [2], [3]])

    def test_preserves_order(self) -> None:
        seq = list(range(10))
        chunks = list(chunked(seq, 3))
        flat = [x for chunk in chunks for x in chunk]
        self.assertEqual(flat, seq)

    def test_non_destructive(self) -> None:
        original = [1, 2, 3, 4]
        _ = list(chunked(original, 2))
        self.assertEqual(original, [1, 2, 3, 4])


class TestParallelMap(unittest.TestCase):
    def test_order_preservation(self) -> None:
        result = parallel_map(lambda x: x * 2, list(range(10)))
        self.assertEqual(result, [i * 2 for i in range(10)])

    def test_empty_input(self) -> None:
        result = parallel_map(lambda x: x, [])
        self.assertEqual(result, [])

    def test_exception_returns_none_by_default(self) -> None:
        def boom(x: int) -> int:
            if x == 2:
                raise ValueError("bad")
            return x

        result = parallel_map(boom, [1, 2, 3])
        self.assertEqual(result[0], 1)
        self.assertIsNone(result[1])
        self.assertEqual(result[2], 3)

    def test_return_exceptions_true(self) -> None:
        def boom(x: int) -> int:
            if x == 1:
                raise RuntimeError("oops")
            return x

        result = parallel_map(boom, [0, 1, 2], return_exceptions=True)
        self.assertEqual(result[0], 0)
        self.assertIsInstance(result[1], RuntimeError)
        self.assertEqual(result[2], 2)

    def test_max_workers_clamped_to_one(self) -> None:
        result = parallel_map(lambda x: x + 1, [1, 2, 3], max_workers=0)
        self.assertEqual(result, [2, 3, 4])

    def test_max_workers_custom(self) -> None:
        result = parallel_map(lambda x: x * x, [1, 2, 3, 4], max_workers=2)
        self.assertEqual(result, [1, 4, 9, 16])

    def test_single_item(self) -> None:
        result = parallel_map(str, [42])
        self.assertEqual(result, ["42"])


if __name__ == "__main__":
    unittest.main()
