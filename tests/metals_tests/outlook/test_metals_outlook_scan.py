"""Tests for metals outlook_scan module."""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

from metals.outlook_scan import (
    QUERIES,
    run,
    main,
)


# HTTP requests are routed through HttpClient -> requests.Session.request, so tests
# patch that single seam.
_SESSION_SEAM = "requests.sessions.Session.request"


def _make_resp(status=200, json_data=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_data if json_data is not None else {}
    r.headers = {}
    r.raise_for_status.return_value = None
    return r


class TestQueries(unittest.TestCase):
    """Tests for QUERIES constant."""

    def test_queries_defined(self):
        """Test QUERIES are defined."""
        self.assertIsInstance(QUERIES, list)
        self.assertGreater(len(QUERIES), 0)

    def test_queries_have_names_and_patterns(self):
        """Test each query has name and pattern."""
        for name, pattern in QUERIES:
            self.assertIsInstance(name, str)
            self.assertIsInstance(pattern, str)
            self.assertGreater(len(name), 0)
            self.assertGreater(len(pattern), 0)

    def test_td_query_exists(self):
        """Test TD query exists."""
        names = [name for name, _ in QUERIES]
        self.assertIn("TD", names)

    def test_costco_query_exists(self):
        """Test Costco query exists."""
        names = [name for name, _ in QUERIES]
        self.assertIn("Costco", names)

    def test_rcm_query_exists(self):
        """Test RCM query exists."""
        names = [name for name, _ in QUERIES]
        self.assertIn("RCM", names)


class TestRun(unittest.TestCase):
    """Tests for run function."""

    @patch("metals.outlook_scan.OutlookClient")
    @patch("metals.outlook_scan.resolve_outlook_credentials")
    def test_run_success(self, mock_resolve, mock_client_class):
        """Test successful run."""
        mock_resolve.return_value = ("client_id", "tenant", "token.json")
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"

        # Mock search results
        mock_client.search_inbox_messages.return_value = ["msg1", "msg2"]
        mock_client.get_message.return_value = {
            "id": "msg1",
            "subject": "TD Precious Metals Order",
            "receivedDateTime": "2024-01-15T10:00:00Z",
            "from": {"emailAddress": {"address": "noreply@td.com"}},
        }

        result = run(
            profile="test",
            days=30,
            top=10,
            pages=1,
            folder="inbox",
        )
        self.assertEqual(result, 0)
        mock_client.authenticate.assert_called_once()

    @patch("metals.outlook_scan.resolve_outlook_credentials")
    def test_run_missing_client_id(self, mock_resolve):
        """Test run fails with missing client_id."""
        mock_resolve.return_value = (None, "tenant", "token.json")

        with self.assertRaises(SystemExit):
            run(
                profile="test",
                days=30,
                top=10,
                pages=1,
                folder="inbox",
            )

    @patch("metals.outlook_scan.OutlookClient")
    @patch("metals.outlook_scan.resolve_outlook_credentials")
    def test_run_handles_search_exception(self, mock_resolve, mock_client_class):
        """Test run handles search exceptions gracefully."""
        mock_resolve.return_value = ("client_id", "tenant", "token.json")
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.search_inbox_messages.side_effect = Exception("Search failed")

        # Should not raise, just continue
        result = run(
            profile="test",
            days=30,
            top=10,
            pages=1,
            folder="inbox",
        )
        self.assertEqual(result, 0)

    @patch("metals.outlook_scan.OutlookClient")
    @patch("metals.outlook_scan.resolve_outlook_credentials")
    def test_run_all_folder_search(self, mock_resolve, mock_client_class):
        """Test run with all folders search."""
        mock_resolve.return_value = ("client_id", "tenant", "token.json")
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.GRAPH = "https://graph.microsoft.com/v1.0"

        # Mock the _headers_search method
        mock_client._headers_search.return_value = {"Authorization": "Bearer token"}

        with patch(_SESSION_SEAM) as mock_req:
            mock_req.return_value = _make_resp(200, {"value": []})

            result = run(
                profile="test",
                days=30,
                top=10,
                pages=1,
                folder="all",
            )
            self.assertEqual(result, 0)


class TestMain(unittest.TestCase):
    """Tests for main function."""

    @patch("metals.outlook_scan.run")
    def test_main_with_defaults(self, mock_run):
        """Test main with default arguments."""
        mock_run.return_value = 0
        result = main([])
        self.assertEqual(result, 0)
        mock_run.assert_called_once_with(
            profile="outlook_personal",
            days=365,
            top=50,
            pages=3,
            folder="inbox",
        )

    @patch("metals.outlook_scan.run")
    def test_main_with_custom_args(self, mock_run):
        """Test main with custom arguments."""
        mock_run.return_value = 0
        result = main([
            "--profile", "work_outlook",
            "--days", "90",
            "--top", "100",
            "--pages", "5",
            "--folder", "all",
        ])
        self.assertEqual(result, 0)
        mock_run.assert_called_once_with(
            profile="work_outlook",
            days=90,
            top=100,
            pages=5,
            folder="all",
        )


if __name__ == "__main__":
    unittest.main()
