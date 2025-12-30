"""Tests for calendars/scan_common.py schedule parsing utilities."""
import unittest

from calendars.scan_common import (
    DAY_MAP,
    MONTH_MAP,
    norm_time,
    infer_meta_from_text,
)


class DayMapTests(unittest.TestCase):
    """Tests for DAY_MAP constant."""

    def test_monday_variants(self):
        self.assertEqual(DAY_MAP["monday"], "MO")
        self.assertEqual(DAY_MAP["mon"], "MO")

    def test_tuesday_variants(self):
        self.assertEqual(DAY_MAP["tuesday"], "TU")
        self.assertEqual(DAY_MAP["tue"], "TU")
        self.assertEqual(DAY_MAP["tues"], "TU")

    def test_wednesday_variants(self):
        self.assertEqual(DAY_MAP["wednesday"], "WE")
        self.assertEqual(DAY_MAP["wed"], "WE")

    def test_thursday_variants(self):
        self.assertEqual(DAY_MAP["thursday"], "TH")
        self.assertEqual(DAY_MAP["thu"], "TH")
        self.assertEqual(DAY_MAP["thur"], "TH")
        self.assertEqual(DAY_MAP["thurs"], "TH")

    def test_friday_variants(self):
        self.assertEqual(DAY_MAP["friday"], "FR")
        self.assertEqual(DAY_MAP["fri"], "FR")

    def test_saturday_variants(self):
        self.assertEqual(DAY_MAP["saturday"], "SA")
        self.assertEqual(DAY_MAP["sat"], "SA")

    def test_sunday_variants(self):
        self.assertEqual(DAY_MAP["sunday"], "SU")
        self.assertEqual(DAY_MAP["sun"], "SU")


class MonthMapTests(unittest.TestCase):
    """Tests for MONTH_MAP constant."""

    def test_full_month_names(self):
        self.assertEqual(MONTH_MAP["january"], 1)
        self.assertEqual(MONTH_MAP["february"], 2)
        self.assertEqual(MONTH_MAP["march"], 3)
        self.assertEqual(MONTH_MAP["december"], 12)

    def test_abbreviated_month_names(self):
        self.assertEqual(MONTH_MAP["jan"], 1)
        self.assertEqual(MONTH_MAP["feb"], 2)
        self.assertEqual(MONTH_MAP["mar"], 3)
        self.assertEqual(MONTH_MAP["dec"], 12)


class NormTimeTests(unittest.TestCase):
    """Tests for norm_time function."""

    def test_24h_format(self):
        result = norm_time("14", "30", None)
        self.assertEqual(result, "14:30")

    def test_12h_am(self):
        result = norm_time("9", "00", "am")
        self.assertEqual(result, "09:00")

    def test_12h_pm(self):
        result = norm_time("2", "30", "pm")
        self.assertEqual(result, "14:30")

    def test_12_pm_noon(self):
        result = norm_time("12", "00", "pm")
        self.assertEqual(result, "12:00")

    def test_12_am_midnight(self):
        result = norm_time("12", "00", "am")
        self.assertEqual(result, "00:00")

    def test_no_minutes(self):
        result = norm_time("10", None, None)
        self.assertEqual(result, "10:00")

    def test_pm_with_dots(self):
        result = norm_time("3", "15", "p.m.")
        self.assertEqual(result, "15:15")

    def test_am_with_dots(self):
        result = norm_time("9", "45", "a.m.")
        self.assertEqual(result, "09:45")

    def test_single_digit_hour(self):
        result = norm_time("8", "00", "am")
        self.assertEqual(result, "08:00")


class InferMetaFromTextTests(unittest.TestCase):
    """Tests for infer_meta_from_text function."""

    def test_empty_text(self):
        result = infer_meta_from_text("")
        self.assertEqual(result, {})

    def test_none_text(self):
        result = infer_meta_from_text(None)
        self.assertEqual(result, {})

    def test_extracts_location_from_label(self):
        text = "Location: Downtown Community Center\nClass starts Monday"
        result = infer_meta_from_text(text)
        self.assertEqual(result["location"], "Downtown Community Center")

    def test_extracts_venue_label(self):
        text = "Venue: Main Hall\nTime: 10am"
        result = infer_meta_from_text(text)
        self.assertEqual(result["location"], "Main Hall")

    def test_extracts_facility_from_text(self):
        text = "Swimming lessons at Ed Sackfield Arena"
        result = infer_meta_from_text(text)
        self.assertEqual(result["location"], "Ed Sackfield")

    def test_extracts_date_range(self):
        text = "Program runs from January 15, 2025 to March 30, 2025"
        result = infer_meta_from_text(text)
        self.assertIn("range", result)
        self.assertEqual(result["range"]["start_date"], "2025-01-15")
        self.assertEqual(result["range"]["until"], "2025-03-30")

    def test_extracts_date_range_abbreviated_months(self):
        text = "Session: Jan 6 to Feb 28, 2025"
        result = infer_meta_from_text(text)
        self.assertIn("range", result)
        self.assertEqual(result["range"]["start_date"], "2025-01-06")
        self.assertEqual(result["range"]["until"], "2025-02-28")

    def test_extracts_swimmer_class(self):
        text = "Your child is enrolled in Swimmer 3 on Tuesdays"
        result = infer_meta_from_text(text)
        self.assertIn("subject", result)
        self.assertIn("Swimmer", result["subject"])

    def test_extracts_swim_kids_class(self):
        text = "Swim Kids 5 - Mondays at 4pm"
        result = infer_meta_from_text(text)
        self.assertIn("subject", result)
        self.assertIn("Swim", result["subject"])

    def test_extracts_preschool_class(self):
        text = "Preschool A swimming program"
        result = infer_meta_from_text(text)
        self.assertIn("subject", result)
        self.assertIn("Preschool", result["subject"])

    def test_extracts_bronze_medallion(self):
        text = "Bronze Medallion certification course"
        result = infer_meta_from_text(text)
        self.assertIn("subject", result)
        self.assertIn("Bronze", result["subject"])

    def test_extracts_private_lesson(self):
        text = "Private Lesson scheduled for Saturday"
        result = infer_meta_from_text(text)
        self.assertIn("subject", result)
        self.assertIn("Private", result["subject"])

    def test_location_label_takes_precedence(self):
        # Location: label should take precedence over facility match
        text = "Location: Custom Venue\nEd Sackfield is nearby"
        result = infer_meta_from_text(text)
        self.assertEqual(result["location"], "Custom Venue")

    def test_multiple_facilities_first_match(self):
        text = "At Richmond Green or Elgin West"
        result = infer_meta_from_text(text)
        self.assertIn(result["location"], ["Richmond Green", "Elgin West"])

    def test_default_year_used(self):
        text = "From Jan 15 to Mar 30"
        result = infer_meta_from_text(text, default_year=2026)
        self.assertIn("range", result)
        self.assertEqual(result["range"]["start_date"], "2026-01-15")
        self.assertEqual(result["range"]["until"], "2026-03-30")

    def test_complex_email_text(self):
        text = """
        Dear Parent,

        Your child is enrolled in Swimmer 2 at Ed Sackfield Arena.
        The session runs from January 6, 2025 to March 15, 2025.

        Location: Ed Sackfield Arena
        Day: Monday
        Time: 4:00 pm - 4:30 pm
        """
        result = infer_meta_from_text(text)
        self.assertEqual(result["location"], "Ed Sackfield Arena")
        self.assertIn("range", result)
        self.assertIn("subject", result)


if __name__ == "__main__":
    unittest.main()
