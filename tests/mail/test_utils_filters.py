"""Tests for mail/utils/filters.py filter building utilities."""

import unittest
from unittest.mock import MagicMock

from mail.utils.filters import (
    filters_normalize,
    build_criteria_from_match,
    build_gmail_query,
    action_to_label_changes,
    categories_to_system_labels,
    expand_categories,
)


class FiltersNormalizeTests(unittest.TestCase):
    def test_empty_dict(self):
        self.assertEqual(filters_normalize({}), {})

    def test_none_input(self):
        self.assertEqual(filters_normalize(None), {})

    def test_removes_none_values(self):
        result = filters_normalize({"a": "value", "b": None})
        self.assertEqual(result, {"a": "value"})

    def test_removes_empty_list(self):
        result = filters_normalize({"a": "value", "b": []})
        self.assertEqual(result, {"a": "value"})

    def test_removes_empty_string(self):
        result = filters_normalize({"a": "value", "b": ""})
        self.assertEqual(result, {"a": "value"})

    def test_keeps_valid_values(self):
        result = filters_normalize({"a": "value", "b": ["item"], "c": 0, "d": False})
        self.assertEqual(result, {"a": "value", "b": ["item"], "c": 0, "d": False})


class BuildCriteriaFromMatchTests(unittest.TestCase):
    def test_empty_match(self):
        result = build_criteria_from_match({})
        self.assertEqual(result, {})

    def test_none_match(self):
        result = build_criteria_from_match(None)
        self.assertEqual(result, {})

    def test_from_field(self):
        result = build_criteria_from_match({"from": "sender@example.com"})
        self.assertEqual(result, {"from": "sender@example.com"})

    def test_to_field(self):
        result = build_criteria_from_match({"to": "recipient@example.com"})
        self.assertEqual(result, {"to": "recipient@example.com"})

    def test_subject_field(self):
        result = build_criteria_from_match({"subject": "Test Subject"})
        self.assertEqual(result, {"subject": "Test Subject"})

    def test_query_field(self):
        result = build_criteria_from_match({"query": "is:unread"})
        self.assertEqual(result, {"query": "is:unread"})

    def test_negated_query(self):
        result = build_criteria_from_match({"negatedQuery": "is:spam"})
        self.assertEqual(result, {"negatedQuery": "is:spam"})

    def test_has_attachment(self):
        result = build_criteria_from_match({"hasAttachment": True})
        self.assertEqual(result, {"hasAttachment": True})

    def test_size_fields(self):
        result = build_criteria_from_match({"size": 1000, "sizeComparison": "larger"})
        self.assertEqual(result, {"size": 1000, "sizeComparison": "larger"})

    def test_multiple_fields(self):
        match = {"from": "sender@example.com", "subject": "Test", "hasAttachment": True}
        result = build_criteria_from_match(match)
        self.assertEqual(result["from"], "sender@example.com")
        self.assertEqual(result["subject"], "Test")
        self.assertEqual(result["hasAttachment"], True)

    def test_filters_empty_values(self):
        match = {"from": "sender@example.com", "to": None, "subject": ""}
        result = build_criteria_from_match(match)
        self.assertEqual(result, {"from": "sender@example.com"})


class BuildGmailQueryTests(unittest.TestCase):
    def test_empty_match(self):
        result = build_gmail_query({})
        self.assertEqual(result, "")

    def test_none_match(self):
        result = build_gmail_query(None)
        self.assertEqual(result, "")

    def test_from_query(self):
        result = build_gmail_query({"from": "sender@example.com"})
        self.assertEqual(result, "from:(sender@example.com)")

    def test_to_query(self):
        result = build_gmail_query({"to": "recipient@example.com"})
        self.assertEqual(result, "to:(recipient@example.com)")

    def test_subject_no_spaces(self):
        result = build_gmail_query({"subject": "Newsletter"})
        self.assertEqual(result, "subject:Newsletter")

    def test_subject_with_spaces(self):
        result = build_gmail_query({"subject": "Weekly Report"})
        self.assertEqual(result, 'subject:"Weekly Report"')

    def test_raw_query(self):
        result = build_gmail_query({"query": "is:unread label:inbox"})
        self.assertEqual(result, "is:unread label:inbox")

    def test_negated_query(self):
        result = build_gmail_query({"negatedQuery": "is:spam"})
        self.assertEqual(result, "-(is:spam)")

    def test_has_attachment(self):
        result = build_gmail_query({"hasAttachment": True})
        self.assertEqual(result, "has:attachment")

    def test_days_newer_than(self):
        result = build_gmail_query({}, days=7)
        self.assertEqual(result, "newer_than:7d")

    def test_older_than_days(self):
        result = build_gmail_query({}, older_than_days=30)
        self.assertEqual(result, "older_than:30d")

    def test_only_inbox(self):
        result = build_gmail_query({}, only_inbox=True)
        self.assertEqual(result, "in:inbox")

    def test_combined_options(self):
        result = build_gmail_query(
            {"from": "sender@example.com"},
            days=7,
            only_inbox=True,
        )
        self.assertIn("from:(sender@example.com)", result)
        self.assertIn("newer_than:7d", result)
        self.assertIn("in:inbox", result)

    def test_multiple_match_fields(self):
        match = {
            "from": "sender@example.com",
            "subject": "Test",
            "hasAttachment": True,
        }
        result = build_gmail_query(match)
        self.assertIn("from:(sender@example.com)", result)
        self.assertIn("subject:Test", result)
        self.assertIn("has:attachment", result)


class ActionToLabelChangesTests(unittest.TestCase):
    def _make_mock_client(self):
        client = MagicMock()
        client.get_label_id_map.return_value = {
            "Work": "Label_1",
            "Personal": "Label_2",
        }
        client.ensure_label.return_value = "Label_New"
        return client

    def test_empty_action(self):
        client = self._make_mock_client()
        add_ids, rem_ids = action_to_label_changes(client, {})
        self.assertEqual(add_ids, [])
        self.assertEqual(rem_ids, [])

    def test_none_action(self):
        client = self._make_mock_client()
        add_ids, rem_ids = action_to_label_changes(client, None)
        self.assertEqual(add_ids, [])
        self.assertEqual(rem_ids, [])

    def test_add_known_label(self):
        client = self._make_mock_client()
        add_ids, rem_ids = action_to_label_changes(client, {"add": ["Work"]})
        self.assertEqual(add_ids, ["Label_1"])
        self.assertEqual(rem_ids, [])

    def test_add_system_label(self):
        client = self._make_mock_client()
        add_ids, rem_ids = action_to_label_changes(client, {"add": ["INBOX"]})
        self.assertEqual(add_ids, ["INBOX"])

    def test_remove_known_label(self):
        client = self._make_mock_client()
        add_ids, rem_ids = action_to_label_changes(client, {"remove": ["Personal"]})
        self.assertEqual(rem_ids, ["Label_2"])

    def test_remove_system_label(self):
        client = self._make_mock_client()
        add_ids, rem_ids = action_to_label_changes(client, {"remove": ["UNREAD"]})
        self.assertEqual(rem_ids, ["UNREAD"])

    def test_add_unknown_label_creates_it(self):
        client = self._make_mock_client()
        add_ids, rem_ids = action_to_label_changes(client, {"add": ["NewLabel"]})
        client.ensure_label.assert_called_with("NewLabel")
        self.assertEqual(add_ids, ["Label_New"])

    def test_mixed_add_remove(self):
        client = self._make_mock_client()
        add_ids, rem_ids = action_to_label_changes(
            client, {"add": ["Work"], "remove": ["Personal"]}
        )
        self.assertEqual(add_ids, ["Label_1"])
        self.assertEqual(rem_ids, ["Label_2"])

    def test_skips_empty_strings(self):
        client = self._make_mock_client()
        add_ids, rem_ids = action_to_label_changes(
            client, {"add": ["Work", "", None], "remove": [""]}
        )
        self.assertEqual(add_ids, ["Label_1"])
        self.assertEqual(rem_ids, [])


class CategoriesToSystemLabelsTests(unittest.TestCase):
    def test_empty_spec(self):
        result = categories_to_system_labels({})
        self.assertEqual(result, [])

    def test_non_dict_returns_empty(self):
        result = categories_to_system_labels(None)
        self.assertEqual(result, [])
        result = categories_to_system_labels("string")
        self.assertEqual(result, [])

    def test_categorize_as_promotions(self):
        result = categories_to_system_labels({"categorizeAs": "promotions"})
        self.assertEqual(result, ["CATEGORY_PROMOTIONS"])

    def test_categorize_forums(self):
        result = categories_to_system_labels({"categorize": "forums"})
        self.assertEqual(result, ["CATEGORY_FORUMS"])

    def test_categorize_updates(self):
        result = categories_to_system_labels({"categorize": "updates"})
        self.assertEqual(result, ["CATEGORY_UPDATES"])

    def test_categorize_social(self):
        result = categories_to_system_labels({"categorize": "social"})
        self.assertEqual(result, ["CATEGORY_SOCIAL"])

    def test_categorize_personal(self):
        result = categories_to_system_labels({"categorize": "personal"})
        self.assertEqual(result, ["CATEGORY_PERSONAL"])

    def test_case_insensitive(self):
        result = categories_to_system_labels({"categorize": "PROMOTIONS"})
        self.assertEqual(result, ["CATEGORY_PROMOTIONS"])

    def test_strips_whitespace(self):
        result = categories_to_system_labels({"categorize": "  forums  "})
        self.assertEqual(result, ["CATEGORY_FORUMS"])

    def test_categories_list(self):
        result = categories_to_system_labels({"categories": ["promotions", "forums"]})
        self.assertIn("CATEGORY_PROMOTIONS", result)
        self.assertIn("CATEGORY_FORUMS", result)

    def test_categorize_list(self):
        result = categories_to_system_labels({"categorize": ["updates", "social"]})
        self.assertIn("CATEGORY_UPDATES", result)
        self.assertIn("CATEGORY_SOCIAL", result)

    def test_unknown_category_ignored(self):
        result = categories_to_system_labels({"categorize": "unknown"})
        self.assertEqual(result, [])


class ExpandCategoriesTests(unittest.TestCase):
    def test_empty_spec(self):
        result = expand_categories({})
        self.assertEqual(result, [])

    def test_non_dict_returns_empty(self):
        result = expand_categories(None)
        self.assertEqual(result, [])

    def test_categorize_as(self):
        result = expand_categories({"categorizeAs": "promotions"})
        self.assertEqual(result, ["CATEGORY_PROMOTIONS"])

    def test_categorize_string(self):
        result = expand_categories({"categorize": "forums"})
        self.assertEqual(result, ["CATEGORY_FORUMS"])

    def test_categories_list(self):
        result = expand_categories({"categories": ["social", "updates"]})
        self.assertIn("CATEGORY_SOCIAL", result)
        self.assertIn("CATEGORY_UPDATES", result)


if __name__ == "__main__":
    unittest.main()
