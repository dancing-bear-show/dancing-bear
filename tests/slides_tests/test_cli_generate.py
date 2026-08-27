"""Tests for slides.cli.cmd_generate and related generate helpers.

Rewritten against the dest CLIApp decorator pattern: source's
SlidesCLI._cmd_generate bound method has no equivalent class here.
slides.cli exposes a module-level cmd_generate(args) -> int function
instead, plus a module-level _apply_layout_map(deck, cli_layout_map,
exported_template) helper.

SCOPE REDUCTION (per port-tests-cli stage spec): Google Drive/Slides
integration (--from-deck, --upload, --profile, --title upload label,
_export_deck_as_template, _upload_to_drive) is out of scope for this port.
Dropped entirely, not stubbed:
  - TestSlidesCLIFromDeck            (reason: from-deck / Google Slides export)
  - TestSlidesCLIUpload              (reason: upload / Google Drive)
  - TestSlidesCLIFromDeckAndUpload   (reason: from-deck + upload combined)
  - TestSlidesCLIExportDeckAsTemplate (reason: google-mocks / Drive client)
  - TestSlidesCLIUploadToDrive       (reason: google-mocks / Drive client)

The source module also imports GOOGLE_TEST_PRESENTATION_ID from
tests.helpers.google_mocks at module level -- that helper module is not
ported, and is NOT imported here. Any surviving test that used it or a
from_deck=... argument was dropped rather than adapted, per the stage's
CRITICAL #1 requirement.

Kept in scope: template resolution (explicit / YAML / none), --layout-map
parsing and application, YAML load errors, generation exceptions, and
output-path derivation -- the CLI's core generate-from-YAML behavior.
"""

from __future__ import annotations

import argparse
import unittest
from unittest.mock import MagicMock, patch

from slides.cli import cmd_generate, _apply_layout_map

TEST_OUTPUT_PATH = "/tmp/output.pptx"  # nosec B108 - string literal for mock data, no actual file created
TEST_TEMPLATE_PATH = "/path/to/template.pptx"
TEST_YAML_TEMPLATE_PATH = "/yaml/template.pptx"
TEST_EXPLICIT_TEMPLATE_PATH = "/explicit/template.pptx"
TEST_CUSTOM_OUTPUT_PATH = "/custom/path/slides.pptx"


def _make_generate_args(**overrides: object) -> argparse.Namespace:
    """Create a Namespace for cmd_generate with all required attributes.

    No from_deck/upload/title/profile fields -- those flags do not exist on
    the rewritten CLI (Google Drive/Slides integration is out of scope).
    """
    defaults = {
        "yaml_file": "deck.yaml",
        "output": None,
        "template": None,
        "layout_map": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestCmdGenerate(unittest.TestCase):
    """Tests for cmd_generate."""

    @patch("slides.cli.Path")
    def test_missing_yaml_returns_1(self, mock_path_class):
        """cmd_generate returns 1 when YAML file does not exist."""
        mock_path_class.return_value.exists.return_value = False

        args = _make_generate_args(yaml_file="/nonexistent/deck.yaml")
        result = cmd_generate(args)
        self.assertEqual(result, 1)

    @patch("slides.cli.load_deck_from_yaml")
    @patch("slides.cli.Path")
    def test_no_template_anywhere_returns_1(self, mock_path_class, mock_load_deck):
        """cmd_generate returns 1 when no template is specified anywhere."""
        mock_path_class.return_value.exists.return_value = True

        mock_deck = MagicMock()
        mock_deck.template_path = None
        mock_load_deck.return_value = mock_deck

        args = _make_generate_args()
        result = cmd_generate(args)
        self.assertEqual(result, 1)

    @patch("slides.generator.SlideGenerator.generate")
    @patch("slides.cli.load_deck_from_yaml")
    @patch("slides.cli.Path")
    def test_generate_success_with_explicit_template(
        self, mock_path_class, mock_load_deck, mock_gen
    ):
        """cmd_generate returns 0 on successful generation with explicit template."""
        mock_path_class.return_value.exists.return_value = True
        mock_deck = MagicMock()
        mock_deck.metadata.layout_map = None
        mock_deck.template_path = None
        mock_load_deck.return_value = mock_deck
        mock_gen.return_value = TEST_OUTPUT_PATH

        args = _make_generate_args(
            output=TEST_OUTPUT_PATH,
            template=TEST_TEMPLATE_PATH,
        )
        result = cmd_generate(args)
        self.assertEqual(result, 0)
        mock_gen.assert_called_once_with(mock_deck, TEST_OUTPUT_PATH)

    @patch("slides.generator.SlideGenerator.generate")
    @patch("slides.cli.load_deck_from_yaml")
    @patch("slides.cli.Path")
    def test_generate_success_with_yaml_template(
        self, mock_path_class, mock_load_deck, mock_gen
    ):
        """cmd_generate returns 0 when template is in YAML (not --template)."""
        mock_path_class.return_value.exists.return_value = True

        mock_deck = MagicMock()
        mock_deck.template_path = TEST_YAML_TEMPLATE_PATH
        mock_deck.metadata.layout_map = None
        mock_load_deck.return_value = mock_deck

        mock_gen.return_value = TEST_OUTPUT_PATH

        args = _make_generate_args(output=TEST_OUTPUT_PATH)
        result = cmd_generate(args)
        self.assertEqual(result, 0)
        mock_gen.assert_called_once_with(mock_deck, TEST_OUTPUT_PATH)

    @patch(
        "slides.generator.SlideGenerator.generate",
        side_effect=RuntimeError("Generation failed"),
    )
    @patch("slides.cli.load_deck_from_yaml")
    @patch("slides.cli.Path")
    def test_generate_exception_returns_1(self, mock_path_class, mock_load_deck, mock_gen):
        """cmd_generate returns 1 when SlideGenerator.generate raises an exception."""
        mock_path_class.return_value.exists.return_value = True
        mock_deck = MagicMock()
        mock_deck.metadata.layout_map = None
        mock_deck.template_path = None
        mock_load_deck.return_value = mock_deck

        args = _make_generate_args(
            output=TEST_OUTPUT_PATH,
            template=TEST_TEMPLATE_PATH,
        )
        result = cmd_generate(args)
        self.assertEqual(result, 1)

    @patch("slides.generator.SlideGenerator.generate")
    @patch("slides.cli.load_deck_from_yaml")
    @patch("slides.cli.Path")
    def test_output_defaults_to_data_home_for_yaml(self, mock_path_class, mock_load_deck, mock_gen):
        """cmd_generate defaults the output into output_dir("slides"), not beside the YAML.

        Behaviour change from the ported source, which wrote a sibling .pptx.
        Per CLAUDE.md, output-producing domains resolve implicit paths via
        core.paths.output_dir so generated artifacts land outside the checkout
        (those paths are gitignored, which prevents a stray commit but not a
        `git clean -fdx`). An explicit -o is still honoured verbatim.
        """
        mock_path_class.return_value.exists.return_value = True
        mock_path_class.return_value.stem = "deck"
        mock_deck = MagicMock()
        mock_deck.metadata.layout_map = None
        mock_deck.template_path = None
        mock_load_deck.return_value = mock_deck
        mock_gen.return_value = "deck.pptx"

        args = _make_generate_args(template=TEST_TEMPLATE_PATH)
        result = cmd_generate(args)
        self.assertEqual(result, 0)
        out_path = mock_gen.call_args[0][1]
        self.assertTrue(out_path.endswith("deck.pptx"), out_path)
        self.assertIn("slides", out_path)
        self.assertNotEqual(out_path, "deck.pptx")

    @patch("slides.generator.SlideGenerator.generate")
    @patch("slides.cli.load_deck_from_yaml")
    @patch("slides.cli.Path")
    def test_output_defaults_to_data_home_for_yml(self, mock_path_class, mock_load_deck, mock_gen):
        """A .yml deck defaults into output_dir("slides") using the deck's stem."""
        mock_path_class.return_value.exists.return_value = True
        mock_path_class.return_value.stem = "deck"
        mock_deck = MagicMock()
        mock_deck.metadata.layout_map = None
        mock_deck.template_path = None
        mock_load_deck.return_value = mock_deck
        mock_gen.return_value = "deck.pptx"

        args = _make_generate_args(
            yaml_file="deck.yml",
            template=TEST_TEMPLATE_PATH,
        )
        result = cmd_generate(args)
        self.assertEqual(result, 0)
        out_path = mock_gen.call_args[0][1]
        self.assertTrue(out_path.endswith("deck.pptx"), out_path)
        self.assertIn("slides", out_path)
        self.assertNotEqual(out_path, "deck.pptx")

    @patch("slides.generator.SlideGenerator.generate")
    @patch("slides.cli.load_deck_from_yaml")
    @patch("slides.cli.Path")
    def test_generate_prints_result_on_success(self, mock_path_class, mock_load_deck, mock_gen):
        """cmd_generate prints the generated file path on success."""
        mock_path_class.return_value.exists.return_value = True
        mock_deck = MagicMock()
        mock_deck.metadata.layout_map = None
        mock_deck.template_path = None
        mock_load_deck.return_value = mock_deck
        mock_gen.return_value = TEST_OUTPUT_PATH

        args = _make_generate_args(
            output=TEST_OUTPUT_PATH,
            template=TEST_TEMPLATE_PATH,
        )
        with patch("builtins.print") as mock_print:
            cmd_generate(args)
            mock_print.assert_called_once_with("Generated: /tmp/output.pptx")

    @patch(
        "slides.generator.SlideGenerator.generate",
        side_effect=ValueError("bad config"),
    )
    @patch("slides.cli.load_deck_from_yaml")
    @patch("slides.cli.Path")
    def test_generate_prints_error_on_exception(self, mock_path_class, mock_load_deck, mock_gen):
        """cmd_generate prints error to stderr on exception."""
        mock_path_class.return_value.exists.return_value = True
        mock_deck = MagicMock()
        mock_deck.metadata.layout_map = None
        mock_deck.template_path = None
        mock_load_deck.return_value = mock_deck

        args = _make_generate_args(
            output=TEST_OUTPUT_PATH,
            template=TEST_TEMPLATE_PATH,
        )
        with patch("builtins.print") as mock_print:
            cmd_generate(args)
            call_args = mock_print.call_args
            self.assertIn("bad config", str(call_args))

    @patch("slides.generator.SlideGenerator.generate")
    @patch("slides.cli.load_deck_from_yaml")
    @patch("slides.cli.Path")
    def test_explicit_output_used_when_provided(self, mock_path_class, mock_load_deck, mock_gen):
        """cmd_generate uses explicit output path when provided."""
        mock_path_class.return_value.exists.return_value = True
        mock_deck = MagicMock()
        mock_deck.metadata.layout_map = None
        mock_deck.template_path = None
        mock_load_deck.return_value = mock_deck
        mock_gen.return_value = TEST_CUSTOM_OUTPUT_PATH

        args = _make_generate_args(
            output=TEST_CUSTOM_OUTPUT_PATH,
            template=TEST_TEMPLATE_PATH,
        )
        cmd_generate(args)
        mock_gen.assert_called_once_with(mock_deck, TEST_CUSTOM_OUTPUT_PATH)


class TestCmdGenerateNoCommandStderr(unittest.TestCase):
    """Tests verifying stderr output for error cases in generate."""

    @patch("slides.cli.Path")
    def test_missing_yaml_generate_prints_error(self, mock_path_class):
        """cmd_generate prints error about missing YAML file to stderr."""
        mock_path_class.return_value.exists.return_value = False

        args = _make_generate_args(yaml_file="/missing/deck.yaml")
        with patch("builtins.print") as mock_print:
            cmd_generate(args)
            call_args_list = [str(call) for call in mock_print.call_args_list]
            joined = "\n".join(call_args_list)
            self.assertIn("/missing/deck.yaml", joined)

    @patch("slides.cli.load_deck_from_yaml")
    @patch("slides.cli.Path")
    def test_no_template_prints_error(self, mock_path_class, mock_load_deck):
        """cmd_generate prints error when no template available."""
        mock_path_class.return_value.exists.return_value = True

        mock_deck = MagicMock()
        mock_deck.template_path = None
        mock_load_deck.return_value = mock_deck

        args = _make_generate_args()
        with patch("builtins.print") as mock_print:
            cmd_generate(args)
            call_args_list = [str(call) for call in mock_print.call_args_list]
            joined = "\n".join(call_args_list)
            self.assertIn("No template specified", joined)


class TestCmdGenerateTemplateFromYaml(unittest.TestCase):
    """Tests for template resolution logic in cmd_generate."""

    @patch("slides.generator.SlideGenerator.generate")
    @patch("slides.cli.load_deck_from_yaml")
    @patch("slides.cli.Path")
    def test_always_loads_deck_from_yaml(
        self, mock_path_class, mock_load_deck, mock_gen
    ):
        """cmd_generate always loads deck from YAML (needed for layout_map)."""
        mock_path_class.return_value.exists.return_value = True
        mock_deck = MagicMock()
        mock_deck.metadata.layout_map = None
        mock_deck.template_path = None
        mock_load_deck.return_value = mock_deck
        mock_gen.return_value = "/tmp/out.pptx"  # nosec B108 - mock return value, no file created

        args = _make_generate_args(
            output="/tmp/out.pptx",  # nosec B108 - mock arg, no file created
            template=TEST_EXPLICIT_TEMPLATE_PATH,
        )
        cmd_generate(args)

        mock_load_deck.assert_called_once_with("deck.yaml")

    @patch("slides.generator.SlideGenerator.generate")
    @patch("slides.cli.load_deck_from_yaml")
    @patch("slides.cli.Path")
    def test_calls_load_deck_when_no_template(
        self, mock_path_class, mock_load_deck, mock_gen
    ):
        """cmd_generate calls load_deck_from_yaml to check template when --template not given."""
        mock_path_class.return_value.exists.return_value = True

        mock_deck = MagicMock()
        mock_deck.template_path = TEST_YAML_TEMPLATE_PATH
        mock_deck.metadata.layout_map = None
        mock_load_deck.return_value = mock_deck

        mock_gen.return_value = "/tmp/out.pptx"  # nosec B108 - mock return value, no file created

        args = _make_generate_args(output="/tmp/out.pptx")  # nosec B108 - mock arg, no file created
        cmd_generate(args)

        mock_load_deck.assert_called_once_with("deck.yaml")


class TestApplyLayoutMap(unittest.TestCase):
    """Tests for _apply_layout_map."""

    def test_cli_layout_map_overrides_yaml_value(self):
        """A --layout-map value replaces whatever the deck YAML declared."""
        mock_deck = MagicMock()
        mock_deck.metadata.layout_map = {"existing": 5}

        _apply_layout_map(mock_deck, cli_layout_map={"section": 0, "bullet": 1})

        self.assertEqual(mock_deck.metadata.layout_map, {"section": 0, "bullet": 1})

    def test_none_leaves_deck_layout_map_untouched(self):
        """Without --layout-map the deck's own layout_map survives unchanged."""
        mock_deck = MagicMock()
        mock_deck.metadata.layout_map = {"existing": 5}

        _apply_layout_map(mock_deck, cli_layout_map=None)

        self.assertEqual(mock_deck.metadata.layout_map, {"existing": 5})


class TestCmdGenerateYamlLoadError(unittest.TestCase):
    """Tests for cmd_generate YAML load error path."""

    @patch("slides.cli.load_deck_from_yaml", side_effect=ValueError("bad YAML"))
    @patch("slides.cli.Path")
    def test_yaml_load_error_returns_1(self, mock_path_class, mock_load_deck):
        """cmd_generate returns 1 when load_deck_from_yaml raises."""
        mock_path_class.return_value.exists.return_value = True

        args = _make_generate_args(template=TEST_TEMPLATE_PATH)
        result = cmd_generate(args)

        self.assertEqual(result, 1)

    @patch("slides.cli.load_deck_from_yaml", side_effect=RuntimeError("parse fail"))
    @patch("slides.cli.Path")
    def test_yaml_load_error_prints_message(self, mock_path_class, mock_load_deck):
        """cmd_generate prints error message when load_deck_from_yaml raises."""
        mock_path_class.return_value.exists.return_value = True

        args = _make_generate_args(template=TEST_TEMPLATE_PATH)
        with patch("builtins.print") as mock_print:
            cmd_generate(args)

        printed = [str(c) for c in mock_print.call_args_list]
        joined = "\n".join(printed)
        self.assertIn("Error loading YAML", joined)
        self.assertIn("parse fail", joined)


class TestCmdGenerateLayoutMapParseError(unittest.TestCase):
    """Tests for cmd_generate --layout-map parse error path."""

    @patch("slides.cli.load_deck_from_yaml")
    @patch("slides.cli.Path")
    def test_invalid_layout_map_returns_1(self, mock_path_class, mock_load_deck):
        """cmd_generate returns 1 when --layout-map value cannot be parsed."""
        mock_path_class.return_value.exists.return_value = True
        mock_deck = MagicMock()
        mock_deck.metadata.layout_map = None
        mock_load_deck.return_value = mock_deck

        # Value without '=' is invalid per _parse_layout_map_flag
        args = _make_generate_args(
            template=TEST_TEMPLATE_PATH,
            layout_map="notvalid",
        )
        result = cmd_generate(args)

        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
