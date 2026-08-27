"""Tests for slides CLI parser construction and command dispatch.

FULL REWRITE, not a mechanical port: the original CLI-instantiation,
build-parser, agentic-extras, and run-dispatch test classes all targeted a
CLI-subclass pattern (build_parser() override plus a dispatch dict) with no
equivalent here. core.cli_framework.CLIApp is decorator-registration only
(@app.command, @app.argument); there is no parser subclass, no dispatch
dict, and no per-CLI agentic_extras() method to call -- agentic capsule
content lives in a standalone slides/agentic.py module, wired in
automatically once main() calls run_with_assistant.

Rebuilt here against the actual CLIApp constructs, following the house
pattern of invoking app.build_parser() directly and asserting on the
parsed Namespace plus dispatched _cmd_func (see
worker/cli.py empirical verification, and tests/wifi_tests/, tests/charts_tests/
for house style of testing a CLIApp-based CLI).

SCOPE REDUCTION: publish (and all --from-deck/--upload/--profile/--title
Google Drive flags) is out of scope for this port and asserted ABSENT from
the parser here, not ported as a subcommand test.
"""

from __future__ import annotations

import argparse
import unittest

from slides.cli import app


class TestSlidesParserBasics(unittest.TestCase):
    """Tests for the slides CLIApp parser structure."""

    def setUp(self):
        self.parser = app.build_parser()

    def test_parser_is_argument_parser(self):
        """build_parser returns an ArgumentParser instance."""
        self.assertIsInstance(self.parser, argparse.ArgumentParser)

    def test_parser_has_generate_subcommand(self):
        """Parser accepts 'generate' subcommand with a yaml_file positional."""
        ns = self.parser.parse_args(["generate", "deck.yaml"])
        self.assertEqual(ns.yaml_file, "deck.yaml")

    def test_parser_has_validate_subcommand(self):
        """Parser accepts 'validate' subcommand with a yaml_file positional."""
        ns = self.parser.parse_args(["validate", "deck.yaml"])
        self.assertEqual(ns.yaml_file, "deck.yaml")

    def test_parser_has_templates_subcommand(self):
        """Parser accepts 'templates' subcommand with a pptx positional."""
        ns = self.parser.parse_args(["templates", "template.pptx"])
        self.assertEqual(ns.pptx, "template.pptx")

    def test_parser_has_no_publish_subcommand(self):
        """Parser does NOT accept a 'publish' subcommand -- out of scope."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["publish", "data.csv"])


class TestGenerateSubcommandFlags(unittest.TestCase):
    """Tests for generate subcommand flags."""

    def setUp(self):
        self.parser = app.build_parser()

    def test_generate_has_output_flag(self):
        """Generate subcommand accepts -o/--output flag."""
        ns = self.parser.parse_args(["generate", "deck.yaml", "-o", "out.pptx"])
        self.assertEqual(ns.output, "out.pptx")

        ns_long = self.parser.parse_args(
            ["generate", "deck.yaml", "--output", "out2.pptx"]
        )
        self.assertEqual(ns_long.output, "out2.pptx")

    def test_generate_has_template_flag(self):
        """Generate subcommand accepts -t/--template flag."""
        ns = self.parser.parse_args(
            ["generate", "deck.yaml", "--template", "/tpl.pptx"]
        )
        self.assertEqual(ns.template, "/tpl.pptx")

        ns_short = self.parser.parse_args(
            ["generate", "deck.yaml", "-t", "/tpl.pptx"]
        )
        self.assertEqual(ns_short.template, "/tpl.pptx")

    def test_generate_output_default_is_none(self):
        """Generate subcommand output defaults to None when not specified."""
        ns = self.parser.parse_args(["generate", "deck.yaml"])
        self.assertIsNone(ns.output)

    def test_generate_template_default_is_none(self):
        """Generate subcommand template defaults to None when not specified."""
        ns = self.parser.parse_args(["generate", "deck.yaml"])
        self.assertIsNone(ns.template)

    def test_generate_has_layout_map_flag(self):
        """Generate subcommand accepts --layout-map flag."""
        ns = self.parser.parse_args(
            ["generate", "deck.yaml", "--layout-map", "section=0,bullet=1"]
        )
        self.assertEqual(ns.layout_map, "section=0,bullet=1")

    def test_generate_layout_map_default_is_none(self):
        """Generate subcommand --layout-map defaults to None."""
        ns = self.parser.parse_args(["generate", "deck.yaml"])
        self.assertIsNone(ns.layout_map)

    def test_generate_has_no_from_deck_flag(self):
        """Generate subcommand does NOT accept --from-deck -- out of scope."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["generate", "deck.yaml", "--from-deck", "ABC123"])

    def test_generate_has_no_upload_flag(self):
        """Generate subcommand does NOT accept --upload -- out of scope."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["generate", "deck.yaml", "--upload"])


class TestTemplatesSubcommandFlags(unittest.TestCase):
    """Tests for templates subcommand flags."""

    def setUp(self):
        self.parser = app.build_parser()

    def test_templates_format_default_is_table(self):
        """Templates subcommand format defaults to 'table'."""
        ns = self.parser.parse_args(["templates", "template.pptx"])
        self.assertEqual(ns.format, "table")

    def test_templates_format_accepts_json(self):
        """Templates subcommand accepts --format json."""
        ns = self.parser.parse_args(["templates", "template.pptx", "--format", "json"])
        self.assertEqual(ns.format, "json")

    def test_templates_format_accepts_yaml(self):
        """Templates subcommand accepts --format yaml."""
        ns = self.parser.parse_args(["templates", "template.pptx", "--format", "yaml"])
        self.assertEqual(ns.format, "yaml")

    def test_templates_format_rejects_text(self):
        """Templates subcommand rejects --format text -- not a declared choice.

        Per cli-surface.md's resolved gap: "text" was never a valid choice
        even in source (its own add_format_argument call declares only
        table/json/yaml), so this is a scope boundary, not a regression.
        """
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["templates", "template.pptx", "--format", "text"])

    def test_templates_format_rejects_unknown_choice(self):
        """Templates subcommand rejects an unrecognized --format value."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["templates", "template.pptx", "--format", "bogus"])


class TestCommandDispatch(unittest.TestCase):
    """Tests that the parser resolves each subcommand to its command function."""

    def setUp(self):
        self.parser = app.build_parser()

    def test_generate_dispatches_to_cmd_generate(self):
        """'generate' subcommand resolves to the cmd_generate function."""
        from slides.cli import cmd_generate

        ns = self.parser.parse_args(["generate", "deck.yaml"])
        self.assertEqual(ns._cmd_func, cmd_generate)

    def test_validate_dispatches_to_cmd_validate(self):
        """'validate' subcommand resolves to the cmd_validate function."""
        from slides.cli import cmd_validate

        ns = self.parser.parse_args(["validate", "deck.yaml"])
        self.assertEqual(ns._cmd_func, cmd_validate)

    def test_templates_dispatches_to_cmd_templates(self):
        """'templates' subcommand resolves to the cmd_templates function."""
        from slides.cli import cmd_templates

        ns = self.parser.parse_args(["templates", "template.pptx"])
        self.assertEqual(ns._cmd_func, cmd_templates)


# ---------------------------------------------------------------------------
# _apply_layout_map: a CLI layout map overrides the deck's own
# ---------------------------------------------------------------------------

class TestApplyLayoutMap(unittest.TestCase):
    """Tests for _apply_layout_map."""

    def test_cli_layout_map_overrides_deck_layout_map(self):
        """_apply_layout_map sets deck.metadata.layout_map when cli_layout_map is provided."""
        from slides.cli import _apply_layout_map
        deck = argparse.Namespace(metadata=argparse.Namespace(layout_map=None), template_path=None)
        _apply_layout_map(deck, {"bullet": 0})
        self.assertEqual(deck.metadata.layout_map, {"bullet": 0})


# ---------------------------------------------------------------------------
# _lazy_agentic: lru_cache lazy import (lines 38-40)
# ---------------------------------------------------------------------------

class TestLazyAgentic(unittest.TestCase):
    """Tests for the _lazy_agentic lru_cache helper."""

    def test_returns_callable(self):
        """_lazy_agentic() returns a callable (emit_agentic_context)."""
        from slides.cli import _lazy_agentic
        fn = _lazy_agentic()
        self.assertTrue(callable(fn))

    def test_second_call_returns_same_object(self):
        """_lazy_agentic() is cached — second call returns the exact same function."""
        from slides.cli import _lazy_agentic
        fn1 = _lazy_agentic()
        fn2 = _lazy_agentic()
        self.assertIs(fn1, fn2)


# ---------------------------------------------------------------------------
# _parse_layout_map_entry: empty name and reserved name errors (lines 59, 103)
# ---------------------------------------------------------------------------

class TestParseLayoutMapEntry(unittest.TestCase):
    """Tests for _parse_layout_map_entry ValueErrors."""

    def test_empty_name_raises_value_error(self):
        """An entry like '=0' (empty name) raises ValueError."""
        from slides.cli import _parse_layout_map_entry
        with self.assertRaises(ValueError) as ctx:
            _parse_layout_map_entry("=0")
        self.assertIn("empty", str(ctx.exception).lower())

    def test_reserved_name_raises_value_error(self):
        """An entry using the reserved layout key raises ValueError."""
        from slides.cli import _parse_layout_map_entry
        from slides.constants import RESERVED_LAYOUT_KEY
        with self.assertRaises(ValueError) as ctx:
            _parse_layout_map_entry(f"{RESERVED_LAYOUT_KEY}=0")
        self.assertIn("reserved", str(ctx.exception).lower())

    def test_valid_entry_returns_tuple(self):
        """A valid 'name=index' entry returns (name, index) tuple."""
        from slides.cli import _parse_layout_map_entry
        name, index = _parse_layout_map_entry("bullet=1")
        self.assertEqual(name, "bullet")
        self.assertEqual(index, 1)


# ---------------------------------------------------------------------------
# main() entry point (line 281)
# ---------------------------------------------------------------------------

class TestMain(unittest.TestCase):
    """Tests for the main() entry point."""

    def test_main_no_args_returns_int(self):
        """main() with no subcommand returns an integer exit code."""
        from slides.cli import main
        result = main([])
        self.assertIsInstance(result, int)

    def test_main_help_exits_zero(self):
        """main(['--help']) exits with code 0."""
        from slides.cli import main
        with self.assertRaises(SystemExit) as ctx:
            main(["--help"])
        self.assertEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
