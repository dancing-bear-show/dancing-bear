"""Tests for run_filters_list and run_filters_delete commands."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from mail.filters.commands import (
    run_filters_list,
    run_filters_delete,
)

from tests.mail_tests.fixtures import FakeGmailClient, make_args


def _make_context_with_client(client: FakeGmailClient, **extra_args) -> SimpleNamespace:
    """Create args namespace with client injection."""
    args = make_args(**extra_args)
    args._gmail_client = client
    return args


class TestRunFiltersList(unittest.TestCase):
    """Tests for run_filters_list function."""

    def test_lists_filters_with_labels(self):
        client = FakeGmailClient(
            labels=[
                {"id": "LBL_VIP", "name": "VIP"},
                {"id": "LBL_WORK", "name": "Work"},
            ],
            filters=[
                {
                    "id": "F1",
                    "criteria": {"from": "boss@company.com"},
                    "action": {"addLabelIds": ["LBL_WORK"], "removeLabelIds": ["INBOX"]},
                },
                {
                    "id": "F2",
                    "criteria": {"subject": "Important"},
                    "action": {"addLabelIds": ["LBL_VIP"]},
                },
            ],
        )
        args = _make_context_with_client(client)

        buf = io.StringIO()
        with redirect_stdout(buf):
            result = run_filters_list(args)

        self.assertEqual(result, 0)
        output = buf.getvalue()
        # Should show filter IDs
        self.assertIn("F1", output)
        self.assertIn("F2", output)
        # Should translate label IDs to names
        self.assertIn("Work", output)
        self.assertIn("VIP", output)

    def test_lists_filters_with_forward(self):
        client = FakeGmailClient(
            labels=[],
            filters=[
                {
                    "id": "F1",
                    "criteria": {"from": "important@example.com"},
                    "action": {"forward": "backup@example.com"},
                },
            ],
        )
        args = _make_context_with_client(client)

        buf = io.StringIO()
        with redirect_stdout(buf):
            result = run_filters_list(args)

        self.assertEqual(result, 0)
        output = buf.getvalue()
        self.assertIn("backup@example.com", output)

    def test_lists_empty_filters(self):
        client = FakeGmailClient(labels=[], filters=[])
        args = _make_context_with_client(client)

        buf = io.StringIO()
        with redirect_stdout(buf):
            result = run_filters_list(args)

        self.assertEqual(result, 0)

    def test_shows_query_criteria(self):
        client = FakeGmailClient(
            labels=[],
            filters=[
                {
                    "id": "F1",
                    "criteria": {"query": "is:starred"},
                    "action": {},
                },
            ],
        )
        args = _make_context_with_client(client)

        buf = io.StringIO()
        with redirect_stdout(buf):
            run_filters_list(args)

        output = buf.getvalue()
        self.assertIn("is:starred", output)


class TestRunFiltersDelete(unittest.TestCase):
    """Tests for run_filters_delete function."""

    def test_deletes_filter_by_id(self):
        client = FakeGmailClient(
            labels=[],
            filters=[
                {"id": "F1", "criteria": {"from": "spam@example.com"}, "action": {}},
                {"id": "F2", "criteria": {"from": "keep@example.com"}, "action": {}},
            ],
        )

        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=client):
            args = SimpleNamespace(id="F1")

            buf = io.StringIO()
            with redirect_stdout(buf):
                result = run_filters_delete(args)

        self.assertEqual(result, 0)
        self.assertIn("F1", client.deleted_filter_ids)
        output = buf.getvalue()
        self.assertIn("Deleted", output)
        self.assertIn("F1", output)


if __name__ == "__main__":
    unittest.main()
