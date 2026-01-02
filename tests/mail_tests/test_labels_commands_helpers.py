"""Unit tests for mail/labels/commands.py helper functions."""

import unittest
from unittest.mock import MagicMock, patch

from tests.mail_tests.fixtures import (
    FakeGmailClient,
    capture_stdout,
    make_user_label,
    make_system_label,
    make_label_with_visibility,
    make_message,
    NESTED_LABELS,
    IMAP_STYLE_LABELS,
)


# -----------------------------------------------------------------------------
# Local test helpers
# -----------------------------------------------------------------------------


def make_mock_client_with_headers(header_responses: list) -> MagicMock:
    """Create a MagicMock client with headers_to_dict responses."""
    client = MagicMock()
    client.headers_to_dict.side_effect = header_responses
    return client


# -----------------------------------------------------------------------------
# Test Classes
# -----------------------------------------------------------------------------


class TestExtractEmailFromHeader(unittest.TestCase):
    """Tests for _extract_email_from_header."""

    @classmethod
    def setUpClass(cls):
        from mail.labels.commands import _extract_email_from_header
        cls.extract = staticmethod(_extract_email_from_header)

    def test_simple_email(self):
        self.assertEqual(self.extract("user@example.com"), "user@example.com")

    def test_name_with_email(self):
        self.assertEqual(self.extract("John Doe <john@example.com>"), "john@example.com")

    def test_empty_string(self):
        self.assertEqual(self.extract(""), "")

    def test_none_value(self):
        self.assertEqual(self.extract(None), "")

    def test_lowercases_result(self):
        self.assertEqual(self.extract("USER@EXAMPLE.COM"), "user@example.com")


class TestExtractDomain(unittest.TestCase):
    """Tests for _extract_domain."""

    @classmethod
    def setUpClass(cls):
        from mail.labels.commands import _extract_domain
        cls.extract = staticmethod(_extract_domain)

    def test_extracts_domain(self):
        self.assertEqual(self.extract("user@example.com"), "example.com")

    def test_no_at_sign(self):
        self.assertEqual(self.extract("nodomain"), "nodomain")

    def test_lowercases_domain(self):
        self.assertEqual(self.extract("user@EXAMPLE.COM"), "example.com")

    def test_strips_whitespace(self):
        self.assertEqual(self.extract("user@example.com "), "example.com")


class TestIsProtectedSender(unittest.TestCase):
    """Tests for _is_protected_sender."""

    @classmethod
    def setUpClass(cls):
        from mail.labels.commands import _is_protected_sender
        cls.is_protected = staticmethod(_is_protected_sender)

    def test_exact_email_match(self):
        self.assertTrue(self.is_protected("boss@company.com", ["boss@company.com"]))

    def test_domain_pattern_match(self):
        self.assertTrue(self.is_protected("anyone@company.com", ["@company.com"]))

    def test_domain_without_at_match(self):
        self.assertTrue(self.is_protected("user@company.com", ["@company.com"]))

    def test_no_match(self):
        self.assertFalse(self.is_protected("user@other.com", ["@company.com"]))

    def test_empty_patterns(self):
        self.assertFalse(self.is_protected("user@example.com", []))

    def test_skips_empty_pattern(self):
        self.assertFalse(self.is_protected("user@example.com", ["", None]))


class TestClassifyDomain(unittest.TestCase):
    """Tests for _classify_domain."""

    @classmethod
    def setUpClass(cls):
        from mail.labels.commands import _classify_domain
        cls.classify = staticmethod(_classify_domain)

    def test_commercial_classification(self):
        hints = {"promotions": 5, "list": 1}
        self.assertEqual(self.classify(hints, 10), "Lists/Commercial")

    def test_newsletter_classification(self):
        hints = {"promotions": 0, "list": 5}
        self.assertEqual(self.classify(hints, 10), "Lists/Newsletters")

    def test_no_classification(self):
        hints = {"promotions": 0, "list": 0}
        self.assertIsNone(self.classify(hints, 10))

    def test_threshold_calculation(self):
        # With count=9, threshold=max(1, 9//3)=3
        hints = {"promotions": 3, "list": 0}
        self.assertEqual(self.classify(hints, 9), "Lists/Commercial")


class TestGetEmptyUserLabels(unittest.TestCase):
    """Tests for _get_empty_user_labels."""

    @classmethod
    def setUpClass(cls):
        from mail.labels.commands import _get_empty_user_labels
        cls.get_empty = staticmethod(_get_empty_user_labels)

    def test_filters_empty_labels(self):
        labels = [
            make_user_label("Empty", messages=0),
            make_user_label("HasMessages", messages=5),
        ]
        result = self.get_empty(labels)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Empty")

    def test_excludes_system_labels(self):
        labels = [make_system_label("INBOX"), make_user_label("UserEmpty", messages=0)]
        result = self.get_empty(labels)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "UserEmpty")

    def test_handles_missing_messagesTotal(self):
        labels = [{"name": "NoCount", "type": "user"}]
        result = self.get_empty(labels)
        self.assertEqual(len(result), 1)


class TestAnalyzeLabels(unittest.TestCase):
    """Tests for _analyze_labels."""

    @classmethod
    def setUpClass(cls):
        from mail.labels.commands import _analyze_labels
        cls.analyze = staticmethod(_analyze_labels)

    def test_counts_total(self):
        labels = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
        self.assertEqual(self.analyze(labels)["total"], 3)

    def test_finds_duplicates(self):
        labels = [{"name": "Dup"}, {"name": "Dup"}, {"name": "Unique"}]
        self.assertEqual(self.analyze(labels)["duplicates"], ["Dup"])

    def test_calculates_max_depth(self):
        self.assertEqual(self.analyze(NESTED_LABELS)["max_depth"], 4)

    def test_identifies_imap_labels(self):
        result = self.analyze(IMAP_STYLE_LABELS)
        self.assertEqual(len(result["imapish"]), 2)


class TestFixLabelVisibility(unittest.TestCase):
    """Tests for _fix_label_visibility."""

    @classmethod
    def setUpClass(cls):
        from mail.labels.commands import _fix_label_visibility
        cls.fix_visibility = staticmethod(_fix_label_visibility)

    def test_updates_missing_visibility(self):
        client = FakeGmailClient(labels=[make_user_label("Test", "L1")])
        self.assertEqual(self.fix_visibility(client, client.labels), 1)

    def test_skips_system_labels(self):
        client = FakeGmailClient(labels=[make_system_label("INBOX")])
        self.assertEqual(self.fix_visibility(client, client.labels), 0)

    def test_skips_labels_with_visibility(self):
        client = FakeGmailClient(labels=[make_label_with_visibility("Test", "L1")])
        self.assertEqual(self.fix_visibility(client, client.labels), 0)


class TestDeleteImapLabels(unittest.TestCase):
    """Tests for _delete_imap_labels."""

    @classmethod
    def setUpClass(cls):
        from mail.labels.commands import _delete_imap_labels
        cls.delete_labels = staticmethod(_delete_imap_labels)

    def test_deletes_existing_labels(self):
        client = FakeGmailClient(labels=[
            make_user_label("ToDelete", "L1"),
            make_user_label("Keep", "L2"),
        ])
        changed = self.delete_labels(client, ["ToDelete"])
        self.assertEqual(changed, 1)
        self.assertEqual(len(client.labels), 1)
        self.assertEqual(client.labels[0]["name"], "Keep")

    def test_skips_missing_labels(self):
        client = FakeGmailClient(labels=[])
        with capture_stdout():
            self.assertEqual(self.delete_labels(client, ["NonExistent"]), 0)


class TestDeleteLabelWithRetry(unittest.TestCase):
    """Tests for _delete_label_with_retry."""

    @classmethod
    def setUpClass(cls):
        from mail.labels.commands import _delete_label_with_retry
        cls.delete_retry = staticmethod(_delete_label_with_retry)

    def test_successful_delete(self):
        client = FakeGmailClient(labels=[make_user_label("Test", "L1")])
        with capture_stdout():
            self.assertTrue(self.delete_retry(client, "L1", "Test"))

    def test_retry_on_failure(self):
        client = MagicMock()
        client.delete_label.side_effect = [Exception("fail"), Exception("fail"), None]
        with patch("time.sleep"), capture_stdout():
            result = self.delete_retry(client, "L1", "Test", max_retries=3)
        self.assertTrue(result)
        self.assertEqual(client.delete_label.call_count, 3)

    def test_fails_after_max_retries(self):
        client = MagicMock()
        client.delete_label.side_effect = Exception("persistent failure")
        with patch("time.sleep"), capture_stdout() as buf:
            result = self.delete_retry(client, "L1", "Test", max_retries=3)
        self.assertFalse(result)
        self.assertIn("Warning", buf.getvalue())


class TestCollectDomainStats(unittest.TestCase):
    """Tests for _collect_domain_stats."""

    @classmethod
    def setUpClass(cls):
        from mail.labels.commands import _collect_domain_stats
        cls.collect_stats = staticmethod(_collect_domain_stats)

    def test_counts_domains(self):
        client = make_mock_client_with_headers([
            {"from": "user1@example.com"},
            {"from": "user2@example.com"},
            {"from": "other@different.com"},
        ])
        msgs = [make_message("1"), make_message("2"), make_message("3")]
        counts, _ = self.collect_stats(client, msgs, [])
        self.assertEqual(counts["example.com"], 2)
        self.assertEqual(counts["different.com"], 1)

    def test_skips_protected_senders(self):
        client = make_mock_client_with_headers([
            {"from": "user@protected.com"},
            {"from": "user@allowed.com"},
        ])
        msgs = [make_message("1"), make_message("2")]
        counts, _ = self.collect_stats(client, msgs, ["@protected.com"])
        self.assertNotIn("protected.com", counts)
        self.assertEqual(counts["allowed.com"], 1)

    def test_tracks_list_hints(self):
        client = MagicMock()
        client.headers_to_dict.return_value = {
            "from": "news@example.com",
            "list-unsubscribe": "<mailto:unsub@example.com>",
        }
        msgs = [make_message("1")]
        _, hints = self.collect_stats(client, msgs, [])
        self.assertEqual(hints["example.com"]["list"], 1)

    def test_tracks_promotions_hints(self):
        client = MagicMock()
        client.headers_to_dict.return_value = {"from": "promo@shop.com"}
        msgs = [make_message("1", ["CATEGORY_PROMOTIONS"])]
        _, hints = self.collect_stats(client, msgs, [])
        self.assertEqual(hints["shop.com"]["promotions"], 1)


class TestResolveLabelsIds(unittest.TestCase):
    """Tests for _resolve_label_ids in mail/utils/filters.py."""

    @classmethod
    def setUpClass(cls):
        from mail.utils.filters import _resolve_label_ids
        cls.resolve = staticmethod(_resolve_label_ids)

    def test_resolves_existing_labels(self):
        client = FakeGmailClient(labels=[make_user_label("Work", "L1")])
        ids = self.resolve(client, ["Work"], client.get_label_id_map())
        self.assertEqual(ids, ["L1"])

    def test_creates_missing_labels(self):
        client = FakeGmailClient(labels=[])
        ids = self.resolve(client, ["NewLabel"], client.get_label_id_map())
        self.assertEqual(len(ids), 1)
        self.assertTrue(ids[0].startswith("LBL_"))

    def test_preserves_system_label_ids(self):
        client = FakeGmailClient()
        ids = self.resolve(client, ["INBOX", "TRASH"], {})
        self.assertEqual(ids, ["INBOX", "TRASH"])

    def test_skips_empty_names(self):
        client = FakeGmailClient()
        ids = self.resolve(client, ["", None, "Valid"], {})
        self.assertEqual(len(ids), 1)


if __name__ == "__main__":
    unittest.main()
