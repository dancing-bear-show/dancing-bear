import json
import unittest

from whatsapp import search


class TestWhatsAppSearchHelpers(unittest.TestCase):
    def test_build_like_clause_filters_terms(self):
        clause, params = search._build_like_clause(
            "m.ZTEXT", [" Hello ", "", "WORLD", None], match_all=False
        )
        self.assertEqual(clause, "(lower(m.ZTEXT) LIKE ? OR lower(m.ZTEXT) LIKE ?)")
        self.assertEqual(params, ["%hello%", "%world%"])

    def test_build_like_clause_empty(self):
        clause, params = search._build_like_clause("m.ZTEXT", [" ", ""], match_all=True)
        self.assertEqual(clause, "")
        self.assertEqual(params, [])

    def test_build_where_includes_contact_and_from(self):
        where, params = search._build_where(
            contains=["alpha", "beta"],
            match_all=True,
            contact="Teacher",
            from_me=True,
            since_days=None,
        )
        self.assertIn("m.ZTEXT IS NOT NULL", where)
        self.assertIn("lower(m.ZTEXT) LIKE ? AND lower(m.ZTEXT) LIKE ?", where)
        self.assertIn("lower(s.ZPARTNERNAME) LIKE ?", where)
        self.assertIn("m.ZISFROMME = 1", where)
        self.assertEqual(params[:3], ["%alpha%", "%beta%", "%teacher%"])

    def test_format_rows_json(self):
        rows = [
            search.MessageRow(ts="2024-01-02 03:04", partner="Alice", from_me=1, text="Hello"),
            search.MessageRow(ts="2024-01-02 03:05", partner="Bob", from_me=0, text="Hi"),
        ]
        raw = search.format_rows_json(rows)
        data = json.loads(raw)
        self.assertEqual(data[0]["from_me"], True)
        self.assertEqual(data[1]["from_me"], False)
        self.assertEqual(data[0]["partner"], "Alice")


if __name__ == "__main__":
    unittest.main(verbosity=2)
