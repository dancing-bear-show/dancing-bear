"""Tests for calendars/helpers.py."""
import unittest
from argparse import Namespace
from unittest.mock import MagicMock, patch

from calendars.helpers import build_gmail_service_from_args


class TestBuildGmailServiceFromArgs(unittest.TestCase):
    """Tests for build_gmail_service_from_args function."""

    @patch('calendars.helpers._build_gmail_service_from_args')
    def test_delegates_to_core_auth(self, mock_build):
        """build_gmail_service_from_args should delegate to core.auth."""
        # Setup mock
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        # Create args
        args = Namespace(credentials='creds.json', token='token.json')  # nosec B106 - test fixture, not a password

        # Call function
        result = build_gmail_service_from_args(args)

        # Verify delegation
        mock_build.assert_called_once()
        call_args = mock_build.call_args

        # Check that args was passed
        self.assertEqual(call_args[0][0], args)

        # Check that service_cls keyword argument was passed
        self.assertIn('service_cls', call_args[1])

        # Verify result
        self.assertEqual(result, mock_service)

    @patch('calendars.helpers._build_gmail_service_from_args')
    def test_passes_gmail_service_class(self, mock_build):
        """build_gmail_service_from_args should pass GmailService class."""
        from calendars.gmail_service import GmailService

        mock_build.return_value = MagicMock()
        args = Namespace(credentials='c.json', token='t.json')  # nosec B106 - test fixture, not a password

        build_gmail_service_from_args(args)

        # Verify service_cls=GmailService was passed
        call_args = mock_build.call_args
        self.assertEqual(call_args[1]['service_cls'], GmailService)


if __name__ == '__main__':
    unittest.main()
