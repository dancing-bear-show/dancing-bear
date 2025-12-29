"""Tests for mail/cli/filters.py CLI registration."""

from __future__ import annotations

import argparse
import unittest

from mail.cli.filters import register


def _noop(*args, **kwargs):
    """No-op handler for testing."""
    pass


def _make_parser_with_filters():
    """Create an argparse parser with filters subcommand registered."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    register(
        subparsers,
        f_list=_noop,
        f_export=_noop,
        f_sync=_noop,
        f_plan=_noop,
        f_impact=_noop,
        f_sweep=_noop,
        f_sweep_range=_noop,
        f_delete=_noop,
        f_prune_empty=_noop,
        f_add_forward_by_label=_noop,
        f_add_from_token=_noop,
        f_rm_from_token=_noop,
    )
    return parser


class TestFiltersRegister(unittest.TestCase):
    """Tests for the filters CLI registration."""

    def setUp(self):
        self.parser = _make_parser_with_filters()

    def test_filters_group_registered(self):
        """Test that filters group is registered."""
        args = self.parser.parse_args(["filters"])
        self.assertEqual(args.command, "filters")

    def test_filters_has_common_args(self):
        """Test that filters group has common Gmail args."""
        args = self.parser.parse_args([
            "filters", "--credentials", "/creds.json", "--token", "/tok.json", "--cache", "/cache"
        ])
        self.assertEqual(args.credentials, "/creds.json")
        self.assertEqual(args.token, "/tok.json")
        self.assertEqual(args.cache, "/cache")


class TestFiltersListSubcommand(unittest.TestCase):
    """Tests for filters list subcommand."""

    def setUp(self):
        self.parser = _make_parser_with_filters()

    def test_list_subcommand(self):
        """Test list subcommand is registered."""
        args = self.parser.parse_args(["filters", "list"])
        self.assertEqual(args.filters_cmd, "list")
        self.assertEqual(args.func, _noop)


class TestFiltersExportSubcommand(unittest.TestCase):
    """Tests for filters export subcommand."""

    def setUp(self):
        self.parser = _make_parser_with_filters()

    def test_export_subcommand(self):
        """Test export subcommand with required --out arg."""
        args = self.parser.parse_args(["filters", "export", "--out", "/out.yaml"])
        self.assertEqual(args.filters_cmd, "export")
        self.assertEqual(args.out, "/out.yaml")

    def test_export_requires_out(self):
        """Test export requires --out argument."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["filters", "export"])


class TestFiltersSyncSubcommand(unittest.TestCase):
    """Tests for filters sync subcommand."""

    def setUp(self):
        self.parser = _make_parser_with_filters()

    def test_sync_subcommand(self):
        """Test sync subcommand with required --config arg."""
        args = self.parser.parse_args(["filters", "sync", "--config", "/cfg.yaml"])
        self.assertEqual(args.filters_cmd, "sync")
        self.assertEqual(args.config, "/cfg.yaml")

    def test_sync_dry_run_flag(self):
        """Test sync --dry-run flag."""
        args = self.parser.parse_args(["filters", "sync", "--config", "/c.yaml", "--dry-run"])
        self.assertTrue(args.dry_run)

    def test_sync_delete_missing_flag(self):
        """Test sync --delete-missing flag."""
        args = self.parser.parse_args(["filters", "sync", "--config", "/c.yaml", "--delete-missing"])
        self.assertTrue(args.delete_missing)

    def test_sync_require_forward_verified_flag(self):
        """Test sync --require-forward-verified flag."""
        args = self.parser.parse_args([
            "filters", "sync", "--config", "/c.yaml", "--require-forward-verified"
        ])
        self.assertTrue(args.require_forward_verified)


class TestFiltersPlanSubcommand(unittest.TestCase):
    """Tests for filters plan subcommand."""

    def setUp(self):
        self.parser = _make_parser_with_filters()

    def test_plan_subcommand(self):
        """Test plan subcommand with required --config arg."""
        args = self.parser.parse_args(["filters", "plan", "--config", "/cfg.yaml"])
        self.assertEqual(args.filters_cmd, "plan")
        self.assertEqual(args.config, "/cfg.yaml")

    def test_plan_delete_missing_flag(self):
        """Test plan --delete-missing flag."""
        args = self.parser.parse_args(["filters", "plan", "--config", "/c.yaml", "--delete-missing"])
        self.assertTrue(args.delete_missing)


class TestFiltersImpactSubcommand(unittest.TestCase):
    """Tests for filters impact subcommand."""

    def setUp(self):
        self.parser = _make_parser_with_filters()

    def test_impact_subcommand(self):
        """Test impact subcommand with required --config arg."""
        args = self.parser.parse_args(["filters", "impact", "--config", "/cfg.yaml"])
        self.assertEqual(args.filters_cmd, "impact")
        self.assertEqual(args.config, "/cfg.yaml")

    def test_impact_optional_args(self):
        """Test impact optional arguments."""
        args = self.parser.parse_args([
            "filters", "impact", "--config", "/c.yaml",
            "--days", "30", "--only-inbox", "--pages", "10"
        ])
        self.assertEqual(args.days, 30)
        self.assertTrue(args.only_inbox)
        self.assertEqual(args.pages, 10)

    def test_impact_pages_default(self):
        """Test impact --pages default value."""
        args = self.parser.parse_args(["filters", "impact", "--config", "/c.yaml"])
        self.assertEqual(args.pages, 5)


class TestFiltersSweepSubcommand(unittest.TestCase):
    """Tests for filters sweep subcommand."""

    def setUp(self):
        self.parser = _make_parser_with_filters()

    def test_sweep_subcommand(self):
        """Test sweep subcommand with required --config arg."""
        args = self.parser.parse_args(["filters", "sweep", "--config", "/cfg.yaml"])
        self.assertEqual(args.filters_cmd, "sweep")
        self.assertEqual(args.config, "/cfg.yaml")

    def test_sweep_all_options(self):
        """Test sweep with all optional arguments."""
        args = self.parser.parse_args([
            "filters", "sweep", "--config", "/c.yaml",
            "--days", "7", "--only-inbox", "--pages", "100",
            "--batch-size", "1000", "--max-msgs", "5000", "--dry-run"
        ])
        self.assertEqual(args.days, 7)
        self.assertTrue(args.only_inbox)
        self.assertEqual(args.pages, 100)
        self.assertEqual(args.batch_size, 1000)
        self.assertEqual(args.max_msgs, 5000)
        self.assertTrue(args.dry_run)

    def test_sweep_defaults(self):
        """Test sweep default values."""
        args = self.parser.parse_args(["filters", "sweep", "--config", "/c.yaml"])
        self.assertEqual(args.pages, 50)
        self.assertEqual(args.batch_size, 500)


class TestFiltersSweepRangeSubcommand(unittest.TestCase):
    """Tests for filters sweep-range subcommand."""

    def setUp(self):
        self.parser = _make_parser_with_filters()

    def test_sweep_range_subcommand(self):
        """Test sweep-range subcommand with required args."""
        args = self.parser.parse_args([
            "filters", "sweep-range", "--config", "/cfg.yaml", "--to-days", "365"
        ])
        self.assertEqual(args.filters_cmd, "sweep-range")
        self.assertEqual(args.config, "/cfg.yaml")
        self.assertEqual(args.to_days, 365)

    def test_sweep_range_requires_to_days(self):
        """Test sweep-range requires --to-days argument."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["filters", "sweep-range", "--config", "/c.yaml"])

    def test_sweep_range_all_options(self):
        """Test sweep-range with all optional arguments."""
        args = self.parser.parse_args([
            "filters", "sweep-range", "--config", "/c.yaml", "--to-days", "3650",
            "--from-days", "30", "--step-days", "180",
            "--pages", "200", "--batch-size", "1000", "--max-msgs", "10000", "--dry-run"
        ])
        self.assertEqual(args.from_days, 30)
        self.assertEqual(args.to_days, 3650)
        self.assertEqual(args.step_days, 180)
        self.assertEqual(args.pages, 200)
        self.assertEqual(args.batch_size, 1000)
        self.assertEqual(args.max_msgs, 10000)
        self.assertTrue(args.dry_run)

    def test_sweep_range_defaults(self):
        """Test sweep-range default values."""
        args = self.parser.parse_args([
            "filters", "sweep-range", "--config", "/c.yaml", "--to-days", "365"
        ])
        self.assertEqual(args.from_days, 0)
        self.assertEqual(args.step_days, 90)
        self.assertEqual(args.pages, 100)
        self.assertEqual(args.batch_size, 500)


class TestFiltersDeleteSubcommand(unittest.TestCase):
    """Tests for filters delete subcommand."""

    def setUp(self):
        self.parser = _make_parser_with_filters()

    def test_delete_subcommand(self):
        """Test delete subcommand with required --id arg."""
        args = self.parser.parse_args(["filters", "delete", "--id", "F123"])
        self.assertEqual(args.filters_cmd, "delete")
        self.assertEqual(args.id, "F123")

    def test_delete_requires_id(self):
        """Test delete requires --id argument."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["filters", "delete"])


class TestFiltersPruneEmptySubcommand(unittest.TestCase):
    """Tests for filters prune-empty subcommand."""

    def setUp(self):
        self.parser = _make_parser_with_filters()

    def test_prune_empty_subcommand(self):
        """Test prune-empty subcommand."""
        args = self.parser.parse_args(["filters", "prune-empty"])
        self.assertEqual(args.filters_cmd, "prune-empty")

    def test_prune_empty_all_options(self):
        """Test prune-empty with all optional arguments."""
        args = self.parser.parse_args([
            "filters", "prune-empty",
            "--days", "14", "--only-inbox", "--pages", "5", "--dry-run"
        ])
        self.assertEqual(args.days, 14)
        self.assertTrue(args.only_inbox)
        self.assertEqual(args.pages, 5)
        self.assertTrue(args.dry_run)

    def test_prune_empty_defaults(self):
        """Test prune-empty default values."""
        args = self.parser.parse_args(["filters", "prune-empty"])
        self.assertEqual(args.days, 7)
        self.assertEqual(args.pages, 2)


class TestFiltersAddForwardByLabelSubcommand(unittest.TestCase):
    """Tests for filters add-forward-by-label subcommand."""

    def setUp(self):
        self.parser = _make_parser_with_filters()

    def test_add_forward_by_label_subcommand(self):
        """Test add-forward-by-label subcommand with required args."""
        args = self.parser.parse_args([
            "filters", "add-forward-by-label",
            "--label-prefix", "Kids", "--email", "fwd@example.com"
        ])
        self.assertEqual(args.filters_cmd, "add-forward-by-label")
        self.assertEqual(args.label_prefix, "Kids")
        self.assertEqual(args.email, "fwd@example.com")

    def test_add_forward_by_label_requires_label_prefix(self):
        """Test add-forward-by-label requires --label-prefix."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args([
                "filters", "add-forward-by-label", "--email", "fwd@example.com"
            ])

    def test_add_forward_by_label_requires_email(self):
        """Test add-forward-by-label requires --email."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args([
                "filters", "add-forward-by-label", "--label-prefix", "Kids"
            ])

    def test_add_forward_by_label_optional_flags(self):
        """Test add-forward-by-label optional flags."""
        args = self.parser.parse_args([
            "filters", "add-forward-by-label",
            "--label-prefix", "Kids", "--email", "fwd@example.com",
            "--dry-run", "--require-forward-verified"
        ])
        self.assertTrue(args.dry_run)
        self.assertTrue(args.require_forward_verified)


class TestFiltersAddFromTokenSubcommand(unittest.TestCase):
    """Tests for filters add-from-token subcommand."""

    def setUp(self):
        self.parser = _make_parser_with_filters()

    def test_add_from_token_subcommand(self):
        """Test add-from-token subcommand with required args."""
        args = self.parser.parse_args([
            "filters", "add-from-token",
            "--label-prefix", "Kids", "--needle", "school",
            "--add", "teacher@school.edu"
        ])
        self.assertEqual(args.filters_cmd, "add-from-token")
        self.assertEqual(args.label_prefix, "Kids")
        self.assertEqual(args.needle, "school")
        self.assertEqual(args.add, ["teacher@school.edu"])

    def test_add_from_token_multiple_add(self):
        """Test add-from-token with multiple --add values."""
        args = self.parser.parse_args([
            "filters", "add-from-token",
            "--label-prefix", "Kids", "--needle", "school",
            "--add", "a@b.com", "--add", "c@d.com"
        ])
        self.assertEqual(args.add, ["a@b.com", "c@d.com"])

    def test_add_from_token_dry_run(self):
        """Test add-from-token --dry-run flag."""
        args = self.parser.parse_args([
            "filters", "add-from-token",
            "--label-prefix", "Kids", "--needle", "school",
            "--add", "a@b.com", "--dry-run"
        ])
        self.assertTrue(args.dry_run)


class TestFiltersRmFromTokenSubcommand(unittest.TestCase):
    """Tests for filters rm-from-token subcommand."""

    def setUp(self):
        self.parser = _make_parser_with_filters()

    def test_rm_from_token_subcommand(self):
        """Test rm-from-token subcommand with required args."""
        args = self.parser.parse_args([
            "filters", "rm-from-token",
            "--label-prefix", "Kids", "--needle", "school",
            "--remove", "old@school.edu"
        ])
        self.assertEqual(args.filters_cmd, "rm-from-token")
        self.assertEqual(args.label_prefix, "Kids")
        self.assertEqual(args.needle, "school")
        self.assertEqual(args.remove, ["old@school.edu"])

    def test_rm_from_token_multiple_remove(self):
        """Test rm-from-token with multiple --remove values."""
        args = self.parser.parse_args([
            "filters", "rm-from-token",
            "--label-prefix", "Kids", "--needle", "school",
            "--remove", "a@b.com", "--remove", "c@d.com"
        ])
        self.assertEqual(args.remove, ["a@b.com", "c@d.com"])

    def test_rm_from_token_dry_run(self):
        """Test rm-from-token --dry-run flag."""
        args = self.parser.parse_args([
            "filters", "rm-from-token",
            "--label-prefix", "Kids", "--needle", "school",
            "--remove", "a@b.com", "--dry-run"
        ])
        self.assertTrue(args.dry_run)


if __name__ == "__main__":
    unittest.main()
