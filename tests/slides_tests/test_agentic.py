"""Unit tests for slides/agentic.py -- agentic capsule build and emit.

Adopts AgenticBuilderContractMixin for the shared builder contract
(build_agentic_capsule / emit_agentic_context). slides hand-writes its capsule
(no build_domain_map, no CLI tree), so EXPECT_DOMAIN_MAP and EXPECT_CLI_TREE
are both False.

The CLI --agentic surface is covered by test_slides_agentic_cli.py via
AgenticCLIContractMixin.
"""

import unittest

from tests.agentic_builder_contract import AgenticBuilderContractMixin
from tests.fixtures import capture_stdout

from slides.agentic import build_agentic_capsule, emit_agentic_context


class TestSlidesAgenticBuilder(AgenticBuilderContractMixin, unittest.TestCase):
    """The shared agentic builder contract."""

    MODULE_PATH = "slides.agentic"
    APP_ID = "slides"
    EXPECT_CLI_TREE = False
    EXPECT_DOMAIN_MAP = False


class TestSlidesCapsuleContent(unittest.TestCase):
    """slides-specific capsule content not covered by the shared contract."""

    def test_contains_generate_command(self):
        self.assertIn("generate", build_agentic_capsule())

    def test_contains_validate_command(self):
        self.assertIn("validate", build_agentic_capsule())

    def test_contains_template_note(self):
        self.assertIn("template", build_agentic_capsule().lower())

    def test_multiple_calls_idempotent(self):
        self.assertEqual(build_agentic_capsule(), build_agentic_capsule())

    def test_emit_output_matches_build_agentic_capsule(self):
        """Printed output equals build_agentic_capsule() plus a newline."""
        with capture_stdout() as buf:
            emit_agentic_context()
        self.assertEqual(buf.getvalue(), build_agentic_capsule() + "\n")


if __name__ == "__main__":
    unittest.main()
