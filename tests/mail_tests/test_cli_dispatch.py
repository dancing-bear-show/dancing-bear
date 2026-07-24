"""Tests for mail/cli/main.py dispatch routing.

Only tests parser structure and pre/post hooks — no live Gmail/Outlook API calls.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestMainHelp(unittest.TestCase):
    """Test that --help exits with code 0 without hitting any API."""

    def test_help_exits_zero(self):
        from mail.cli.main import main
        with self.assertRaises(SystemExit) as ctx:
            main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_labels_help_exits_zero(self):
        from mail.cli.main import main
        with self.assertRaises(SystemExit) as ctx:
            main(["labels", "--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_filters_help_exits_zero(self):
        from mail.cli.main import main
        with self.assertRaises(SystemExit) as ctx:
            main(["filters", "--help"])
        self.assertEqual(ctx.exception.code, 0)


class TestMainUnknownSubcommand(unittest.TestCase):
    """Unknown / misspelled subcommands must exit non-zero."""

    def test_unknown_top_level_command_exits_nonzero(self):
        from mail.cli.main import main
        with self.assertRaises(SystemExit) as ctx:
            main(["totally-unknown-subcommand"])
        self.assertNotEqual(ctx.exception.code, 0)


class TestInstallOutputMaskingHook(unittest.TestCase):
    """Verify _install_output_masking is wired as the pre_run_hook in main()."""

    def test_output_masking_passed_as_pre_run_hook(self):
        """main() must pass _install_output_masking as pre_run_hook to run_with_assistant."""
        with patch("mail.cli.main.app.run_with_assistant") as mock_run:
            mock_run.return_value = 0
            from mail.cli import main as main_module
            main_module.main([])
            # Verify pre_run_hook is the module-level _install_output_masking function
            _, kwargs = mock_run.call_args
            self.assertIs(kwargs["pre_run_hook"], main_module._install_output_masking)

    def test_masking_failure_does_not_crash_main(self):
        """pre_run_hook exceptions are swallowed by run_with_assistant."""
        with patch("mail.cli.main._install_output_masking", side_effect=RuntimeError("boom")):
            from mail.cli.main import main
            # run_with_assistant catches hook failures and continues; no subcommand prints help
            result = main([])
            # No subcommand -> prints help and returns 0
            self.assertEqual(result, 0)


class TestParserSubcommandRegistration(unittest.TestCase):
    """Smoke-test that known command groups and top-level commands are registered."""

    def setUp(self):
        from mail.cli.main import app
        self._app = app

    def _get_parser(self):
        """Build (or reuse) the app parser without running any command."""
        return self._app.build_parser()

    def test_labels_group_registered(self):
        self.assertIn("labels", self._app._groups)

    def test_filters_group_registered(self):
        self.assertIn("filters", self._app._groups)

    def test_messages_group_registered(self):
        self.assertIn("messages", self._app._groups)

    def test_outlook_group_registered(self):
        self.assertIn("outlook", self._app._groups)

    def test_forwarding_group_registered(self):
        self.assertIn("forwarding", self._app._groups)

    def test_signatures_group_registered(self):
        self.assertIn("signatures", self._app._groups)

    def test_config_group_registered(self):
        self.assertIn("config", self._app._groups)

    def test_accounts_group_registered(self):
        self.assertIn("accounts", self._app._groups)

    def test_cache_group_registered(self):
        self.assertIn("cache", self._app._groups)

    def test_auto_group_registered(self):
        self.assertIn("auto", self._app._groups)

    def test_auth_top_level_command_registered(self):
        self.assertIn("auth", self._app._commands)

    def test_backup_top_level_command_registered(self):
        self.assertIn("backup", self._app._commands)


class TestSubcommandDispatch(unittest.TestCase):
    """Verify subcommand parsing routes to the correct handler function."""

    def _parse_args(self, *argv):
        from mail.cli.main import app
        parser = app.build_parser()
        from mail.cli.main import assistant
        assistant.add_agentic_flags(parser)
        from mail.cli.main import _add_common_args
        _add_common_args(parser)
        return parser.parse_args(list(argv))

    def test_auth_command_has_cmd_func(self):
        args = self._parse_args("auth")
        cmd_func = getattr(args, "_cmd_func", None)
        self.assertIsNotNone(cmd_func)

    def test_backup_command_has_cmd_func(self):
        args = self._parse_args("backup")
        cmd_func = getattr(args, "_cmd_func", None)
        self.assertIsNotNone(cmd_func)

    def test_labels_list_sets_cmd_func(self):
        args = self._parse_args("labels", "list")
        cmd_func = getattr(args, "_cmd_func", None)
        self.assertIsNotNone(cmd_func)

    def test_filters_list_sets_cmd_func(self):
        args = self._parse_args("filters", "list")
        cmd_func = getattr(args, "_cmd_func", None)
        self.assertIsNotNone(cmd_func)

    def test_messages_search_sets_cmd_func(self):
        args = self._parse_args("messages", "search")
        cmd_func = getattr(args, "_cmd_func", None)
        self.assertIsNotNone(cmd_func)

    def test_forwarding_list_sets_cmd_func(self):
        args = self._parse_args("forwarding", "list")
        cmd_func = getattr(args, "_cmd_func", None)
        self.assertIsNotNone(cmd_func)

    def test_no_subcommand_sets_no_cmd_func(self):
        args = self._parse_args()
        cmd_func = getattr(args, "_cmd_func", None)
        self.assertIsNone(cmd_func)


class TestMainReturnCode(unittest.TestCase):
    """Verify main() returns the exit code from the underlying command."""

    def test_no_subcommand_returns_zero(self):
        """With no subcommand, run_with_assistant prints help and returns 0."""
        with patch("mail.cli.main._install_output_masking"):
            from mail.cli.main import main
            result = main([])
        self.assertEqual(result, 0)

    def test_agentic_flag_handled(self):
        """--agentic flag should emit context and return without calling a real command."""
        fake_emit = MagicMock(return_value=0)
        with patch("mail.cli.main._install_output_masking"):
            with patch("mail.cli.main._lazy_emit_agentic", return_value=fake_emit):
                from mail.cli.main import main
                result = main(["--agentic"])
        self.assertEqual(result, 0)
        fake_emit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
