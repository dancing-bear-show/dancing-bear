"""Tests for mail/outlook/helpers.py."""
import unittest
from unittest.mock import Mock, patch, MagicMock
import os

from mail.outlook.helpers import (
    norm_label_name_outlook,
    OUTLOOK_COLOR_NAMES,
    norm_label_color_outlook,
    resolve_outlook_args,
)


class TestNormLabelNameOutlook(unittest.TestCase):
    """Tests for norm_label_name_outlook function."""

    def test_simple_name_unchanged(self):
        self.assertEqual(norm_label_name_outlook("Work"), "Work")

    def test_nested_label_default_join_dash(self):
        self.assertEqual(norm_label_name_outlook("Work/Projects"), "Work-Projects")

    def test_deeply_nested_label(self):
        self.assertEqual(
            norm_label_name_outlook("Work/Projects/Active"),
            "Work-Projects-Active"
        )

    def test_mode_first(self):
        self.assertEqual(
            norm_label_name_outlook("Work/Projects/Active", mode="first"),
            "Work"
        )

    def test_mode_join_colon(self):
        self.assertEqual(
            norm_label_name_outlook("Work/Projects", mode="join-colon"),
            "Work:Projects"
        )

    def test_mode_join_dash_explicit(self):
        self.assertEqual(
            norm_label_name_outlook("A/B/C", mode="join-dash"),
            "A-B-C"
        )

    def test_empty_string(self):
        self.assertEqual(norm_label_name_outlook(""), "")

    def test_none_input(self):
        # None is coerced to "" by the function
        self.assertEqual(norm_label_name_outlook(None), "")

    def test_no_slash(self):
        self.assertEqual(norm_label_name_outlook("SinglePart"), "SinglePart")

    def test_trailing_slash(self):
        # "Work/" splits to ["Work", ""]
        self.assertEqual(norm_label_name_outlook("Work/"), "Work-")

    def test_leading_slash(self):
        # "/Work" splits to ["", "Work"]
        self.assertEqual(norm_label_name_outlook("/Work"), "-Work")


class TestOutlookColorNames(unittest.TestCase):
    """Tests for OUTLOOK_COLOR_NAMES constant."""

    def test_contains_preset_colors(self):
        self.assertIn("preset0", OUTLOOK_COLOR_NAMES)
        self.assertIn("preset7", OUTLOOK_COLOR_NAMES)

    def test_is_set(self):
        self.assertIsInstance(OUTLOOK_COLOR_NAMES, set)

    def test_has_eight_presets(self):
        self.assertEqual(len(OUTLOOK_COLOR_NAMES), 8)


class TestNormLabelColorOutlook(unittest.TestCase):
    """Tests for norm_label_color_outlook function."""

    def test_valid_color_dict(self):
        color = {"name": "preset0", "extra": "ignored"}
        result = norm_label_color_outlook(color)
        self.assertEqual(result, {"name": "preset0"})

    def test_color_with_only_name(self):
        color = {"name": "blue"}
        result = norm_label_color_outlook(color)
        self.assertEqual(result, {"name": "blue"})

    def test_none_input(self):
        self.assertIsNone(norm_label_color_outlook(None))

    def test_string_input(self):
        self.assertIsNone(norm_label_color_outlook("blue"))

    def test_empty_dict(self):
        self.assertIsNone(norm_label_color_outlook({}))

    def test_dict_without_name(self):
        self.assertIsNone(norm_label_color_outlook({"color": "blue"}))

    def test_dict_with_none_name(self):
        self.assertIsNone(norm_label_color_outlook({"name": None}))

    def test_dict_with_empty_name(self):
        # Empty string is falsy
        self.assertIsNone(norm_label_color_outlook({"name": ""}))

    def test_dict_with_int_name(self):
        # Non-string name
        self.assertIsNone(norm_label_color_outlook({"name": 123}))

    def test_list_input(self):
        self.assertIsNone(norm_label_color_outlook(["blue"]))


class TestResolveOutlookArgs(unittest.TestCase):
    """Tests for resolve_outlook_args function."""

    def test_returns_tuple_of_four(self):
        args = Mock()
        args.profile = None
        args.client_id = None
        args.tenant = None
        args.token = None
        args.cache_dir = None
        args.cache = None
        args.accounts_config = None
        args.account = None

        with patch("mail.outlook.helpers.resolve_outlook_credentials") as mock_resolve:
            mock_resolve.return_value = (None, None, None)
            result = resolve_outlook_args(args)

        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 4)

    def test_uses_profile_credentials(self):
        args = Mock()
        args.profile = "work"
        args.client_id = None
        args.tenant = None
        args.token = None
        args.cache_dir = None
        args.cache = None
        args.accounts_config = None
        args.account = None

        with patch("mail.outlook.helpers.resolve_outlook_credentials") as mock_resolve:
            mock_resolve.return_value = ("client-123", "tenant-abc", "/path/token.json")
            client_id, tenant, token_path, cache_dir = resolve_outlook_args(args)

        self.assertEqual(client_id, "client-123")
        self.assertEqual(tenant, "tenant-abc")
        self.assertEqual(token_path, "/path/token.json")

    def test_uses_cache_dir_from_args(self):
        args = Mock()
        args.profile = None
        args.client_id = "client-123"
        args.tenant = "common"
        args.token = None
        args.cache_dir = "/custom/cache"
        args.cache = None
        args.accounts_config = None
        args.account = None

        with patch("mail.outlook.helpers.resolve_outlook_credentials") as mock_resolve:
            mock_resolve.return_value = ("client-123", "common", None)
            _, _, _, cache_dir = resolve_outlook_args(args)

        self.assertEqual(cache_dir, "/custom/cache")

    def test_uses_cache_from_args(self):
        args = Mock()
        args.profile = None
        args.client_id = "client-123"
        args.tenant = "common"
        args.token = None
        args.cache_dir = None
        args.cache = "/alt/cache"
        args.accounts_config = None
        args.account = None

        with patch("mail.outlook.helpers.resolve_outlook_credentials") as mock_resolve:
            mock_resolve.return_value = ("client-123", "common", None)
            _, _, _, cache_dir = resolve_outlook_args(args)

        self.assertEqual(cache_dir, "/alt/cache")

    def test_missing_attribute_handled(self):
        # Args object without some attributes
        args = Mock(spec=["profile"])
        args.profile = None

        with patch("mail.outlook.helpers.resolve_outlook_credentials") as mock_resolve:
            mock_resolve.return_value = (None, None, None)
            # Should not raise AttributeError
            result = resolve_outlook_args(args)

        self.assertEqual(len(result), 4)


class TestResolveOutlookArgsFromConfig(unittest.TestCase):
    """Tests for resolve_outlook_args with accounts config."""

    def test_loads_from_accounts_config(self):
        import tempfile
        import os

        # Create a temp config file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("""
accounts:
  - name: personal
    provider: outlook
    client_id: cfg-client-123
    tenant: consumers
    token: /path/to/token.json
    cache: /path/to/cache
""")
            config_path = f.name

        try:
            args = Mock()
            args.profile = None
            args.client_id = None
            args.tenant = None
            args.token = None
            args.cache_dir = None
            args.cache = None
            args.accounts_config = config_path
            args.account = None

            with patch("mail.outlook.helpers.resolve_outlook_credentials") as mock_resolve:
                mock_resolve.return_value = (None, None, None)
                client_id, tenant, token_path, cache_dir = resolve_outlook_args(args)

            self.assertEqual(client_id, "cfg-client-123")
            self.assertEqual(tenant, "consumers")
            self.assertEqual(cache_dir, "/path/to/cache")
        finally:
            os.unlink(config_path)

    def test_selects_named_account(self):
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("""
accounts:
  - name: work
    provider: outlook
    client_id: work-client
    tenant: org-tenant
  - name: personal
    provider: outlook
    client_id: personal-client
    tenant: consumers
""")
            config_path = f.name

        try:
            args = Mock()
            args.profile = None
            args.client_id = None
            args.tenant = None
            args.token = None
            args.cache_dir = None
            args.cache = None
            args.accounts_config = config_path
            args.account = "personal"

            with patch("mail.outlook.helpers.resolve_outlook_credentials") as mock_resolve:
                mock_resolve.return_value = (None, None, None)
                client_id, tenant, _, _ = resolve_outlook_args(args)

            self.assertEqual(client_id, "personal-client")
            self.assertEqual(tenant, "consumers")
        finally:
            os.unlink(config_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
