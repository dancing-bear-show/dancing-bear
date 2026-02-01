"""Tests for calendars/gmail/commands.py."""
import argparse
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from calendars.gmail.commands import (
    run_gmail_mail_list,
    run_gmail_sweep_top,
    run_gmail_scan_classes,
    run_gmail_scan_receipts,
    run_gmail_scan_activerh,
)


class TestRunGmailMailList(unittest.TestCase):
    """Tests for run_gmail_mail_list command."""

    @patch('calendars.gmail.commands.run_pipeline')
    def test_run_gmail_mail_list_creates_request(self, mock_run_pipeline):
        """run_gmail_mail_list should create GmailMailListRequest and run pipeline."""
        mock_run_pipeline.return_value = 0
        args = argparse.Namespace(
            profile='test',
            credentials='/creds',
            token='/token',
            cache='/cache',
            query='test query',
            from_text='sender@example.com',
            days=14,
            pages=2,
            page_size=20,
            inbox_only=True,
        )

        result = run_gmail_mail_list(args)

        self.assertEqual(result, 0)
        mock_run_pipeline.assert_called_once()
        # Verify request was created with correct values
        call_args = mock_run_pipeline.call_args
        request = call_args[0][0]
        self.assertEqual(request.auth.profile, 'test')
        self.assertEqual(request.query, 'test query')
        self.assertEqual(request.days, 14)

    @patch('calendars.gmail.commands.run_pipeline')
    def test_run_gmail_mail_list_with_defaults(self, mock_run_pipeline):
        """run_gmail_mail_list should use defaults when args missing."""
        mock_run_pipeline.return_value = 0
        args = argparse.Namespace()

        result = run_gmail_mail_list(args)

        self.assertEqual(result, 0)
        call_args = mock_run_pipeline.call_args
        request = call_args[0][0]
        self.assertIsNone(request.auth.profile)
        self.assertIsNone(request.query)


class TestRunGmailSweepTop(unittest.TestCase):
    """Tests for run_gmail_sweep_top command."""

    @patch('calendars.gmail.commands.run_pipeline')
    def test_run_gmail_sweep_top_creates_request(self, mock_run_pipeline):
        """run_gmail_sweep_top should create GmailSweepTopRequest and run pipeline."""
        mock_run_pipeline.return_value = 0
        args = argparse.Namespace(
            profile='test',
            credentials='/creds',
            token='/token',
            cache='/cache',
            query='test',
            from_text='sender',
            days=20,
            pages=3,
            page_size=50,
            inbox_only=False,
            top=15,
            out='/tmp/out.yaml',
        )

        result = run_gmail_sweep_top(args)

        self.assertEqual(result, 0)
        call_args = mock_run_pipeline.call_args
        request = call_args[0][0]
        self.assertEqual(request.days, 20)
        self.assertEqual(request.top, 15)
        self.assertEqual(request.out_path, Path('/tmp/out.yaml'))

    @patch('calendars.gmail.commands.run_pipeline')
    def test_run_gmail_sweep_top_without_out_path(self, mock_run_pipeline):
        """run_gmail_sweep_top should handle missing out path."""
        mock_run_pipeline.return_value = 0
        args = argparse.Namespace()

        result = run_gmail_sweep_top(args)

        call_args = mock_run_pipeline.call_args
        request = call_args[0][0]
        self.assertIsNone(request.out_path)


class TestRunGmailScanClasses(unittest.TestCase):
    """Tests for run_gmail_scan_classes command."""

    @patch('calendars.gmail.commands.run_pipeline')
    def test_run_gmail_scan_classes_creates_request(self, mock_run_pipeline):
        """run_gmail_scan_classes should create GmailScanClassesRequest."""
        mock_run_pipeline.return_value = 0
        args = argparse.Namespace(
            profile='test',
            credentials='/creds',
            token='/token',
            cache='/cache',
            query='classes',
            from_text='active',
            days=90,
            pages=10,
            page_size=200,
            inbox_only=True,
            calendar='Activities',
            out='/tmp/plan.yaml',
        )

        result = run_gmail_scan_classes(args)

        self.assertEqual(result, 0)
        call_args = mock_run_pipeline.call_args
        request = call_args[0][0]
        self.assertEqual(request.days, 90)
        self.assertEqual(request.calendar, 'Activities')
        self.assertEqual(request.out_path, Path('/tmp/plan.yaml'))

    @patch('calendars.gmail.commands.run_pipeline')
    def test_run_gmail_scan_classes_with_defaults(self, mock_run_pipeline):
        """run_gmail_scan_classes should use defaults."""
        mock_run_pipeline.return_value = 0
        args = argparse.Namespace()

        result = run_gmail_scan_classes(args)

        call_args = mock_run_pipeline.call_args
        request = call_args[0][0]
        self.assertEqual(request.days, 60)  # Default
        self.assertIsNone(request.out_path)


class TestRunGmailScanReceipts(unittest.TestCase):
    """Tests for run_gmail_scan_receipts command."""

    @patch('calendars.gmail.commands.run_pipeline')
    def test_run_gmail_scan_receipts_creates_request(self, mock_run_pipeline):
        """run_gmail_scan_receipts should create GmailReceiptsRequest."""
        mock_run_pipeline.return_value = 0
        args = argparse.Namespace(
            profile='test',
            credentials='/creds',
            token='/token',
            cache='/cache',
            query='receipts',
            from_text='rh.ca',
            days=180,
            pages=5,
            page_size=50,
            calendar='Family',
            out='/tmp/receipts.yaml',
        )

        result = run_gmail_scan_receipts(args)

        self.assertEqual(result, 0)
        call_args = mock_run_pipeline.call_args
        request = call_args[0][0]
        self.assertEqual(request.days, 180)
        self.assertEqual(request.calendar, 'Family')
        self.assertEqual(request.out_path, Path('/tmp/receipts.yaml'))


class TestRunGmailScanActiveRH(unittest.TestCase):
    """Tests for run_gmail_scan_activerh command."""

    @patch('calendars.gmail.commands.run_gmail_scan_receipts')
    def test_run_gmail_scan_activerh_with_explicit_query(self, mock_scan_receipts):
        """run_gmail_scan_activerh should delegate to scan_receipts if query provided."""
        mock_scan_receipts.return_value = 0
        args = argparse.Namespace(query='custom query')

        result = run_gmail_scan_activerh(args)

        self.assertEqual(result, 0)
        mock_scan_receipts.assert_called_once_with(args)

    @patch('calendars.gmail.commands.run_gmail_scan_receipts')
    @patch('calendars.gmail_service.GmailService')
    def test_run_gmail_scan_activerh_builds_query(self, mock_service, mock_scan_receipts):
        """run_gmail_scan_activerh should build ActiveRH query when none provided."""
        mock_service.build_activerh_query.return_value = 'built query'
        mock_scan_receipts.return_value = 0
        args = argparse.Namespace(days=365, from_text='richmond')

        result = run_gmail_scan_activerh(args)

        self.assertEqual(result, 0)
        mock_service.build_activerh_query.assert_called_once_with(
            days=365,
            explicit=None,
            programs=None,
            from_text='richmond',
        )
        # Should have set the query on args
        self.assertEqual(args.query, 'built query')
        mock_scan_receipts.assert_called_once_with(args)

    @patch('calendars.gmail.commands.run_gmail_scan_receipts')
    @patch('calendars.gmail_service.GmailService')
    def test_run_gmail_scan_activerh_defaults(self, mock_service, mock_scan_receipts):
        """run_gmail_scan_activerh should use defaults for missing args."""
        mock_service.build_activerh_query.return_value = 'query'
        mock_scan_receipts.return_value = 0
        args = argparse.Namespace()

        result = run_gmail_scan_activerh(args)

        self.assertEqual(result, 0)
        mock_service.build_activerh_query.assert_called_once()
        call_args = mock_service.build_activerh_query.call_args
        self.assertEqual(call_args[1]['days'], 365)
        self.assertIsNone(call_args[1]['from_text'])
