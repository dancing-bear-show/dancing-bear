"""Unit tests for slides/agentic.py — agentic capsule build and emit."""

import unittest

from tests.fixtures import capture_stdout

from slides.agentic import build_agentic_capsule, emit_agentic_context


# ---------------------------------------------------------------------------
# build_agentic_capsule
# ---------------------------------------------------------------------------

class TestBuildAgenticCapsule(unittest.TestCase):
    """Tests for build_agentic_capsule."""

    def test_returns_string(self):
        """build_agentic_capsule returns a str."""
        result = build_agentic_capsule()
        self.assertIsInstance(result, str)

    def test_contains_agentic_header(self):
        """Capsule text starts with the agentic slides header line."""
        result = build_agentic_capsule()
        self.assertIn("agentic: slides", result)

    def test_contains_generate_command(self):
        """Capsule text includes the generate command example."""
        result = build_agentic_capsule()
        self.assertIn("generate", result)

    def test_contains_validate_command(self):
        """Capsule text includes the validate command example."""
        result = build_agentic_capsule()
        self.assertIn("validate", result)

    def test_contains_template_note(self):
        """Capsule text mentions template requirement."""
        result = build_agentic_capsule()
        self.assertIn("template", result.lower())

    def test_is_non_empty(self):
        """Capsule text is non-empty."""
        result = build_agentic_capsule()
        self.assertGreater(len(result), 0)

    def test_multiple_calls_idempotent(self):
        """Multiple calls return identical output (no side effects)."""
        self.assertEqual(build_agentic_capsule(), build_agentic_capsule())


# ---------------------------------------------------------------------------
# emit_agentic_context
# ---------------------------------------------------------------------------

class TestEmitAgenticContext(unittest.TestCase):
    """Tests for emit_agentic_context."""

    def test_returns_zero(self):
        """emit_agentic_context returns 0 (success exit code)."""
        with capture_stdout():
            result = emit_agentic_context()
        self.assertEqual(result, 0)

    def test_prints_capsule_to_stdout(self):
        """emit_agentic_context prints the capsule text to stdout."""
        with capture_stdout() as buf:
            emit_agentic_context()
        output = buf.getvalue()
        self.assertIn("agentic: slides", output)

    def test_format_param_accepted(self):
        """emit_agentic_context accepts a fmt argument without error."""
        with capture_stdout() as buf:
            result = emit_agentic_context("json")
        self.assertEqual(result, 0)
        self.assertTrue(buf.getvalue())

    def test_compact_param_accepted(self):
        """emit_agentic_context accepts compact=True without error."""
        with capture_stdout() as buf:
            result = emit_agentic_context("text", True)
        self.assertEqual(result, 0)
        self.assertTrue(buf.getvalue())

    def test_output_matches_build_agentic_capsule(self):
        """Printed output equals build_agentic_capsule() plus a newline."""
        with capture_stdout() as buf:
            emit_agentic_context()
        self.assertEqual(buf.getvalue(), build_agentic_capsule() + "\n")


if __name__ == "__main__":
    unittest.main()
