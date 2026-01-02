"""Tests for mail/filters/commands.py command layer functions."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mail.context import MailContext
from mail.filters.commands import (
    run_filters_list,
    run_filters_delete,
    run_filters_plan,
    run_filters_sync,
    run_filters_export,
    _run_filter_pipeline,
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


class TestRunFiltersPlan(unittest.TestCase):
    """Tests for run_filters_plan function."""

    def test_plan_shows_diff(self):
        client = FakeGmailClient(
            labels=[
                {"id": "LBL_VIP", "name": "VIP"},
            ],
            filters=[
                # Existing filter that's not in YAML - will be marked for deletion
                {
                    "id": "EXTRA",
                    "criteria": {"from": "old@example.com"},
                    "action": {"addLabelIds": ["LBL_VIP"]},
                },
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "filters.yaml"
            cfg_path.write_text(
                "filters:\n"
                "  - match:\n"
                "      from: new@example.com\n"
                "    action:\n"
                "      add:\n"
                "        - VIP\n"
            )

            args = make_args(config=str(cfg_path), delete_missing=True)
            ctx = MailContext.from_args(args)
            ctx.gmail_client = client

            # Patch MailContext.from_args to return our context
            with patch("mail.filters.commands.MailContext.from_args", return_value=ctx):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    result = run_filters_plan(args)

            self.assertEqual(result, 0)
            output = buf.getvalue()
            self.assertIn("Plan:", output)


class TestRunFiltersExport(unittest.TestCase):
    """Tests for run_filters_export function."""

    def test_exports_filters_to_yaml(self):
        client = FakeGmailClient(
            labels=[
                {"id": "LBL_WORK", "name": "Work"},
            ],
            filters=[
                {
                    "id": "F1",
                    "criteria": {"from": "boss@company.com"},
                    "action": {"addLabelIds": ["LBL_WORK"]},
                },
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "exported.yaml"
            args = make_args(out=str(out_path))
            ctx = MailContext.from_args(args)
            ctx.gmail_client = client

            with patch("mail.filters.commands.MailContext.from_args", return_value=ctx):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    result = run_filters_export(args)

            self.assertEqual(result, 0)
            self.assertTrue(out_path.exists())
            content = out_path.read_text()
            self.assertIn("filters:", content)


class TestRunFiltersSync(unittest.TestCase):
    """Tests for run_filters_sync with dry_run."""

    def test_sync_dry_run_shows_changes(self):
        client = FakeGmailClient(
            labels=[
                {"id": "LBL_VIP", "name": "VIP"},
            ],
            filters=[],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "filters.yaml"
            cfg_path.write_text(
                "filters:\n"
                "  - match:\n"
                "      from: vip@example.com\n"
                "    action:\n"
                "      add:\n"
                "        - VIP\n"
            )

            args = make_args(config=str(cfg_path), dry_run=True, delete_missing=False)
            ctx = MailContext.from_args(args)
            ctx.gmail_client = client

            with patch("mail.filters.commands.MailContext.from_args", return_value=ctx):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    result = run_filters_sync(args)

            self.assertEqual(result, 0)
            # In dry run, no filters should be created
            self.assertEqual(len(client.created_filters), 0)

    def test_sync_creates_filters_when_not_dry_run(self):
        client = FakeGmailClient(
            labels=[
                {"id": "LBL_VIP", "name": "VIP"},
            ],
            filters=[],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "filters.yaml"
            cfg_path.write_text(
                "filters:\n"
                "  - match:\n"
                "      from: vip@example.com\n"
                "    action:\n"
                "      add:\n"
                "        - VIP\n"
            )

            args = make_args(config=str(cfg_path), dry_run=False, delete_missing=False)
            ctx = MailContext.from_args(args)
            ctx.gmail_client = client

            with patch("mail.filters.commands.MailContext.from_args", return_value=ctx):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    result = run_filters_sync(args)

            self.assertEqual(result, 0)
            # Filter should be created
            self.assertEqual(len(client.created_filters), 1)


class TestRunFilterPipeline(unittest.TestCase):
    """Tests for _run_filter_pipeline helper function."""

    def test_successful_pipeline_returns_zero(self):
        """Test successful pipeline execution returns 0."""
        # Mock consumer
        class MockConsumer:
            def __init__(self, context):
                self.context = context

            def consume(self):
                return SimpleNamespace(value="test_payload")

        # Mock processor
        class MockProcessor:
            def process(self, payload):
                # Return successful envelope
                return SimpleNamespace(
                    result=SimpleNamespace(output="processed"),
                    ok=lambda: True,
                )

        # Mock producer
        class MockProducer:
            def __init__(self, payload):
                self.payload = payload

            def produce(self, envelope):
                pass

        args = make_args()
        ctx = MailContext.from_args(args)

        with patch("mail.filters.commands.MailContext.from_args", return_value=ctx):
            result = _run_filter_pipeline(
                args,
                MockConsumer,
                MockProcessor,
                MockProducer,
            )

        self.assertEqual(result, 0)

    def test_consumer_value_error_returns_one(self):
        """Test consumer ValueError is caught and returns 1."""

        class MockConsumer:
            def __init__(self, context):
                self.context = context

            def consume(self):
                raise ValueError("Invalid configuration")

        class MockProcessor:
            def process(self, payload):
                pass

        args = make_args()
        ctx = MailContext.from_args(args)

        with patch("mail.filters.commands.MailContext.from_args", return_value=ctx):
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = _run_filter_pipeline(
                    args,
                    MockConsumer,
                    MockProcessor,
                    lambda p: None,
                )

        self.assertEqual(result, 1)
        output = buf.getvalue()
        self.assertIn("Invalid configuration", output)

    def test_processor_error_with_default_handler(self):
        """Test processor error with default error handling."""

        class MockConsumer:
            def __init__(self, context):
                self.context = context

            def consume(self):
                return SimpleNamespace(value="test")

        class MockProcessor:
            def process(self, payload):
                # Return failed envelope
                return SimpleNamespace(
                    ok=lambda: False,
                    diagnostics={"message": "Processing failed", "code": 2},
                )

        args = make_args()
        ctx = MailContext.from_args(args)

        with patch("mail.filters.commands.MailContext.from_args", return_value=ctx):
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = _run_filter_pipeline(
                    args,
                    MockConsumer,
                    MockProcessor,
                    lambda p: None,
                )

        self.assertEqual(result, 2)
        output = buf.getvalue()
        self.assertIn("Processing failed", output)

    def test_processor_error_with_custom_handler(self):
        """Test processor error with custom error handler."""

        class MockConsumer:
            def __init__(self, context):
                self.context = context

            def consume(self):
                return SimpleNamespace(value="test")

        class MockProcessor:
            def process(self, payload):
                return SimpleNamespace(
                    ok=lambda: False,
                    diagnostics={"message": "Custom error", "code": 42},
                )

        def custom_error_handler(envelope):
            print("Custom handler invoked")
            return 99

        args = make_args()
        ctx = MailContext.from_args(args)

        with patch("mail.filters.commands.MailContext.from_args", return_value=ctx):
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = _run_filter_pipeline(
                    args,
                    MockConsumer,
                    MockProcessor,
                    lambda p: None,
                    handle_error=custom_error_handler,
                )

        self.assertEqual(result, 99)
        output = buf.getvalue()
        self.assertIn("Custom handler invoked", output)

    def test_processor_error_missing_diagnostics(self):
        """Test processor error with missing diagnostics."""

        class MockConsumer:
            def __init__(self, context):
                self.context = context

            def consume(self):
                return SimpleNamespace(value="test")

        class MockProcessor:
            def process(self, payload):
                return SimpleNamespace(
                    ok=lambda: False,
                    diagnostics=None,
                )

        args = make_args()
        ctx = MailContext.from_args(args)

        with patch("mail.filters.commands.MailContext.from_args", return_value=ctx):
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = _run_filter_pipeline(
                    args,
                    MockConsumer,
                    MockProcessor,
                    lambda p: None,
                )

        self.assertEqual(result, 1)
        output = buf.getvalue()
        self.assertIn("Pipeline failed", output)

    def test_producer_receives_payload(self):
        """Test producer receives correct payload."""
        received_payload = []

        class MockConsumer:
            def __init__(self, context):
                self.context = context

            def consume(self):
                return SimpleNamespace(value="test_value")

        class MockProcessor:
            def process(self, payload):
                return SimpleNamespace(
                    result=SimpleNamespace(output="processed"),
                    ok=lambda: True,
                )

        class MockProducer:
            def __init__(self, payload):
                received_payload.append(payload)

            def produce(self, envelope):
                pass

        args = make_args()
        ctx = MailContext.from_args(args)

        with patch("mail.filters.commands.MailContext.from_args", return_value=ctx):
            result = _run_filter_pipeline(
                args,
                MockConsumer,
                MockProcessor,
                MockProducer,
            )

        self.assertEqual(result, 0)
        self.assertEqual(len(received_payload), 1)
        self.assertEqual(received_payload[0].value, "test_value")


if __name__ == "__main__":
    unittest.main()
