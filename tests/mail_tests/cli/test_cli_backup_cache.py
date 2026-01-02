"""Tests for mail/cli/backup_cache.py registration helpers."""

from __future__ import annotations

from tests.fixtures import test_path
import argparse
import unittest


class TestBackupCacheCliRegister(unittest.TestCase):
    """Test the backup and cache CLI registration helpers."""

    def _make_mock_func(self, name):
        """Create a mock function for testing."""
        def mock_func(args):
            return name
        return mock_func

    def test_register_backup_creates_parser(self):
        from mail.cli.backup_cache import register_backup

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        register_backup(
            subparsers,
            f_backup=self._make_mock_func("backup"),
        )

        # Parse backup command
        args = parser.parse_args(["backup"])
        self.assertEqual(args.command, "backup")

    def test_register_backup_has_credentials_arg(self):
        from mail.cli.backup_cache import register_backup

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        register_backup(
            subparsers,
            f_backup=self._make_mock_func("backup"),
        )

        args = parser.parse_args(["backup", "--credentials", "/path/to/creds.json"])
        self.assertEqual(args.credentials, "/path/to/creds.json")

    def test_register_backup_has_token_arg(self):
        from mail.cli.backup_cache import register_backup

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        register_backup(
            subparsers,
            f_backup=self._make_mock_func("backup"),
        )

        args = parser.parse_args(["backup", "--token", "/path/to/token.json"])
        self.assertEqual(args.token, "/path/to/token.json")

    def test_register_backup_has_out_dir_arg(self):
        from mail.cli.backup_cache import register_backup

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        register_backup(
            subparsers,
            f_backup=self._make_mock_func("backup"),
        )

        args = parser.parse_args(["backup", "--out-dir", "/custom/backup/dir"])
        self.assertEqual(args.out_dir, "/custom/backup/dir")

    def test_register_cache_creates_parser(self):
        from mail.cli.backup_cache import register_cache

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        register_cache(
            subparsers,
            f_stats=self._make_mock_func("stats"),
            f_clear=self._make_mock_func("clear"),
            f_prune=self._make_mock_func("prune"),
        )

        # Parse cache command with required --cache arg
        args = parser.parse_args(["cache", "--cache", test_path("cache")])  # nosec B108 - test fixture path
        self.assertEqual(args.command, "cache")
        self.assertEqual(args.cache, test_path("cache"))  # nosec B108 - test fixture path

    def test_register_cache_stats_subcommand(self):
        from mail.cli.backup_cache import register_cache

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        register_cache(
            subparsers,
            f_stats=self._make_mock_func("stats"),
            f_clear=self._make_mock_func("clear"),
            f_prune=self._make_mock_func("prune"),
        )

        args = parser.parse_args(["cache", "--cache", test_path("cache"), "stats"])  # nosec B108 - test fixture path
        self.assertEqual(args.cache_cmd, "stats")
        self.assertTrue(hasattr(args, "func"))

    def test_register_cache_clear_subcommand(self):
        from mail.cli.backup_cache import register_cache

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        register_cache(
            subparsers,
            f_stats=self._make_mock_func("stats"),
            f_clear=self._make_mock_func("clear"),
            f_prune=self._make_mock_func("prune"),
        )

        args = parser.parse_args(["cache", "--cache", test_path("cache"), "clear"])  # nosec B108 - test fixture path
        self.assertEqual(args.cache_cmd, "clear")
        self.assertTrue(hasattr(args, "func"))

    def test_register_cache_prune_subcommand(self):
        from mail.cli.backup_cache import register_cache

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        register_cache(
            subparsers,
            f_stats=self._make_mock_func("stats"),
            f_clear=self._make_mock_func("clear"),
            f_prune=self._make_mock_func("prune"),
        )

        args = parser.parse_args(["cache", "--cache", test_path("cache"), "prune", "--days", "30"])  # nosec B108 - test fixture path
        self.assertEqual(args.cache_cmd, "prune")
        self.assertEqual(args.days, 30)
        self.assertTrue(hasattr(args, "func"))

    def test_register_cache_requires_cache_arg(self):
        from mail.cli.backup_cache import register_cache

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        register_cache(
            subparsers,
            f_stats=self._make_mock_func("stats"),
            f_clear=self._make_mock_func("clear"),
            f_prune=self._make_mock_func("prune"),
        )

        # --cache is required
        with self.assertRaises(SystemExit):
            parser.parse_args(["cache", "stats"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
