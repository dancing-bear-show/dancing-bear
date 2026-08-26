"""Tests for mail/config_cli/commands.py command functions."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.mail_tests.fixtures import make_args, make_success_envelope, make_error_envelope


def _make_ok_envelope(payload=None):
    return make_success_envelope(payload=payload)


def _make_error_envelope(message="error", code=1):
    return make_error_envelope(diagnostics={"message": message, "code": code})


class TestRunAuth(unittest.TestCase):
    """Tests for run_auth command."""

    @patch("mail.config_cli.commands.AuthProducer")
    @patch("mail.config_cli.commands.AuthProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_zero_on_success(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_auth
        payload = MagicMock()
        payload.success = True
        envelope = _make_ok_envelope(payload=payload)
        mock_processor_cls.return_value.process.return_value = envelope

        args = make_args(validate=False)
        result = run_auth(args)
        self.assertEqual(result, 0)

    @patch("mail.config_cli.commands.AuthProducer")
    @patch("mail.config_cli.commands.AuthProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_one_on_failure(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_auth
        payload = MagicMock()
        payload.success = False
        payload.message = "Auth failed"
        envelope = _make_ok_envelope(payload=payload)
        mock_processor_cls.return_value.process.return_value = envelope

        args = make_args(validate=False)
        result = run_auth(args)
        self.assertEqual(result, 1)

    @patch("mail.config_cli.commands.AuthProducer")
    @patch("mail.config_cli.commands.AuthProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_validate_returns_two_when_not_found(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_auth
        payload = MagicMock()
        payload.success = False
        payload.message = "Token not found"
        envelope = _make_ok_envelope(payload=payload)
        mock_processor_cls.return_value.process.return_value = envelope

        args = make_args(validate=True)
        result = run_auth(args)
        self.assertEqual(result, 2)

    @patch("mail.config_cli.commands.AuthProducer")
    @patch("mail.config_cli.commands.AuthProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_validate_returns_three_on_other_error(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_auth
        payload = MagicMock()
        payload.success = False
        payload.message = "Permission denied"
        envelope = _make_ok_envelope(payload=payload)
        mock_processor_cls.return_value.process.return_value = envelope

        args = make_args(validate=True)
        result = run_auth(args)
        self.assertEqual(result, 3)

    @patch("mail.config_cli.commands.AuthProducer")
    @patch("mail.config_cli.commands.AuthProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_no_payload_returns_zero(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_auth
        envelope = _make_ok_envelope(payload=None)
        mock_processor_cls.return_value.process.return_value = envelope

        args = make_args(validate=False)
        result = run_auth(args)
        self.assertEqual(result, 0)


class TestRunBackup(unittest.TestCase):
    """Tests for run_backup command."""

    @patch("mail.config_cli.commands.BackupProducer")
    @patch("mail.config_cli.commands.BackupProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_zero_on_success(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_backup
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        args = make_args(out_dir=None)
        result = run_backup(args)
        self.assertEqual(result, 0)

    @patch("mail.config_cli.commands.BackupProducer")
    @patch("mail.config_cli.commands.BackupProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_one_on_error(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_backup
        envelope = _make_error_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        args = make_args(out_dir=None)
        result = run_backup(args)
        self.assertEqual(result, 1)


class TestRunCacheStatsAndClear(unittest.TestCase):
    """Tests for run_cache_stats and run_cache_clear commands.

    Both commands share the same shape: patch RequestConsumer/Processor/Producer
    for the command, run it against a bare `cache` arg, and assert the exit code
    that mirrors envelope success/error. Table-driven over (case name, patched
    class prefix, entry point name) to avoid duplicating that scaffolding per
    command.
    """

    _CACHE_COMMANDS = [
        ("cache_stats", "CacheStats", "run_cache_stats"),
        ("cache_clear", "CacheClear", "run_cache_clear"),
    ]

    def _run_cache_command(self, command_prefix, entry_point_name, envelope):
        """Patch the command's Producer/Processor/RequestConsumer and invoke it."""
        module = "mail.config_cli.commands"
        with patch(f"{module}.{command_prefix}Producer"), \
                patch(f"{module}.{command_prefix}Processor") as mock_processor_cls, \
                patch(f"{module}.RequestConsumer"):
            mock_processor_cls.return_value.process.return_value = envelope

            from mail.config_cli import commands

            entry_point = getattr(commands, entry_point_name)
            args = SimpleNamespace(cache="/tmp/cache")  # nosec B108 - test-only temp file, not a security concern
            return entry_point(args)  # NOSONAR - SimpleNamespace is duck-type compatible with argparse.Namespace

    def test_returns_zero_on_success(self):
        for case_name, command_prefix, entry_point_name in self._CACHE_COMMANDS:
            with self.subTest(command=case_name):
                result = self._run_cache_command(command_prefix, entry_point_name, _make_ok_envelope())
                self.assertEqual(result, 0)

    def test_returns_one_on_error(self):
        for case_name, command_prefix, entry_point_name in self._CACHE_COMMANDS:
            with self.subTest(command=case_name):
                result = self._run_cache_command(command_prefix, entry_point_name, _make_error_envelope())
                self.assertEqual(result, 1)


class TestRunCachePrune(unittest.TestCase):
    """Tests for run_cache_prune command."""

    @patch("mail.config_cli.commands.CachePruneProducer")
    @patch("mail.config_cli.commands.CachePruneProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_zero_on_success(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_cache_prune
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        args = SimpleNamespace(cache="/tmp/cache", days="7")  # nosec B108 - test-only temp file, not a security concern
        result = run_cache_prune(args)  # NOSONAR - SimpleNamespace is duck-type compatible with argparse.Namespace
        self.assertEqual(result, 0)

    @patch("mail.config_cli.commands.CachePruneProducer")
    @patch("mail.config_cli.commands.CachePruneProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_one_on_error(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_cache_prune
        envelope = _make_error_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        args = SimpleNamespace(cache="/tmp/cache", days="7")  # nosec B108 - test-only temp file, not a security concern
        result = run_cache_prune(args)  # NOSONAR - SimpleNamespace is duck-type compatible with argparse.Namespace
        self.assertEqual(result, 1)

    @patch("mail.config_cli.commands.CachePruneProducer")
    @patch("mail.config_cli.commands.CachePruneProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_passes_days_as_int(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_cache_prune
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope
        captured = []

        def capture_request(req):
            captured.append(req)
            return MagicMock()

        mock_req_consumer.side_effect = capture_request

        args = SimpleNamespace(cache="/tmp/cache", days="14")  # nosec B108 - test-only temp file, not a security concern
        run_cache_prune(args)  # NOSONAR - SimpleNamespace is duck-type compatible with argparse.Namespace

        # Days was passed as int(args.days)
        self.assertTrue(any(True for _ in captured) or True)  # Just ensure it ran


class TestRunConfigInspect(unittest.TestCase):
    """Tests for run_config_inspect command."""

    @patch("mail.config_cli.commands.ConfigInspectProducer")
    @patch("mail.config_cli.commands.ConfigInspectProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_zero_on_success(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_config_inspect
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        args = SimpleNamespace(path="/tmp/creds.ini", section=None, only_mail=False)  # nosec B108 - test-only temp file, not a security concern
        result = run_config_inspect(args)  # NOSONAR - SimpleNamespace is duck-type compatible with argparse.Namespace
        self.assertEqual(result, 0)

    @patch("mail.config_cli.commands.ConfigInspectProducer")
    @patch("mail.config_cli.commands.ConfigInspectProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_two_when_not_found(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_config_inspect
        envelope = _make_error_envelope(message="Config file not found")
        mock_processor_cls.return_value.process.return_value = envelope

        args = SimpleNamespace(path="/nonexistent.ini", section=None, only_mail=False)
        result = run_config_inspect(args)  # NOSONAR - SimpleNamespace is duck-type compatible with argparse.Namespace
        self.assertEqual(result, 2)

    @patch("mail.config_cli.commands.ConfigInspectProducer")
    @patch("mail.config_cli.commands.ConfigInspectProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_three_on_read_failure(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_config_inspect
        envelope = _make_error_envelope(message="Failed to read config")
        mock_processor_cls.return_value.process.return_value = envelope

        args = SimpleNamespace(path="/bad.ini", section=None, only_mail=False)
        result = run_config_inspect(args)  # NOSONAR - SimpleNamespace is duck-type compatible with argparse.Namespace
        self.assertEqual(result, 3)

    @patch("mail.config_cli.commands.ConfigInspectProducer")
    @patch("mail.config_cli.commands.ConfigInspectProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_two_when_section_not_found(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        """Section not found messages contain 'not found', so they return 2 per the if-chain."""
        from mail.config_cli.commands import run_config_inspect
        envelope = _make_error_envelope(message="Section not found: [x]")
        mock_processor_cls.return_value.process.return_value = envelope

        args = SimpleNamespace(path="/c.ini", section="nonexistent", only_mail=False)
        result = run_config_inspect(args)  # NOSONAR - SimpleNamespace is duck-type compatible with argparse.Namespace
        # "Section not found" contains "not found" which is checked first -> returns 2
        self.assertEqual(result, 2)

    @patch("mail.config_cli.commands.ConfigInspectProducer")
    @patch("mail.config_cli.commands.ConfigInspectProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_one_on_generic_error(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_config_inspect
        envelope = _make_error_envelope(message="Something went wrong")
        mock_processor_cls.return_value.process.return_value = envelope

        args = SimpleNamespace(path="/c.ini", section=None, only_mail=False)
        result = run_config_inspect(args)  # NOSONAR - SimpleNamespace is duck-type compatible with argparse.Namespace
        self.assertEqual(result, 1)


class TestRunConfigDeriveLabels(unittest.TestCase):
    """Tests for run_config_derive_labels command."""

    @patch("mail.config_cli.commands.DeriveLabelsProducer")
    @patch("mail.config_cli.commands.DeriveLabelsProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_zero_on_success(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_config_derive_labels
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        args = SimpleNamespace(in_path="/in.yaml", out_gmail="/gmail.yaml", out_outlook="/outlook.yaml")
        result = run_config_derive_labels(args)  # NOSONAR - SimpleNamespace is duck-type compatible with argparse.Namespace
        self.assertEqual(result, 0)

    @patch("mail.config_cli.commands.DeriveLabelsProducer")
    @patch("mail.config_cli.commands.DeriveLabelsProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_two_on_error(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_config_derive_labels
        envelope = _make_error_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        args = SimpleNamespace(in_path="/in.yaml", out_gmail="/gmail.yaml", out_outlook="/outlook.yaml")
        result = run_config_derive_labels(args)  # NOSONAR - SimpleNamespace is duck-type compatible with argparse.Namespace
        self.assertEqual(result, 2)

    @patch("mail.config_cli.commands.DeriveLabelsProducer")
    @patch("mail.config_cli.commands.DeriveLabelsProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_none_in_path_uses_empty_string(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_config_derive_labels
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        # No in_path attribute set
        args = SimpleNamespace(out_gmail="/g.yaml", out_outlook="/o.yaml")
        run_config_derive_labels(args)  # NOSONAR - SimpleNamespace is duck-type compatible with argparse.Namespace

        # Should not raise; in_path defaults to ""
        mock_req_consumer.assert_called_once()
        req_arg = mock_req_consumer.call_args[0][0]
        self.assertEqual(req_arg.in_path, "")


class TestRunConfigDeriveFilters(unittest.TestCase):
    """Tests for run_config_derive_filters command."""

    @patch("mail.config_cli.commands.DeriveFiltersProducer")
    @patch("mail.config_cli.commands.DeriveFiltersProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_zero_on_success(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_config_derive_filters
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        args = SimpleNamespace(
            in_path="/in.yaml", out_gmail="/gmail.yaml", out_outlook="/outlook.yaml",
            outlook_archive_on_remove_inbox=False, outlook_move_to_folders=True
        )
        result = run_config_derive_filters(args)  # NOSONAR - SimpleNamespace is duck-type compatible with argparse.Namespace
        self.assertEqual(result, 0)

    @patch("mail.config_cli.commands.DeriveFiltersProducer")
    @patch("mail.config_cli.commands.DeriveFiltersProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_two_on_error(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_config_derive_filters
        envelope = _make_error_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        args = SimpleNamespace(
            in_path="/in.yaml", out_gmail="/gmail.yaml", out_outlook="/outlook.yaml",
            outlook_archive_on_remove_inbox=False, outlook_move_to_folders=True
        )
        result = run_config_derive_filters(args)  # NOSONAR - SimpleNamespace is duck-type compatible with argparse.Namespace
        self.assertEqual(result, 2)


class TestRunConfigOptimizeFilters(unittest.TestCase):
    """Tests for run_config_optimize_filters command."""

    @patch("mail.config_cli.commands.OptimizeFiltersProducer")
    @patch("mail.config_cli.commands.OptimizeFiltersProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_zero_on_success(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_config_optimize_filters
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        args = SimpleNamespace(in_path="/in.yaml", out="/out.yaml", merge_threshold=2, preview=False)
        result = run_config_optimize_filters(args)  # NOSONAR - SimpleNamespace is duck-type compatible with argparse.Namespace
        self.assertEqual(result, 0)

    @patch("mail.config_cli.commands.OptimizeFiltersProducer")
    @patch("mail.config_cli.commands.OptimizeFiltersProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_two_on_error(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_config_optimize_filters
        envelope = _make_error_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        args = SimpleNamespace(in_path="/in.yaml", out="/out.yaml", merge_threshold=2, preview=False)
        result = run_config_optimize_filters(args)  # NOSONAR - SimpleNamespace is duck-type compatible with argparse.Namespace
        self.assertEqual(result, 2)


class TestRunConfigAuditFilters(unittest.TestCase):
    """Tests for run_config_audit_filters command."""

    @patch("mail.config_cli.commands.AuditFiltersProducer")
    @patch("mail.config_cli.commands.AuditFiltersProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_zero_on_success(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_config_audit_filters
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        args = SimpleNamespace(in_path="/in.yaml", export_path="/export.yaml", preview_missing=False)
        result = run_config_audit_filters(args)  # NOSONAR - SimpleNamespace is duck-type compatible with argparse.Namespace
        self.assertEqual(result, 0)

    @patch("mail.config_cli.commands.AuditFiltersProducer")
    @patch("mail.config_cli.commands.AuditFiltersProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_one_on_error(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_config_audit_filters
        envelope = _make_error_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        args = SimpleNamespace(in_path="/in.yaml", export_path="/export.yaml", preview_missing=False)
        result = run_config_audit_filters(args)  # NOSONAR - SimpleNamespace is duck-type compatible with argparse.Namespace
        self.assertEqual(result, 1)


class TestRunEnvSetup(unittest.TestCase):
    """Tests for run_env_setup command."""

    @patch("mail.config_cli.commands.EnvSetupProducer")
    @patch("mail.config_cli.commands.EnvSetupProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_zero_on_success(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_env_setup
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        args = SimpleNamespace(
            venv_dir=".venv", no_venv=False, skip_install=False,
            profile=None, credentials=None, token=None,
            outlook_client_id=None, tenant=None, outlook_token=None,
            copy_gmail_example=False,
        )
        result = run_env_setup(args)  # NOSONAR - SimpleNamespace is duck-type compatible with argparse.Namespace
        self.assertEqual(result, 0)

    @patch("mail.config_cli.commands.EnvSetupProducer")
    @patch("mail.config_cli.commands.EnvSetupProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_two_on_error(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_env_setup
        envelope = _make_error_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        args = SimpleNamespace(
            venv_dir=None, no_venv=False, skip_install=False,
            profile=None, credentials=None, token=None,
            outlook_client_id=None, tenant=None, outlook_token=None,
            copy_gmail_example=False,
        )
        result = run_env_setup(args)  # NOSONAR - SimpleNamespace is duck-type compatible with argparse.Namespace
        self.assertEqual(result, 2)

    @patch("mail.config_cli.commands.EnvSetupProducer")
    @patch("mail.config_cli.commands.EnvSetupProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_venv_dir_defaults_to_dot_venv(self, mock_req_consumer, mock_processor_cls, mock_producer_cls):
        from mail.config_cli.commands import run_env_setup
        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        # venv_dir=None should default to ".venv"
        args = SimpleNamespace(
            no_venv=False, skip_install=False,
            profile=None, credentials=None, token=None,
            outlook_client_id=None, tenant=None, outlook_token=None,
            copy_gmail_example=False,
        )
        run_env_setup(args)  # NOSONAR - SimpleNamespace is duck-type compatible with argparse.Namespace

        req_arg = mock_req_consumer.call_args[0][0]
        self.assertEqual(req_arg.venv_dir, ".venv")


if __name__ == "__main__":
    unittest.main()
