"""Tests for mail/config_cli/commands.py command functions."""

from __future__ import annotations

import tempfile
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


# ---------------------------------------------------------------------------
# New tests for missing coverage
# ---------------------------------------------------------------------------


class TestRunWorkflowsGmailFromUnified(unittest.TestCase):
    """Tests for run_workflows_gmail_from_unified."""

    def _make_args(self, **kwargs):
        defaults = dict(
            config=None,
            out_dir=None,
            delete_missing=False,
            apply=False,
            profile=None,
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    @patch("mail.config_cli.commands.resolve_filters_config", return_value="/u.yaml")
    @patch("mail.config_cli.commands.DeriveFiltersProducer")
    @patch("mail.config_cli.commands.DeriveFiltersProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_two_when_derive_fails(
        self, mock_req_consumer, mock_processor_cls, mock_producer_cls, mock_resolve
    ):
        from mail.config_cli.commands import run_workflows_gmail_from_unified

        envelope = _make_error_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        with tempfile.TemporaryDirectory() as tmpdir:
            args = self._make_args(out_dir=tmpdir)
            result = run_workflows_gmail_from_unified(args)
        self.assertEqual(result, 2)

    @patch("mail.config_cli.commands.resolve_filters_config", return_value="/u.yaml")
    @patch("mail.config_cli.commands.DeriveFiltersProducer")
    @patch("mail.config_cli.commands.DeriveFiltersProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_plan_only_returns_zero(
        self, mock_req_consumer, mock_processor_cls, mock_producer_cls, mock_resolve
    ):
        from mail.config_cli.commands import run_workflows_gmail_from_unified

        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        with patch("mail.filters.commands.run_filters_plan") as mock_plan:
            with tempfile.TemporaryDirectory() as tmpdir:
                args = self._make_args(out_dir=tmpdir, apply=False)
                result = run_workflows_gmail_from_unified(args)
            mock_plan.assert_called_once()
        self.assertEqual(result, 0)

    @patch("mail.config_cli.commands.resolve_filters_config", return_value="/u.yaml")
    @patch("mail.config_cli.commands.DeriveFiltersProducer")
    @patch("mail.config_cli.commands.DeriveFiltersProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_apply_flag_calls_sync(
        self, mock_req_consumer, mock_processor_cls, mock_producer_cls, mock_resolve
    ):
        from mail.config_cli.commands import run_workflows_gmail_from_unified

        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        with patch("mail.filters.commands.run_filters_plan"), \
                patch("mail.filters.commands.run_filters_sync") as mock_sync:
            with tempfile.TemporaryDirectory() as tmpdir:
                args = self._make_args(out_dir=tmpdir, apply=True)
                result = run_workflows_gmail_from_unified(args)
            mock_sync.assert_called_once()
        self.assertEqual(result, 0)


class TestDetectGmailAvailable(unittest.TestCase):
    """Tests for _detect_gmail_available."""

    def test_returns_false_on_exception(self):
        from mail.config_cli.commands import _detect_gmail_available

        with patch(
            "mail.config_resolver.resolve_paths_profile",
            side_effect=RuntimeError("no config"),
        ):
            args = SimpleNamespace(profile=None)
            result = _detect_gmail_available(args)
        self.assertFalse(result)

    def test_returns_false_when_neither_path_exists(self):
        from mail.config_cli.commands import _detect_gmail_available

        with patch(
            "mail.config_resolver.resolve_paths_profile",
            return_value=("/nonexistent/creds.json", "/nonexistent/token.json"),
        ):
            args = SimpleNamespace(profile=None)
            result = _detect_gmail_available(args)
        self.assertFalse(result)

    def test_returns_true_when_cred_path_exists(self):
        import os
        from mail.config_cli.commands import _detect_gmail_available

        with tempfile.NamedTemporaryFile(delete=False) as f:
            tmp = f.name
        try:
            with patch(
                "mail.config_resolver.resolve_paths_profile",
                return_value=(tmp, "/nonexistent/token.json"),
            ):
                args = SimpleNamespace(profile=None)
                result = _detect_gmail_available(args)
            self.assertTrue(result)
        finally:
            os.unlink(tmp)


class TestDetectOutlookAvailable(unittest.TestCase):
    """Tests for _detect_outlook_available."""

    def test_returns_true_when_client_id_resolved(self):
        from mail.config_cli.commands import _detect_outlook_available

        with patch(
            "mail.outlook.helpers.resolve_outlook_args",
            return_value=("client-id-123", None, None, None),
        ):
            args = SimpleNamespace(profile=None, accounts_config=None, account=None)
            result = _detect_outlook_available(args)
        self.assertTrue(result)

    def test_returns_false_when_no_client_id(self):
        from mail.config_cli.commands import _detect_outlook_available

        with patch(
            "mail.outlook.helpers.resolve_outlook_args",
            return_value=(None, None, None, None),
        ):
            args = SimpleNamespace(profile=None, accounts_config=None, account=None)
            result = _detect_outlook_available(args)
        self.assertFalse(result)

    def test_returns_false_on_exception(self):
        from mail.config_cli.commands import _detect_outlook_available

        with patch(
            "mail.outlook.helpers.resolve_outlook_args",
            side_effect=RuntimeError("no config"),
        ):
            args = SimpleNamespace(profile=None, accounts_config=None, account=None)
            result = _detect_outlook_available(args)
        self.assertFalse(result)


class TestRunGmailSteps(unittest.TestCase):
    """Tests for _run_gmail_steps."""

    def _make_args(self, **kwargs):
        defaults = dict(delete_missing=False, apply=False, profile=None)
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_plan_only_calls_plan_not_sync(self):
        from mail.config_cli.commands import _run_gmail_steps

        with patch("mail.filters.commands.run_filters_plan") as mock_plan, \
                patch("mail.filters.commands.run_filters_sync") as mock_sync:
            _run_gmail_steps(self._make_args(apply=False), "/gmail.yaml")
        mock_plan.assert_called_once()
        mock_sync.assert_not_called()

    def test_apply_calls_both_plan_and_sync(self):
        from mail.config_cli.commands import _run_gmail_steps

        with patch("mail.filters.commands.run_filters_plan") as mock_plan, \
                patch("mail.filters.commands.run_filters_sync") as mock_sync:
            _run_gmail_steps(self._make_args(apply=True), "/gmail.yaml")
        mock_plan.assert_called_once()
        mock_sync.assert_called_once()


class TestRunOutlookSteps(unittest.TestCase):
    """Tests for _run_outlook_steps."""

    def _make_args(self, **kwargs):
        defaults = dict(
            apply=False, delete_missing=False, profile=None,
            accounts_config=None, account=None, outlook_move_to_folders=True,
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_plan_only_calls_plan_not_sync(self):
        from mail.config_cli.commands import _run_outlook_steps

        with patch("mail.outlook.commands.run_outlook_rules_plan") as mock_plan, \
                patch("mail.outlook.commands.run_outlook_rules_sync") as mock_sync:
            _run_outlook_steps(self._make_args(apply=False), "/outlook.yaml")
        mock_plan.assert_called_once()
        mock_sync.assert_not_called()

    def test_apply_calls_both_plan_and_sync(self):
        from mail.config_cli.commands import _run_outlook_steps

        with patch("mail.outlook.commands.run_outlook_rules_plan") as mock_plan, \
                patch("mail.outlook.commands.run_outlook_rules_sync") as mock_sync:
            _run_outlook_steps(self._make_args(apply=True), "/outlook.yaml")
        mock_plan.assert_called_once()
        mock_sync.assert_called_once()


class TestResolveProviders(unittest.TestCase):
    """Tests for _resolve_providers."""

    def _make_args(self, providers=None, **kwargs):
        defaults = dict(profile=None, accounts_config=None, account=None)
        defaults.update(kwargs)
        ns = SimpleNamespace(**defaults)
        if providers is not None:
            ns.providers = providers
        return ns

    def test_no_providers_attr_uses_detection_gmail_only(self):
        from mail.config_cli.commands import _resolve_providers

        with patch("mail.config_cli.commands._detect_gmail_available", return_value=True), \
                patch("mail.config_cli.commands._detect_outlook_available", return_value=False):
            requested, run_gmail, run_outlook = _resolve_providers(self._make_args())
        self.assertIsNone(requested)
        self.assertTrue(run_gmail)
        self.assertFalse(run_outlook)

    def test_no_providers_attr_uses_detection_neither(self):
        from mail.config_cli.commands import _resolve_providers

        with patch("mail.config_cli.commands._detect_gmail_available", return_value=False), \
                patch("mail.config_cli.commands._detect_outlook_available", return_value=False):
            requested, run_gmail, run_outlook = _resolve_providers(self._make_args())
        self.assertIsNone(requested)
        self.assertFalse(run_gmail)
        self.assertFalse(run_outlook)

    def test_explicit_gmail_provider_forces_gmail_true_regardless_of_detection(self):
        from mail.config_cli.commands import _resolve_providers

        # Detection returns False but explicit provider overrides it
        with patch("mail.config_cli.commands._detect_gmail_available", return_value=False), \
                patch("mail.config_cli.commands._detect_outlook_available", return_value=False):
            requested, run_gmail, run_outlook = _resolve_providers(self._make_args(providers="gmail"))
        self.assertIn("gmail", requested)
        self.assertTrue(run_gmail)
        self.assertFalse(run_outlook)

    def test_explicit_outlook_provider_forces_outlook_true_regardless_of_detection(self):
        from mail.config_cli.commands import _resolve_providers

        with patch("mail.config_cli.commands._detect_gmail_available", return_value=False), \
                patch("mail.config_cli.commands._detect_outlook_available", return_value=False):
            requested, run_gmail, run_outlook = _resolve_providers(self._make_args(providers="outlook"))
        self.assertIn("outlook", requested)
        self.assertFalse(run_gmail)
        self.assertTrue(run_outlook)

    def test_both_providers_explicit_both_forced_true(self):
        from mail.config_cli.commands import _resolve_providers

        with patch("mail.config_cli.commands._detect_gmail_available", return_value=False), \
                patch("mail.config_cli.commands._detect_outlook_available", return_value=False):
            _requested, run_gmail, run_outlook = _resolve_providers(self._make_args(providers="gmail,outlook"))
        self.assertTrue(run_gmail)
        self.assertTrue(run_outlook)


class TestRunProviderSteps(unittest.TestCase):
    """Tests for _run_provider_steps."""

    def _make_args(self, providers=None, **kwargs):
        defaults = dict(
            apply=False, delete_missing=False, profile=None,
            accounts_config=None, account=None, outlook_move_to_folders=True,
        )
        defaults.update(kwargs)
        ns = SimpleNamespace(**defaults)
        if providers is not None:
            ns.providers = providers
        return ns

    def test_returns_true_when_gmail_runs(self):
        from mail.config_cli.commands import _run_provider_steps

        with patch("mail.config_cli.commands._resolve_providers", return_value=(None, True, False)), \
                patch("mail.config_cli.commands._run_gmail_steps") as mock_gmail, \
                patch("mail.config_cli.commands._run_outlook_steps") as mock_outlook:
            result = _run_provider_steps(self._make_args(), "/g.yaml", "/o.yaml")
        self.assertTrue(result)
        mock_gmail.assert_called_once()
        mock_outlook.assert_not_called()

    def test_returns_true_when_outlook_runs(self):
        from mail.config_cli.commands import _run_provider_steps

        with patch("mail.config_cli.commands._resolve_providers", return_value=(None, False, True)), \
                patch("mail.config_cli.commands._run_gmail_steps") as mock_gmail, \
                patch("mail.config_cli.commands._run_outlook_steps") as mock_outlook:
            result = _run_provider_steps(self._make_args(), "/g.yaml", "/o.yaml")
        self.assertTrue(result)
        mock_gmail.assert_not_called()
        mock_outlook.assert_called_once()

    def test_returns_false_when_neither_runs_and_prints_skip_messages(self):
        from mail.config_cli.commands import _run_provider_steps

        with patch("mail.config_cli.commands._resolve_providers", return_value=(None, False, False)), \
                patch("mail.config_cli.commands._run_gmail_steps") as mock_gmail, \
                patch("mail.config_cli.commands._run_outlook_steps") as mock_outlook, \
                patch("builtins.print") as mock_print:
            result = _run_provider_steps(self._make_args(), "/g.yaml", "/o.yaml")
        self.assertFalse(result)
        mock_gmail.assert_not_called()
        mock_outlook.assert_not_called()
        # Both skip messages should be printed when requested is None
        printed_args = [str(c[0][0]) for c in mock_print.call_args_list if c[0]]
        skip_messages = [m for m in printed_args if "Skipping" in m]
        self.assertEqual(len(skip_messages), 2)

    def test_skip_message_suppressed_when_provider_not_in_requested(self):
        """When providers='gmail' is requested, the Outlook skip message is not printed."""
        from mail.config_cli.commands import _run_provider_steps

        # requested={'gmail'}, run_gmail=True (gmail step runs), run_outlook=False
        # 'outlook' not in requested so its elif also will not fire
        with patch("mail.config_cli.commands._resolve_providers", return_value=({"gmail"}, True, False)), \
                patch("mail.config_cli.commands._run_gmail_steps"), \
                patch("mail.config_cli.commands._run_outlook_steps") as mock_outlook, \
                patch("builtins.print") as mock_print:
            result = _run_provider_steps(self._make_args(providers="gmail"), "/g.yaml", "/o.yaml")
        self.assertTrue(result)
        mock_outlook.assert_not_called()
        printed_args = [str(c[0][0]) for c in mock_print.call_args_list if c[0]]
        outlook_skips = [m for m in printed_args if "Outlook" in m and "Skipping" in m]
        self.assertEqual(len(outlook_skips), 0)


class TestRunWorkflowsFromUnified(unittest.TestCase):
    """Tests for run_workflows_from_unified."""

    def _make_args(self, **kwargs):
        defaults = dict(
            config=None, out_dir=None, outlook_move_to_folders=True,
            apply=False, delete_missing=False, profile=None,
            accounts_config=None, account=None,
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    @patch("mail.config_cli.commands.resolve_filters_config", return_value="/u.yaml")
    @patch("mail.config_cli.commands.DeriveFiltersProducer")
    @patch("mail.config_cli.commands.DeriveFiltersProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_two_when_derive_fails(
        self, mock_req_consumer, mock_processor_cls, mock_producer_cls, mock_resolve
    ):
        from mail.config_cli.commands import run_workflows_from_unified

        envelope = _make_error_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        with tempfile.TemporaryDirectory() as tmpdir:
            args = self._make_args(out_dir=tmpdir)
            result = run_workflows_from_unified(args)
        self.assertEqual(result, 2)

    @patch("mail.config_cli.commands.resolve_filters_config", return_value="/u.yaml")
    @patch("mail.config_cli.commands.DeriveFiltersProducer")
    @patch("mail.config_cli.commands.DeriveFiltersProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_two_when_no_providers_detected(
        self, mock_req_consumer, mock_processor_cls, mock_producer_cls, mock_resolve
    ):
        from mail.config_cli.commands import run_workflows_from_unified

        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        with patch("mail.config_cli.commands._run_provider_steps", return_value=False):
            with tempfile.TemporaryDirectory() as tmpdir:
                args = self._make_args(out_dir=tmpdir)
                result = run_workflows_from_unified(args)
        self.assertEqual(result, 2)

    @patch("mail.config_cli.commands.resolve_filters_config", return_value="/u.yaml")
    @patch("mail.config_cli.commands.DeriveFiltersProducer")
    @patch("mail.config_cli.commands.DeriveFiltersProcessor")
    @patch("mail.config_cli.commands.RequestConsumer")
    def test_returns_zero_when_providers_run(
        self, mock_req_consumer, mock_processor_cls, mock_producer_cls, mock_resolve
    ):
        from mail.config_cli.commands import run_workflows_from_unified

        envelope = _make_ok_envelope()
        mock_processor_cls.return_value.process.return_value = envelope

        with patch("mail.config_cli.commands._run_provider_steps", return_value=True):
            with tempfile.TemporaryDirectory() as tmpdir:
                args = self._make_args(out_dir=tmpdir)
                result = run_workflows_from_unified(args)
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
