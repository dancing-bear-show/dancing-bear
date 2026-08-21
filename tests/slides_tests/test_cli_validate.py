"""Tests for slides.cli.cmd_validate.

Rewritten against the dest CLIApp decorator pattern: the source's
SlidesCLI._cmd_validate bound method has no equivalent here. slides.cli
exposes a module-level cmd_validate(args) -> int function instead, so tests
call that function directly with an argparse.Namespace, matching the house
pattern for CLIApp-based CLIs (see tests/charts_tests/test_cli_handlers.py).

_cmd_validate's body has zero source-CLI-framework dependency (per
cli-surface.md), so behavioral assertions (print output content, order,
return codes) port unchanged -- only the call convention changes from
self.cli._cmd_validate(args) to slides.cli.cmd_validate(args).
"""

from __future__ import annotations

import argparse
import unittest
from unittest.mock import MagicMock, patch

from slides.cli import cmd_validate

TEST_TEMPLATE_PATH = "/path/to/template.pptx"


class TestCmdValidate(unittest.TestCase):
    """Tests for cmd_validate."""

    @patch("slides.cli.Path")
    def test_missing_yaml_returns_1(self, mock_path_class):
        """cmd_validate returns 1 when YAML file does not exist."""
        mock_path_class.return_value.exists.return_value = False

        args = argparse.Namespace(yaml_file="/nonexistent/deck.yaml")
        result = cmd_validate(args)
        self.assertEqual(result, 1)

    @patch("slides.cli.load_deck_from_yaml")
    @patch("slides.cli.Path")
    def test_validate_success_returns_0(self, mock_path_class, mock_load_deck):
        """cmd_validate returns 0 on successful validation."""
        mock_path_class.return_value.exists.return_value = True

        mock_slide = MagicMock()
        mock_slide.title = "Slide 1"
        mock_slide.bullets = ["Bullet A", "Bullet B"]

        mock_metadata = MagicMock()
        mock_metadata.title = "Test Deck"
        mock_metadata.author = "Test Author"
        mock_metadata.date = "2026-01-15"
        mock_metadata.template_slide_index = 11
        mock_metadata.theme_color = "LIGHT_2"

        mock_deck = MagicMock()
        mock_deck.metadata = mock_metadata
        mock_deck.template_path = TEST_TEMPLATE_PATH
        mock_deck.slides = [mock_slide]
        mock_load_deck.return_value = mock_deck

        args = argparse.Namespace(yaml_file="deck.yaml")
        result = cmd_validate(args)
        self.assertEqual(result, 0)

    @patch("slides.cli.load_deck_from_yaml")
    @patch("slides.cli.Path")
    def test_validate_exception_returns_1(self, mock_path_class, mock_load_deck):
        """cmd_validate returns 1 when load_deck_from_yaml raises an exception."""
        mock_path_class.return_value.exists.return_value = True
        mock_load_deck.side_effect = ValueError("Invalid YAML structure")

        args = argparse.Namespace(yaml_file="deck.yaml")
        result = cmd_validate(args)
        self.assertEqual(result, 1)

    @patch("slides.cli.load_deck_from_yaml")
    @patch("slides.cli.Path")
    def test_validate_prints_deck_info(self, mock_path_class, mock_load_deck):
        """cmd_validate prints deck metadata and slide info on success."""
        mock_path_class.return_value.exists.return_value = True

        mock_slide = MagicMock()
        mock_slide.title = "Introduction"
        mock_slide.bullets = ["Point 1", "Point 2", "Point 3"]

        mock_metadata = MagicMock()
        mock_metadata.title = "My Deck"
        mock_metadata.author = "Author Name"
        mock_metadata.date = "2026-02-01"
        mock_metadata.template_slide_index = 5
        mock_metadata.theme_color = "ACCENT_1"

        mock_deck = MagicMock()
        mock_deck.metadata = mock_metadata
        mock_deck.template_path = "/tpl.pptx"
        mock_deck.slides = [mock_slide]
        mock_load_deck.return_value = mock_deck

        args = argparse.Namespace(yaml_file="deck.yaml")
        with patch("builtins.print") as mock_print:
            cmd_validate(args)

            printed = [str(call) for call in mock_print.call_args_list]
            joined = "\n".join(printed)

            self.assertIn("My Deck", joined)
            self.assertIn("Author Name", joined)
            self.assertIn("2026-02-01", joined)
            self.assertIn("ACCENT_1", joined)
            self.assertIn("Validation: OK", joined)
            self.assertIn("Introduction", joined)
            self.assertIn("3 bullets", joined)

    @patch("slides.cli.load_deck_from_yaml")
    @patch("slides.cli.Path")
    def test_validate_handles_none_optional_fields(
        self, mock_path_class, mock_load_deck
    ):
        """cmd_validate handles None author, date, and template_path."""
        mock_path_class.return_value.exists.return_value = True

        mock_metadata = MagicMock()
        mock_metadata.title = "Minimal Deck"
        mock_metadata.author = None
        mock_metadata.date = None
        mock_metadata.template_slide_index = 11
        mock_metadata.theme_color = "LIGHT_2"

        mock_deck = MagicMock()
        mock_deck.metadata = mock_metadata
        mock_deck.template_path = None
        mock_deck.slides = []
        mock_load_deck.return_value = mock_deck

        args = argparse.Namespace(yaml_file="deck.yaml")
        with patch("builtins.print") as mock_print:
            result = cmd_validate(args)
            self.assertEqual(result, 0)

            printed = [str(call) for call in mock_print.call_args_list]
            joined = "\n".join(printed)

            self.assertIn("(not set)", joined)
            self.assertIn("Slides: 0", joined)

    @patch("slides.cli.load_deck_from_yaml")
    @patch("slides.cli.Path")
    def test_validate_prints_error_on_exception(
        self, mock_path_class, mock_load_deck
    ):
        """cmd_validate prints the validation error to stderr."""
        mock_path_class.return_value.exists.return_value = True
        mock_load_deck.side_effect = RuntimeError("Parse error in YAML")

        args = argparse.Namespace(yaml_file="deck.yaml")
        with patch("builtins.print") as mock_print:
            cmd_validate(args)
            call_args_list = [str(call) for call in mock_print.call_args_list]
            joined = "\n".join(call_args_list)
            self.assertIn("Parse error in YAML", joined)

    @patch("slides.cli.load_deck_from_yaml")
    @patch("slides.cli.Path")
    def test_validate_multiple_slides(self, mock_path_class, mock_load_deck):
        """cmd_validate prints info for multiple slides."""
        mock_path_class.return_value.exists.return_value = True

        mock_slide_1 = MagicMock()
        mock_slide_1.title = "Slide One"
        mock_slide_1.bullets = ["A"]

        mock_slide_2 = MagicMock()
        mock_slide_2.title = "Slide Two"
        mock_slide_2.bullets = ["B", "C"]

        mock_slide_3 = MagicMock()
        mock_slide_3.title = "Slide Three"
        mock_slide_3.bullets = []

        mock_metadata = MagicMock()
        mock_metadata.title = "Multi-Slide"
        mock_metadata.author = "Author"
        mock_metadata.date = "2026-01-01"
        mock_metadata.template_slide_index = 11
        mock_metadata.theme_color = "LIGHT_2"

        mock_deck = MagicMock()
        mock_deck.metadata = mock_metadata
        mock_deck.template_path = "/tpl.pptx"
        mock_deck.slides = [mock_slide_1, mock_slide_2, mock_slide_3]
        mock_load_deck.return_value = mock_deck

        args = argparse.Namespace(yaml_file="deck.yaml")
        with patch("builtins.print") as mock_print:
            result = cmd_validate(args)
            self.assertEqual(result, 0)

            printed = [str(call) for call in mock_print.call_args_list]
            joined = "\n".join(printed)

            self.assertIn("Slides: 3", joined)
            self.assertIn("Slide One", joined)
            self.assertIn("1 bullets", joined)
            self.assertIn("Slide Two", joined)
            self.assertIn("2 bullets", joined)
            self.assertIn("Slide Three", joined)
            self.assertIn("0 bullets", joined)


class TestCmdValidateNoCommandStderr(unittest.TestCase):
    """Tests verifying stderr output for validate error cases."""

    @patch("slides.cli.Path")
    def test_missing_yaml_validate_prints_error(self, mock_path_class):
        """cmd_validate prints error about missing YAML file to stderr."""
        mock_path_class.return_value.exists.return_value = False

        args = argparse.Namespace(yaml_file="/missing/deck.yaml")
        with patch("builtins.print") as mock_print:
            cmd_validate(args)
            call_args_list = [str(call) for call in mock_print.call_args_list]
            joined = "\n".join(call_args_list)
            self.assertIn("/missing/deck.yaml", joined)


if __name__ == "__main__":
    unittest.main()
