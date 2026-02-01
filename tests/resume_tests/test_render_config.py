"""Tests for resume/render_config.py dataclass models."""

from __future__ import annotations

import unittest

from resume.render_config import (
    BulletConfig,
    HeaderLineConfig,
    MetaRunConfig,
    RenderContext,
    ExperienceRenderConfig,
)


class TestBulletConfig(unittest.TestCase):
    """Tests for BulletConfig dataclass."""

    def test_default_values(self):
        config = BulletConfig()
        self.assertEqual(config.glyph, "•")
        self.assertEqual(config.list_style, "List Bullet")
        self.assertTrue(config.plain)
        self.assertEqual(config.sep, ": ")

    def test_custom_glyph(self):
        config = BulletConfig(glyph="-")
        self.assertEqual(config.glyph, "-")
        self.assertEqual(config.list_style, "List Bullet")
        self.assertTrue(config.plain)
        self.assertEqual(config.sep, ": ")

    def test_custom_list_style(self):
        config = BulletConfig(list_style="Custom Style")
        self.assertEqual(config.glyph, "•")
        self.assertEqual(config.list_style, "Custom Style")
        self.assertTrue(config.plain)
        self.assertEqual(config.sep, ": ")

    def test_plain_false(self):
        config = BulletConfig(plain=False)
        self.assertEqual(config.glyph, "•")
        self.assertEqual(config.list_style, "List Bullet")
        self.assertFalse(config.plain)
        self.assertEqual(config.sep, ": ")

    def test_custom_separator(self):
        config = BulletConfig(sep=" - ")
        self.assertEqual(config.glyph, "•")
        self.assertEqual(config.list_style, "List Bullet")
        self.assertTrue(config.plain)
        self.assertEqual(config.sep, " - ")

    def test_all_custom_values(self):
        config = BulletConfig(
            glyph="*",
            list_style="Custom Bullet",
            plain=False,
            sep=": ",
        )
        self.assertEqual(config.glyph, "*")
        self.assertEqual(config.list_style, "Custom Bullet")
        self.assertFalse(config.plain)
        self.assertEqual(config.sep, ": ")

    def test_empty_glyph(self):
        config = BulletConfig(glyph="")
        self.assertEqual(config.glyph, "")
        self.assertEqual(config.list_style, "List Bullet")

    def test_empty_separator(self):
        config = BulletConfig(sep="")
        self.assertEqual(config.glyph, "•")
        self.assertEqual(config.sep, "")


class TestHeaderLineConfig(unittest.TestCase):
    """Tests for HeaderLineConfig dataclass."""

    def test_default_values(self):
        config = HeaderLineConfig()
        self.assertEqual(config.title_text, "")
        self.assertEqual(config.company_text, "")
        self.assertEqual(config.loc_text, "")
        self.assertEqual(config.span_text, "")
        self.assertEqual(config.style, "Normal")

    def test_title_text_only(self):
        config = HeaderLineConfig(title_text="Senior Developer")
        self.assertEqual(config.title_text, "Senior Developer")
        self.assertEqual(config.company_text, "")
        self.assertEqual(config.loc_text, "")
        self.assertEqual(config.span_text, "")
        self.assertEqual(config.style, "Normal")

    def test_company_text_only(self):
        config = HeaderLineConfig(company_text="TechCorp")
        self.assertEqual(config.title_text, "")
        self.assertEqual(config.company_text, "TechCorp")
        self.assertEqual(config.loc_text, "")
        self.assertEqual(config.span_text, "")
        self.assertEqual(config.style, "Normal")

    def test_location_text(self):
        config = HeaderLineConfig(loc_text="San Francisco, CA")
        self.assertEqual(config.title_text, "")
        self.assertEqual(config.company_text, "")
        self.assertEqual(config.loc_text, "San Francisco, CA")
        self.assertEqual(config.span_text, "")
        self.assertEqual(config.style, "Normal")

    def test_span_text(self):
        config = HeaderLineConfig(span_text="2020-2023")
        self.assertEqual(config.title_text, "")
        self.assertEqual(config.company_text, "")
        self.assertEqual(config.loc_text, "")
        self.assertEqual(config.span_text, "2020-2023")
        self.assertEqual(config.style, "Normal")

    def test_custom_style(self):
        config = HeaderLineConfig(style="Heading 2")
        self.assertEqual(config.title_text, "")
        self.assertEqual(config.company_text, "")
        self.assertEqual(config.loc_text, "")
        self.assertEqual(config.span_text, "")
        self.assertEqual(config.style, "Heading 2")

    def test_all_fields_populated(self):
        config = HeaderLineConfig(
            title_text="Lead Engineer",
            company_text="BigCo",
            loc_text="New York, NY",
            span_text="Jan 2020 - Present",
            style="Custom Header",
        )
        self.assertEqual(config.title_text, "Lead Engineer")
        self.assertEqual(config.company_text, "BigCo")
        self.assertEqual(config.loc_text, "New York, NY")
        self.assertEqual(config.span_text, "Jan 2020 - Present")
        self.assertEqual(config.style, "Custom Header")

    def test_partial_fields(self):
        config = HeaderLineConfig(
            title_text="Developer",
            company_text="Startup",
        )
        self.assertEqual(config.title_text, "Developer")
        self.assertEqual(config.company_text, "Startup")
        self.assertEqual(config.loc_text, "")
        self.assertEqual(config.span_text, "")
        self.assertEqual(config.style, "Normal")


class TestMetaRunConfig(unittest.TestCase):
    """Tests for MetaRunConfig dataclass."""

    def test_default_values(self):
        config = MetaRunConfig()
        self.assertTrue(config.brackets)
        self.assertEqual(config.open_br, "[")
        self.assertEqual(config.close_br, "]")
        self.assertIsNone(config.meta_pt)
        self.assertIsNone(config.color)
        self.assertFalse(config.italic)

    def test_brackets_false(self):
        config = MetaRunConfig(brackets=False)
        self.assertFalse(config.brackets)
        self.assertEqual(config.open_br, "[")
        self.assertEqual(config.close_br, "]")

    def test_custom_brackets(self):
        config = MetaRunConfig(open_br="(", close_br=")")
        self.assertTrue(config.brackets)
        self.assertEqual(config.open_br, "(")
        self.assertEqual(config.close_br, ")")
        self.assertIsNone(config.meta_pt)
        self.assertIsNone(config.color)
        self.assertFalse(config.italic)

    def test_custom_point_size(self):
        config = MetaRunConfig(meta_pt=10.5)
        self.assertTrue(config.brackets)
        self.assertEqual(config.open_br, "[")
        self.assertEqual(config.close_br, "]")
        self.assertEqual(config.meta_pt, 10.5)
        self.assertIsNone(config.color)
        self.assertFalse(config.italic)

    def test_custom_color(self):
        config = MetaRunConfig(color="FF0000")
        self.assertTrue(config.brackets)
        self.assertEqual(config.open_br, "[")
        self.assertEqual(config.close_br, "]")
        self.assertIsNone(config.meta_pt)
        self.assertEqual(config.color, "FF0000")
        self.assertFalse(config.italic)

    def test_italic_true(self):
        config = MetaRunConfig(italic=True)
        self.assertTrue(config.brackets)
        self.assertEqual(config.open_br, "[")
        self.assertEqual(config.close_br, "]")
        self.assertIsNone(config.meta_pt)
        self.assertIsNone(config.color)
        self.assertTrue(config.italic)

    def test_all_custom_values(self):
        config = MetaRunConfig(
            brackets=False,
            open_br="<",
            close_br=">",
            meta_pt=9.0,
            color="0000FF",
            italic=True,
        )
        self.assertFalse(config.brackets)
        self.assertEqual(config.open_br, "<")
        self.assertEqual(config.close_br, ">")
        self.assertEqual(config.meta_pt, 9.0)
        self.assertEqual(config.color, "0000FF")
        self.assertTrue(config.italic)

    def test_empty_brackets(self):
        config = MetaRunConfig(open_br="", close_br="")
        self.assertTrue(config.brackets)
        self.assertEqual(config.open_br, "")
        self.assertEqual(config.close_br, "")

    def test_asymmetric_brackets(self):
        config = MetaRunConfig(open_br="«", close_br="»")
        self.assertEqual(config.open_br, "«")
        self.assertEqual(config.close_br, "»")

    def test_zero_point_size(self):
        config = MetaRunConfig(meta_pt=0.0)
        self.assertEqual(config.meta_pt, 0.0)

    def test_large_point_size(self):
        config = MetaRunConfig(meta_pt=72.0)
        self.assertEqual(config.meta_pt, 72.0)


class TestRenderContext(unittest.TestCase):
    """Tests for RenderContext dataclass."""

    def test_default_values(self):
        context = RenderContext()
        self.assertIsNone(context.sec)
        self.assertIsNone(context.keywords)

    def test_with_section_config(self):
        sec_config = {"name": "Experience", "style": "Heading 1"}
        context = RenderContext(sec=sec_config)
        self.assertEqual(context.sec, sec_config)
        self.assertIsNone(context.keywords)

    def test_with_keywords(self):
        keywords = ["Python", "JavaScript", "Docker"]
        context = RenderContext(keywords=keywords)
        self.assertIsNone(context.sec)
        self.assertEqual(context.keywords, keywords)

    def test_with_both_values(self):
        sec_config = {"name": "Skills"}
        keywords = ["API", "REST", "GraphQL"]
        context = RenderContext(sec=sec_config, keywords=keywords)
        self.assertEqual(context.sec, sec_config)
        self.assertEqual(context.keywords, keywords)

    def test_empty_section_dict(self):
        context = RenderContext(sec={})
        self.assertEqual(context.sec, {})
        self.assertIsNone(context.keywords)

    def test_empty_keywords_list(self):
        context = RenderContext(keywords=[])
        self.assertIsNone(context.sec)
        self.assertEqual(context.keywords, [])

    def test_complex_section_config(self):
        sec_config = {
            "name": "Experience",
            "style": "Heading 1",
            "bullets": {"glyph": "•", "style": "List Bullet"},
            "max_entries": 5,
        }
        context = RenderContext(sec=sec_config)
        self.assertEqual(context.sec, sec_config)
        self.assertEqual(context.sec["name"], "Experience")
        self.assertEqual(context.sec["bullets"]["glyph"], "•")

    def test_keywords_not_mutated(self):
        keywords = ["Python", "Java"]
        context1 = RenderContext(keywords=keywords)
        context2 = RenderContext(keywords=keywords)
        # Modifying one should not affect the other (they share the reference)
        # This is expected behavior for dataclasses without field(default_factory)
        self.assertIs(context1.keywords, context2.keywords)

    def test_section_dict_not_mutated(self):
        sec = {"name": "Experience"}
        context1 = RenderContext(sec=sec)
        context2 = RenderContext(sec=sec)
        # They share the same dict reference
        self.assertIs(context1.sec, context2.sec)


class TestExperienceRenderConfig(unittest.TestCase):
    """Tests for ExperienceRenderConfig dataclass."""

    def test_default_values(self):
        config = ExperienceRenderConfig()
        self.assertEqual(config.role_style, "Normal")
        self.assertEqual(config.bullet_style, "List Bullet")
        self.assertEqual(config.max_bullets, -1)

    def test_custom_role_style(self):
        config = ExperienceRenderConfig(role_style="Heading 2")
        self.assertEqual(config.role_style, "Heading 2")
        self.assertEqual(config.bullet_style, "List Bullet")
        self.assertEqual(config.max_bullets, -1)

    def test_custom_bullet_style(self):
        config = ExperienceRenderConfig(bullet_style="Custom Bullet")
        self.assertEqual(config.role_style, "Normal")
        self.assertEqual(config.bullet_style, "Custom Bullet")
        self.assertEqual(config.max_bullets, -1)

    def test_max_bullets_zero(self):
        config = ExperienceRenderConfig(max_bullets=0)
        self.assertEqual(config.role_style, "Normal")
        self.assertEqual(config.bullet_style, "List Bullet")
        self.assertEqual(config.max_bullets, 0)

    def test_max_bullets_positive(self):
        config = ExperienceRenderConfig(max_bullets=5)
        self.assertEqual(config.role_style, "Normal")
        self.assertEqual(config.bullet_style, "List Bullet")
        self.assertEqual(config.max_bullets, 5)

    def test_max_bullets_unlimited(self):
        config = ExperienceRenderConfig(max_bullets=-1)
        self.assertEqual(config.max_bullets, -1)

    def test_all_custom_values(self):
        config = ExperienceRenderConfig(
            role_style="Job Title",
            bullet_style="Achievement Bullet",
            max_bullets=10,
        )
        self.assertEqual(config.role_style, "Job Title")
        self.assertEqual(config.bullet_style, "Achievement Bullet")
        self.assertEqual(config.max_bullets, 10)

    def test_max_bullets_large_value(self):
        config = ExperienceRenderConfig(max_bullets=1000)
        self.assertEqual(config.max_bullets, 1000)

    def test_empty_style_strings(self):
        config = ExperienceRenderConfig(
            role_style="",
            bullet_style="",
        )
        self.assertEqual(config.role_style, "")
        self.assertEqual(config.bullet_style, "")

    def test_partial_configuration(self):
        config = ExperienceRenderConfig(max_bullets=3)
        self.assertEqual(config.role_style, "Normal")
        self.assertEqual(config.bullet_style, "List Bullet")
        self.assertEqual(config.max_bullets, 3)


if __name__ == "__main__":
    unittest.main()
