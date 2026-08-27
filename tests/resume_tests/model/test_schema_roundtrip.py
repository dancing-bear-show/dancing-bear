"""Round-trip contract tests for resume/schema.py.

The contract under test is stated in the schema module docstring:
``Resume.from_dict(d).to_dict() == d`` key-for-key, modulo two documented
one-directional legacy upgrades. These tests exercise the ``extra``,
``_present``, and ``_order`` mechanisms that make that exact rather than
approximate.

Validation is advisory by design (gate decision 3): ``from_dict`` warns and
returns a usable object, it never raises. Tests named ``test_rejects_*`` /
``test_invalid_*`` therefore assert graceful tolerance and the specific
documented fallback -- not an exception.
"""

from __future__ import annotations

import logging
import unittest

from resume.schema import (
    ExperienceEntry,
    PriorityItem,
    Resume,
    SkillGroup,
    SkillGroupItem,
)

from tests.resume_tests.fixtures import (
    SAMPLE_CANDIDATE_WITH_GROUPS,
    make_candidate,
    make_experience_entry,
    make_skills_group,
)

WARN_LOGGER = "resume.schema"


class RoundTripMixin:
    """Shared assertion for the exact round-trip contract."""

    def assert_round_trips(self, data: dict) -> Resume:
        """Assert ``from_dict -> to_dict`` reproduces ``data`` exactly."""
        resume = Resume.from_dict(data)
        self.assertEqual(resume.to_dict(), data)
        return resume

    def assert_tolerates(self, data: dict) -> Resume:
        """Assert malformed input yields a usable Resume without raising."""
        resume = Resume.from_dict(data)
        self.assertIsInstance(resume, Resume)
        return resume


class TestSectionRoundTrip(RoundTripMixin, unittest.TestCase):
    """Each section survives dict -> dataclass -> dict unchanged."""

    def test_experience_section_round_trips(self):
        data = make_candidate(
            experience=[make_experience_entry(bullets=[{"text": "Shipped it"}])]
        )
        resume = self.assert_round_trips(data)
        self.assertIsInstance(resume.experience[0], ExperienceEntry)
        self.assertEqual(resume.experience[0].company, "TechCorp")

    def test_skills_groups_section_round_trips(self):
        data = make_candidate(
            skills_groups=[make_skills_group(items=[{"name": "Python"}])]
        )
        resume = self.assert_round_trips(data)
        self.assertIsInstance(resume.skills_groups[0], SkillGroup)
        self.assertIsInstance(resume.skills_groups[0].items[0], SkillGroupItem)

    def test_sample_candidate_with_groups_round_trips_except_string_bullets(self):
        """The shared fixture uses legacy ``list[str]`` bullets, which upgrade.

        Everything else in it must survive untouched, so this asserts the
        upgrade is the *only* difference.
        """
        data = dict(SAMPLE_CANDIDATE_WITH_GROUPS)
        out = Resume.from_dict(data).to_dict()
        self.assertEqual(out["name"], data["name"])
        self.assertEqual(out["skills_groups"], data["skills_groups"])
        for emitted, source in zip(out["experience"], data["experience"], strict=True):
            self.assertEqual(
                emitted["bullets"], [{"text": b} for b in source["bullets"]]
            )
            self.assertEqual(
                {k: v for k, v in emitted.items() if k != "bullets"},
                {k: v for k, v in source.items() if k != "bullets"},
            )

    def test_education_section_round_trips(self):
        data = make_candidate(
            education=[{"degree": "B.S.", "institution": "State", "year": "2016"}]
        )
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.education[0].institution, "State")

    def test_presentations_section_round_trips(self):
        data = {
            "presentations": [
                {"title": "A Talk", "event": "ConfX", "authors": "A, B", "link": "u"}
            ]
        }
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.presentations[0].event, "ConfX")

    def test_languages_and_coursework_round_trip(self):
        data = {
            "languages": [{"name": "French", "level": "fluent"}],
            "coursework": [{"name": "Algorithms", "desc": "graduate"}],
            "certifications": [{"name": "CKA"}],
        }
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.languages[0].level, "fluent")
        self.assertEqual(resume.coursework[0].desc, "graduate")

    def test_untyped_sections_round_trip_verbatim(self):
        """skills/teaching/contact are untyped by design and pass through."""
        data = {
            "skills": ["Python", "Go"],
            "teaching": [{"anything": [1, 2]}],
            "contact": {"email": "x@example.com"},
        }
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.skills, ["Python", "Go"])
        self.assertEqual(resume.teaching, [{"anything": [1, 2]}])


class TestUnknownKeyPreservation(RoundTripMixin, unittest.TestCase):
    """Unknown keys survive at every nesting depth."""

    def test_unknown_top_level_key_survives(self):
        data = {"name": "Test", "custom_field": {"nested": [1, 2]}}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.extra["custom_field"], {"nested": [1, 2]})

    def test_unknown_experience_key_survives(self):
        data = {"experience": [{"title": "Dev", "internal_id": 77}]}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.experience[0].extra["internal_id"], 77)

    def test_unknown_bullet_key_survives(self):
        data = {"experience": [{"bullets": [{"text": "Shipped it", "tags": ["a"]}]}]}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.experience[0].bullets[0].extra["tags"], ["a"])

    def test_unknown_skills_group_item_key_survives(self):
        data = {"skills_groups": [{"title": "T", "items": [{"name": "P", "lvl": 3}]}]}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.skills_groups[0].items[0].extra["lvl"], 3)

    def test_unknown_keys_survive_at_all_depths_simultaneously(self):
        data = {
            "top_unknown": 1,
            "experience": [
                {
                    "title": "Dev",
                    "entry_unknown": 2,
                    "bullets": [{"text": "b", "bullet_unknown": 3}],
                }
            ],
            "skills_groups": [
                {"title": "G", "items": [{"name": "P", "item_unknown": 4}]}
            ],
        }
        self.assert_round_trips(data)


class TestKeyOrderAndPresence(RoundTripMixin, unittest.TestCase):
    """``_order`` replay and ``_present`` semantics."""

    def test_input_key_order_is_preserved(self):
        data = {"email": "e@x.com", "name": "N", "headline": "H", "phone": "p"}
        resume = Resume.from_dict(data)
        self.assertEqual(list(resume.to_dict()), ["email", "name", "headline", "phone"])

    def test_key_order_preserved_with_unknown_keys_interleaved(self):
        data = {"zzz_unknown": 1, "name": "N", "aaa_unknown": 2, "email": "e"}
        resume = Resume.from_dict(data)
        self.assertEqual(list(resume.to_dict()), list(data))

    def test_absent_field_is_not_invented_from_default(self):
        resume = Resume.from_dict({"name": "N"})
        out = resume.to_dict()
        self.assertEqual(out, {"name": "N"})
        self.assertNotIn("email", out)
        self.assertNotIn("experience", out)

    def test_absent_priority_stays_absent_on_skills_item(self):
        """Real skills_groups items vary in carrying ``priority``."""
        data = {
            "skills_groups": [
                {"title": "G", "items": [{"name": "With", "priority": 2.0},
                                         {"name": "Without"}]}
            ]
        }
        resume = self.assert_round_trips(data)
        items = resume.skills_groups[0].items
        self.assertEqual(items[0].priority, 2.0)
        self.assertEqual(items[1].priority, 1.0)
        self.assertNotIn("priority", items[1].to_dict())

    def test_field_set_after_construction_is_appended(self):
        resume = Resume.from_dict({"name": "N"})
        resume.headline = "Added"
        resume._present.add("headline")
        self.assertEqual(list(resume.to_dict()), ["name", "headline"])


class TestAlternateSpellings(RoundTripMixin, unittest.TestCase):
    """``text|line|name`` and ``name|title|label`` reconcile, and replay."""

    def test_priority_item_accepts_line_spelling(self):
        data = {"summary": [{"line": "A summary line"}]}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.summary[0].text, "A summary line")

    def test_priority_item_accepts_name_spelling(self):
        data = {"interests": [{"name": "Cycling"}]}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.interests[0].text, "Cycling")

    def test_skill_group_item_accepts_title_and_label_spellings(self):
        data = {
            "skills_groups": [
                {"title": "G", "items": [{"title": "Alpha"}, {"label": "Beta"}]}
            ]
        }
        resume = self.assert_round_trips(data)
        names = [i.name for i in resume.skills_groups[0].items]
        self.assertEqual(names, ["Alpha", "Beta"])

    def test_to_dict_replays_original_spelling_not_canonical(self):
        resume = Resume.from_dict({"summary": [{"line": "L"}]})
        emitted = resume.to_dict()["summary"][0]
        self.assertIn("line", emitted)
        self.assertNotIn("text", emitted)

    def test_named_desc_item_accepts_label_spelling(self):
        data = {"certifications": [{"label": "CKAD", "desc": "k8s"}]}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.certifications[0].name, "CKAD")


class TestSectionSpecificNameSpellings(RoundTripMixin, unittest.TestCase):
    """Domain name keys the DOCX renderers accept must resolve to ``.name``.

    ``docx_sections_simple.py`` reads languages by ``name|language|title``,
    coursework by ``name|course|title``, and certifications by
    ``name|title|cert``. A spelling the renderer honours but the schema does
    not would resolve to an empty ``name`` and render as nothing -- silent
    data loss for an entry the dict renderer displays correctly.
    """

    def test_language_spelling_resolves_to_name(self):
        data = {"languages": [{"language": "Spanish", "level": "native"}]}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.languages[0].name, "Spanish")

    def test_language_spelling_replays_as_language_not_name(self):
        emitted = Resume.from_dict(
            {"languages": [{"language": "Spanish"}]}
        ).to_dict()["languages"][0]
        self.assertIn("language", emitted)
        self.assertNotIn("name", emitted)

    def test_course_spelling_resolves_to_name(self):
        data = {"coursework": [{"course": "Distributed Systems"}]}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.coursework[0].name, "Distributed Systems")

    def test_course_spelling_replays_as_course_not_name(self):
        emitted = Resume.from_dict({"coursework": [{"course": "Compilers"}]}).to_dict()[
            "coursework"
        ][0]
        self.assertIn("course", emitted)
        self.assertNotIn("name", emitted)

    def test_cert_spelling_resolves_to_name(self):
        data = {"certifications": [{"cert": "CKAD", "year": "2024"}]}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.certifications[0].name, "CKAD")

    def test_cert_spelling_replays_as_cert_not_name(self):
        emitted = Resume.from_dict({"certifications": [{"cert": "CKAD"}]}).to_dict()[
            "certifications"
        ][0]
        self.assertIn("cert", emitted)
        self.assertNotIn("name", emitted)

    def test_canonical_name_still_wins_over_domain_spelling(self):
        """``name`` is first in every tuple, so it takes precedence."""
        data = {"languages": [{"name": "Spanish", "language": "ignored"}]}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.languages[0].name, "Spanish")

    def test_domain_spellings_are_scoped_to_their_own_section(self):
        """The new aliases are per-class, not a widening of ``_NAME_KEYS``.

        ``course`` must not name a certification, ``cert`` must not name a
        coursework entry, and ``language`` must not name a skills-group item.
        Each unrecognised key still survives verbatim via ``extra``.
        """
        for section, item in (
            ("certifications", {"course": "Distributed Systems"}),
            ("coursework", {"cert": "CKAD"}),
        ):
            with self.subTest(section=section):
                data = {section: [item]}
                resume = self.assert_round_trips(data)
                self.assertEqual(getattr(resume, section)[0].name, "")

    def test_language_is_not_a_skills_group_item_spelling(self):
        data = {"skills_groups": [{"title": "G", "items": [{"language": "X"}]}]}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.skills_groups[0].items[0].name, "")


class TestLegacyUpgrades(unittest.TestCase):
    """The two documented one-directional upgrades."""

    def test_scalar_summary_reads_as_a_single_item_but_emits_the_scalar(self):
        """A scalar summary is uniform in the typed view and exact on output.

        The typed API always sees a list, so consumers need no special case. But
        ``to_dict`` replays the bare string rather than a one-item list, because
        emitting the list was observably wrong twice over: it rewrote the user's
        file on save, and it rerouted the DOCX renderer from its prose branch to
        its bullet branch, which strips the terminal period.
        """
        resume = Resume.from_dict({"summary": "One line of summary."})
        self.assertEqual(len(resume.summary), 1)
        self.assertIsInstance(resume.summary[0], PriorityItem)
        self.assertEqual(resume.summary[0].text, "One line of summary.")
        self.assertTrue(resume.summary_is_scalar)
        self.assertEqual(resume.to_dict(), {"summary": "One line of summary."})

    def test_single_item_list_summary_stays_a_list(self):
        """A genuine one-item list must not be collapsed into a scalar.

        The counterpart to the test above: both shapes normalize to identical
        typed items, so only the recorded origin distinguishes them. If that
        record were lost, this input would emit a scalar and change how it
        renders.
        """
        resume = Resume.from_dict({"summary": [{"text": "One line of summary."}]})
        self.assertFalse(resume.summary_is_scalar)
        self.assertEqual(
            resume.to_dict(), {"summary": [{"text": "One line of summary."}]}
        )

    def test_string_bullets_become_priority_items(self):
        data = make_candidate(
            experience=[make_experience_entry(bullets=["Shipped X", "Fixed Y"])]
        )
        resume = Resume.from_dict(data)
        bullets = resume.experience[0].bullets
        self.assertIsInstance(bullets[0], PriorityItem)
        self.assertEqual([b.text for b in bullets], ["Shipped X", "Fixed Y"])
        self.assertEqual(bullets[0].priority, 1.0)

    def test_upgraded_bullets_emit_text_only(self):
        """The default priority is not invented onto an upgraded bullet."""
        resume = Resume.from_dict({"experience": [{"bullets": ["only text"]}]})
        self.assertEqual(
            resume.to_dict(), {"experience": [{"bullets": [{"text": "only text"}]}]}
        )


class TestContactPromotion(unittest.TestCase):
    """``contact.*`` promotes to top-level scalars without altering output."""

    def test_contact_promotes_all_four_scalars(self):
        data = {
            "contact": {
                "name": "Promoted Person",
                "email": "p@example.com",
                "phone": "555-0100",
                "location": "Testville",
            }
        }
        resume = Resume.from_dict(data)
        self.assertEqual(resume.name, "Promoted Person")
        self.assertEqual(resume.email, "p@example.com")
        self.assertEqual(resume.phone, "555-0100")
        self.assertEqual(resume.location, "Testville")

    def test_contact_name_is_promoted(self):
        """Guards the audited asymmetry where name was skipped."""
        resume = Resume.from_dict({"contact": {"name": "Only Name"}})
        self.assertEqual(resume.name, "Only Name")

    def test_promotion_does_not_overwrite_existing_top_level_value(self):
        data = {"name": "Top Level", "contact": {"name": "Nested"}}
        resume = Resume.from_dict(data)
        self.assertEqual(resume.name, "Top Level")

    def test_promoted_value_is_not_emitted_as_top_level_key(self):
        data = {"contact": {"name": "N", "email": "e@example.com"}}
        resume = Resume.from_dict(data)
        out = resume.to_dict()
        self.assertEqual(out, data)
        self.assertNotIn("name", out)
        self.assertNotIn("email", out)

    def test_contact_links_promote_when_links_unset(self):
        data = {"contact": {"links": ["https://example.com"]}}
        resume = Resume.from_dict(data)
        self.assertEqual(resume.links, ["https://example.com"])
        self.assertEqual(resume.to_dict(), data)

    def test_existing_links_are_not_overwritten_by_contact(self):
        data = {"links": ["https://kept.example"], "contact": {"links": ["https://x"]}}
        resume = Resume.from_dict(data)
        self.assertEqual(resume.links, ["https://kept.example"])


class TestContactPromotionFalsyTopLevel(RoundTripMixin, unittest.TestCase):
    """A present-but-falsy top-level key blocks promotion.

    Promotion once gated on truthiness, which cannot tell an absent key from
    one that is present and falsy. Both axes were covered in isolation --
    empty-string-vs-absent, and falsy scalars -- but never their intersection
    with a ``contact`` block, which is where the defect lived: the key was
    dropped from the output and its value silently substituted.
    """

    #: (field, falsy top-level value, truthy contact value)
    FALSY_CASES = (
        ("name", "", "Promoted Person"),
        ("email", "", "p@example.com"),
        ("phone", "", "555-0100"),
        ("location", "", "Testville"),
        ("links", [], ["https://example.com"]),
    )

    def test_falsy_top_level_key_survives_alongside_contact(self):
        """The input key is re-emitted rather than discarded by promotion."""
        for field_name, falsy, contact_value in self.FALSY_CASES:
            with self.subTest(field=field_name):
                data = {field_name: falsy, "contact": {field_name: contact_value}}
                resume = self.assert_round_trips(data)
                self.assertIn(field_name, resume.to_dict())

    def test_falsy_top_level_value_is_not_substituted(self):
        """The contact value must not overwrite what the input declared."""
        for field_name, falsy, contact_value in self.FALSY_CASES:
            with self.subTest(field=field_name):
                data = {field_name: falsy, "contact": {field_name: contact_value}}
                resume = Resume.from_dict(data)
                self.assertEqual(getattr(resume, field_name), falsy)

    def test_promotion_still_fires_when_key_is_absent(self):
        """Guards the fix from over-correcting into a no-op."""
        for field_name, _falsy, contact_value in self.FALSY_CASES:
            with self.subTest(field=field_name):
                data = {"contact": {field_name: contact_value}}
                resume = Resume.from_dict(data)
                self.assertEqual(getattr(resume, field_name), contact_value)
                self.assertNotIn(field_name, resume.to_dict())
                self.assertEqual(resume.to_dict(), data)

    def test_falsy_value_inside_contact_round_trips(self):
        """A falsy contact value is skipped, leaving the output untouched."""
        self.assert_round_trips({"contact": {"name": "", "phone": 0}})

    def test_falsy_top_level_and_falsy_contact_round_trip_together(self):
        data = {"name": "", "contact": {"name": ""}}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.name, "")


class TestValueFidelity(RoundTripMixin, unittest.TestCase):
    """Values are stored exactly as given, never coerced."""

    def test_presentation_year_stays_an_int(self):
        data = {"presentations": [{"title": "T", "year": 2020}]}
        resume = self.assert_round_trips(data)
        self.assertIsInstance(resume.presentations[0].year, int)
        self.assertEqual(resume.presentations[0].year, 2020)

    def test_priority_float_is_not_rounded(self):
        data = {"experience": [{"title": "T", "priority": 0.25}]}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.experience[0].priority, 0.25)

    def test_empty_string_value_is_preserved_as_present(self):
        """An explicit empty string differs from an absent field."""
        resume = self.assert_round_trips({"name": ""})
        self.assertIn("name", resume.to_dict())


# ---------------------------------------------------------------------------
# Sad path: advisory tolerance. Nothing below may assert an exception.
# ---------------------------------------------------------------------------


class TestRejectsNullSections(RoundTripMixin, unittest.TestCase):
    """A section set to ``null`` degrades to an empty list, silently."""

    def test_rejects_null_experience_section(self):
        resume = self.assert_tolerates({"experience": None})
        self.assertEqual(resume.experience, [])
        self.assertEqual(resume.to_dict(), {"experience": []})

    def test_rejects_null_summary_section(self):
        resume = self.assert_tolerates({"summary": None})
        self.assertEqual(resume.summary, [])

    def test_rejects_null_education_section(self):
        resume = self.assert_tolerates({"education": None})
        self.assertEqual(resume.education, [])

    def test_rejects_null_section_without_emitting_a_warning(self):
        """``None`` is an expected empty marker, so it is tolerated quietly."""
        logger = logging.getLogger(WARN_LOGGER)
        with self.assertNoLogs(logger, level="WARNING"):
            Resume.from_dict({"experience": None, "summary": None})

    def test_rejects_null_contact_without_warning(self):
        logger = logging.getLogger(WARN_LOGGER)
        with self.assertNoLogs(logger, level="WARNING"):
            resume = Resume.from_dict({"contact": None})
        self.assertIsNone(resume.contact)


class TestRejectsWrongSectionTypes(RoundTripMixin, unittest.TestCase):
    """A section of the wrong type is ignored, with a warning."""

    def assert_warns_and_empties(self, data: dict, attr: str) -> None:
        with self.assertLogs(WARN_LOGGER, level="WARNING") as ctx:
            resume = Resume.from_dict(data)
        self.assertEqual(getattr(resume, attr), [])
        self.assertIn("expected list", "".join(ctx.output))

    def test_rejects_string_experience_section(self):
        self.assert_warns_and_empties({"experience": "not-a-list"}, "experience")

    def test_rejects_integer_summary_section(self):
        self.assert_warns_and_empties({"summary": 12345}, "summary")

    def test_rejects_dict_skills_groups_section(self):
        self.assert_warns_and_empties({"skills_groups": {}}, "skills_groups")

    def test_invalid_section_type_names_the_section_in_the_warning(self):
        with self.assertLogs(WARN_LOGGER, level="WARNING") as ctx:
            Resume.from_dict({"experience": "nope"})
        self.assertIn("Resume.experience", "".join(ctx.output))
        self.assertIn("str", "".join(ctx.output))

    def test_rejects_wrong_type_section_but_keeps_sibling_sections(self):
        data = {"name": "Kept", "experience": "bad", "skills": ["Python"]}
        with self.assertLogs(WARN_LOGGER, level="WARNING"):
            resume = Resume.from_dict(data)
        self.assertEqual(resume.name, "Kept")
        self.assertEqual(resume.skills, ["Python"])


class TestRejectsBadListItems(RoundTripMixin, unittest.TestCase):
    """Wrong-typed and ``None`` items inside an otherwise valid list."""

    def test_rejects_none_items_in_skills_groups(self):
        resume = self.assert_tolerates({"skills_groups": [None]})
        self.assertEqual(len(resume.skills_groups), 1)
        self.assertIsInstance(resume.skills_groups[0], SkillGroup)
        self.assertEqual(resume.skills_groups[0].title, "")

    def test_rejects_none_items_silently(self):
        logger = logging.getLogger(WARN_LOGGER)
        with self.assertNoLogs(logger, level="WARNING"):
            Resume.from_dict({"skills_groups": [None]})

    def test_rejects_wrong_typed_items_with_a_warning_each(self):
        with self.assertLogs(WARN_LOGGER, level="WARNING") as ctx:
            resume = Resume.from_dict({"skills_groups": [123, True]})
        self.assertEqual(len(resume.skills_groups), 2)
        self.assertEqual(len(ctx.output), 2)
        self.assertIn("expected dict", ctx.output[0])

    def test_rejects_wrong_typed_items_by_falling_back_to_defaults(self):
        with self.assertLogs(WARN_LOGGER, level="WARNING"):
            resume = Resume.from_dict({"experience": [42]})
        self.assertIsInstance(resume.experience[0], ExperienceEntry)
        self.assertEqual(resume.experience[0].title, "")
        self.assertEqual(resume.experience[0].to_dict(), {})

    def test_rejects_mixed_valid_and_invalid_items_keeping_the_valid_one(self):
        with self.assertLogs(WARN_LOGGER, level="WARNING"):
            resume = Resume.from_dict({"experience": [{"title": "Good"}, 99]})
        self.assertEqual(resume.experience[0].title, "Good")
        self.assertEqual(resume.experience[1].title, "")

    def test_invalid_bare_string_item_upgrades_to_primary_field(self):
        """A bare string is read as the item's primary field, not discarded."""
        resume = Resume.from_dict({"interests": ["Cycling"]})
        self.assertEqual(resume.interests[0].text, "Cycling")


class TestRejectsDeeplyNestedWrongShapes(RoundTripMixin, unittest.TestCase):
    """Wrong shape below the top level."""

    def test_rejects_dict_valued_bullets(self):
        with self.assertLogs(WARN_LOGGER, level="WARNING") as ctx:
            resume = Resume.from_dict({"experience": [{"bullets": {"x": 1}}]})
        self.assertEqual(resume.experience[0].bullets, [])
        self.assertIn("ExperienceEntry.bullets", "".join(ctx.output))

    def test_rejects_integer_valued_bullets(self):
        with self.assertLogs(WARN_LOGGER, level="WARNING"):
            resume = Resume.from_dict({"experience": [{"bullets": 5}]})
        self.assertEqual(resume.experience[0].bullets, [])

    def test_rejects_wrong_shaped_bullets_but_keeps_the_entry(self):
        with self.assertLogs(WARN_LOGGER, level="WARNING"):
            resume = Resume.from_dict(
                {"experience": [{"title": "Dev", "company": "Co", "bullets": 5}]}
            )
        self.assertEqual(resume.experience[0].title, "Dev")
        self.assertEqual(resume.experience[0].company, "Co")

    def test_rejects_string_valued_skills_group_items(self):
        with self.assertLogs(WARN_LOGGER, level="WARNING"):
            resume = Resume.from_dict({"skills_groups": [{"title": "G", "items": "x"}]})
        self.assertEqual(resume.skills_groups[0].items, [])
        self.assertEqual(resume.skills_groups[0].title, "G")


class TestRejectsNonDictInput(unittest.TestCase):
    """A non-dict document, and an empty or wholly unknown one."""

    def test_rejects_string_document(self):
        with self.assertLogs(WARN_LOGGER, level="WARNING") as ctx:
            resume = Resume.from_dict("not a resume")
        self.assertEqual(resume.to_dict(), {})
        self.assertIn("Resume: expected dict", "".join(ctx.output))

    def test_rejects_none_document(self):
        with self.assertLogs(WARN_LOGGER, level="WARNING"):
            resume = Resume.from_dict(None)
        self.assertEqual(resume.to_dict(), {})

    def test_rejects_list_document(self):
        with self.assertLogs(WARN_LOGGER, level="WARNING"):
            resume = Resume.from_dict([{"name": "N"}])
        self.assertEqual(resume.name, "")

    def test_invalid_empty_document_round_trips_as_empty(self):
        resume = Resume.from_dict({})
        self.assertEqual(resume.to_dict(), {})

    def test_invalid_document_of_only_unknown_keys_round_trips(self):
        data = {"alpha": 1, "beta": {"gamma": [2]}}
        resume = Resume.from_dict(data)
        self.assertEqual(resume.to_dict(), data)
        self.assertEqual(resume.extra, data)


class TestRejectsBadContact(unittest.TestCase):
    """``contact`` of the wrong type warns but is preserved verbatim."""

    def test_rejects_string_contact(self):
        with self.assertLogs(WARN_LOGGER, level="WARNING") as ctx:
            resume = Resume.from_dict({"contact": "not-a-dict"})
        self.assertIn("Resume.contact: expected dict", "".join(ctx.output))
        self.assertEqual(resume.to_dict(), {"contact": "not-a-dict"})

    def test_rejects_list_contact_without_promoting_anything(self):
        with self.assertLogs(WARN_LOGGER, level="WARNING"):
            resume = Resume.from_dict({"contact": [{"name": "N"}]})
        self.assertEqual(resume.name, "")
        self.assertEqual(resume.to_dict(), {"contact": [{"name": "N"}]})

    def test_rejects_contact_with_non_list_links(self):
        resume = Resume.from_dict({"contact": {"links": "https://one"}})
        self.assertEqual(resume.links, [])
        self.assertEqual(resume.to_dict(), {"contact": {"links": "https://one"}})


class TestRejectsAmbiguousSpellings(RoundTripMixin, unittest.TestCase):
    """A key present under two observed spellings at once."""

    def test_rejects_priority_item_carrying_both_text_and_name(self):
        """``_ALIASES`` order wins: ``text`` before ``line`` before ``name``."""
        data = {"summary": [{"text": "Canonical", "name": "Alias"}]}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.summary[0].text, "Canonical")
        self.assertEqual(resume.summary[0].extra, {"name": "Alias"})

    def test_rejects_priority_item_carrying_both_line_and_name(self):
        data = {"summary": [{"line": "FromLine", "name": "FromName"}]}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.summary[0].text, "FromLine")
        self.assertEqual(resume.summary[0].extra, {"name": "FromName"})

    def test_rejects_skill_item_carrying_name_title_and_label(self):
        data = {
            "skills_groups": [
                {"title": "G", "items": [{"name": "N", "title": "T", "label": "L"}]}
            ]
        }
        resume = self.assert_round_trips(data)
        item = resume.skills_groups[0].items[0]
        self.assertEqual(item.name, "N")
        self.assertEqual(item.extra, {"title": "T", "label": "L"})

    def test_invalid_duplicate_spellings_still_round_trip_exactly(self):
        """The losing spellings are kept in ``extra``, so nothing is lost."""
        data = {"interests": [{"line": "A", "name": "B", "text": "C"}]}
        self.assert_round_trips(data)


class TestRejectsNestedNullAndEmpty(RoundTripMixin, unittest.TestCase):
    """``null`` and empty containers below the top level."""

    def test_rejects_null_skills_group_items(self):
        resume = self.assert_tolerates({"skills_groups": [{"title": "G", "items": None}]})
        self.assertEqual(resume.skills_groups[0].items, [])
        self.assertEqual(resume.skills_groups[0].title, "G")

    def test_rejects_null_bullets(self):
        resume = self.assert_tolerates({"experience": [{"bullets": None}]})
        self.assertEqual(resume.experience[0].bullets, [])

    def test_rejects_null_nested_containers_without_warning(self):
        logger = logging.getLogger(WARN_LOGGER)
        with self.assertNoLogs(logger, level="WARNING"):
            Resume.from_dict({"experience": [{"bullets": None}]})

    def test_invalid_empty_item_dict_round_trips_as_empty(self):
        self.assert_round_trips({"experience": [{}]})

    def test_invalid_deeply_nested_empty_dicts_round_trip(self):
        self.assert_round_trips({"skills_groups": [{"items": [{}]}]})

    def test_invalid_empty_list_sections_round_trip(self):
        self.assert_round_trips({"experience": [], "summary": []})

    def test_rejects_none_item_mixed_with_a_valid_item(self):
        resume = self.assert_tolerates(
            {"skills_groups": [{"title": "G", "items": [None, {"name": "OK"}]}]}
        )
        items = resume.skills_groups[0].items
        self.assertEqual(items[0].name, "")
        self.assertEqual(items[1].name, "OK")


class TestRejectsBareStringItems(unittest.TestCase):
    """A bare string in a typed list maps onto that type's primary field."""

    def test_rejects_bare_string_presentation(self):
        resume = Resume.from_dict({"presentations": ["bare title"]})
        self.assertEqual(resume.presentations[0].title, "bare title")
        self.assertEqual(resume.to_dict(), {"presentations": [{"title": "bare title"}]})

    def test_rejects_bare_string_language(self):
        resume = Resume.from_dict({"languages": ["French"]})
        self.assertEqual(resume.languages[0].name, "French")

    def test_rejects_bare_string_education_entry(self):
        """``Education``'s primary field is ``degree``, its first declared field."""
        resume = Resume.from_dict({"education": ["MIT"]})
        self.assertEqual(resume.education[0].degree, "MIT")

    def test_rejects_bare_string_skills_group(self):
        resume = Resume.from_dict({"skills_groups": ["Languages"]})
        self.assertEqual(resume.skills_groups[0].title, "Languages")

    def test_invalid_bare_string_emits_only_the_primary_field(self):
        resume = Resume.from_dict({"languages": ["French"]})
        self.assertEqual(resume.to_dict(), {"languages": [{"name": "French"}]})


class TestRejectsMoreWrongSectionTypes(unittest.TestCase):
    """Section types beyond str/int/dict."""

    def test_rejects_boolean_experience_section(self):
        with self.assertLogs(WARN_LOGGER, level="WARNING") as ctx:
            resume = Resume.from_dict({"experience": True})
        self.assertEqual(resume.experience, [])
        self.assertIn("bool", "".join(ctx.output))

    def test_rejects_float_summary_section(self):
        with self.assertLogs(WARN_LOGGER, level="WARNING"):
            resume = Resume.from_dict({"summary": 1.5})
        self.assertEqual(resume.summary, [])

    def test_rejects_nested_list_as_a_bullet_item(self):
        with self.assertLogs(WARN_LOGGER, level="WARNING") as ctx:
            resume = Resume.from_dict({"experience": [{"bullets": [["a"]]}]})
        self.assertEqual(resume.experience[0].bullets[0].text, "")
        self.assertIn("expected dict", "".join(ctx.output))

    def test_invalid_bullet_of_only_unknown_keys_round_trips(self):
        data = {"experience": [{"bullets": [{"nested": {"a": 1}}]}]}
        resume = Resume.from_dict(data)
        self.assertEqual(resume.to_dict(), data)


class TestRejectsHostileStrings(RoundTripMixin, unittest.TestCase):
    """Unicode, RTL, emoji, control characters, and very long values."""

    def test_rejects_unicode_and_emoji_in_identity_fields(self):
        data = {"name": "Zoë 中文 \U0001f680", "headline": "Engineer ✨"}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.name, "Zoë 中文 \U0001f680")

    def test_rejects_rtl_text_in_company_field(self):
        data = {"experience": [{"company": "مرحبا", "title": "שלום"}]}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.experience[0].company, "مرحبا")

    def test_rejects_null_bytes_and_control_characters(self):
        data = {"name": "a\x00b\x01c\x1fd"}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.name, "a\x00b\x01c\x1fd")

    def test_rejects_control_characters_in_bullet_text(self):
        data = {"experience": [{"bullets": [{"text": "line\x00one\ttab\nnewline"}]}]}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.experience[0].bullets[0].text, "line\x00one\ttab\nnewline")

    def test_rejects_very_long_bullet_string(self):
        long_text = "x" * 10000
        data = {"experience": [{"bullets": [{"text": long_text}]}]}
        resume = self.assert_round_trips(data)
        self.assertEqual(len(resume.experience[0].bullets[0].text), 10000)

    def test_rejects_unicode_in_unknown_keys(self):
        data = {"中文键": "\U0001f680", "name": "N"}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.extra["中文键"], "\U0001f680")


class TestRejectsWrongScalarTypes(RoundTripMixin, unittest.TestCase):
    """Numbers and booleans where strings are declared."""

    def test_rejects_integer_name_without_coercing_it(self):
        resume = self.assert_round_trips({"name": 42})
        self.assertIsInstance(resume.name, int)
        self.assertEqual(resume.name, 42)

    def test_rejects_boolean_headline_without_warning(self):
        """Scalar type mismatches are stored as-is; only shapes are checked."""
        logger = logging.getLogger(WARN_LOGGER)
        with self.assertNoLogs(logger, level="WARNING"):
            resume = Resume.from_dict({"headline": True})
        self.assertIs(resume.headline, True)

    def test_rejects_string_priority_on_experience(self):
        data = {"experience": [{"title": "T", "priority": "high"}]}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.experience[0].priority, "high")

    def test_rejects_numeric_bullet_text(self):
        data = {"experience": [{"bullets": [{"text": 7}]}]}
        resume = self.assert_round_trips(data)
        self.assertEqual(resume.experience[0].bullets[0].text, 7)

    def test_invalid_scalar_types_survive_round_trip_unchanged(self):
        data = {"name": 1, "phone": 5551234, "location": False, "email": None}
        self.assert_round_trips(data)


if __name__ == "__main__":
    unittest.main()
