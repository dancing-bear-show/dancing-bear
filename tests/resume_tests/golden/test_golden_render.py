"""Golden-output rendering harness for the resume DOCX renderers.

Renders synthetic fixtures through both the standard single-column writer and
the two-column sidebar writer, and asserts the rendered output has not changed.
This is the acceptance criterion for the typed-schema migration: every step
that touches a rendering module must leave these goldens untouched.

REGENERATING THE GOLDENS
    Set ``RESUME_GOLDEN_UPDATE=1`` and run the suite. Golden files under
    ``tests/resume_tests/golden/goldens/`` are rewritten in place and the run
    FAILS, so a regeneration can never be mistaken for a passing build:

        RESUME_GOLDEN_UPDATE=1 make test

    Then ``git diff`` the goldens and confirm every moved digest corresponds to
    a change you intended. A regeneration that you cannot explain part-by-part
    is a regression you are about to commit. When a golden moves, the failure
    message from a normal run names the archive parts that differ (see
    ``describe_mismatch``) — read that first, before regenerating.

WHY NOT HASH THE RAW .docx BYTES
    Because it is not reproducible; this was measured, not assumed. See the
    module docstring of ``golden_docx`` for the two clock-driven sources of
    variation and for exactly what the chosen representation does and does not
    catch.

FIXTURES ARE SYNTHETIC
    Goldens are committed, so fixtures must never derive from a real profile.
    See ``golden_fixtures``.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from resume.docx_writer import write_resume_docx

from tests.resume_tests.golden.golden_docx import describe_mismatch, fingerprint_docx
from tests.resume_tests.golden.golden_fixtures import (
    CANDIDATE_FIXTURES,
    SIDEBAR_FIXTURES,
    sidebar_template,
    standard_template,
)

GOLDEN_DIR = Path(__file__).parent / "goldens"
UPDATE_ENV_VAR = "RESUME_GOLDEN_UPDATE"


def _updating() -> bool:
    return os.environ.get(UPDATE_ENV_VAR, "") not in ("", "0", "false")


class GoldenRenderTests(unittest.TestCase):
    """Byte-stable rendering contract for both DOCX layouts."""

    maxDiff = None

    def _render(self, candidate, template, out_dir: str) -> str:
        out_path = os.path.join(out_dir, "resume.docx")
        write_resume_docx(candidate, template, out_path)
        return out_path

    def _check_golden(self, name: str, candidate, template) -> None:
        """Render one fixture and compare against (or rewrite) its golden."""
        with tempfile.TemporaryDirectory() as tmp:
            actual = fingerprint_docx(self._render(candidate, template, tmp))

        golden_path = GOLDEN_DIR / f"{name}.json"

        if _updating():
            GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
            golden_path.write_text(
                json.dumps(actual.to_golden(), indent=2, sort_keys=True) + "\n"
            )
            self.fail(
                f"{UPDATE_ENV_VAR} is set: rewrote {golden_path.name}. "
                "Review the diff, then unset it and re-run."
            )

        self.assertTrue(
            golden_path.exists(),
            f"Missing golden {golden_path}. Create it with "
            f"{UPDATE_ENV_VAR}=1 make test",
        )
        expected = json.loads(golden_path.read_text())
        if expected.get("digest") != actual.digest:
            self.fail(describe_mismatch(expected, actual))

    # -- standard layout: every fixture ------------------------------------

    def test_standard_layout_matches_golden(self):
        for name, build in CANDIDATE_FIXTURES.items():
            with self.subTest(fixture=name, layout="standard"):
                self._check_golden(f"standard__{name}", build(), standard_template())

    # -- sidebar layout: the same data through the other renderer ----------

    def test_sidebar_layout_matches_golden(self):
        for name in SIDEBAR_FIXTURES:
            with self.subTest(fixture=name, layout="sidebar"):
                self._check_golden(
                    f"sidebar__{name}", CANDIDATE_FIXTURES[name](), sidebar_template()
                )

    # -- harness self-checks -----------------------------------------------

    def test_rendering_is_reproducible_within_a_run(self):
        """The representation must be stable, or the goldens are noise.

        Renders the same fixture twice into different directories and asserts
        the fingerprints agree. This is the property that makes the golden
        comparison trustworthy; if python-docx ever starts stamping a clock
        into a part that is not scrubbed, this fails here with a clear cause
        rather than failing at random in every other golden test.
        """
        candidate = CANDIDATE_FIXTURES["mixed_shapes"]()
        for label, template in (
            ("standard", standard_template()),
            ("sidebar", sidebar_template()),
        ):
            with self.subTest(layout=label):
                with tempfile.TemporaryDirectory() as tmp_a:
                    first = fingerprint_docx(self._render(candidate, template, tmp_a))
                with tempfile.TemporaryDirectory() as tmp_b:
                    second = fingerprint_docx(self._render(candidate, template, tmp_b))
                self.assertEqual(first.digest, second.digest)
                self.assertEqual(first.members, second.members)

    def test_fingerprint_detects_a_changed_body(self):
        """A real content change must move the digest.

        Guards the harness against becoming a no-op: if the fingerprint were
        computed over something insensitive (or over nothing at all), every
        golden would pass forever. Altering one bullet's text must change both
        the overall digest and specifically word/document.xml.
        """
        template = standard_template()
        baseline_data = CANDIDATE_FIXTURES["dict_bullets"]()
        with tempfile.TemporaryDirectory() as tmp:
            baseline = fingerprint_docx(self._render(baseline_data, template, tmp))

        perturbed_data = CANDIDATE_FIXTURES["dict_bullets"]()
        perturbed_data["experience"][0]["bullets"][0]["text"] = "A different bullet."
        with tempfile.TemporaryDirectory() as tmp:
            perturbed = fingerprint_docx(self._render(perturbed_data, template, tmp))

        self.assertNotEqual(baseline.digest, perturbed.digest)
        self.assertNotEqual(
            baseline.digests["word/document.xml"],
            perturbed.digests["word/document.xml"],
        )

    def test_mismatch_message_names_the_differing_part(self):
        """A failure must say WHAT changed, not just that a hash moved."""
        template = standard_template()
        data = CANDIDATE_FIXTURES["dict_bullets"]()
        with tempfile.TemporaryDirectory() as tmp:
            baseline = fingerprint_docx(self._render(data, template, tmp))

        data["experience"][0]["bullets"][0]["text"] = "Changed."
        with tempfile.TemporaryDirectory() as tmp:
            actual = fingerprint_docx(self._render(data, template, tmp))

        message = describe_mismatch(baseline.to_golden(), actual)
        self.assertIn("word/document.xml", message)
        self.assertIn("the document body differs", message)
        self.assertIn(UPDATE_ENV_VAR, message)


if __name__ == "__main__":
    unittest.main()
