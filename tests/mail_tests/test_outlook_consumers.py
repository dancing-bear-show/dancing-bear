"""Tests for mail/outlook/consumers.py."""

from tests.fixtures import test_path
import unittest
from unittest.mock import Mock

from mail.outlook.consumers import (
    # Payload dataclasses
    OutlookRulesListPayload,
    OutlookRulesExportPayload,
    OutlookRulesSyncPayload,
    OutlookRulesSweepPayload,
    OutlookCategoriesListPayload,
    OutlookFoldersSyncPayload,
    OutlookCalendarAddPayload,
    OutlookCalendarAddRecurringPayload,
    OutlookRulesListConsumer,
    OutlookRulesExportConsumer,
    OutlookRulesSyncConsumer,
    OutlookRulesDeleteConsumer,
    OutlookRulesSweepConsumer,
    OutlookCategoriesListConsumer,
    OutlookCategoriesSyncConsumer,
    OutlookFoldersSyncConsumer,
    OutlookCalendarAddConsumer,
    OutlookCalendarAddRecurringConsumer,
    OutlookCalendarAddFromConfigConsumer,
)


# =============================================================================
# Payload Dataclass Tests
# =============================================================================

class TestOutlookRulesListPayload(unittest.TestCase):
    """Tests for OutlookRulesListPayload."""

    def test_default_values(self):
        client = Mock()
        payload = OutlookRulesListPayload(client=client)
        self.assertEqual(payload.client, client)
        self.assertFalse(payload.use_cache)
        self.assertEqual(payload.cache_ttl, 600)

    def test_custom_values(self):
        client = Mock()
        payload = OutlookRulesListPayload(client=client, use_cache=True, cache_ttl=300)
        self.assertTrue(payload.use_cache)
        self.assertEqual(payload.cache_ttl, 300)


class TestOutlookRulesExportPayload(unittest.TestCase):
    """Tests for OutlookRulesExportPayload."""

    def test_required_fields(self):
        client = Mock()
        payload = OutlookRulesExportPayload(client=client, out_path=test_path("rules.yaml"))  # noqa: S108
        self.assertEqual(payload.out_path, test_path("rules.yaml"))  # noqa: S108

    def test_default_cache_values(self):
        client = Mock()
        payload = OutlookRulesExportPayload(client=client, out_path=test_path("out.yaml"))  # noqa: S108
        self.assertFalse(payload.use_cache)
        self.assertEqual(payload.cache_ttl, 600)


class TestOutlookRulesSyncPayload(unittest.TestCase):
    """Tests for OutlookRulesSyncPayload."""

    def test_default_values(self):
        client = Mock()
        payload = OutlookRulesSyncPayload(client=client, config_path="/cfg.yaml")
        self.assertFalse(payload.dry_run)
        self.assertFalse(payload.delete_missing)
        self.assertFalse(payload.move_to_folders)
        self.assertFalse(payload.verbose)

    def test_all_flags(self):
        client = Mock()
        payload = OutlookRulesSyncPayload(
            client=client,
            config_path="/cfg.yaml",
            dry_run=True,
            delete_missing=True,
            move_to_folders=True,
            verbose=True,
        )
        self.assertTrue(payload.dry_run)
        self.assertTrue(payload.delete_missing)
        self.assertTrue(payload.move_to_folders)
        self.assertTrue(payload.verbose)


class TestOutlookRulesSweepPayload(unittest.TestCase):
    """Tests for OutlookRulesSweepPayload."""

    def test_default_values(self):
        client = Mock()
        payload = OutlookRulesSweepPayload(client=client, config_path="/cfg.yaml")
        self.assertEqual(payload.days, 30)
        self.assertEqual(payload.top, 25)
        self.assertEqual(payload.pages, 2)
        self.assertFalse(payload.clear_cache)

    def test_custom_pagination(self):
        client = Mock()
        payload = OutlookRulesSweepPayload(
            client=client,
            config_path="/cfg.yaml",
            days=7,
            top=50,
            pages=5,
        )
        self.assertEqual(payload.days, 7)
        self.assertEqual(payload.top, 50)
        self.assertEqual(payload.pages, 5)


class TestOutlookCalendarAddPayload(unittest.TestCase):
    """Tests for OutlookCalendarAddPayload."""

    def test_required_fields(self):
        client = Mock()
        payload = OutlookCalendarAddPayload(
            client=client,
            subject="Meeting",
            start_iso="2024-01-15T10:00:00",
            end_iso="2024-01-15T11:00:00",
        )
        self.assertEqual(payload.subject, "Meeting")
        self.assertEqual(payload.start_iso, "2024-01-15T10:00:00")

    def test_optional_fields_defaults(self):
        client = Mock()
        payload = OutlookCalendarAddPayload(
            client=client,
            subject="Test",
            start_iso="2024-01-01",
            end_iso="2024-01-02",
        )
        self.assertIsNone(payload.calendar_name)
        self.assertIsNone(payload.tz)
        self.assertIsNone(payload.body_html)
        self.assertFalse(payload.all_day)
        self.assertIsNone(payload.location)
        self.assertFalse(payload.no_reminder)


class TestOutlookCalendarAddRecurringPayload(unittest.TestCase):
    """Tests for OutlookCalendarAddRecurringPayload."""

    def test_required_fields(self):
        client = Mock()
        payload = OutlookCalendarAddRecurringPayload(
            client=client,
            subject="Standup",
            start_time="09:00",
            end_time="09:30",
            repeat="weekly",
            range_start="2024-01-01",
        )
        self.assertEqual(payload.subject, "Standup")
        self.assertEqual(payload.repeat, "weekly")

    def test_optional_recurrence_fields(self):
        client = Mock()
        payload = OutlookCalendarAddRecurringPayload(
            client=client,
            subject="Test",
            start_time="10:00",
            end_time="11:00",
            repeat="daily",
            range_start="2024-01-01",
            interval=2,
            byday=["MO", "WE", "FR"],
            until="2024-12-31",
            count=52,
            exdates=["2024-07-04"],
        )
        self.assertEqual(payload.interval, 2)
        self.assertEqual(payload.byday, ["MO", "WE", "FR"])
        self.assertEqual(payload.until, "2024-12-31")
        self.assertEqual(payload.count, 52)
        self.assertEqual(payload.exdates, ["2024-07-04"])


# =============================================================================
# Consumer Class Tests
# =============================================================================

class TestOutlookRulesListConsumer(unittest.TestCase):
    """Tests for OutlookRulesListConsumer."""

    def test_consume_creates_payload(self):
        client = Mock()
        consumer = OutlookRulesListConsumer(client=client)
        payload = consumer.consume()
        self.assertIsInstance(payload, OutlookRulesListPayload)
        self.assertEqual(payload.client, client)

    def test_consume_with_cache(self):
        client = Mock()
        consumer = OutlookRulesListConsumer(client=client, use_cache=True, cache_ttl=120)
        payload = consumer.consume()
        self.assertTrue(payload.use_cache)
        self.assertEqual(payload.cache_ttl, 120)


class TestOutlookRulesExportConsumer(unittest.TestCase):
    """Tests for OutlookRulesExportConsumer."""

    def test_consume_creates_payload(self):
        client = Mock()
        consumer = OutlookRulesExportConsumer(client=client, out_path="/out.yaml")
        payload = consumer.consume()
        self.assertEqual(payload.out_path, "/out.yaml")


class TestOutlookRulesSyncConsumer(unittest.TestCase):
    """Tests for OutlookRulesSyncConsumer."""

    def test_consume_with_all_flags(self):
        client = Mock()
        consumer = OutlookRulesSyncConsumer(
            client=client,
            config_path="/config.yaml",
            dry_run=True,
            delete_missing=True,
            move_to_folders=True,
            verbose=True,
        )
        payload = consumer.consume()
        self.assertEqual(payload.config_path, "/config.yaml")
        self.assertTrue(payload.dry_run)
        self.assertTrue(payload.delete_missing)


class TestOutlookRulesDeleteConsumer(unittest.TestCase):
    """Tests for OutlookRulesDeleteConsumer."""

    def test_consume_creates_payload(self):
        client = Mock()
        consumer = OutlookRulesDeleteConsumer(client=client, rule_id="rule-123")
        payload = consumer.consume()
        self.assertEqual(payload.rule_id, "rule-123")


class TestOutlookRulesSweepConsumer(unittest.TestCase):
    """Tests for OutlookRulesSweepConsumer."""

    def test_consume_with_custom_params(self):
        client = Mock()
        consumer = OutlookRulesSweepConsumer(
            client=client,
            config_path="/cfg.yaml",
            days=14,
            top=100,
            pages=10,
            clear_cache=True,
        )
        payload = consumer.consume()
        self.assertEqual(payload.days, 14)
        self.assertEqual(payload.top, 100)
        self.assertTrue(payload.clear_cache)


class TestOutlookCategoriesListConsumer(unittest.TestCase):
    """Tests for OutlookCategoriesListConsumer."""

    def test_consume_creates_payload(self):
        client = Mock()
        consumer = OutlookCategoriesListConsumer(client=client)
        payload = consumer.consume()
        self.assertIsInstance(payload, OutlookCategoriesListPayload)


class TestOutlookCategoriesSyncConsumer(unittest.TestCase):
    """Tests for OutlookCategoriesSyncConsumer."""

    def test_consume_with_dry_run(self):
        client = Mock()
        consumer = OutlookCategoriesSyncConsumer(
            client=client, config_path="/labels.yaml", dry_run=True
        )
        payload = consumer.consume()
        self.assertTrue(payload.dry_run)


class TestOutlookFoldersSyncConsumer(unittest.TestCase):
    """Tests for OutlookFoldersSyncConsumer."""

    def test_consume_creates_payload(self):
        client = Mock()
        consumer = OutlookFoldersSyncConsumer(client=client, config_path="/labels.yaml")
        payload = consumer.consume()
        self.assertIsInstance(payload, OutlookFoldersSyncPayload)


class TestOutlookCalendarAddConsumer(unittest.TestCase):
    """Tests for OutlookCalendarAddConsumer."""

    def test_consume_creates_payload(self):
        client = Mock()
        consumer = OutlookCalendarAddConsumer(
            client=client,
            subject="Meeting",
            start_iso="2024-01-15T10:00:00",
            end_iso="2024-01-15T11:00:00",
            calendar_name="Work",
            location="Room 101",
        )
        payload = consumer.consume()
        self.assertEqual(payload.subject, "Meeting")
        self.assertEqual(payload.calendar_name, "Work")
        self.assertEqual(payload.location, "Room 101")


class TestOutlookCalendarAddRecurringConsumer(unittest.TestCase):
    """Tests for OutlookCalendarAddRecurringConsumer."""

    def test_consume_creates_payload(self):
        client = Mock()
        consumer = OutlookCalendarAddRecurringConsumer(
            client=client,
            subject="Standup",
            start_time="09:00",
            end_time="09:30",
            repeat="weekly",
            range_start="2024-01-01",
            byday=["MO", "TU", "WE", "TH", "FR"],
        )
        payload = consumer.consume()
        self.assertEqual(payload.repeat, "weekly")
        self.assertEqual(payload.byday, ["MO", "TU", "WE", "TH", "FR"])


class TestOutlookCalendarAddFromConfigConsumer(unittest.TestCase):
    """Tests for OutlookCalendarAddFromConfigConsumer."""

    def test_consume_creates_payload(self):
        client = Mock()
        consumer = OutlookCalendarAddFromConfigConsumer(
            client=client, config_path="/events.yaml", no_reminder=True
        )
        payload = consumer.consume()
        self.assertEqual(payload.config_path, "/events.yaml")
        self.assertTrue(payload.no_reminder)


if __name__ == "__main__":
    unittest.main(verbosity=2)
