"""Tests for resume/render_config.py — render config dataclasses."""

from __future__ import annotations

import unittest


class TestBulletConfig(unittest.TestCase):
    """Tests for BulletConfig dataclass."""

    def test_default_values(self):
        from resume.render_config import BulletConfig

        cfg = BulletConfig()
        self.assertEqual(cfg.glyph, "•")
        self.assertEqual(cfg.list_style, "List Bullet")
        self.assertTrue(cfg.plain)
        self.assertEqual(cfg.sep, ": ")

    def test_custom_glyph(self):
        from resume.render_config import BulletConfig

        cfg = BulletConfig(glyph="-")
        self.assertEqual(cfg.glyph, "-")

    def test_custom_list_style(self):
        from resume.render_config import BulletConfig

        cfg = BulletConfig(list_style="List Bullet 2")
        self.assertEqual(cfg.list_style, "List Bullet 2")

    def test_plain_false(self):
        from resume.render_config import BulletConfig

        cfg = BulletConfig(plain=False)
        self.assertFalse(cfg.plain)

    def test_custom_sep(self):
        from resume.render_config import BulletConfig

        cfg = BulletConfig(sep=" — ")
        self.assertEqual(cfg.sep, " — ")


class TestHeaderLineConfig(unittest.TestCase):
    """Tests for HeaderLineConfig dataclass."""

    def test_default_values(self):
        from resume.render_config import HeaderLineConfig

        cfg = HeaderLineConfig()
        self.assertEqual(cfg.title_text, "")
        self.assertEqual(cfg.company_text, "")
        self.assertEqual(cfg.loc_text, "")
        self.assertEqual(cfg.span_text, "")
        self.assertEqual(cfg.style, "Normal")

    def test_custom_values(self):
        from resume.render_config import HeaderLineConfig

        cfg = HeaderLineConfig(
            title_text="Engineer",
            company_text="TechCorp",
            loc_text="NYC",
            span_text="2020-2023",
            style="Heading 2",
        )
        self.assertEqual(cfg.title_text, "Engineer")
        self.assertEqual(cfg.company_text, "TechCorp")
        self.assertEqual(cfg.loc_text, "NYC")
        self.assertEqual(cfg.span_text, "2020-2023")
        self.assertEqual(cfg.style, "Heading 2")


class TestMetaRunConfig(unittest.TestCase):
    """Tests for MetaRunConfig dataclass."""

    def test_default_values(self):
        from resume.render_config import MetaRunConfig

        cfg = MetaRunConfig()
        self.assertTrue(cfg.brackets)
        self.assertEqual(cfg.open_br, "[")
        self.assertEqual(cfg.close_br, "]")
        self.assertIsNone(cfg.meta_pt)
        self.assertIsNone(cfg.color)
        self.assertFalse(cfg.italic)

    def test_no_brackets(self):
        from resume.render_config import MetaRunConfig

        cfg = MetaRunConfig(brackets=False)
        self.assertFalse(cfg.brackets)

    def test_custom_brackets(self):
        from resume.render_config import MetaRunConfig

        cfg = MetaRunConfig(open_br="(", close_br=")")
        self.assertEqual(cfg.open_br, "(")
        self.assertEqual(cfg.close_br, ")")

    def test_custom_meta_pt_and_color(self):
        from resume.render_config import MetaRunConfig

        cfg = MetaRunConfig(meta_pt=9.0, color="#888888")
        self.assertEqual(cfg.meta_pt, 9.0)
        self.assertEqual(cfg.color, "#888888")

    def test_italic(self):
        from resume.render_config import MetaRunConfig

        cfg = MetaRunConfig(italic=True)
        self.assertTrue(cfg.italic)


class TestRenderContext(unittest.TestCase):
    """Tests for RenderContext dataclass."""

    def test_default_values(self):
        from resume.render_config import RenderContext

        ctx = RenderContext()
        self.assertIsNone(ctx.sec)
        self.assertIsNone(ctx.keywords)

    def test_with_section_and_keywords(self):
        from resume.render_config import RenderContext

        sec = {"key": "experience", "title": "Experience"}
        keywords = ["Python", "AWS"]
        ctx = RenderContext(sec=sec, keywords=keywords)
        self.assertEqual(ctx.sec, sec)
        self.assertEqual(ctx.keywords, keywords)

    def test_keywords_can_be_empty_list(self):
        from resume.render_config import RenderContext

        ctx = RenderContext(keywords=[])
        self.assertEqual(ctx.keywords, [])


class TestExperienceRenderConfig(unittest.TestCase):
    """Tests for ExperienceRenderConfig dataclass."""

    def test_default_values(self):
        from resume.render_config import ExperienceRenderConfig

        cfg = ExperienceRenderConfig()
        self.assertEqual(cfg.role_style, "Normal")
        self.assertEqual(cfg.bullet_style, "List Bullet")
        self.assertEqual(cfg.max_bullets, -1)

    def test_custom_values(self):
        from resume.render_config import ExperienceRenderConfig

        cfg = ExperienceRenderConfig(
            role_style="Heading 3",
            bullet_style="List Bullet 2",
            max_bullets=5,
        )
        self.assertEqual(cfg.role_style, "Heading 3")
        self.assertEqual(cfg.bullet_style, "List Bullet 2")
        self.assertEqual(cfg.max_bullets, 5)

    def test_max_bullets_zero(self):
        from resume.render_config import ExperienceRenderConfig

        cfg = ExperienceRenderConfig(max_bullets=0)
        self.assertEqual(cfg.max_bullets, 0)

    def test_max_bullets_unlimited(self):
        from resume.render_config import ExperienceRenderConfig

        cfg = ExperienceRenderConfig(max_bullets=-1)
        self.assertEqual(cfg.max_bullets, -1)


if __name__ == "__main__":
    unittest.main()
