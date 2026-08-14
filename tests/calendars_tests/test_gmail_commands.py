"""Tests for calendars/gmail/commands.py — argument-to-request builders."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from calendars.gmail.commands import (
    run_gmail_mail_list,
    run_gmail_sweep_top,
    run_gmail_scan_classes,
    run_gmail_scan_receipts,
    run_gmail_scan_activerh,
)
from tests.fakes.gmail import FakeGmailClient
from tests.fixtures import capture_stdout


def _mock_run_pipeline(rc=0):
    """Return a patcher that stubs core.pipeline.run_pipeline."""
    mock = MagicMock(return_value=rc)
    return patch("calendars.gmail.commands.run_pipeline", mock), mock


class TestRunGmailMailList(unittest.TestCase):
    def test_builds_request_and_calls_pipeline(self):
        patcher, mock_rp = _mock_run_pipeline()
        with patcher:
            args = SimpleNamespace(
                profile="personal",
                credentials=None,
                token=None,
                cache=None,
                query=None,
                from_text=None,
                days=7,
                pages=1,
                page_size=10,
                inbox_only=False,
            )
            rc = run_gmail_mail_list(args)
        self.assertEqual(rc, 0)
        mock_rp.assert_called_once()
        req = mock_rp.call_args[0][0]
        self.assertEqual(req.auth.profile, "personal")
        self.assertEqual(req.days, 7)
        self.assertEqual(req.pages, 1)

    def test_default_days_used_when_not_provided(self):
        patcher, mock_rp = _mock_run_pipeline()
        with patcher:
            # 'days' not set — should fallback to int(getattr(..., "days", 7))
            args = SimpleNamespace(
                profile=None, credentials=None, token=None, cache=None,
                query=None, from_text=None, pages=1, page_size=10, inbox_only=False,
            )
            run_gmail_mail_list(args)
        req = mock_rp.call_args[0][0]
        self.assertEqual(req.days, 7)


class TestRunGmailSweepTop(unittest.TestCase):
    def test_builds_request_with_out_path(self):
        patcher, mock_rp = _mock_run_pipeline()
        with patcher:
            args = SimpleNamespace(
                profile=None, credentials=None, token=None, cache=None,
                query=None, from_text="newsletter",
                days=10, pages=5, page_size=100, inbox_only=True, top=10,
                out="out/sweep.yaml",
            )
            rc = run_gmail_sweep_top(args)
        self.assertEqual(rc, 0)
        req = mock_rp.call_args[0][0]
        self.assertEqual(req.from_text, "newsletter")
        self.assertEqual(req.top, 10)
        self.assertIsNotNone(req.out_path)

    def test_builds_request_without_out_path(self):
        patcher, mock_rp = _mock_run_pipeline()
        with patcher:
            args = SimpleNamespace(
                profile=None, credentials=None, token=None, cache=None,
                query=None, from_text=None,
                days=10, pages=5, page_size=100, inbox_only=True, top=10,
                out=None,
            )
            run_gmail_sweep_top(args)
        req = mock_rp.call_args[0][0]
        self.assertIsNone(req.out_path)


class TestRunGmailScanClasses(unittest.TestCase):
    def test_builds_request(self):
        patcher, mock_rp = _mock_run_pipeline()
        with patcher:
            args = SimpleNamespace(
                profile=None, credentials=None, token=None, cache=None,
                query="from:school", from_text=None,
                days=60, pages=5, page_size=100, inbox_only=False,
                calendar="Family", out=None,
            )
            rc = run_gmail_scan_classes(args)
        self.assertEqual(rc, 0)
        req = mock_rp.call_args[0][0]
        self.assertEqual(req.query, "from:school")
        self.assertEqual(req.calendar, "Family")
        self.assertIsNone(req.out_path)

    def test_out_path_set_when_provided(self):
        patcher, mock_rp = _mock_run_pipeline()
        with patcher:
            args = SimpleNamespace(
                profile=None, credentials=None, token=None, cache=None,
                query=None, from_text=None,
                days=60, pages=5, page_size=100, inbox_only=False,
                calendar=None, out="out/classes.yaml",
            )
            run_gmail_scan_classes(args)
        req = mock_rp.call_args[0][0]
        self.assertIsNotNone(req.out_path)


class TestRunGmailScanReceipts(unittest.TestCase):
    def test_builds_request(self):
        patcher, mock_rp = _mock_run_pipeline()
        with patcher:
            args = SimpleNamespace(
                profile=None, credentials=None, token=None, cache=None,
                query=None, from_text=None,
                days=365, pages=5, page_size=100,
                calendar=None, out="receipts.yaml",
            )
            rc = run_gmail_scan_receipts(args)
        self.assertEqual(rc, 0)
        req = mock_rp.call_args[0][0]
        self.assertEqual(req.days, 365)
        self.assertIsNotNone(req.out_path)


class TestRunGmailScanActiverh(unittest.TestCase):
    def test_with_explicit_query_delegates_to_scan_receipts(self):
        patcher, mock_rp = _mock_run_pipeline()
        with patcher:
            args = SimpleNamespace(
                profile=None, credentials=None, token=None, cache=None,
                query="from:activerh@example.com",
                from_text=None,
                days=365, pages=5, page_size=100,
                calendar=None, out="out.yaml",
            )
            rc = run_gmail_scan_activerh(args)
        self.assertEqual(rc, 0)
        # When query is provided, it just calls scan_receipts path (same pipeline call)
        mock_rp.assert_called_once()

    def test_without_query_builds_activerh_query(self):
        patcher_rp, mock_rp = _mock_run_pipeline()
        # GmailService is imported locally inside run_gmail_scan_activerh, patch at source
        with patcher_rp, patch(
            "calendars.gmail_service.GmailService.build_activerh_query",
            return_value="from:activerh subject:receipt",
        ) as mock_bq:
            args = SimpleNamespace(
                profile=None, credentials=None, token=None, cache=None,
                query=None, from_text=None,
                days=365, pages=5, page_size=100,
                calendar=None, out="out.yaml",
            )
            rc = run_gmail_scan_activerh(args)

        self.assertEqual(rc, 0)
        mock_bq.assert_called_once()
        # The query should have been set on args
        mock_rp.assert_called_once()


class TestGmailScanCommandsEndToEnd(unittest.TestCase):
    """E2E coverage through a FakeGmailClient — real text extraction and pipeline execution.

    Distinct from the classes above, which mock run_pipeline entirely and so
    never exercise real message-fetch -> text-parse -> event-building, nor the
    real "wrote N events to"/"candidate recurring" output messages.
    """

    def test_scan_receipts_extracts_event(self):
        text = "\n".join([
            "Enrollment in Swim Kids 5 (RH)",
            "Meeting Dates: From January 1, 2025 to March 1, 2025",
            "Each Monday from 5:00 pm to 5:30 pm",
            "Location: Elgin West Community Centre",
        ])
        fake = FakeGmailClient(
            message_ids_by_query={"richmondhill": ["m1"]},
            messages={"m1": {"text": text}},
        )
        tf = tempfile.NamedTemporaryFile("w+", delete=False, suffix=".yaml")
        tf.close()
        try:
            args = SimpleNamespace(
                from_text="richmondhill.ca", days=365, pages=1, page_size=10, query=None, out=tf.name,
                profile=None, credentials=None, token=None, cache=None, calendar=None,
            )
            with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=fake):
                with capture_stdout() as buf:
                    rc = run_gmail_scan_receipts(args)
            out = buf.getvalue().lower()
            self.assertEqual(rc, 0, msg=out)
            self.assertIn("wrote 1 events to", out)
        finally:
            os.unlink(tf.name)

    def test_scan_classes_extracts_schedule_lines(self):
        body = "\n".join([
            "Subject: Schedule",
            "Monday 5:00 pm to 5:30 pm",
            "Wednesday 6:00 pm to 6:30 pm",
        ])
        fake = FakeGmailClient(
            message_ids_by_query={"active": ["m1"]},
            messages={"m1": {"text": body}},
        )
        args = SimpleNamespace(
            from_text="active rh", days=60, pages=1, page_size=10, query=None, inbox_only=False, out=None,
            profile=None, credentials=None, token=None, cache=None, calendar=None,
        )
        with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=fake):
            with capture_stdout() as buf:
                rc = run_gmail_scan_classes(args)
        out = buf.getvalue().lower()
        self.assertEqual(rc, 0, msg=out)
        self.assertIn("candidate recurring", out)

    def test_scan_activerh_builds_query_delegates(self):
        text = "\n".join([
            "Enrollment in Swim Kids 2",
            "Meeting Dates: From January 5, 2025 to March 5, 2025",
            "Each Monday from 5:00 pm to 5:30 pm",
            "Location: Bayview Hill Community Centre",
        ])
        # Empty key matches any query (activerh builds its own custom query).
        fake = FakeGmailClient(
            message_ids_by_query={"": ["m1"]},
            messages={"m1": {"text": text}},
        )
        tf = tempfile.NamedTemporaryFile("w+", delete=False, suffix=".yaml")
        tf.close()
        try:
            args = SimpleNamespace(
                days=365, pages=1, page_size=10, query=None, out=tf.name,
                profile=None, credentials=None, token=None, cache=None, calendar=None, from_text=None,
            )
            with patch("mail.utils.cli_helpers.gmail_provider_from_args", return_value=fake):
                with capture_stdout() as buf:
                    rc = run_gmail_scan_activerh(args)
            out = buf.getvalue().lower()
            self.assertEqual(rc, 0, msg=out)
            self.assertIn("wrote 1 events to", out)
        finally:
            os.unlink(tf.name)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
