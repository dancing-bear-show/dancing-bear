"""Unit tests for slides bullet parsing primitives (_parse_bullets)."""

import unittest

from slides._parse_bullets import _body_to_bullets, _parse_bullets


# ---------------------------------------------------------------------------
# _parse_bullets
# ---------------------------------------------------------------------------

class TestParseBullets(unittest.TestCase):
    """Tests for _parse_bullets helper — dict bold, list/tuple shorthand."""

    def test_string_bullet(self):
        result = _parse_bullets(["hello"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "hello")
        self.assertEqual(result[0].level, 0)
        self.assertFalse(result[0].bold)

    def test_dict_bullet_with_bold_true(self):
        result = _parse_bullets([{"text": "important", "bold": True}])
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].bold)

    def test_dict_bullet_with_bold_false(self):
        result = _parse_bullets([{"text": "normal", "bold": False}])
        self.assertFalse(result[0].bold)

    def test_dict_bullet_bold_default(self):
        result = _parse_bullets([{"text": "no bold key"}])
        self.assertFalse(result[0].bold)

    def test_dict_bullet_bold_string_false_rejected(self):
        """bold: 'false' (string) should NOT be treated as True."""
        result = _parse_bullets([{"text": "tricky", "bold": "false"}])
        self.assertFalse(result[0].bold)

    def test_dict_bullet_bold_one_rejected(self):
        """bold: 1 (int) should NOT be treated as True — only bool True."""
        result = _parse_bullets([{"text": "tricky", "bold": 1}])
        self.assertFalse(result[0].bold)

    def test_list_bullet_text_only(self):
        result = _parse_bullets([["just text"]])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "just text")
        self.assertEqual(result[0].level, 0)

    def test_list_bullet_with_level(self):
        result = _parse_bullets([["indented", 1]])
        self.assertEqual(result[0].text, "indented")
        self.assertEqual(result[0].level, 1)

    def test_tuple_bullet_with_level(self):
        result = _parse_bullets([("sub-item", 2)])
        self.assertEqual(result[0].text, "sub-item")
        self.assertEqual(result[0].level, 2)

    def test_list_bullet_negative_level_raises(self):
        with self.assertRaisesRegex(ValueError, "non-negative"):
            _parse_bullets([["bad", -1]])

    def test_list_bullet_empty_raises(self):
        with self.assertRaisesRegex(ValueError, "1 or 2 elements"):
            _parse_bullets([[]])

    def test_list_bullet_too_many_elements_raises(self):
        with self.assertRaisesRegex(ValueError, "1 or 2 elements"):
            _parse_bullets([["text", 1, "extra"]])

    def test_mixed_bullet_types(self):
        result = _parse_bullets([
            "plain",
            {"text": "bold line", "bold": True},
            ["indented", 1],
        ])
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].text, "plain")
        self.assertFalse(result[0].bold)
        self.assertTrue(result[1].bold)
        self.assertEqual(result[2].level, 1)

    def test_dict_bullet_with_url(self):
        """Dict bullet with explicit url field sets url on BulletItem."""
        result = _parse_bullets([{"text": "Dashboard", "url": "https://grafana.example.com"}])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "Dashboard")
        self.assertEqual(result[0].url, "https://grafana.example.com")

    def test_dict_bullet_without_url(self):
        """Dict bullet without url field defaults to None."""
        result = _parse_bullets([{"text": "No link"}])
        self.assertIsNone(result[0].url)

    def test_string_bullet_url_autodetect_https(self):
        """String bullet starting with https:// auto-sets url."""
        result = _parse_bullets(["https://example.com/dashboard"])
        self.assertEqual(result[0].text, "https://example.com/dashboard")
        self.assertEqual(result[0].url, "https://example.com/dashboard")

    def test_string_bullet_url_autodetect_http(self):
        """String bullet starting with http:// auto-sets url."""
        result = _parse_bullets(["http://internal.example.com"])
        self.assertEqual(result[0].url, "http://internal.example.com")

    def test_string_bullet_no_url_autodetect(self):
        """Plain string bullet does not auto-detect url."""
        result = _parse_bullets(["Plain text bullet"])
        self.assertIsNone(result[0].url)

    def test_string_bullet_url_not_at_start(self):
        """String with URL in the middle does not auto-detect."""
        result = _parse_bullets(["Visit https://example.com for details"])
        self.assertIsNone(result[0].url)

    def test_list_bullet_no_url(self):
        """List/tuple bullets do not support url field."""
        result = _parse_bullets([["some text", 1]])
        self.assertIsNone(result[0].url)


# ---------------------------------------------------------------------------
# _body_to_bullets
# ---------------------------------------------------------------------------

class TestBodyToBullets(unittest.TestCase):
    """Tests for _body_to_bullets helper — multiline body string to BulletItem list."""

    def test_plain_lines_level_zero(self):
        """Plain text lines become level-0 bullets."""
        result = _body_to_bullets("Line one\nLine two")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].text, "Line one")
        self.assertEqual(result[0].level, 0)
        self.assertEqual(result[1].text, "Line two")
        self.assertEqual(result[1].level, 0)

    def test_dash_bullet_level_one(self):
        """Lines starting with '- ' become level-1 bullets."""
        result = _body_to_bullets("- First item\n- Second item")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].text, "First item")
        self.assertEqual(result[0].level, 1)
        self.assertEqual(result[1].text, "Second item")
        self.assertEqual(result[1].level, 1)

    def test_indented_dash_bullet_level_two(self):
        """Lines with 2+ spaces before '- ' become level-2 bullets."""
        # Note: body.strip("\n") only strips newlines (not spaces), but the
        # first line still has no leading indent — use a plain line first
        # to test that indentation on subsequent lines is preserved.
        result = _body_to_bullets("Header\n  - Sub-item\n    - Deep sub-item")
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].text, "Header")
        self.assertEqual(result[0].level, 0)
        self.assertEqual(result[1].text, "Sub-item")
        self.assertEqual(result[1].level, 2)
        self.assertEqual(result[2].text, "Deep sub-item")
        self.assertEqual(result[2].level, 2)

    def test_mixed_levels(self):
        """Mix of plain, dash, and indented dash lines."""
        body = "Overview\n- Point one\n  - Detail\nConclusion"
        result = _body_to_bullets(body)
        self.assertEqual(len(result), 4)
        self.assertEqual(result[0].level, 0)
        self.assertEqual(result[1].level, 1)
        self.assertEqual(result[2].level, 2)
        self.assertEqual(result[3].level, 0)

    def test_blank_lines_skipped(self):
        """Blank lines are skipped."""
        result = _body_to_bullets("Line one\n\n\nLine two")
        self.assertEqual(len(result), 2)

    def test_leading_trailing_whitespace_stripped(self):
        """Leading/trailing blank lines from body.strip() are handled."""
        result = _body_to_bullets("\n\nContent here\n\n")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "Content here")

    def test_empty_string(self):
        """Empty string returns empty list."""
        result = _body_to_bullets("")
        self.assertEqual(result, [])

    def test_whitespace_only(self):
        """Whitespace-only string returns empty list."""
        result = _body_to_bullets("   \n  \n  ")
        self.assertEqual(result, [])

if __name__ == "__main__":
    unittest.main()
