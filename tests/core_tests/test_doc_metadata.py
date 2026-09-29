"""Tests for core.doc_metadata, shared by the slides and sheets generators."""

from __future__ import annotations

import datetime
import unittest

from core.doc_metadata import HEADER_BG_HEX, DocMetadata, parse_doc_metadata


class TestParseDocMetadata(unittest.TestCase):
    def test_missing_fields_use_default_title_and_none(self) -> None:
        self.assertEqual(
            parse_doc_metadata({}, "Untitled"),
            DocMetadata(title="Untitled", author=None, date=None),
        )

    def test_null_date_is_none(self) -> None:
        self.assertIsNone(parse_doc_metadata({"date": None}, "T").date)

    def test_empty_values_pass_through(self) -> None:
        meta = parse_doc_metadata({"title": "", "author": "", "date": ""}, "T")
        self.assertEqual(meta, DocMetadata(title="", author="", date=""))

    def test_present_fields(self) -> None:
        meta = parse_doc_metadata(
            {"title": "Deck", "author": "Alice", "date": "2026-01-15"}, "T"
        )
        self.assertEqual(meta, DocMetadata(title="Deck", author="Alice", date="2026-01-15"))

    def test_yaml_date_object_is_stringified(self) -> None:
        meta = parse_doc_metadata({"date": datetime.date(2026, 1, 15)}, "T")
        self.assertEqual(meta.date, "2026-01-15")


class TestHeaderBgHex(unittest.TestCase):
    def test_is_six_char_hex_without_hash(self) -> None:
        self.assertEqual(len(HEADER_BG_HEX), 6)
        int(HEADER_BG_HEX, 16)


if __name__ == "__main__":
    unittest.main()
