"""Tests for mail/outlook/commands.py command orchestration."""

import argparse
import unittest
from unittest.mock import MagicMock, patch
from io import StringIO


class TestRunOutlookCalendarAddRecurring(unittest.TestCase):
    """Tests for run_outlook_calendar_add_recurring validation logic."""

    def _make_args(self, **kwargs):
        """Create an argparse Namespace with defaults."""
        defaults = {
            "subject": "Test Event",
            "start_time": "09:00",
            "end_time": "10:00",
            "repeat": "weekly",
            "range_start": "2024-01-01",
            "until": None,
            "count": None,
            "byday": None,
            "calendar": None,
            "tz": None,
            "interval": 1,
            "body_html": None,
            "location": None,
            "exdates": None,
            "no_reminder": False,
            "profile": None,
            "client_id": None,
            "tenant": None,
            "token": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_requires_until_or_count(self):
        from mail.outlook.commands import run_outlook_calendar_add_recurring
        args = self._make_args(until=None, count=None)
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = run_outlook_calendar_add_recurring(args)
        self.assertEqual(result, 2)
        self.assertIn("--until", mock_stdout.getvalue())

    def test_weekly_requires_byday(self):
        from mail.outlook.commands import run_outlook_calendar_add_recurring
        args = self._make_args(repeat="weekly", until="2024-12-31", byday=None)
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = run_outlook_calendar_add_recurring(args)
        self.assertEqual(result, 2)
        self.assertIn("--byday", mock_stdout.getvalue())

    @patch("mail.outlook.commands.get_outlook_client")
    def test_parses_byday_string(self, mock_get_client):
        from mail.outlook.commands import run_outlook_calendar_add_recurring
        mock_client = MagicMock()
        mock_get_client.return_value = (mock_client, 0)

        # Mock the consumer/processor/producer chain
        with patch("mail.outlook.commands.OutlookCalendarAddRecurringConsumer") as mock_consumer_cls:
            with patch("mail.outlook.commands.OutlookCalendarAddRecurringProcessor") as mock_proc_cls:
                with patch("mail.outlook.commands.OutlookCalendarAddRecurringProducer") as mock_prod_cls:
                    mock_consumer = MagicMock()
                    mock_consumer.consume.return_value = {}
                    mock_consumer_cls.return_value = mock_consumer

                    mock_processor = MagicMock()
                    mock_envelope = MagicMock()
                    mock_envelope.ok.return_value = True
                    mock_processor.process.return_value = mock_envelope
                    mock_proc_cls.return_value = mock_processor

                    mock_producer = MagicMock()
                    mock_prod_cls.return_value = mock_producer

                    args = self._make_args(
                        repeat="weekly",
                        until="2024-12-31",
                        byday="MO,WE,FR",
                    )
                    result = run_outlook_calendar_add_recurring(args)

        self.assertEqual(result, 0)
        # Verify byday was parsed correctly
        call_kwargs = mock_consumer_cls.call_args[1]
        self.assertEqual(call_kwargs["byday"], ["MO", "WE", "FR"])


class TestRunOutlookRulesList(unittest.TestCase):
    """Tests for run_outlook_rules_list command."""

    def _make_args(self, **kwargs):
        defaults = {
            "use_cache": False,
            "cache_ttl": 600,
            "profile": None,
            "client_id": None,
            "tenant": None,
            "token": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("mail.outlook.commands.get_outlook_client")
    def test_returns_error_when_client_fails(self, mock_get_client):
        from mail.outlook.commands import run_outlook_rules_list
        mock_get_client.return_value = (None, 1)
        args = self._make_args()
        result = run_outlook_rules_list(args)
        self.assertEqual(result, 1)

    @patch("mail.outlook.commands.get_outlook_client")
    def test_executes_pipeline(self, mock_get_client):
        from mail.outlook.commands import run_outlook_rules_list
        mock_client = MagicMock()
        mock_get_client.return_value = (mock_client, 0)

        with patch("mail.outlook.commands.OutlookRulesListConsumer") as mock_cons_cls:
            with patch("mail.outlook.commands.OutlookRulesListProcessor") as mock_proc_cls:
                with patch("mail.outlook.commands.OutlookRulesListProducer") as mock_prod_cls:
                    mock_consumer = MagicMock()
                    mock_consumer.consume.return_value = {}
                    mock_cons_cls.return_value = mock_consumer

                    mock_processor = MagicMock()
                    mock_envelope = MagicMock()
                    mock_envelope.ok.return_value = True
                    mock_processor.process.return_value = mock_envelope
                    mock_proc_cls.return_value = mock_processor

                    mock_producer = MagicMock()
                    mock_prod_cls.return_value = mock_producer

                    args = self._make_args()
                    result = run_outlook_rules_list(args)

        self.assertEqual(result, 0)


class TestRunOutlookRulesSync(unittest.TestCase):
    """Tests for run_outlook_rules_sync command."""

    def _make_args(self, **kwargs):
        defaults = {
            "config": "config.yaml",
            "dry_run": False,
            "delete_missing": False,
            "move_to_folders": False,
            "verbose": False,
            "profile": None,
            "client_id": None,
            "tenant": None,
            "token": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("mail.outlook.commands.get_outlook_client")
    def test_passes_sync_options(self, mock_get_client):
        from mail.outlook.commands import run_outlook_rules_sync
        mock_client = MagicMock()
        mock_get_client.return_value = (mock_client, 0)

        with patch("mail.outlook.commands.OutlookRulesSyncConsumer") as mock_cons_cls:
            with patch("mail.outlook.commands.OutlookRulesSyncProcessor") as mock_proc_cls:
                with patch("mail.outlook.commands.OutlookRulesSyncProducer") as mock_prod_cls:
                    mock_consumer = MagicMock()
                    mock_consumer.consume.return_value = {}
                    mock_cons_cls.return_value = mock_consumer

                    mock_processor = MagicMock()
                    mock_envelope = MagicMock()
                    mock_envelope.ok.return_value = True
                    mock_processor.process.return_value = mock_envelope
                    mock_proc_cls.return_value = mock_processor

                    mock_producer = MagicMock()
                    mock_prod_cls.return_value = mock_producer

                    args = self._make_args(
                        dry_run=True,
                        delete_missing=True,
                        move_to_folders=True,
                    )
                    result = run_outlook_rules_sync(args)

        self.assertEqual(result, 0)
        call_kwargs = mock_cons_cls.call_args[1]
        self.assertTrue(call_kwargs["dry_run"])
        self.assertTrue(call_kwargs["delete_missing"])
        self.assertTrue(call_kwargs["move_to_folders"])


class TestRunOutlookCategoriesSync(unittest.TestCase):
    """Tests for run_outlook_categories_sync command."""

    def _make_args(self, **kwargs):
        defaults = {
            "config": "labels.yaml",
            "dry_run": False,
            "profile": None,
            "client_id": None,
            "tenant": None,
            "token": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("mail.outlook.commands.get_outlook_client")
    def test_returns_error_when_client_fails(self, mock_get_client):
        from mail.outlook.commands import run_outlook_categories_sync
        mock_get_client.return_value = (None, 1)
        args = self._make_args()
        result = run_outlook_categories_sync(args)
        self.assertEqual(result, 1)

    @patch("mail.outlook.commands.get_outlook_client")
    @patch("mail.yamlio.load_config")
    @patch("mail.dsl.normalize_labels_for_outlook")
    def test_dry_run_does_not_create(self, mock_normalize, mock_load, mock_get_client):
        from mail.outlook.commands import run_outlook_categories_sync
        mock_client = MagicMock()
        mock_client.list_labels.return_value = []
        mock_get_client.return_value = (mock_client, 0)
        mock_load.return_value = {"labels": [{"name": "Work"}]}
        mock_normalize.return_value = [{"name": "Work"}]

        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            args = self._make_args(dry_run=True)
            result = run_outlook_categories_sync(args)

        self.assertEqual(result, 0)
        mock_client.create_label.assert_not_called()
        self.assertIn("Would create", mock_stdout.getvalue())


class TestRunOutlookCalendarAdd(unittest.TestCase):
    """Tests for run_outlook_calendar_add command."""

    def _make_args(self, **kwargs):
        defaults = {
            "subject": "Test Event",
            "start": "2024-01-15T09:00:00",
            "end": "2024-01-15T10:00:00",
            "calendar": None,
            "tz": None,
            "body_html": None,
            "all_day": False,
            "location": None,
            "no_reminder": False,
            "profile": None,
            "client_id": None,
            "tenant": None,
            "token": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("mail.outlook.commands.get_outlook_client")
    def test_returns_error_when_client_fails(self, mock_get_client):
        from mail.outlook.commands import run_outlook_calendar_add
        mock_get_client.return_value = (None, 1)
        args = self._make_args()
        result = run_outlook_calendar_add(args)
        self.assertEqual(result, 1)

    @patch("mail.outlook.commands.get_outlook_client")
    def test_creates_event_with_args(self, mock_get_client):
        from mail.outlook.commands import run_outlook_calendar_add
        mock_client = MagicMock()
        mock_get_client.return_value = (mock_client, 0)

        with patch("mail.outlook.commands.OutlookCalendarAddConsumer") as mock_cons_cls:
            with patch("mail.outlook.commands.OutlookCalendarAddProcessor") as mock_proc_cls:
                with patch("mail.outlook.commands.OutlookCalendarAddProducer") as mock_prod_cls:
                    mock_consumer = MagicMock()
                    mock_consumer.consume.return_value = {}
                    mock_cons_cls.return_value = mock_consumer

                    mock_processor = MagicMock()
                    mock_envelope = MagicMock()
                    mock_envelope.ok.return_value = True
                    mock_processor.process.return_value = mock_envelope
                    mock_proc_cls.return_value = mock_processor

                    mock_producer = MagicMock()
                    mock_prod_cls.return_value = mock_producer

                    args = self._make_args(
                        subject="Meeting",
                        location="Room A",
                        no_reminder=True,
                    )
                    result = run_outlook_calendar_add(args)

        self.assertEqual(result, 0)
        call_kwargs = mock_cons_cls.call_args[1]
        self.assertEqual(call_kwargs["subject"], "Meeting")
        self.assertEqual(call_kwargs["location"], "Room A")
        self.assertTrue(call_kwargs["no_reminder"])


class TestRunOutlookAuthDeviceCode(unittest.TestCase):
    """Tests for run_outlook_auth_device_code command."""

    def _make_args(self, **kwargs):
        defaults = {
            "out": "/tmp/flow.json",
            "profile": None,
            "client_id": None,
            "tenant": None,
            "verbose": False,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("mail.outlook.commands.resolve_outlook_credentials")
    def test_fails_without_client_id(self, mock_resolve):
        from mail.outlook.commands import run_outlook_auth_device_code
        mock_resolve.return_value = (None, "consumers", None)
        args = self._make_args()
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = run_outlook_auth_device_code(args)
        self.assertEqual(result, 2)
        self.assertIn("--client-id", mock_stdout.getvalue())


class TestRunOutlookAuthValidate(unittest.TestCase):
    """Tests for run_outlook_auth_validate command."""

    def _make_args(self, **kwargs):
        defaults = {
            "profile": None,
            "client_id": None,
            "tenant": None,
            "token": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("mail.outlook.commands.resolve_outlook_credentials")
    def test_fails_without_client_id(self, mock_resolve):
        from mail.outlook.commands import run_outlook_auth_validate
        mock_resolve.return_value = (None, "consumers", "/tmp/token.json")
        args = self._make_args()
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = run_outlook_auth_validate(args)
        self.assertEqual(result, 2)
        self.assertIn("--client-id", mock_stdout.getvalue())


class TestRunOutlookFoldersSync(unittest.TestCase):
    """Tests for run_outlook_folders_sync command."""

    def _make_args(self, **kwargs):
        defaults = {
            "config": "folders.yaml",
            "dry_run": False,
            "profile": None,
            "client_id": None,
            "tenant": None,
            "token": None,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("mail.outlook.commands.get_outlook_client")
    def test_returns_error_when_client_fails(self, mock_get_client):
        from mail.outlook.commands import run_outlook_folders_sync
        mock_get_client.return_value = (None, 1)
        args = self._make_args()
        result = run_outlook_folders_sync(args)
        self.assertEqual(result, 1)

    @patch("mail.outlook.commands.get_outlook_client")
    def test_passes_dry_run_flag(self, mock_get_client):
        from mail.outlook.commands import run_outlook_folders_sync
        mock_client = MagicMock()
        mock_get_client.return_value = (mock_client, 0)

        with patch("mail.outlook.commands.OutlookFoldersSyncConsumer") as mock_cons_cls:
            with patch("mail.outlook.commands.OutlookFoldersSyncProcessor") as mock_proc_cls:
                with patch("mail.outlook.commands.OutlookFoldersSyncProducer") as mock_prod_cls:
                    mock_consumer = MagicMock()
                    mock_consumer.consume.return_value = {}
                    mock_cons_cls.return_value = mock_consumer

                    mock_processor = MagicMock()
                    mock_envelope = MagicMock()
                    mock_envelope.ok.return_value = True
                    mock_processor.process.return_value = mock_envelope
                    mock_proc_cls.return_value = mock_processor

                    mock_producer = MagicMock()
                    mock_prod_cls.return_value = mock_producer

                    args = self._make_args(dry_run=True)
                    result = run_outlook_folders_sync(args)

        self.assertEqual(result, 0)
        call_kwargs = mock_cons_cls.call_args[1]
        self.assertTrue(call_kwargs["dry_run"])


if __name__ == "__main__":
    unittest.main()
