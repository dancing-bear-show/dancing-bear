"""Tests for calendars/gmail/commands.py — argument-to-request builders."""
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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
