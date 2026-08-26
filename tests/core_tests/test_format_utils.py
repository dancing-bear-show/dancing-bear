"""Tests for core/format_utils.py — canonical token-count formatter."""
from __future__ import annotations

import unittest

from core.format_utils import format_tokens


class TestFormatTokens(unittest.TestCase):
    def test_sub_thousand_passthrough(self):
        self.assertEqual(format_tokens(0), "0")
        self.assertEqual(format_tokens(500), "500")
        self.assertEqual(format_tokens(999), "999")

    def test_exactly_one_thousand(self):
        self.assertEqual(format_tokens(1_000), "1K")

    def test_mid_k_banker_rounding(self):
        # :.0f uses round-half-to-even: 1.5 -> 2, 2.5 -> 2, 3.5 -> 4.
        self.assertEqual(format_tokens(1_500), "2K")
        # 2500 / 1000 = 2.5, banker's rounding -> 2
        self.assertEqual(format_tokens(2_500), "2K")
        # 3500 / 1000 = 3.5, banker's rounding -> 4
        self.assertEqual(format_tokens(3_500), "4K")

    def test_last_value_still_renders_as_k(self):
        self.assertEqual(format_tokens(999_499), "999K")

    def test_999_500_rollover_to_m(self):
        # 999_500 / 1000 = 999.5 -> rounds to 1000K, which must roll over to
        # 1.0M rather than emit four K digits.  The M threshold is checked
        # *before* the K branch so the rollover is guaranteed.
        self.assertEqual(format_tokens(999_500), "1.0M")
        self.assertEqual(format_tokens(999_999), "1.0M")

    def test_m_range(self):
        self.assertEqual(format_tokens(1_000_000), "1.0M")
        self.assertEqual(format_tokens(2_500_000), "2.5M")
        self.assertEqual(format_tokens(10_000_000), "10.0M")


if __name__ == "__main__":
    unittest.main()
