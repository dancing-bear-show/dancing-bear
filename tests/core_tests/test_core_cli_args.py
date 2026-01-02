"""Tests for core/cli_args.py helper functions extracted during refactoring."""

from __future__ import annotations

import argparse
import unittest

from core.cli_args import (
    _add_argument_with_help,
    add_outlook_auth_args,
    OutlookAuthConfig,
)


class TestAddArgumentWithHelp(unittest.TestCase):
    """Test _add_argument_with_help helper function."""

    def test_adds_argument_without_help(self):
        """Test adding argument without help text."""
        parser = argparse.ArgumentParser()
        _add_argument_with_help(parser, "--test", None)

        args = parser.parse_args(["--test", "value"])
        self.assertEqual(args.test, "value")

    def test_adds_argument_with_help(self):
        """Test adding argument with help text."""
        parser = argparse.ArgumentParser()
        _add_argument_with_help(parser, "--test", "Test argument")

        # Verify help text is included
        help_text = parser.format_help()
        self.assertIn("Test argument", help_text)

    def test_passes_through_kwargs(self):
        """Test that additional kwargs are passed through."""
        parser = argparse.ArgumentParser()
        _add_argument_with_help(parser, "--test", "Help text", default="default_val", required=False)

        args = parser.parse_args([])
        self.assertEqual(args.test, "default_val")

    def test_with_default_value(self):
        """Test argument with default value."""
        parser = argparse.ArgumentParser()
        _add_argument_with_help(parser, "--port", "Port number", default=8080)

        args = parser.parse_args([])
        self.assertEqual(args.port, 8080)

    def test_with_action(self):
        """Test argument with action parameter."""
        parser = argparse.ArgumentParser()
        _add_argument_with_help(parser, "--verbose", "Enable verbose", action="store_true")

        args = parser.parse_args(["--verbose"])
        self.assertTrue(args.verbose)


class TestAddOutlookAuthArgsHelpers(unittest.TestCase):
    """Test add_outlook_auth_args uses helper functions correctly."""

    def test_creates_arguments_without_help(self):
        """Test arguments are created even without help text."""
        parser = argparse.ArgumentParser()
        config = OutlookAuthConfig(
            client_id_help=None,
            tenant_help=None,
            token_help=None
        )
        add_outlook_auth_args(parser, config)

        args = parser.parse_args(["--client-id", "test-id", "--tenant", "common", "--token", "token.json"])
        self.assertEqual(args.client_id, "test-id")
        self.assertEqual(args.tenant, "common")
        self.assertEqual(args.token, "token.json")

    def test_creates_arguments_with_help(self):
        """Test arguments include help text when provided."""
        parser = argparse.ArgumentParser()
        config = OutlookAuthConfig(
            client_id_help="Client ID help",
            tenant_help="Tenant help",
            token_help="Token help"  # nosec B106 - test help string
        )
        add_outlook_auth_args(parser, config)

        help_text = parser.format_help()
        self.assertIn("Client ID help", help_text)
        self.assertIn("Tenant help", help_text)
        self.assertIn("Token help", help_text)

    def test_tenant_default_applied(self):
        """Test tenant default value is applied."""
        parser = argparse.ArgumentParser()
        config = OutlookAuthConfig(tenant_default="consumers")
        add_outlook_auth_args(parser, config)

        args = parser.parse_args(["--client-id", "test-id", "--token", "token.json"])
        self.assertEqual(args.tenant, "consumers")

    def test_profile_argument_optional(self):
        """Test profile argument is only added when requested."""
        parser = argparse.ArgumentParser()
        config = OutlookAuthConfig(include_profile=False)
        add_outlook_auth_args(parser, config)

        # Should not have --profile argument
        with self.assertRaises(SystemExit):
            parser.parse_args(["--profile", "test"])

    def test_profile_argument_included(self):
        """Test profile argument is added when requested."""
        parser = argparse.ArgumentParser()
        config = OutlookAuthConfig(include_profile=True, profile_help="Profile name")
        add_outlook_auth_args(parser, config)

        args = parser.parse_args(["--profile", "work", "--client-id", "id", "--token", "token.json"])
        self.assertEqual(args.profile, "work")

    def test_uses_defaults_when_config_not_provided(self):
        """Test default config is used when not provided."""
        parser = argparse.ArgumentParser()
        add_outlook_auth_args(parser)

        help_text = parser.format_help()
        # Should have default help text for client-id
        self.assertIn("Azure app", help_text)

    def test_explicit_none_removes_help(self):
        """Test explicit None removes help text."""
        parser = argparse.ArgumentParser()
        config = OutlookAuthConfig(client_id_help=None)
        add_outlook_auth_args(parser, config)

        args = parser.parse_args(["--client-id", "test"])
        self.assertEqual(args.client_id, "test")


class TestAddOutlookAuthArgsIntegration(unittest.TestCase):
    """Integration tests for add_outlook_auth_args with all helpers."""

    def test_full_argument_set_with_defaults(self):
        """Test full set of arguments with default values."""
        parser = argparse.ArgumentParser()
        config = OutlookAuthConfig(
            include_profile=True,
            profile_help="Select profile",
            client_id_help="App client ID",
            tenant_help="Azure tenant",
            tenant_default="common",
            token_help="Token cache path"  # nosec B106 - test help string
        )
        add_outlook_auth_args(parser, config)

        args = parser.parse_args([
            "--profile", "work",
            "--client-id", "abc123",
            "--token", "/path/to/token.json"
        ])

        self.assertEqual(args.profile, "work")
        self.assertEqual(args.client_id, "abc123")
        self.assertEqual(args.tenant, "common")  # default
        self.assertEqual(args.token, "/path/to/token.json")

    def test_minimal_argument_set(self):
        """Test minimal required arguments."""
        parser = argparse.ArgumentParser()
        config = OutlookAuthConfig(include_profile=False)
        add_outlook_auth_args(parser, config)

        args = parser.parse_args([
            "--client-id", "test-id",
            "--token", "token.json"
        ])

        self.assertEqual(args.client_id, "test-id")
        self.assertEqual(args.token, "token.json")

    def test_override_all_defaults(self):
        """Test overriding all default values."""
        parser = argparse.ArgumentParser()
        config = OutlookAuthConfig(
            include_profile=True,
            tenant_default="organizations"
        )
        add_outlook_auth_args(parser, config)

        args = parser.parse_args([
            "--profile", "personal",
            "--client-id", "xyz789",
            "--tenant", "custom-tenant",
            "--token", "cache.json"
        ])

        self.assertEqual(args.profile, "personal")
        self.assertEqual(args.client_id, "xyz789")
        self.assertEqual(args.tenant, "custom-tenant")
        self.assertEqual(args.token, "cache.json")


if __name__ == "__main__":
    unittest.main()
