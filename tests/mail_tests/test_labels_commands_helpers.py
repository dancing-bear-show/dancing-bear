"""Unit tests for mail/labels/commands.py helper functions."""

import unittest
from collections import Counter
from unittest.mock import MagicMock, patch

from tests.mail_tests.fixtures import FakeGmailClient, capture_stdout


class TestExtractEmailFromHeader(unittest.TestCase):
    """Tests for _extract_email_from_header."""

    def test_simple_email(self):
        from mail.labels.commands import _extract_email_from_header
        self.assertEqual(_extract_email_from_header("user@example.com"), "user@example.com")

    def test_name_with_email(self):
        from mail.labels.commands import _extract_email_from_header
        self.assertEqual(_extract_email_from_header("John Doe <john@example.com>"), "john@example.com")

    def test_empty_string(self):
        from mail.labels.commands import _extract_email_from_header
        self.assertEqual(_extract_email_from_header(""), "")

    def test_none_value(self):
        from mail.labels.commands import _extract_email_from_header
        self.assertEqual(_extract_email_from_header(None), "")

    def test_lowercases_result(self):
        from mail.labels.commands import _extract_email_from_header
        self.assertEqual(_extract_email_from_header("USER@EXAMPLE.COM"), "user@example.com")


class TestExtractDomain(unittest.TestCase):
    """Tests for _extract_domain."""

    def test_extracts_domain(self):
        from mail.labels.commands import _extract_domain
        self.assertEqual(_extract_domain("user@example.com"), "example.com")

    def test_no_at_sign(self):
        from mail.labels.commands import _extract_domain
        self.assertEqual(_extract_domain("nodomain"), "nodomain")

    def test_lowercases_domain(self):
        from mail.labels.commands import _extract_domain
        self.assertEqual(_extract_domain("user@EXAMPLE.COM"), "example.com")

    def test_strips_whitespace(self):
        from mail.labels.commands import _extract_domain
        self.assertEqual(_extract_domain("user@example.com "), "example.com")


class TestIsProtectedSender(unittest.TestCase):
    """Tests for _is_protected_sender."""

    def test_exact_email_match(self):
        from mail.labels.commands import _is_protected_sender
        self.assertTrue(_is_protected_sender("boss@company.com", ["boss@company.com"]))

    def test_domain_pattern_match(self):
        from mail.labels.commands import _is_protected_sender
        self.assertTrue(_is_protected_sender("anyone@company.com", ["@company.com"]))

    def test_domain_without_at_match(self):
        from mail.labels.commands import _is_protected_sender
        # Pattern "@company.com" should match domain "company.com"
        self.assertTrue(_is_protected_sender("user@company.com", ["@company.com"]))

    def test_no_match(self):
        from mail.labels.commands import _is_protected_sender
        self.assertFalse(_is_protected_sender("user@other.com", ["@company.com"]))

    def test_empty_patterns(self):
        from mail.labels.commands import _is_protected_sender
        self.assertFalse(_is_protected_sender("user@example.com", []))

    def test_skips_empty_pattern(self):
        from mail.labels.commands import _is_protected_sender
        self.assertFalse(_is_protected_sender("user@example.com", ["", None]))


class TestClassifyDomain(unittest.TestCase):
    """Tests for _classify_domain."""

    def test_commercial_classification(self):
        from mail.labels.commands import _classify_domain
        hints = {"promotions": 5, "list": 1}
        self.assertEqual(_classify_domain(hints, 10), "Lists/Commercial")

    def test_newsletter_classification(self):
        from mail.labels.commands import _classify_domain
        hints = {"promotions": 0, "list": 5}
        self.assertEqual(_classify_domain(hints, 10), "Lists/Newsletters")

    def test_no_classification(self):
        from mail.labels.commands import _classify_domain
        hints = {"promotions": 0, "list": 0}
        self.assertIsNone(_classify_domain(hints, 10))

    def test_threshold_calculation(self):
        from mail.labels.commands import _classify_domain
        # With count=9, threshold=max(1, 9//3)=3
        # promotions=3 should trigger commercial
        hints = {"promotions": 3, "list": 0}
        self.assertEqual(_classify_domain(hints, 9), "Lists/Commercial")


class TestGetEmptyUserLabels(unittest.TestCase):
    """Tests for _get_empty_user_labels."""

    def test_filters_empty_labels(self):
        from mail.labels.commands import _get_empty_user_labels
        labels = [
            {"name": "Empty", "type": "user", "messagesTotal": 0},
            {"name": "HasMessages", "type": "user", "messagesTotal": 5},
        ]
        result = _get_empty_user_labels(labels)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Empty")

    def test_excludes_system_labels(self):
        from mail.labels.commands import _get_empty_user_labels
        labels = [
            {"name": "INBOX", "type": "system", "messagesTotal": 0},
            {"name": "UserEmpty", "type": "user", "messagesTotal": 0},
        ]
        result = _get_empty_user_labels(labels)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "UserEmpty")

    def test_handles_missing_messagesTotal(self):
        from mail.labels.commands import _get_empty_user_labels
        labels = [{"name": "NoCount", "type": "user"}]
        result = _get_empty_user_labels(labels)
        self.assertEqual(len(result), 1)


class TestAnalyzeLabels(unittest.TestCase):
    """Tests for _analyze_labels."""

    def test_counts_total(self):
        from mail.labels.commands import _analyze_labels
        labels = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
        result = _analyze_labels(labels)
        self.assertEqual(result["total"], 3)

    def test_finds_duplicates(self):
        from mail.labels.commands import _analyze_labels
        labels = [{"name": "Dup"}, {"name": "Dup"}, {"name": "Unique"}]
        result = _analyze_labels(labels)
        self.assertEqual(result["duplicates"], ["Dup"])

    def test_calculates_max_depth(self):
        from mail.labels.commands import _analyze_labels
        labels = [{"name": "A"}, {"name": "A/B"}, {"name": "A/B/C/D"}]
        result = _analyze_labels(labels)
        self.assertEqual(result["max_depth"], 4)

    def test_identifies_imap_labels(self):
        from mail.labels.commands import _analyze_labels
        labels = [{"name": "[Gmail]/Trash"}, {"name": "IMAP/Folder"}, {"name": "Normal"}]
        result = _analyze_labels(labels)
        self.assertEqual(len(result["imapish"]), 2)


class TestFixLabelVisibility(unittest.TestCase):
    """Tests for _fix_label_visibility."""

    def test_updates_missing_visibility(self):
        from mail.labels.commands import _fix_label_visibility
        client = FakeGmailClient(labels=[
            {"id": "L1", "name": "Test", "type": "user"},
        ])
        changed = _fix_label_visibility(client, client.labels)
        self.assertEqual(changed, 1)

    def test_skips_system_labels(self):
        from mail.labels.commands import _fix_label_visibility
        client = FakeGmailClient(labels=[
            {"id": "INBOX", "name": "INBOX", "type": "system"},
        ])
        changed = _fix_label_visibility(client, client.labels)
        self.assertEqual(changed, 0)

    def test_skips_labels_with_visibility(self):
        from mail.labels.commands import _fix_label_visibility
        client = FakeGmailClient(labels=[
            {"id": "L1", "name": "Test", "type": "user",
             "labelListVisibility": "labelShow", "messageListVisibility": "show"},
        ])
        changed = _fix_label_visibility(client, client.labels)
        self.assertEqual(changed, 0)


class TestDeleteImapLabels(unittest.TestCase):
    """Tests for _delete_imap_labels."""

    def test_deletes_existing_labels(self):
        from mail.labels.commands import _delete_imap_labels
        client = FakeGmailClient(labels=[
            {"id": "L1", "name": "ToDelete", "type": "user"},
            {"id": "L2", "name": "Keep", "type": "user"},
        ])
        changed = _delete_imap_labels(client, ["ToDelete"])
        self.assertEqual(changed, 1)
        self.assertEqual(len(client.labels), 1)
        self.assertEqual(client.labels[0]["name"], "Keep")

    def test_skips_missing_labels(self):
        from mail.labels.commands import _delete_imap_labels
        client = FakeGmailClient(labels=[])
        with capture_stdout() as buf:
            changed = _delete_imap_labels(client, ["NonExistent"])
        self.assertEqual(changed, 0)


class TestDeleteLabelWithRetry(unittest.TestCase):
    """Tests for _delete_label_with_retry."""

    def test_successful_delete(self):
        from mail.labels.commands import _delete_label_with_retry
        client = FakeGmailClient(labels=[{"id": "L1", "name": "Test"}])
        with capture_stdout():
            result = _delete_label_with_retry(client, "L1", "Test")
        self.assertTrue(result)

    def test_retry_on_failure(self):
        from mail.labels.commands import _delete_label_with_retry
        client = MagicMock()
        client.delete_label.side_effect = [Exception("fail"), Exception("fail"), None]
        with patch("time.sleep"):
            with capture_stdout():
                result = _delete_label_with_retry(client, "L1", "Test", max_retries=3)
        self.assertTrue(result)
        self.assertEqual(client.delete_label.call_count, 3)

    def test_fails_after_max_retries(self):
        from mail.labels.commands import _delete_label_with_retry
        client = MagicMock()
        client.delete_label.side_effect = Exception("persistent failure")
        with patch("time.sleep"):
            with capture_stdout() as buf:
                result = _delete_label_with_retry(client, "L1", "Test", max_retries=3)
        self.assertFalse(result)
        self.assertIn("Warning", buf.getvalue())


class TestCollectDomainStats(unittest.TestCase):
    """Tests for _collect_domain_stats."""

    def test_counts_domains(self):
        from mail.labels.commands import _collect_domain_stats

        client = MagicMock()
        client.headers_to_dict.side_effect = [
            {"from": "user1@example.com"},
            {"from": "user2@example.com"},
            {"from": "other@different.com"},
        ]
        msgs = [{"id": "1"}, {"id": "2"}, {"id": "3"}]

        counts, hints = _collect_domain_stats(client, msgs, [])
        self.assertEqual(counts["example.com"], 2)
        self.assertEqual(counts["different.com"], 1)

    def test_skips_protected_senders(self):
        from mail.labels.commands import _collect_domain_stats

        client = MagicMock()
        client.headers_to_dict.side_effect = [
            {"from": "user@protected.com"},
            {"from": "user@allowed.com"},
        ]
        msgs = [{"id": "1"}, {"id": "2"}]

        counts, hints = _collect_domain_stats(client, msgs, ["@protected.com"])
        self.assertNotIn("protected.com", counts)
        self.assertEqual(counts["allowed.com"], 1)

    def test_tracks_list_hints(self):
        from mail.labels.commands import _collect_domain_stats

        client = MagicMock()
        client.headers_to_dict.return_value = {
            "from": "news@example.com",
            "list-unsubscribe": "<mailto:unsub@example.com>",
        }
        msgs = [{"id": "1", "labelIds": []}]

        counts, hints = _collect_domain_stats(client, msgs, [])
        self.assertEqual(hints["example.com"]["list"], 1)

    def test_tracks_promotions_hints(self):
        from mail.labels.commands import _collect_domain_stats

        client = MagicMock()
        client.headers_to_dict.return_value = {"from": "promo@shop.com"}
        msgs = [{"id": "1", "labelIds": ["CATEGORY_PROMOTIONS"]}]

        counts, hints = _collect_domain_stats(client, msgs, [])
        self.assertEqual(hints["shop.com"]["promotions"], 1)


class TestResolveLabelsIds(unittest.TestCase):
    """Tests for _resolve_label_ids in mail/utils/filters.py."""

    def test_resolves_existing_labels(self):
        from mail.utils.filters import _resolve_label_ids
        client = FakeGmailClient(labels=[{"id": "L1", "name": "Work"}])
        name_to_id = client.get_label_id_map()
        ids = _resolve_label_ids(client, ["Work"], name_to_id)
        self.assertEqual(ids, ["L1"])

    def test_creates_missing_labels(self):
        from mail.utils.filters import _resolve_label_ids
        client = FakeGmailClient(labels=[])
        name_to_id = client.get_label_id_map()
        ids = _resolve_label_ids(client, ["NewLabel"], name_to_id)
        self.assertEqual(len(ids), 1)
        self.assertTrue(ids[0].startswith("LBL_"))

    def test_preserves_system_label_ids(self):
        from mail.utils.filters import _resolve_label_ids
        client = FakeGmailClient()
        name_to_id = {}
        ids = _resolve_label_ids(client, ["INBOX", "TRASH"], name_to_id)
        self.assertEqual(ids, ["INBOX", "TRASH"])

    def test_skips_empty_names(self):
        from mail.utils.filters import _resolve_label_ids
        client = FakeGmailClient()
        ids = _resolve_label_ids(client, ["", None, "Valid"], {})
        self.assertEqual(len(ids), 1)


if __name__ == "__main__":
    unittest.main()
