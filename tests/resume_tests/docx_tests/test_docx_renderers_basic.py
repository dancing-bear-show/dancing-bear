"""Basic docx renderer tests: BulletRenderer, HeaderRenderer, ListSectionRenderer, misc."""
from __future__ import annotations
import unittest
from tests.resume_tests.fixtures import make_fake_renderer, mock_docx_modules
from resume.render_config import HeaderLineConfig
from resume.schema import Resume


@mock_docx_modules
class TestBulletRenderer(unittest.TestCase):
    """Tests for BulletRenderer class."""

    def _get_renderer(self):
        from resume.docx_renderers import BulletRenderer
        return make_fake_renderer(BulletRenderer)

    def test_resolve_glyph_defaults(self):
        """Absent config resolves to the default glyph."""
        renderer, _ = self._get_renderer()
        self.assertEqual(renderer.resolve_glyph(None), "•")

    def test_resolve_glyph_custom_from_section(self):
        """Test custom glyph from section config."""
        renderer, _ = self._get_renderer()
        self.assertEqual(renderer.resolve_glyph({"bullets": {"glyph": "→"}}), "→")

    def test_resolve_glyph_ignores_the_obsolete_style_keys(self):
        """``bullets.style`` and ``plain_bullets`` no longer select a mechanism.

        They used to choose between a Word ``List Bullet`` paragraph and a
        literal-glyph paragraph. There is one mechanism now, so both keys are
        accepted (old templates still load) and ignored.
        """
        renderer, _ = self._get_renderer()
        self.assertEqual(renderer.resolve_glyph({"bullets": {"style": "plain"}}), "•")
        self.assertEqual(renderer.resolve_glyph({"plain_bullets": False}), "•")

    def test_resolve_glyph_prefers_section_over_page(self):
        """Section config wins over the constructor-level page config."""
        from resume.docx_renderers import BulletRenderer
        from tests.resume_tests.fixtures import FakeDocument
        renderer = BulletRenderer(FakeDocument(), {"bullets": {"glyph": "★"}})
        self.assertEqual(renderer.resolve_glyph({"bullets": {"glyph": "→"}}), "→")

    def test_add_bullet_line(self):
        """Test adding a bullet line."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line("Test item", glyph="•")
        self.assertEqual(len(doc.paragraphs), 1)
        runs = doc.paragraphs[0].runs
        self.assertEqual(runs[0].text, "• ")
        self.assertEqual(runs[1].text, "Test item")

    def test_add_named_bullet(self):
        """Test adding a bullet with bold name."""
        renderer, doc = self._get_renderer()
        renderer.add_named_bullet("Python", "Programming language", glyph="•")
        self.assertEqual(len(doc.paragraphs), 1)
        runs = doc.paragraphs[0].runs
        self.assertEqual(runs[0].text, "• ")
        self.assertEqual(runs[1].text, "Python")
        self.assertTrue(runs[1].bold)
        self.assertEqual(runs[2].text, ": ")
        self.assertEqual(runs[3].text, "Programming language")

    def test_add_named_bullet_without_desc_emits_no_separator_run(self):
        """A name with no description stops after the bold name.

        The separator exists to divide two halves; with only one half it would
        render as trailing punctuation. Asserted on the run list rather than on
        the paragraph text because an empty run is invisible in the text but
        still present in the XML.
        """
        renderer, doc = self._get_renderer()
        renderer.add_named_bullet("Python", "", glyph="•")
        runs = doc.paragraphs[0].runs
        self.assertEqual([r.text for r in runs], ["• ", "Python"])
        self.assertTrue(runs[1].bold)

    def test_add_bullets_emits_one_paragraph_per_item(self):
        """Test adding multiple bullets."""
        renderer, doc = self._get_renderer()
        renderer.add_bullets(["Item 1", "Item 2", "Item 3"], glyph="•")
        self.assertEqual(len(doc.paragraphs), 3)

    def test_add_bullets_never_emits_a_word_list_style(self):
        """Every bullet is a ``Normal`` paragraph carrying a literal glyph."""
        renderer, doc = self._get_renderer()
        renderer.add_bullets(["Item 1", "Item 2"], glyph="•")
        self.assertEqual(len(doc.paragraphs), 2)
        for p in doc.paragraphs:
            self.assertNotEqual(getattr(p.style, "name", p.style), "List Bullet")
            self.assertTrue("".join(r.text for r in p.runs).startswith("• "))

    def test_resolve_glyph_page_cfg_fallback(self):
        """Constructor-level page_cfg supplies the glyph when sec is None."""
        from resume.docx_renderers import BulletRenderer
        from tests.resume_tests.fixtures import FakeDocument
        renderer = BulletRenderer(FakeDocument(), {"bullets": {"glyph": "★"}})
        self.assertEqual(renderer.resolve_glyph(None), "★")

    def test_bold_keywords(self):
        """Test keyword bolding in text."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line(
            "Experience with Python and JavaScript",
            keywords=["Python", "JavaScript"],
            glyph="•",
        )
        runs = doc.paragraphs[0].runs
        # Find the bolded runs
        bolded = [r.text for r in runs if r.bold]
        self.assertIn("Python", bolded)
        self.assertIn("JavaScript", bolded)

    def test_bold_keywords_overlapping(self):
        """Test keyword bolding with overlapping keywords.

        Note: When keywords overlap (e.g., "Python" within "Pythonic"),
        the algorithm matches the first occurrence it finds, which may
        consume characters needed for a longer match.
        """
        renderer, doc = self._get_renderer()
        # "Python" appears both standalone and within "Pythonic"
        renderer.add_bullet_line(
            "Expert in Python and Pythonic code",
            keywords=["Python", "Pythonic"],
            glyph="•",
        )
        runs = doc.paragraphs[0].runs
        bolded = [r.text for r in runs if r.bold]
        # "Python" matches in both locations (including within "Pythonic")
        # This documents current behavior - not ideal, but consistent
        self.assertEqual(bolded.count("Python"), 2)

    def test_bold_keywords_case_insensitive(self):
        """Test keyword bolding is case-insensitive."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line(
            "Developed with PYTHON and javascript frameworks",
            keywords=["Python", "JavaScript"],
            glyph="•",
        )
        runs = doc.paragraphs[0].runs
        # Should match case-insensitively
        bolded = [r.text for r in runs if r.bold]
        self.assertIn("PYTHON", bolded)
        self.assertIn("javascript", bolded)

    def test_bold_keywords_empty_list(self):
        """Test keyword bolding with empty keyword list."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line(
            "Experience with Python",
            keywords=[],
            glyph="•",
        )
        runs = doc.paragraphs[0].runs
        # With no keywords, text should not be bolded
        bolded = [r.text for r in runs if r.bold]
        self.assertEqual(len(bolded), 0)

    def test_bold_keywords_none_in_list(self):
        """Test keyword bolding handles None in keyword list."""
        renderer, doc = self._get_renderer()
        renderer.add_bullet_line(
            "Experience with Python",
            keywords=["Python", None, ""],
            glyph="•",
        )
        runs = doc.paragraphs[0].runs
        # Should still bold Python, ignore None/empty
        bolded = [r.text for r in runs if r.bold]
        self.assertIn("Python", bolded)


@mock_docx_modules
class TestHeaderRenderer(unittest.TestCase):
    """Tests for HeaderRenderer class."""

    def _get_renderer(self):
        from resume.docx_renderers import HeaderRenderer
        return make_fake_renderer(HeaderRenderer)

    def test_add_header_line_title_only(self):
        """Test header with title only."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(HeaderLineConfig(title_text="Software Engineer"))
        self.assertEqual(len(doc.paragraphs), 1)
        runs = doc.paragraphs[0].runs
        self.assertEqual(runs[0].text, "Software Engineer")
        self.assertTrue(runs[0].bold)

    def test_add_header_line_title_and_company(self):
        """Test header with title and company."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(HeaderLineConfig(title_text="Software Engineer", company_text="Acme Corp"))
        runs = doc.paragraphs[0].runs
        texts = [r.text for r in runs]
        self.assertIn("Software Engineer", texts)
        self.assertIn(" at ", texts)
        self.assertIn("Acme Corp", texts)

    def test_add_header_line_with_location(self):
        """Test header with location."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(
            HeaderLineConfig(
                title_text="Engineer",
                company_text="Company",
                loc_text="New York",
            )
        )
        runs = doc.paragraphs[0].runs
        texts = [r.text for r in runs]
        self.assertIn("New York", texts)

    def test_add_header_line_location_brackets_by_default(self):
        """Location is bracketed by default: distinct '[' / ']' runs."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(HeaderLineConfig(title_text="Engineer", loc_text="NYC"))
        texts = [r.text for r in doc.paragraphs[0].runs]
        self.assertIn("[", texts)
        self.assertIn("]", texts)

    def test_add_header_line_without_location_brackets(self):
        """sec={"location_brackets": False} suppresses the bracket runs."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(
            HeaderLineConfig(title_text="Engineer", loc_text="NYC"),
            sec={"location_brackets": False},
        )
        texts = [r.text for r in doc.paragraphs[0].runs]
        self.assertNotIn("[", texts)
        self.assertNotIn("]", texts)

    def test_add_header_line_with_duration(self):
        """Test header with duration."""
        renderer, doc = self._get_renderer()
        renderer.add_header_line(
            HeaderLineConfig(
                title_text="Engineer",
                span_text="2020-2024",
            )
        )
        runs = doc.paragraphs[0].runs
        texts = [r.text for r in runs]
        self.assertIn("2020-2024", texts)

    def test_parse_meta_pt_valid(self):
        """Test parsing valid meta_pt."""
        renderer, _ = self._get_renderer()
        result = renderer._parse_meta_pt({"meta_pt": "10"})
        self.assertEqual(result, 10.0)

    def test_parse_meta_pt_invalid(self):
        """Test parsing invalid meta_pt."""
        renderer, _ = self._get_renderer()
        result = renderer._parse_meta_pt({"meta_pt": "not-a-number"})
        self.assertIsNone(result)

    def test_parse_meta_pt_empty(self):
        """Test parsing empty meta_pt."""
        renderer, _ = self._get_renderer()
        result = renderer._parse_meta_pt({})
        self.assertIsNone(result)

    def test_parse_meta_pt_float(self):
        """A bare float value passes through unchanged."""
        renderer, _ = self._get_renderer()
        self.assertEqual(renderer._parse_meta_pt({"meta_pt": 10.5}), 10.5)

    def test_parse_meta_pt_int_as_float(self):
        """An int value is coerced to float."""
        renderer, _ = self._get_renderer()
        self.assertEqual(renderer._parse_meta_pt({"meta_pt": 12}), 12.0)

    def test_parse_meta_pt_none_value(self):
        """An explicit None value (vs. missing key) returns None."""
        renderer, _ = self._get_renderer()
        self.assertIsNone(renderer._parse_meta_pt({"meta_pt": None}))

    def test_add_group_title(self):
        """Test adding a group title."""
        renderer, doc = self._get_renderer()
        renderer.add_group_title("Programming Languages")
        self.assertEqual(len(doc.paragraphs), 1)
        runs = doc.paragraphs[0].runs
        self.assertEqual(runs[0].text, "Programming Languages")
        self.assertTrue(runs[0].bold)

    def test_add_group_title_empty(self):
        """Test adding empty group title returns None."""
        renderer, doc = self._get_renderer()
        result = renderer.add_group_title("")
        self.assertIsNone(result)
        self.assertEqual(len(doc.paragraphs), 0)


@mock_docx_modules
class TestListSectionRenderer(unittest.TestCase):
    """Tests for ListSectionRenderer class."""

    def _get_renderer(self):
        from resume.docx_renderers import ListSectionRenderer
        return make_fake_renderer(ListSectionRenderer)

    def test_extract_item_text_string(self):
        """Test extracting text from string item."""
        renderer, _ = self._get_renderer()
        result = renderer._extract_item_text("  Hello World  ", ("name",), None, " — ")
        self.assertEqual(result, "Hello World")

    def test_extract_item_text_dict_with_name(self):
        """Test extracting text from dict with name key."""
        renderer, _ = self._get_renderer()
        result = renderer._extract_item_text(
            {"name": "Python"},
            ("name", "title"),
            None,
            " — ",
        )
        self.assertEqual(result, "Python")

    def test_extract_item_text_dict_with_desc(self):
        """Test extracting text from dict with description."""
        renderer, _ = self._get_renderer()
        result = renderer._extract_item_text(
            {"name": "Python", "level": "Expert"},
            ("name",),
            "level",
            " — ",
        )
        self.assertEqual(result, "Python — Expert")

    def test_extract_item_text_empty(self):
        """Test extracting text from empty item."""
        renderer, _ = self._get_renderer()
        result = renderer._extract_item_text("", ("name",), None, " — ")
        self.assertIsNone(result)

    def test_extract_item_text_dict_with_title_fallback(self):
        """The 'title' key is used when 'name' is absent."""
        renderer, _ = self._get_renderer()
        result = renderer._extract_item_text({"title": "Docker"}, ("name", "title"), None, " — ")
        self.assertEqual(result, "Docker")

    def test_extract_item_text_empty_dict(self):
        """An empty dict (distinct from an empty string) yields None."""
        renderer, _ = self._get_renderer()
        result = renderer._extract_item_text({}, ("name",), None, " — ")
        self.assertIsNone(result)

    # -- typed (schema item) branch of _extract_item_text --------------------
    # These exercise the ``isinstance(it, _Item)`` path directly. Before this
    # suite existed the typed branch was reachable only through golden digests,
    # which report *that* a rendered byte changed without saying why.

    def test_extract_item_text_named_level_item(self):
        """A NamedLevelItem renders its name and level."""
        from resume.schema import NamedLevelItem
        renderer, _ = self._get_renderer()
        item = NamedLevelItem.from_dict({"language": "Spanish", "level": "Fluent"})
        result = renderer._extract_item_text(
            item, ("name", "language", "title"), "level", " — "
        )
        self.assertEqual(result, "Spanish — Fluent")

    def test_extract_item_text_certification_item_year(self):
        """A CertificationItem renders its year as the description."""
        from resume.schema import CertificationItem
        renderer, _ = self._get_renderer()
        item = CertificationItem.from_dict({"cert": "AWS SAA", "year": "2021"})
        result = renderer._extract_item_text(
            item, ("name", "title", "cert"), "year", " — "
        )
        self.assertEqual(result, "AWS SAA — 2021")

    def test_extract_item_text_certification_label_is_rejected(self):
        """A 'label'-keyed certification renders as nothing, deliberately.

        The schema resolves ``label`` onto ``CertificationItem.name``, but the
        certifications renderer passes ``("name", "title", "cert")`` and has
        never rendered a label-keyed entry. Pinning the drop here means the
        follow-up PR that widens the renderer flips this assertion rather than
        silently regenerating a golden digest.
        """
        from resume.schema import CertificationItem
        renderer, _ = self._get_renderer()
        item = CertificationItem.from_dict({"label": "Internal Cert", "year": "2020"})
        result = renderer._extract_item_text(
            item, ("name", "title", "cert"), "year", " — "
        )
        self.assertIsNone(result)

    def test_item_name_prefers_renderer_key_order_over_schema(self):
        """Renderer precedence wins when the two orderings disagree.

        ``PriorityItem`` aliases ``text`` as ``(text, line, name)`` so the
        schema resolves ``text`` onto the primary field, while this renderer
        accepts ``(name, title, label, text)`` and prefers ``name``. The
        displayed spelling must follow the renderer.
        """
        from resume.schema import PriorityItem
        renderer, _ = self._get_renderer()
        item = PriorityItem.from_dict({"name": "Cycling", "text": "Chess"})
        result = renderer._extract_item_text(
            item, ("name", "title", "label", "text"), None, " — "
        )
        self.assertEqual(result, "Cycling")

    def test_item_name_recovers_spelling_the_schema_filed_in_extra(self):
        """A losing alias spelling still displays when the renderer accepts it.

        ``line`` outranks ``name`` in the schema's alias tuple but is absent
        from this renderer's keys. Reading the primary field alone would render
        the item as nothing at all.
        """
        from resume.schema import PriorityItem
        renderer, _ = self._get_renderer()
        item = PriorityItem.from_dict({"line": "Bullet form", "name": "Cycling"})
        result = renderer._extract_item_text(
            item, ("name", "title", "label", "text"), None, " — "
        )
        self.assertEqual(result, "Cycling")

    def test_item_name_falls_back_to_primary_field(self):
        """With no competing spelling, the primary field is displayed."""
        from resume.schema import PriorityItem
        renderer, _ = self._get_renderer()
        item = PriorityItem.from_dict({"text": "Chess"})
        result = renderer._extract_item_text(
            item, ("name", "title", "label", "text"), None, " — "
        )
        self.assertEqual(result, "Chess")

    def test_render_simple_list(self):
        """Test rendering a simple list."""
        renderer, doc = self._get_renderer()
        items = ["Item 1", "Item 2", "Item 3"]
        result = renderer.render_simple_list(items)
        self.assertEqual(result, ["Item 1", "Item 2", "Item 3"])
        self.assertEqual(len(doc.paragraphs), 3)

    def test_render_simple_list_ignores_bullets_false(self):
        """``bullets: false`` no longer collapses the list into one paragraph.

        That branch joined every item with ``separator`` into a single
        paragraph, burying the glyph inside the text so Word wrapped the
        section as prose. It is gone: each item gets its own paragraph
        regardless of the flag, and ``separator`` is not consulted here.
        """
        renderer, doc = self._get_renderer()
        sec = {"bullets": False, "separator": ", "}
        renderer.render_simple_list(["A", "B", "C"], sec)
        self.assertEqual(len(doc.paragraphs), 3)
        # Bullet text lands in runs, not FakeParagraph.text, so read the runs
        # -- asserting on p.text would pass vacuously against empty strings.
        bodies = ["".join(r.text for r in p.runs) for p in doc.paragraphs]
        self.assertEqual(bodies, ["• A", "• B", "• C"])

    def test_render_simple_list_warns_on_bullets_false(self):
        """The dropped flag warns rather than changing layout silently."""
        renderer, _ = self._get_renderer()
        with self.assertLogs("resume.docx_renderers", level="WARNING") as logs:
            renderer.render_simple_list(["A", "B"], {"bullets": False})
        self.assertIn("bullets: false", "".join(logs.output))

    def test_render_simple_list_does_not_warn_by_default(self):
        """A section that never set the flag must render without a warning."""
        renderer, _ = self._get_renderer()
        with self.assertNoLogs("resume.docx_renderers", level="WARNING"):
            renderer.render_simple_list(["A", "B"], {"bullets": True})

    def test_render_simple_list_skips_empty_items(self):
        """Blank strings and empty dict items are dropped from the rendered list."""
        renderer, _ = self._get_renderer()
        items = ["Valid", "", "  ", {"name": ""}, "Also Valid"]
        result = renderer.render_simple_list(items)
        self.assertEqual(result, ["Valid", "Also Valid"])

    def test_render_simple_list_title_and_label_fallback(self):
        """render_simple_list's default name_keys include 'title' and 'label'."""
        renderer, _ = self._get_renderer()
        items = [{"name": "First"}, {"title": "Second"}, {"label": "Third"}]
        result = renderer.render_simple_list(items)
        self.assertEqual(result, ["First", "Second", "Third"])


@mock_docx_modules
class TestSectionRenderers(unittest.TestCase):
    """Tests for specific section renderers."""

    def test_interests_renderer(self):
        """Test InterestsSectionRenderer."""
        from resume.docx_sections_simple import InterestsSectionRenderer
        renderer, _ = make_fake_renderer(InterestsSectionRenderer)
        data = {"interests": ["Reading", "Hiking", "Photography"]}
        result = renderer.render(Resume.from_dict(data))
        self.assertEqual(len(result), 3)

    def test_languages_renderer(self):
        """Test LanguagesSectionRenderer."""
        from resume.docx_sections_simple import LanguagesSectionRenderer
        renderer, _ = make_fake_renderer(LanguagesSectionRenderer)
        data = {"languages": [
            {"name": "English", "level": "Native"},
            {"language": "Spanish", "level": "Fluent"},
        ]}
        result = renderer.render(Resume.from_dict(data))
        self.assertEqual(len(result), 2)

    def test_coursework_renderer(self):
        """Test CourseworkSectionRenderer."""
        from resume.docx_sections_simple import CourseworkSectionRenderer
        renderer, _ = make_fake_renderer(CourseworkSectionRenderer)
        data = {"coursework": [
            {"name": "Data Structures"},
            {"course": "Algorithms"},
        ]}
        result = renderer.render(Resume.from_dict(data))
        self.assertEqual(len(result), 2)

    def test_certifications_renderer(self):
        """Test CertificationsSectionRenderer."""
        from resume.docx_sections_simple import CertificationsSectionRenderer
        renderer, _ = make_fake_renderer(CertificationsSectionRenderer)
        data = {"certifications": [
            {"name": "AWS Certified", "year": "2023"},
            {"cert": "GCP Professional"},
        ]}
        result = renderer.render(Resume.from_dict(data))
        self.assertEqual(len(result), 2)

    # -- label-keyed entries in the three simple-list sections --------------
    #
    # The schema resolves the "label" spelling onto `name`, but these three
    # renderers used to pass name_keys that omitted "label", so _item_name
    # found no matching spelling and returned "". The entry then rendered as
    # nothing at all, under a section heading that still appeared.

    def test_certifications_renderer_renders_label_keyed_entry(self):
        """A certification spelled with 'label' renders its text."""
        from resume.docx_sections_simple import CertificationsSectionRenderer
        renderer, _ = make_fake_renderer(CertificationsSectionRenderer)
        data = {"certifications": [{"label": "Alias-Keyed Certification"}]}
        result = renderer.render(Resume.from_dict(data))
        self.assertEqual(result, ["Alias-Keyed Certification"])

    def test_coursework_renderer_renders_label_keyed_entry(self):
        """A coursework item spelled with 'label' renders its text."""
        from resume.docx_sections_simple import CourseworkSectionRenderer
        renderer, _ = make_fake_renderer(CourseworkSectionRenderer)
        data = {"coursework": [{"label": "Distributed Systems"}]}
        result = renderer.render(Resume.from_dict(data))
        self.assertEqual(result, ["Distributed Systems"])

    def test_languages_renderer_renders_label_keyed_entry(self):
        """A language spelled with 'label' renders its text."""
        from resume.docx_sections_simple import LanguagesSectionRenderer
        renderer, _ = make_fake_renderer(LanguagesSectionRenderer)
        data = {"languages": [{"label": "Portuguese", "level": "Fluent"}]}
        result = renderer.render(Resume.from_dict(data))
        self.assertEqual(result, ["Portuguese — Fluent"])

    def test_certifications_renderer_prefers_name_over_label(self):
        """Precedence guard: 'label' was appended last, so 'name' still wins."""
        from resume.docx_sections_simple import CertificationsSectionRenderer
        renderer, _ = make_fake_renderer(CertificationsSectionRenderer)
        data = {"certifications": [{"name": "Canonical Name", "label": "Losing Label"}]}
        result = renderer.render(Resume.from_dict(data))
        self.assertEqual(result, ["Canonical Name"])

    def test_coursework_renderer_prefers_name_over_label(self):
        """Precedence guard for coursework."""
        from resume.docx_sections_simple import CourseworkSectionRenderer
        renderer, _ = make_fake_renderer(CourseworkSectionRenderer)
        data = {"coursework": [{"name": "Canonical Course", "label": "Losing Label"}]}
        result = renderer.render(Resume.from_dict(data))
        self.assertEqual(result, ["Canonical Course"])

    def test_languages_renderer_prefers_name_over_label(self):
        """Precedence guard for languages."""
        from resume.docx_sections_simple import LanguagesSectionRenderer
        renderer, _ = make_fake_renderer(LanguagesSectionRenderer)
        data = {"languages": [{"name": "Canonical Lang", "label": "Losing Label"}]}
        result = renderer.render(Resume.from_dict(data))
        self.assertEqual(result, ["Canonical Lang"])

    def test_certifications_renderer_canonical_spellings_unaffected(self):
        """Regression guard: the spellings that already worked still render."""
        from resume.docx_sections_simple import CertificationsSectionRenderer
        renderer, _ = make_fake_renderer(CertificationsSectionRenderer)
        data = {"certifications": [
            {"name": "AWS Certified", "year": "2023"},
            {"cert": "GCP Professional"},
        ]}
        result = renderer.render(Resume.from_dict(data))
        self.assertEqual(result, ["AWS Certified — 2023", "GCP Professional"])

    def test_presentations_renderer(self):
        """Test PresentationsSectionRenderer."""
        from resume.docx_sections_simple import PresentationsSectionRenderer
        renderer, _ = make_fake_renderer(PresentationsSectionRenderer)
        data = {"presentations": [
            {"title": "Intro to Python", "event": "PyCon", "year": "2023"},
            "Another Talk",
        ]}
        result = renderer.render(Resume.from_dict(data))
        self.assertEqual(len(result), 2)

    def test_presentations_link_only_no_duplication(self):
        """Link-only presentation (no title/event/year) renders a single hyperlink run.

        Before the fix, _render_dict_item would set `display = url` (raw URL) then
        add a bullet run with the raw URL AND append a hyperlink run — duplicating
        the URL text. After the fix, only the hyperlink run is appended (with the
        cleaned display URL), not the raw URL as plain text first.
        """
        from resume.docx_sections_simple import PresentationsSectionRenderer
        renderer, doc = make_fake_renderer(PresentationsSectionRenderer)
        data = {"presentations": [
            {"link": "https://slides.example.com/my-talk"},
        ]}
        result = renderer.render(Resume.from_dict(data))

        # Exactly one item rendered.
        self.assertEqual(len(result), 1)
        # The returned display text should be the cleaned URL, not the raw URL.
        self.assertEqual(result[0], "slides.example.com/my-talk")

        # The bullet paragraph should NOT have a plain-text run equal to the raw URL.
        # (add_hyperlink falls back to add_run in fake context, but the glyph run
        # should be the only content run before the hyperlink — never the raw URL.)
        bullet_para = doc.paragraphs[0]
        raw_url = "https://slides.example.com/my-talk"
        plain_runs_with_raw_url = [r for r in bullet_para.runs if r.text == raw_url]
        self.assertEqual(
            plain_runs_with_raw_url, [],
            "Raw URL must not appear as a plain-text run — only as hyperlink display text.",
        )

    def test_presentations_unsafe_link_renders_as_plain_text(self):
        """Presentation with a file: link must NOT create a w:hyperlink — renders plain."""
        from resume.docx_sections_simple import PresentationsSectionRenderer
        renderer, doc = make_fake_renderer(PresentationsSectionRenderer)
        data = {"presentations": [
            {"title": "Secret", "link": "file:///etc/passwd"},
        ]}
        result = renderer.render(Resume.from_dict(data))
        self.assertEqual(len(result), 1)
        # The display should be the title, not any URL.
        self.assertEqual(result[0], "Secret")
        # No paragraph should contain a run with the file: URL.
        for para in doc.paragraphs:
            for r in para.runs:
                self.assertNotIn("file:", r.text)

    def test_presentations_use_the_shared_bullet_mechanism(self):
        """The obsolete style keys no longer route presentations to 'List Bullet'.

        ``plain_bullets: False`` plus ``bullets.style: list`` used to select a
        Word list style here, which is what let this section render at a
        different left edge from the rest of the document. Both keys are now
        ignored and the section emits the same literal-glyph paragraph as every
        other bulleted line.
        """
        from resume.docx_sections_simple import PresentationsSectionRenderer
        renderer, doc = make_fake_renderer(PresentationsSectionRenderer)
        sec = {"plain_bullets": False, "bullets": {"style": "list"}}
        data = {"presentations": [
            {"title": "My Talk", "event": "PyCon", "year": "2024"},
        ]}
        renderer.render(Resume.from_dict(data), sec=sec)
        styles = [getattr(p.style, "name", None) for p in doc.paragraphs]
        self.assertNotIn("List Bullet", styles)
        texts = ["".join(r.text for r in p.runs) for p in doc.paragraphs]
        self.assertTrue(any(t.startswith("• ") for t in texts), texts)


if __name__ == "__main__":
    unittest.main()
