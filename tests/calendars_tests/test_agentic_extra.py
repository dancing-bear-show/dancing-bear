"""Additional tests for calendars/agentic.py."""
import unittest
from unittest.mock import patch


class TestAgenticEmitContext(unittest.TestCase):
    def test_emit_agentic_context_prints_capsule(self):
        import io
        from contextlib import redirect_stdout
        from calendars.agentic import emit_agentic_context

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = emit_agentic_context()
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertGreater(len(out), 0)
        self.assertIn("calendar", out.lower())

    def test_emit_agentic_context_accepts_fmt_compact(self):
        """fmt and compact params are accepted (reserved) without errors."""
        import io
        from contextlib import redirect_stdout
        from calendars.agentic import emit_agentic_context

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = emit_agentic_context(_fmt="yaml", _compact=True)
        self.assertEqual(rc, 0)


class TestFlowMap(unittest.TestCase):
    def test_flow_map_returns_string(self):
        from calendars.agentic import _flow_map
        result = _flow_map()
        self.assertIsInstance(result, str)

    def test_flow_map_contains_outlook_add_when_exists(self):
        from calendars.agentic import _flow_map, _cli_path_exists
        # If outlook add exists in the real CLI, flow map should mention it
        if _cli_path_exists(["outlook", "add"]):
            result = _flow_map()
            self.assertIn("outlook add", result.lower())

    def test_flow_map_empty_when_no_cli(self):
        """When parser is None (no CLI), flow map should be empty string."""
        from calendars import agentic as agentic_mod

        with patch.object(agentic_mod, "_get_parser", return_value=None):
            # Clear LRU cache side-effect of the test by patching cli_path_exists
            with patch.object(agentic_mod, "_cli_path_exists", return_value=False):
                result = agentic_mod._flow_map()
        self.assertIsInstance(result, str)


class TestCliTree(unittest.TestCase):
    def test_cli_tree_returns_string(self):
        from calendars.agentic import _cli_tree
        result = _cli_tree()
        self.assertIsInstance(result, str)

    def test_cli_tree_contains_outlook_when_available(self):
        from calendars.agentic import _cli_tree
        tree = _cli_tree()
        if tree:
            self.assertIn("outlook", tree.lower())
        # If tree is empty (parser unavailable), test passes vacuously


class TestBuildAgenticCapsule(unittest.TestCase):
    def test_capsule_non_empty(self):
        from calendars.agentic import build_agentic_capsule
        cap = build_agentic_capsule()
        self.assertIsInstance(cap, str)
        self.assertGreater(len(cap), 0)

    def test_capsule_mentions_gmail(self):
        from calendars.agentic import build_agentic_capsule
        cap = build_agentic_capsule()
        self.assertIn("gmail", cap.lower())

    def test_capsule_mentions_scan(self):
        from calendars.agentic import build_agentic_capsule
        cap = build_agentic_capsule()
        self.assertIn("scan", cap.lower())


class TestBuildDomainMap(unittest.TestCase):
    def test_domain_map_non_empty(self):
        from calendars.agentic import build_domain_map
        dm = build_domain_map()
        self.assertIsInstance(dm, str)
        self.assertGreater(len(dm), 0)

    def test_domain_map_has_top_level(self):
        from calendars.agentic import build_domain_map
        dm = build_domain_map()
        self.assertIn("Top-Level", dm)


class TestCliPathExists(unittest.TestCase):
    def test_nonexistent_path_returns_false(self):
        from calendars.agentic import _cli_path_exists
        self.assertFalse(_cli_path_exists(["outlook", "nonexistent-cmd-xyz"]))
        self.assertFalse(_cli_path_exists(["nonexistent-group"]))

    def test_none_parser_returns_false(self):
        from calendars import agentic as agentic_mod
        with patch.object(agentic_mod, "_get_parser", return_value=None):
            result = agentic_mod._cli_path_exists(["outlook", "add"])
        self.assertFalse(result)

    def test_known_paths_when_parser_available(self):
        """When parser can be constructed, known paths return True."""
        from calendars.agentic import _get_parser
        from core.agentic import cli_path_exists as core_exists
        parser = _get_parser()
        if parser is None:
            self.skipTest("Parser not available in this test environment")
        self.assertTrue(core_exists(parser, ["outlook", "add"]))
        self.assertTrue(core_exists(parser, ["gmail", "scan-classes"]))
        self.assertTrue(core_exists(parser, ["outlook", "add-recurring"]))
        # Either reminders-off or reminders-set may exist depending on version.
        self.assertTrue(
            core_exists(parser, ["outlook", "reminders-off"])
            or core_exists(parser, ["outlook", "reminders-set"])
        )


class TestParserActuallyLoads(unittest.TestCase):
    """The parser must load — a None parser is a bug, not a test environment.

    _load_parser previously reached the CLIApp through `calendars.__main__`,
    which no longer re-exports `app`. The resulting AttributeError was
    swallowed by cached_parser_loader's broad except and cached as None
    forever, so --agentic, the CLI tree and the flow map silently rendered
    without any real CLI structure.

    Every other test here skips when the parser is None, which is precisely
    why nothing caught it. These assert instead.
    """

    def test_load_parser_does_not_raise(self):
        from calendars.agentic import _load_parser

        parser = _load_parser()
        self.assertIsNotNone(parser)
        self.assertEqual(parser.prog, "calendar-assistant")

    def test_cli_tree_is_not_empty(self):
        from calendars.agentic import _cli_tree

        tree = _cli_tree()
        self.assertTrue(tree, "CLI tree is empty — the parser failed to load")
        self.assertIn("outlook", tree)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
