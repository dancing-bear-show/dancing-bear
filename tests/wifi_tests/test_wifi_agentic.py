"""Tests for wifi/agentic.py agentic capsule and domain map."""

import unittest

from tests.fixtures import capture_stdout

from wifi.agentic import (
    _section,
    build_agentic_capsule,
    build_domain_map,
    emit_agentic_context,
)


class TestSection(unittest.TestCase):
    """Test _section helper function."""

    def test_formats_title_and_body(self):
        result = _section("Title", "body text")
        self.assertEqual(result, "Title:\nbody text")

    def test_multiline_body(self):
        result = _section("Probes", "- line1\n- line2")
        self.assertEqual(result, "Probes:\n- line1\n- line2")

    def test_empty_body(self):
        result = _section("Empty", "")
        self.assertEqual(result, "Empty:\n")


class TestBuildAgenticCapsule(unittest.TestCase):
    """Test build_agentic_capsule function."""

    def test_returns_string(self):
        result = build_agentic_capsule()
        self.assertIsInstance(result, str)

    def test_contains_agentic_header(self):
        result = build_agentic_capsule()
        self.assertIn("agentic: wifi", result)

    def test_contains_purpose(self):
        result = build_agentic_capsule()
        self.assertIn("purpose:", result)
        self.assertIn("Wi-Fi", result)

    def test_contains_commands(self):
        result = build_agentic_capsule()
        self.assertIn("commands:", result)
        self.assertIn("./bin/wifi", result)

    def test_contains_probes_section(self):
        result = build_agentic_capsule()
        self.assertIn("Probes:", result)
        self.assertIn("gateway detection", result)
        self.assertIn("ping sweep", result)
        self.assertIn("DNS timing", result)

    def test_contains_json_output_command(self):
        result = build_agentic_capsule()
        self.assertIn("--json", result)


class TestBuildDomainMap(unittest.TestCase):
    """Test build_domain_map function."""

    def test_returns_string(self):
        result = build_domain_map()
        self.assertIsInstance(result, str)

    def test_contains_top_level_header(self):
        result = build_domain_map()
        self.assertIn("Top-Level", result)

    def test_contains_bin_wrapper(self):
        result = build_domain_map()
        self.assertIn("bin/wifi", result)

    def test_contains_core_modules(self):
        result = build_domain_map()
        self.assertIn("wifi/cli.py", result)
        self.assertIn("wifi/pipeline.py", result)
        self.assertIn("wifi/diagnostics.py", result)
        self.assertIn("wifi/agentic.py", result)
        self.assertIn("wifi/llm_cli.py", result)


class TestEmitAgenticContext(unittest.TestCase):
    """Test emit_agentic_context function."""

    def test_returns_zero(self):
        with capture_stdout():
            rc = emit_agentic_context()
        self.assertEqual(rc, 0)

    def test_prints_capsule_to_stdout(self):
        with capture_stdout() as buf:
            emit_agentic_context()
        output = buf.getvalue()
        self.assertIn("agentic: wifi", output)

    def test_accepts_fmt_parameter(self):
        with capture_stdout():
            rc = emit_agentic_context(fmt="yaml")
        self.assertEqual(rc, 0)

    def test_accepts_compact_parameter(self):
        with capture_stdout():
            rc = emit_agentic_context(compact=True)
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
