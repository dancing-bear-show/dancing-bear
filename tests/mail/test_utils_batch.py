"""Tests for mail/utils/batch.py chunking utilities."""

import unittest

from mail.utils.batch import chunked, apply_in_chunks


class ChunkedTests(unittest.TestCase):
    def test_empty_sequence(self):
        result = list(chunked([], 5))
        self.assertEqual(result, [])

    def test_sequence_smaller_than_chunk(self):
        result = list(chunked([1, 2, 3], 5))
        self.assertEqual(result, [[1, 2, 3]])

    def test_sequence_exact_chunk_size(self):
        result = list(chunked([1, 2, 3, 4], 2))
        self.assertEqual(result, [[1, 2], [3, 4]])

    def test_sequence_with_remainder(self):
        result = list(chunked([1, 2, 3, 4, 5], 2))
        self.assertEqual(result, [[1, 2], [3, 4], [5]])

    def test_chunk_size_one(self):
        result = list(chunked([1, 2, 3], 1))
        self.assertEqual(result, [[1], [2], [3]])

    def test_large_chunk_size(self):
        result = list(chunked([1, 2], 100))
        self.assertEqual(result, [[1, 2]])

    def test_works_with_generator(self):
        gen = (x for x in range(5))
        result = list(chunked(gen, 2))
        self.assertEqual(result, [[0, 1], [2, 3], [4]])

    def test_works_with_strings(self):
        result = list(chunked("abcde", 2))
        self.assertEqual(result, [["a", "b"], ["c", "d"], ["e"]])

    def test_preserves_order(self):
        items = list(range(10))
        result = list(chunked(items, 3))
        flattened = [item for chunk in result for item in chunk]
        self.assertEqual(flattened, items)


class ApplyInChunksTests(unittest.TestCase):
    def test_empty_sequence(self):
        results = []
        apply_in_chunks(lambda x: results.extend(x), [], 5)
        self.assertEqual(results, [])

    def test_applies_to_all_chunks(self):
        results = []
        apply_in_chunks(lambda x: results.append(x), [1, 2, 3, 4, 5], 2)
        self.assertEqual(results, [[1, 2], [3, 4], [5]])

    def test_function_receives_lists(self):
        received = []
        def capture(chunk):
            received.append(type(chunk).__name__)
        apply_in_chunks(capture, range(3), 2)
        self.assertTrue(all(t == "list" for t in received))

    def test_side_effects_applied(self):
        total = [0]  # Using list to allow mutation in nested function
        def sum_chunk(chunk):
            total[0] += sum(chunk)
        apply_in_chunks(sum_chunk, [1, 2, 3, 4, 5], 2)
        self.assertEqual(total[0], 15)

    def test_chunk_size_respected(self):
        max_seen = [0]
        def check_size(chunk):
            max_seen[0] = max(max_seen[0], len(chunk))
        apply_in_chunks(check_size, range(10), 3)
        self.assertLessEqual(max_seen[0], 3)


if __name__ == "__main__":
    unittest.main()
