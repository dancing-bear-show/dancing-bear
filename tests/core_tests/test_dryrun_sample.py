"""Happy-path tests for the dry-run sample module.

These pass despite the module's planted defects — the point of the dry run is
for review threads, not a red suite, to surface them.
"""

from __future__ import annotations

import unittest

from core.dryrun_sample import chunk, clamp, mean


class TestDryrunSample(unittest.TestCase):
    def test_chunk_even_split(self):
        self.assertEqual(chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])

    def test_mean(self):
        self.assertEqual(mean([2.0, 4.0]), 3.0)

    def test_clamp(self):
        self.assertEqual(clamp(5, 0, 3), 3)
        self.assertEqual(clamp(-1, 0, 3), 0)
        self.assertEqual(clamp(2, 0, 3), 2)


if __name__ == "__main__":
    unittest.main()
