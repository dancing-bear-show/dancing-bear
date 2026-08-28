"""Tests for fixed defects in resume.agentic.

Defect 1: _load_parser() imported non-existent build_parser from cli.main;
           the ImportError was swallowed by cached_parser_loader, so
           _get_parser() returned None forever.

Defect 2: _flow_map() passed [["extract"]] (nested list) instead of
           ["extract"] to _cli_path_exists, so the check always failed
           and the resume workflow block was never rendered.
"""
import unittest


class TestResumAgenticParser(unittest.TestCase):
    """_get_parser() must return a real parser, not None."""

    def _get_parser(self):
        import sys
        from pathlib import Path
        # Ensure correct source root is first on path
        src = Path(__file__).parents[3] / "src"
        sys.path.insert(0, str(src))
        from resume.agentic import _get_parser
        return _get_parser()

    def test_get_parser_is_not_none(self):
        parser = self._get_parser()
        self.assertIsNotNone(parser, "_get_parser() must return a real ArgumentParser, not None")

    def test_get_parser_has_extract_subcommand(self):
        parser = self._get_parser()
        self.assertIsNotNone(parser)
        help_text = parser.format_help()
        self.assertIn("extract", help_text)

    def test_get_parser_has_summarize_subcommand(self):
        parser = self._get_parser()
        self.assertIsNotNone(parser)
        help_text = parser.format_help()
        self.assertIn("summarize", help_text)

    def test_get_parser_has_render_subcommand(self):
        parser = self._get_parser()
        self.assertIsNotNone(parser)
        help_text = parser.format_help()
        self.assertIn("render", help_text)


class TestResumAgenticCliPathExists(unittest.TestCase):
    """_cli_path_exists must return True for the core workflow paths."""

    def _cli_path_exists(self, path):
        import sys
        from pathlib import Path
        src = Path(__file__).parents[3] / "src"
        sys.path.insert(0, str(src))
        from resume.agentic import _cli_path_exists
        return _cli_path_exists(path)

    def test_extract_path_exists(self):
        self.assertTrue(self._cli_path_exists(["extract"]))

    def test_summarize_path_exists(self):
        self.assertTrue(self._cli_path_exists(["summarize"]))

    def test_render_path_exists(self):
        self.assertTrue(self._cli_path_exists(["render"]))

    def test_align_path_exists(self):
        self.assertTrue(self._cli_path_exists(["align"]))


class TestResumAgenticFlowMap(unittest.TestCase):
    """_flow_map() must render the extract/summarize/render workflow block."""

    def _flow_map(self):
        import sys
        from pathlib import Path
        src = Path(__file__).parents[3] / "src"
        sys.path.insert(0, str(src))
        from resume.agentic import _flow_map
        return _flow_map()

    def test_flow_map_contains_resume_workflow(self):
        flow = self._flow_map()
        self.assertIn("Resume workflow", flow)

    def test_flow_map_contains_extract(self):
        flow = self._flow_map()
        self.assertIn("Extract:", flow)

    def test_flow_map_contains_summarize(self):
        flow = self._flow_map()
        self.assertIn("Summarize:", flow)

    def test_flow_map_contains_render(self):
        flow = self._flow_map()
        self.assertIn("Render DOCX:", flow)


class TestResumAgenticCliTree(unittest.TestCase):
    """_cli_tree() must return a non-empty string."""

    def _cli_tree(self):
        import sys
        from pathlib import Path
        src = Path(__file__).parents[3] / "src"
        sys.path.insert(0, str(src))
        from resume.agentic import _cli_tree
        return _cli_tree()

    def test_cli_tree_is_non_empty(self):
        tree = self._cli_tree()
        self.assertTrue(tree, "_cli_tree() returned empty string — parser not loaded")

    def test_cli_tree_contains_extract(self):
        self.assertIn("extract", self._cli_tree())

    def test_cli_tree_contains_render(self):
        self.assertIn("render", self._cli_tree())


if __name__ == "__main__":
    unittest.main(verbosity=2)
