"""Tests for diagrams/renderers.py — TextRenderer and LocalRenderer."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# TextRenderer
# ---------------------------------------------------------------------------


class TestTextRendererRenderString(unittest.TestCase):
    def test_raw_string_returned_unchanged(self):
        from diagrams.renderers import TextRenderer

        renderer = TextRenderer()
        result = renderer.render("flowchart LR\n    A-->B")
        self.assertEqual(result, "flowchart LR\n    A-->B")

    def test_builder_object_calls_render(self):
        from diagrams.renderers import TextRenderer

        renderer = TextRenderer()
        mock_builder = MagicMock()
        mock_builder.render.return_value = "flowchart TB\n    A[Node]"
        result = renderer.render(mock_builder)
        mock_builder.render.assert_called_once()
        self.assertEqual(result, "flowchart TB\n    A[Node]")


class TestTextRendererRenderEmbedded(unittest.TestCase):
    def test_embedded_wraps_in_mermaid_fence(self):
        from diagrams.renderers import TextRenderer

        renderer = TextRenderer()
        result = renderer.render_embedded("flowchart LR\n    A-->B")
        self.assertTrue(result.startswith("```mermaid\n"))
        self.assertIn("flowchart LR", result)
        self.assertTrue(result.endswith("```"))

    def test_embedded_with_builder_object(self):
        from diagrams.renderers import TextRenderer

        renderer = TextRenderer()
        mock_builder = MagicMock()
        mock_builder.render.return_value = "sequenceDiagram"
        result = renderer.render_embedded(mock_builder)
        self.assertIn("```mermaid", result)
        self.assertIn("sequenceDiagram", result)


# ---------------------------------------------------------------------------
# LocalRenderer._infer_format
# ---------------------------------------------------------------------------


class TestLocalRendererInferFormat(unittest.TestCase):
    def _infer(self, path):
        from diagrams.renderers import LocalRenderer
        return LocalRenderer._infer_format(path)

    def test_svg_extension(self):
        self.assertEqual(self._infer("output.svg"), "svg")

    def test_png_extension(self):
        self.assertEqual(self._infer("output.png"), "png")

    def test_pdf_extension(self):
        self.assertEqual(self._infer("output.pdf"), "pdf")

    def test_unknown_extension_raises_value_error(self):
        with self.assertRaises(ValueError):
            self._infer("output.gif")

    def test_no_extension_raises_value_error(self):
        with self.assertRaises(ValueError):
            self._infer("outputfile")


# ---------------------------------------------------------------------------
# LocalRenderer.validate_syntax
# ---------------------------------------------------------------------------


class TestLocalRendererValidateSyntax(unittest.TestCase):
    def _make_renderer(self):
        """Construct a LocalRenderer with mmdc_path bypassed."""
        from diagrams.renderers import LocalRenderer

        with patch("shutil.which", return_value="/usr/local/bin/mmdc"):
            return LocalRenderer()

    def test_successful_render_returns_true_none(self):
        renderer = self._make_renderer()
        with patch.object(renderer, "render", return_value=b"<svg>...</svg>"):
            ok, err = renderer.validate_syntax("flowchart LR\n    A-->B")
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_failed_render_returns_false_with_message(self):
        from diagrams.renderers import LocalRendererError

        renderer = self._make_renderer()
        with patch.object(renderer, "render", side_effect=LocalRendererError("bad syntax")):
            ok, err = renderer.validate_syntax("flowchart BROKEN")
        self.assertFalse(ok)
        self.assertEqual(err, "bad syntax")


# ---------------------------------------------------------------------------
# LocalRenderer.__init__ — mmdc discovery
# ---------------------------------------------------------------------------


class TestLocalRendererInit(unittest.TestCase):
    def test_mmdc_not_on_path_raises_local_renderer_error(self):
        from diagrams.renderers import LocalRenderer, LocalRendererError

        with patch("shutil.which", return_value=None):
            with self.assertRaises(LocalRendererError):
                LocalRenderer()

    def test_mmdc_on_path_constructs_successfully(self):
        from diagrams.renderers import LocalRenderer

        with patch("shutil.which", return_value="/usr/local/bin/mmdc"):
            renderer = LocalRenderer()
        self.assertEqual(renderer.mmdc_path, "/usr/local/bin/mmdc")

    def test_explicit_mmdc_path_not_found_raises(self):
        from diagrams.renderers import LocalRenderer, LocalRendererError

        with self.assertRaises(LocalRendererError):
            LocalRenderer(mmdc_path="/nonexistent/path/mmdc")


if __name__ == "__main__":
    unittest.main()
