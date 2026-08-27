"""Tests for FilterPipeline's typed boundary over a dict-domain interior.

`FilterPipeline` takes a `Resume` and returns a `Resume`, but the filters between
those edges keep operating on plain dicts. These tests pin the two properties
that make that safe:

* the conversion itself is lossless -- a pipeline with no filters applied
  round-trips a document byte-for-byte;
* where keys *are* lost, the loss belongs to a filter and predates the typed
  boundary. `TestFilterExtraKeyBehaviour` pins the real, pre-existing behaviour
  rather than the behaviour one might wish for.

All fixtures are synthetic.
"""

from __future__ import annotations

import unittest

from resume.pipeline import FilterPipeline
from resume.schema import Resume
from resume.skills_filter import filter_skills_by_keywords


def _sample_document() -> dict:
    """A synthetic document exercising every round-trip mechanism at once."""
    return {
        "name": "Sample Person",
        "headline": "Platform Engineer",
        "contact": {"email": "sample@example.test"},
        "summary": [{"text": "Builds internal platforms."}],
        "skills_groups": [
            {
                "title": "Cloud",
                "provenance": "seeded",  # unknown key on the GROUP
                "items": [
                    {"name": "Kubernetes", "confidence": 0.9},  # unknown key on ITEM
                    {"label": "Terraform", "confidence": 0.4},  # alias spelling
                ],
            }
        ],
        "experience": [
            {
                "title": "Platform Engineer",
                "company": "Example Corp",
                "team": "infra",  # unknown key on the ENTRY
                "bullets": [{"text": "Ran the build fleet.", "priority": 2.0}],
            }
        ],
        "unknown_top_level": {"nested": 1},
    }


class TestTypedBoundary(unittest.TestCase):
    """The pipeline accepts a Resume and returns a Resume."""

    def test_execute_returns_resume(self):
        """execute() hands back a typed document, not a dict."""
        result = FilterPipeline(Resume.from_dict(_sample_document())).execute()
        self.assertIsInstance(result, Resume)

    def test_interior_is_a_plain_dict(self):
        """The interior stays dict-domain so the filters keep working."""
        pipeline = FilterPipeline(Resume.from_dict(_sample_document()))
        self.assertIsInstance(pipeline._data, dict)
        self.assertIsInstance(pipeline._data["experience"][0], dict)

    def test_typed_fields_survive_the_boundary(self):
        """Declared fields are readable as attributes on the way out."""
        result = FilterPipeline(Resume.from_dict(_sample_document())).execute()
        self.assertEqual(result.name, "Sample Person")
        self.assertEqual(result.experience[0].company, "Example Corp")


class TestNoOpRoundTrip(unittest.TestCase):
    """A pipeline with no filters applied changes nothing."""

    def test_no_op_pipeline_round_trips_document_unchanged(self):
        """to_dict -> (no filters) -> from_dict is the identity."""
        raw = _sample_document()
        result = FilterPipeline(Resume.from_dict(raw)).execute()
        self.assertEqual(result.to_dict(), raw)

    def test_no_op_chain_round_trips_document_unchanged(self):
        """Chaining every builder with no-op arguments is still the identity."""
        raw = _sample_document()
        result = (
            FilterPipeline(Resume.from_dict(raw))
            .with_profile_overlays(None)
            .with_synonyms_from_job(None)
            .with_skill_filter(None)
            .with_experience_filter(None)
            .with_priority_filter(None)
            .execute()
        )
        self.assertEqual(result.to_dict(), raw)

    def test_no_op_pipeline_preserves_key_order(self):
        """Key order survives, so a save is not a whole-file diff."""
        raw = _sample_document()
        result = FilterPipeline(Resume.from_dict(raw)).execute()
        self.assertEqual(list(result.to_dict()), list(raw))

    def test_no_op_pipeline_is_idempotent(self):
        """Feeding the output back through changes nothing further."""
        raw = _sample_document()
        once = FilterPipeline(Resume.from_dict(raw)).execute()
        twice = FilterPipeline(once).execute()
        self.assertEqual(twice.to_dict(), once.to_dict())


class TestLegacyShapeUpgrade(unittest.TestCase):
    """A no-op pipeline is the identity for current-shape input, not for legacy.

    `Resume.from_dict` applies two documented one-directional upgrades: a
    ``list[str]`` ``summary`` and ``list[str]`` ``bullets`` become items. Passing
    legacy-shaped data through the pipeline therefore rewrites it into the
    current shape. That is the schema's contract, not a pipeline defect -- but it
    means "no-op pipeline" means *no filter applied*, not *no change at all*.

    It converges after one pass, so a document is never rewritten twice.
    """

    def test_legacy_string_summary_is_upgraded_to_items(self):
        """A bare-string summary entry comes back as a text item."""
        result = FilterPipeline(
            Resume.from_dict({"summary": ["Builds internal platforms."]})
        ).execute()
        self.assertEqual(
            result.to_dict(), {"summary": [{"text": "Builds internal platforms."}]}
        )

    def test_legacy_string_bullets_are_upgraded_to_items(self):
        """Bare-string bullets come back as text items."""
        result = FilterPipeline(
            Resume.from_dict(
                {"experience": [{"title": "Engineer", "bullets": ["Ran the fleet."]}]}
            )
        ).execute()
        self.assertEqual(
            result.to_dict()["experience"][0]["bullets"], [{"text": "Ran the fleet."}]
        )

    def test_legacy_upgrade_converges_after_one_pass(self):
        """The upgrade is one-directional and stable, so a re-run is a no-op."""
        once = FilterPipeline(
            Resume.from_dict({"summary": ["Builds internal platforms."]})
        ).execute()
        twice = FilterPipeline(once).execute()
        self.assertEqual(twice.to_dict(), once.to_dict())


class TestFilterExtraKeyBehaviour(unittest.TestCase):
    """Pin the real extra-key behaviour of the dict-domain filters.

    `skills_filter` rebuilds each surviving group as a fresh
    ``{"title": ..., "items": ...}`` literal (`skills_filter.py`), so keys the
    group carried that the literal does not name are dropped. Item dicts are
    carried by reference and keep everything.

    This is **pre-existing dict-domain behaviour**, not a consequence of the
    typed boundary: `test_loss_is_the_filters_not_the_conversion` proves the
    output is identical with the schema removed entirely. It is pinned here, not
    fixed here.
    """

    _MATCHED = ["Kubernetes", "Terraform"]

    def _sandwiched(self, raw: dict) -> dict:
        """to_dict -> skills filter -> from_dict, the Step-2 boundary in miniature."""
        filtered = filter_skills_by_keywords(
            Resume.from_dict(raw).to_dict(),
            matched_keywords=self._MATCHED,
            synonyms={},
        )
        return Resume.from_dict(filtered).to_dict()

    def test_group_level_unknown_key_is_dropped_by_skills_filter(self):
        """A group-level unknown key does not survive the fresh dict literal."""
        raw = _sample_document()
        self.assertEqual(raw["skills_groups"][0]["provenance"], "seeded")

        group = self._sandwiched(raw)["skills_groups"][0]

        self.assertNotIn("provenance", group)
        self.assertEqual(group["title"], "Cloud")

    def test_item_level_unknown_key_survives_skills_filter(self):
        """Item dicts are carried by reference, so their unknown keys survive."""
        items = self._sandwiched(_sample_document())["skills_groups"][0]["items"]
        self.assertEqual(items[0]["confidence"], 0.9)

    def test_item_level_alias_spelling_survives_skills_filter(self):
        """The `label` alias is replayed as `label`, not rewritten to `name`."""
        items = self._sandwiched(_sample_document())["skills_groups"][0]["items"]
        self.assertIn("label", items[1])
        self.assertNotIn("name", items[1])

    def test_loss_is_the_filters_not_the_conversion(self):
        """The schema sandwich produces byte-identical output to no schema at all.

        This is the load-bearing assertion: it shows the typed boundary adds no
        loss of its own. Whatever the filter drops, it dropped before this step.
        """
        raw = _sample_document()

        without_schema = filter_skills_by_keywords(
            dict(raw), matched_keywords=self._MATCHED, synonyms={}
        )
        with_schema = self._sandwiched(raw)

        self.assertEqual(with_schema, without_schema)


if __name__ == "__main__":
    unittest.main()
