"""Tests for mail/cli/labels.py CLI registration."""

from __future__ import annotations

import argparse
import unittest


def make_mock_handler(name: str):
    """Create a mock handler function with a name attribute."""
    def handler(args):
        return 0
    handler.__name__ = name
    return handler


# Shared mock handlers for all label subcommands
MOCK_HANDLERS = {
    "f_list": make_mock_handler("list"),
    "f_sync": make_mock_handler("sync"),
    "f_export": make_mock_handler("export"),
    "f_plan": make_mock_handler("plan"),
    "f_doctor": make_mock_handler("doctor"),
    "f_prune_empty": make_mock_handler("prune_empty"),
    "f_learn": make_mock_handler("learn"),
    "f_apply_suggestions": make_mock_handler("apply_suggestions"),
    "f_delete": make_mock_handler("delete"),
    "f_sweep_parents": make_mock_handler("sweep_parents"),
}


class LabelsRegisterTestCase(unittest.TestCase):
    """Base test case that sets up the labels CLI parser."""

    def setUp(self):
        """Create parser and register labels subcommands."""
        from mail.cli.labels import register

        self.parser = argparse.ArgumentParser()
        self.subparsers = self.parser.add_subparsers(dest="command")
        register(self.subparsers, **MOCK_HANDLERS)


class TestLabelsRegister(LabelsRegisterTestCase):
    """Tests for the labels CLI register function."""

    def test_labels_group_registered(self):
        """Test that labels group is registered."""
        args = self.parser.parse_args(["labels"])
        self.assertEqual(args.command, "labels")

    def test_labels_default_is_list(self):
        """Test that labels without subcommand defaults to list."""
        args = self.parser.parse_args(["labels"])
        self.assertEqual(args.func.__name__, "list")

    def test_labels_common_args(self):
        """Test that labels group has common args."""
        args = self.parser.parse_args(["labels", "--credentials", "/path/creds.json"])
        self.assertEqual(args.credentials, "/path/creds.json")

        args = self.parser.parse_args(["labels", "--token", "/path/token.json"])
        self.assertEqual(args.token, "/path/token.json")

        args = self.parser.parse_args(["labels", "--cache", "/path/cache"])
        self.assertEqual(args.cache, "/path/cache")


class TestLabelsListSubcommand(LabelsRegisterTestCase):
    """Tests for labels list subcommand."""

    def test_list_registered(self):
        """Test that list subcommand is registered."""
        args = self.parser.parse_args(["labels", "list"])
        self.assertEqual(args.func.__name__, "list")
        self.assertEqual(args.labels_cmd, "list")


class TestLabelsSyncSubcommand(LabelsRegisterTestCase):
    """Tests for labels sync subcommand."""

    def test_sync_requires_config(self):
        """Test that sync requires --config."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["labels", "sync"])

    def test_sync_with_config(self):
        """Test sync with required config."""
        args = self.parser.parse_args(["labels", "sync", "--config", "labels.yaml"])
        self.assertEqual(args.func.__name__, "sync")
        self.assertEqual(args.config, "labels.yaml")

    def test_sync_dry_run_default_false(self):
        """Test sync --dry-run defaults to false."""
        args = self.parser.parse_args(["labels", "sync", "--config", "x.yaml"])
        self.assertFalse(args.dry_run)

    def test_sync_dry_run_flag(self):
        """Test sync --dry-run flag."""
        args = self.parser.parse_args(["labels", "sync", "--config", "x.yaml", "--dry-run"])
        self.assertTrue(args.dry_run)

    def test_sync_delete_missing_flag(self):
        """Test sync --delete-missing flag."""
        args = self.parser.parse_args(["labels", "sync", "--config", "x.yaml", "--delete-missing"])
        self.assertTrue(args.delete_missing)

    def test_sync_sweep_redirects_flag(self):
        """Test sync --sweep-redirects flag."""
        args = self.parser.parse_args(["labels", "sync", "--config", "x.yaml", "--sweep-redirects"])
        self.assertTrue(args.sweep_redirects)


class TestLabelsExportSubcommand(LabelsRegisterTestCase):
    """Tests for labels export subcommand."""

    def test_export_requires_out(self):
        """Test that export requires --out."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["labels", "export"])

    def test_export_with_out(self):
        """Test export with required --out."""
        args = self.parser.parse_args(["labels", "export", "--out", "labels.yaml"])
        self.assertEqual(args.func.__name__, "export")
        self.assertEqual(args.out, "labels.yaml")


class TestLabelsPlanSubcommand(LabelsRegisterTestCase):
    """Tests for labels plan subcommand."""

    def test_plan_requires_config(self):
        """Test that plan requires --config."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["labels", "plan"])

    def test_plan_with_config(self):
        """Test plan with required config."""
        args = self.parser.parse_args(["labels", "plan", "--config", "labels.yaml"])
        self.assertEqual(args.func.__name__, "plan")
        self.assertEqual(args.config, "labels.yaml")

    def test_plan_delete_missing_flag(self):
        """Test plan --delete-missing flag."""
        args = self.parser.parse_args(["labels", "plan", "--config", "x.yaml", "--delete-missing"])
        self.assertTrue(args.delete_missing)


class TestLabelsDoctorSubcommand(LabelsRegisterTestCase):
    """Tests for labels doctor subcommand."""

    def test_doctor_registered(self):
        """Test that doctor subcommand is registered."""
        args = self.parser.parse_args(["labels", "doctor"])
        self.assertEqual(args.func.__name__, "doctor")

    def test_doctor_set_visibility_flag(self):
        """Test doctor --set-visibility flag."""
        args = self.parser.parse_args(["labels", "doctor", "--set-visibility"])
        self.assertTrue(args.set_visibility)

    def test_doctor_imap_redirect_repeatable(self):
        """Test doctor --imap-redirect can be repeated."""
        args = self.parser.parse_args([
            "labels", "doctor",
            "--imap-redirect", "old1=new1",
            "--imap-redirect", "old2=new2",
        ])
        self.assertEqual(args.imap_redirect, ["old1=new1", "old2=new2"])

    def test_doctor_imap_delete_repeatable(self):
        """Test doctor --imap-delete can be repeated."""
        args = self.parser.parse_args([
            "labels", "doctor",
            "--imap-delete", "label1",
            "--imap-delete", "label2",
        ])
        self.assertEqual(args.imap_delete, ["label1", "label2"])

    def test_doctor_cache_ttl_default(self):
        """Test doctor --cache-ttl default value."""
        args = self.parser.parse_args(["labels", "doctor"])
        self.assertEqual(args.cache_ttl, 300)

    def test_doctor_cache_ttl_custom(self):
        """Test doctor --cache-ttl custom value."""
        args = self.parser.parse_args(["labels", "doctor", "--cache-ttl", "600"])
        self.assertEqual(args.cache_ttl, 600)


class TestLabelsPruneEmptySubcommand(LabelsRegisterTestCase):
    """Tests for labels prune-empty subcommand."""

    def test_prune_empty_registered(self):
        """Test that prune-empty subcommand is registered."""
        args = self.parser.parse_args(["labels", "prune-empty"])
        self.assertEqual(args.func.__name__, "prune_empty")

    def test_prune_empty_dry_run_flag(self):
        """Test prune-empty --dry-run flag."""
        args = self.parser.parse_args(["labels", "prune-empty", "--dry-run"])
        self.assertTrue(args.dry_run)

    def test_prune_empty_limit_default(self):
        """Test prune-empty --limit default value."""
        args = self.parser.parse_args(["labels", "prune-empty"])
        self.assertEqual(args.limit, 0)

    def test_prune_empty_limit_custom(self):
        """Test prune-empty --limit custom value."""
        args = self.parser.parse_args(["labels", "prune-empty", "--limit", "10"])
        self.assertEqual(args.limit, 10)

    def test_prune_empty_sleep_sec_default(self):
        """Test prune-empty --sleep-sec default value."""
        args = self.parser.parse_args(["labels", "prune-empty"])
        self.assertEqual(args.sleep_sec, 0.0)

    def test_prune_empty_sleep_sec_custom(self):
        """Test prune-empty --sleep-sec custom value."""
        args = self.parser.parse_args(["labels", "prune-empty", "--sleep-sec", "0.5"])
        self.assertEqual(args.sleep_sec, 0.5)


class TestLabelsLearnSubcommand(LabelsRegisterTestCase):
    """Tests for labels learn subcommand."""

    def test_learn_requires_out(self):
        """Test that learn requires --out."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["labels", "learn"])

    def test_learn_with_out(self):
        """Test learn with required --out."""
        args = self.parser.parse_args(["labels", "learn", "--out", "suggestions.yaml"])
        self.assertEqual(args.func.__name__, "learn")
        self.assertEqual(args.out, "suggestions.yaml")

    def test_learn_days_default(self):
        """Test learn --days default value."""
        args = self.parser.parse_args(["labels", "learn", "--out", "x.yaml"])
        self.assertEqual(args.days, 30)

    def test_learn_days_custom(self):
        """Test learn --days custom value."""
        args = self.parser.parse_args(["labels", "learn", "--out", "x.yaml", "--days", "60"])
        self.assertEqual(args.days, 60)

    def test_learn_min_count_default(self):
        """Test learn --min-count default value."""
        args = self.parser.parse_args(["labels", "learn", "--out", "x.yaml"])
        self.assertEqual(args.min_count, 5)

    def test_learn_only_inbox_flag(self):
        """Test learn --only-inbox flag."""
        args = self.parser.parse_args(["labels", "learn", "--out", "x.yaml", "--only-inbox"])
        self.assertTrue(args.only_inbox)

    def test_learn_protect_repeatable(self):
        """Test learn --protect can be repeated."""
        args = self.parser.parse_args([
            "labels", "learn", "--out", "x.yaml",
            "--protect", "ceo@company.com",
            "--protect", "important.com",
        ])
        self.assertEqual(args.protect, ["ceo@company.com", "important.com"])

    def test_learn_has_credentials_args(self):
        """Test learn has credential args for convenience."""
        args = self.parser.parse_args([
            "labels", "learn", "--out", "x.yaml",
            "--credentials", "/path/creds.json",
            "--token", "/path/token.json",
        ])
        self.assertEqual(args.credentials, "/path/creds.json")
        self.assertEqual(args.token, "/path/token.json")


class TestLabelsApplySuggestionsSubcommand(LabelsRegisterTestCase):
    """Tests for labels apply-suggestions subcommand."""

    def test_apply_suggestions_requires_config(self):
        """Test that apply-suggestions requires --config."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["labels", "apply-suggestions"])

    def test_apply_suggestions_with_config(self):
        """Test apply-suggestions with required config."""
        args = self.parser.parse_args(["labels", "apply-suggestions", "--config", "suggestions.yaml"])
        self.assertEqual(args.func.__name__, "apply_suggestions")
        self.assertEqual(args.config, "suggestions.yaml")

    def test_apply_suggestions_dry_run_flag(self):
        """Test apply-suggestions --dry-run flag."""
        args = self.parser.parse_args(["labels", "apply-suggestions", "--config", "x.yaml", "--dry-run"])
        self.assertTrue(args.dry_run)

    def test_apply_suggestions_sweep_days(self):
        """Test apply-suggestions --sweep-days option."""
        args = self.parser.parse_args(["labels", "apply-suggestions", "--config", "x.yaml", "--sweep-days", "7"])
        self.assertEqual(args.sweep_days, 7)

    def test_apply_suggestions_pages_default(self):
        """Test apply-suggestions --pages default value."""
        args = self.parser.parse_args(["labels", "apply-suggestions", "--config", "x.yaml"])
        self.assertEqual(args.pages, 50)

    def test_apply_suggestions_batch_size_default(self):
        """Test apply-suggestions --batch-size default value."""
        args = self.parser.parse_args(["labels", "apply-suggestions", "--config", "x.yaml"])
        self.assertEqual(args.batch_size, 500)


class TestLabelsDeleteSubcommand(LabelsRegisterTestCase):
    """Tests for labels delete subcommand."""

    def test_delete_requires_name(self):
        """Test that delete requires --name."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["labels", "delete"])

    def test_delete_with_name(self):
        """Test delete with required --name."""
        args = self.parser.parse_args(["labels", "delete", "--name", "Personal/Alumni"])
        self.assertEqual(args.func.__name__, "delete")
        self.assertEqual(args.name, "Personal/Alumni")

    def test_delete_has_credentials_args(self):
        """Test delete has credential args."""
        args = self.parser.parse_args([
            "labels", "delete", "--name", "Test",
            "--credentials", "/path/creds.json",
        ])
        self.assertEqual(args.credentials, "/path/creds.json")


class TestLabelsSweepParentsSubcommand(LabelsRegisterTestCase):
    """Tests for labels sweep-parents subcommand."""

    def test_sweep_parents_requires_names(self):
        """Test that sweep-parents requires --names."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["labels", "sweep-parents"])

    def test_sweep_parents_with_names(self):
        """Test sweep-parents with required --names."""
        args = self.parser.parse_args(["labels", "sweep-parents", "--names", "Kids,Lists"])
        self.assertEqual(args.func.__name__, "sweep_parents")
        self.assertEqual(args.names, "Kids,Lists")

    def test_sweep_parents_pages_default(self):
        """Test sweep-parents --pages default value."""
        args = self.parser.parse_args(["labels", "sweep-parents", "--names", "X"])
        self.assertEqual(args.pages, 50)

    def test_sweep_parents_batch_size_default(self):
        """Test sweep-parents --batch-size default value."""
        args = self.parser.parse_args(["labels", "sweep-parents", "--names", "X"])
        self.assertEqual(args.batch_size, 500)

    def test_sweep_parents_dry_run_flag(self):
        """Test sweep-parents --dry-run flag."""
        args = self.parser.parse_args(["labels", "sweep-parents", "--names", "X", "--dry-run"])
        self.assertTrue(args.dry_run)

    def test_sweep_parents_has_credentials_args(self):
        """Test sweep-parents has credential args."""
        args = self.parser.parse_args([
            "labels", "sweep-parents", "--names", "X",
            "--credentials", "/path/creds.json",
            "--token", "/path/token.json",
            "--cache", "/path/cache",
        ])
        self.assertEqual(args.credentials, "/path/creds.json")
        self.assertEqual(args.token, "/path/token.json")
        self.assertEqual(args.cache, "/path/cache")


if __name__ == "__main__":
    unittest.main()
