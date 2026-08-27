"""Golden-output rendering harness for the resume DOCX renderers.

Renders synthetic fixtures through both the standard single-column writer and
the two-column sidebar writer, and asserts the rendered output has not changed.
This is the acceptance criterion for the typed-schema migration: every step
that touches a rendering module must leave these goldens untouched.

TWO RENDERING PATHS ARE PINNED
    Fixtures are rendered both *directly* into the writer and *through*
    ``FilterPipeline``. The direct path alone is not sufficient, and that gap is
    not hypothetical: the migration moves the schema conversion onto the
    pipeline path, so a direct-only harness leaves ``Resume.from_dict`` into
    ``to_dict`` completely untested and reports green while that conversion
    reshapes documents. The pipeline cases cover the no-op pipeline (which
    isolates the conversion) and a filter-active pipeline (which covers the
    filters reading the converted shape).

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
from resume.pipeline import FilterPipeline
from resume.schema import Resume

from tests.resume_tests.golden.golden_docx import describe_mismatch, fingerprint_docx
from tests.resume_tests.golden.golden_fixtures import (
    CANDIDATE_FIXTURES,
    PIPELINE_FIXTURES,
    SIDEBAR_FIXTURES,
    alignment_report,
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

    # -- pipeline path: what the migration actually moves -------------------

    def _render_through_pipeline(self, candidate, alignment_path=None):
        """Lower a fixture through FilterPipeline the way the CLI does.

        Mirrors ``cli.main._apply_filter_pipeline``: typed in, filters applied,
        typed out, lowered back to a dict for the writer.
        """
        return (
            FilterPipeline(Resume.from_dict(candidate))
            .with_skill_filter(alignment_path)
            .with_experience_filter(alignment_path)
            .execute()
            .to_dict()
        )

    def test_no_op_pipeline_matches_golden(self):
        """A pipeline with no filters must not alter rendered output.

        This is the case the harness previously could not see. Rendering the
        fixtures directly leaves the whole schema conversion — Resume.from_dict
        into to_dict, which every Step 2-5 change runs through — untested, so a
        conversion that silently reshaped a document still passed. Applying no
        filters isolates exactly that conversion: any difference here is the
        schema round-trip changing the document, not a filter doing its job.
        """
        for name in PIPELINE_FIXTURES:
            with self.subTest(fixture=name, pipeline="noop"):
                self._check_golden(
                    f"pipeline_noop__{name}",
                    self._render_through_pipeline(CANDIDATE_FIXTURES[name]()),
                    standard_template(),
                )

    def test_no_op_pipeline_is_identical_to_direct_rendering(self):
        """The strongest form of the above: same bytes as never using a pipeline.

        Stated as an equality rather than a stored golden, so it holds even if
        both goldens were regenerated together. A no-op pipeline is by
        definition a no-op; if these ever diverge, the schema round-trip is
        lossy and the goldens on this path are pinning the loss.
        """
        template = standard_template()
        for name in PIPELINE_FIXTURES:
            with self.subTest(fixture=name):
                fixture = CANDIDATE_FIXTURES[name]()
                with tempfile.TemporaryDirectory() as tmp:
                    direct = fingerprint_docx(self._render(fixture, template, tmp))
                piped_data = self._render_through_pipeline(CANDIDATE_FIXTURES[name]())
                with tempfile.TemporaryDirectory() as tmp:
                    piped = fingerprint_docx(self._render(piped_data, template, tmp))
                self.assertEqual(direct.digest, piped.digest)

    def test_filtered_pipeline_matches_golden(self):
        """The pipeline with filters active, pinned end to end.

        The no-op case proves the conversion is transparent; this proves the
        filters still produce a document the renderers read correctly after the
        typed boundary was introduced.
        """
        with tempfile.TemporaryDirectory() as tmp:
            alignment_path = os.path.join(tmp, "alignment.json")
            Path(alignment_path).write_text(json.dumps(alignment_report()))
            for name in PIPELINE_FIXTURES:
                with self.subTest(fixture=name, pipeline="filtered"):
                    self._check_golden(
                        f"pipeline_filtered__{name}",
                        self._render_through_pipeline(
                            CANDIDATE_FIXTURES[name](), alignment_path
                        ),
                        standard_template(),
                    )

    def test_filtered_pipeline_actually_removes_content(self):
        """Guard the filtered goldens against pinning a silent no-op.

        If the alignment report stopped matching — a renamed key, a changed
        report shape — the filters would quietly keep everything and the
        goldens above would still pass while testing nothing. Assert the
        filtered document really is smaller than the unfiltered one.
        """
        with tempfile.TemporaryDirectory() as tmp:
            alignment_path = os.path.join(tmp, "alignment.json")
            Path(alignment_path).write_text(json.dumps(alignment_report()))
            fixture = CANDIDATE_FIXTURES["mixed_shapes"]()
            unfiltered = self._render_through_pipeline(fixture)
            filtered = self._render_through_pipeline(fixture, alignment_path)

        self.assertNotEqual(unfiltered, filtered)
        self.assertLess(
            sum(len(g.get("items", [])) for g in filtered.get("skills_groups", [])),
            sum(len(g.get("items", [])) for g in unfiltered.get("skills_groups", [])),
        )

    def test_scalar_summary_keeps_its_terminal_period(self):
        """The exact regression, asserted on rendered text rather than a digest.

        A golden says only that output moved; it does not say the summary lost
        its period, and a reviewer regenerating goldens would not learn it here.
        A scalar summary renders as a prose paragraph, where the terminal period
        is kept; normalizing it into a one-item list moved it to the bullet
        path, which strips that period by design.
        """
        from docx import Document

        fixture = CANDIDATE_FIXTURES["scalar_summary"]()
        expected = fixture["summary"]
        self.assertTrue(expected.endswith("."), "fixture must carry a period")

        for label, data in (
            ("direct", fixture),
            ("pipeline", self._render_through_pipeline(CANDIDATE_FIXTURES["scalar_summary"]())),
        ):
            with self.subTest(path=label):
                with tempfile.TemporaryDirectory() as tmp:
                    path = self._render(data, standard_template(), tmp)
                    text = [p.text for p in Document(path).paragraphs if p.text.strip()]
                self.assertIn(expected, text)

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
