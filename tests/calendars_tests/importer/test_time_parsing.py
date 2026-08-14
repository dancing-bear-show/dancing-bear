"""Tests for time-parsing helpers in calendars/importer.py."""

import unittest

from calendars.importer import (
    normalize_days,
)


class TestNormalizeDays(unittest.TestCase):
    """Tests for normalize_days function."""

    def test_day_range_wraps_around_end_of_week(self):
        """Fri to Mon must wrap past Sunday, distinct from a forward-only range."""
        self.assertEqual(normalize_days("Fri to Mon"), ["FR", "SA", "SU", "MO"])


if __name__ == "__main__":
    unittest.main()
