"""Regression tests: keyword matching over priority-scored list items.

Real candidate data stores summary bullets, experience bullets, skills, and
interests as ``{"text": ..., "priority": 0.9}`` so ``--min-priority`` can filter
them. keyword_match.py called ``str(item)`` on that shape, which yields the dict's
Python repr rather than the prose.

Matching is substring-based, so genuine keywords inside the repr were still
found — the defect is FALSE POSITIVES, not missed matches. The repr carries its
own key names, so "priority" and "text" matched against every candidate using
the priority shape:

    matcher over [Kafka, Kubernetes, priority, text]
    against {"text": "Ran Kafka", "priority": 0.9}
    -> matched: Kafka, Kubernetes, priority, text     (2 spurious)

`resume align` therefore inflated alignment scores with keywords the resume
never contained, on the shape the CLI's own renderers and --min-priority filter
are built around.

Sad-path methods use the test_rejects_* / test_invalid_* naming contract.
"""

from __future__ import annotations

import unittest

from resume.keyword_matcher import KeywordMatcher
from resume.keyword_normalize import item_text


def _matcher(*skills: str) -> KeywordMatcher:
    m = KeywordMatcher()
    m.add_keywords_from_spec(
        {"required": [{"skill": s, "weight": 3} for s in skills]}
    )
    return m


class TestItemText(unittest.TestCase):
    """The shared extractor handles every shape the producers emit."""

    def test_extracts_text_key(self):
        self.assertEqual(item_text({"text": "Ran Kafka", "priority": 0.9}), "Ran Kafka")

    def test_accepts_alternate_key_spellings(self):
        """Renderers and the aligner already tolerate line/name; so must this."""
        self.assertEqual(item_text({"line": "Ran Kafka"}), "Ran Kafka")
        self.assertEqual(item_text({"name": "Kubernetes"}), "Kubernetes")

    def test_passes_plain_string_through(self):
        self.assertEqual(item_text("Ran Kafka"), "Ran Kafka")

    def test_rejects_leaking_dict_repr(self):
        """The defect in one assertion: no braces, quotes, or key names."""
        out = item_text({"text": "Ran Kafka", "priority": 0.9})
        for artefact in ("{", "}", "'", "priority", "text"):
            self.assertNotIn(artefact, out)

    def test_invalid_none_and_empty_yield_empty_string(self):
        for value in (None, "", {}, {"priority": 0.9}):
            with self.subTest(value=value):
                self.assertEqual(item_text(value), "")


class TestMatchingPriorityShapedBullets(unittest.TestCase):
    """collect_matches_from_candidate must see prose, not reprs."""

    CANDIDATE = {
        "summary": [
            {"text": "Build reliability on Kubernetes at scale", "priority": 1.0}
        ],
        "experience": [
            {
                "title": "SRE",
                "company": "Acme",
                "bullets": [
                    {"text": "Cut p99 latency by resharding Kafka", "priority": 0.9}
                ],
            }
        ],
    }

    def test_matches_keyword_inside_priority_bullet(self):
        """Regression: Kafka lives in bullets[0]["text"], not str(bullet)."""
        res = _matcher("Kafka").collect_matches_from_candidate(self.CANDIDATE)
        self.assertIn("Kafka", res)

    def test_matches_keyword_inside_priority_summary(self):
        """Regression: summary is a LIST of items in real data."""
        res = _matcher("Kubernetes").collect_matches_from_candidate(self.CANDIDATE)
        self.assertIn("Kubernetes", res)

    def test_scores_experience_role_from_priority_bullets(self):
        """score_experience_roles drives which roles survive tailoring."""
        scores = _matcher("Kafka").score_experience_roles(self.CANDIDATE)
        self.assertTrue(scores, "no roles scored")
        self.assertGreater(scores[0][1], 0, "priority-shaped bullet scored zero")

    def test_rejects_matching_dict_repr_tokens(self):
        """'priority' and 'text' must NOT match — they are repr artefacts.

        Under the old str(item) behaviour these appeared in the match text, so
        a posting asking for either word scored a hit against a resume that
        never used it.
        """
        res = _matcher("priority", "text").collect_matches_from_candidate(
            self.CANDIDATE
        )
        self.assertEqual(
            sorted(res.keys()), [], f"repr artefacts matched: {sorted(res)}"
        )

    def test_plain_string_bullets_still_match(self):
        """The older flat shape must keep working — both are valid input."""
        candidate = {
            "summary": "Build reliability on Kubernetes",
            "experience": [
                {"title": "SRE", "company": "Acme", "bullets": ["Ran Kafka"]}
            ],
        }
        res = _matcher("Kafka", "Kubernetes").collect_matches_from_candidate(candidate)
        self.assertEqual(sorted(res.keys()), ["Kafka", "Kubernetes"])

    def test_invalid_mixed_shapes_in_one_list(self):
        """A list holding both shapes must match every entry."""
        candidate = {
            "experience": [
                {
                    "title": "SRE",
                    "company": "Acme",
                    "bullets": ["Ran Kafka", {"text": "Ran Kubernetes", "priority": 0.5}],
                }
            ]
        }
        res = _matcher("Kafka", "Kubernetes").collect_matches_from_candidate(candidate)
        self.assertEqual(sorted(res.keys()), ["Kafka", "Kubernetes"])

    def test_invalid_empty_candidate_matches_nothing(self):
        self.assertEqual(_matcher("Kafka").collect_matches_from_candidate({}), {})


if __name__ == "__main__":
    unittest.main()
