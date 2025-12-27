"""Tests for metals CLI module."""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock


class TestMetalsCLI(unittest.TestCase):
    """Tests for metals CLI."""

    def test_app_initialization(self):
        """Test CLI app is properly initialized."""
        from metals.__main__ import app
        self.assertEqual(app.name, "metals")
        self.assertIn("Precious metals", app.description)

    def test_main_help(self):
        """Test --help returns 0."""
        from metals.__main__ import main
        with self.assertRaises(SystemExit) as cm:
            main(["--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_extract_gmail_command_exists(self):
        """Test extract.gmail command exists."""
        from metals.__main__ import app
        self.assertIn("extract.gmail", app._commands)

    def test_extract_outlook_command_exists(self):
        """Test extract.outlook command exists."""
        from metals.__main__ import app
        self.assertIn("extract.outlook", app._commands)

    def test_costs_gmail_command_exists(self):
        """Test costs.gmail command exists."""
        from metals.__main__ import app
        self.assertIn("costs.gmail", app._commands)

    def test_costs_outlook_command_exists(self):
        """Test costs.outlook command exists."""
        from metals.__main__ import app
        self.assertIn("costs.outlook", app._commands)

    def test_spot_fetch_command_exists(self):
        """Test spot.fetch command exists."""
        from metals.__main__ import app
        self.assertIn("spot.fetch", app._commands)

    def test_premium_calc_command_exists(self):
        """Test premium.calc command exists."""
        from metals.__main__ import app
        self.assertIn("premium.calc", app._commands)

    def test_premium_summary_command_exists(self):
        """Test premium.summary command exists."""
        from metals.__main__ import app
        self.assertIn("premium.summary", app._commands)

    def test_build_summaries_command_exists(self):
        """Test build.summaries command exists."""
        from metals.__main__ import app
        self.assertIn("build.summaries", app._commands)

    def test_excel_merge_command_exists(self):
        """Test excel.merge command exists."""
        from metals.__main__ import app
        self.assertIn("excel.merge", app._commands)

    def test_scan_command_exists(self):
        """Test scan command exists."""
        from metals.__main__ import app
        self.assertIn("scan", app._commands)

    def test_extract_gmail_help(self):
        """Test extract gmail --help."""
        from metals.__main__ import main
        with self.assertRaises(SystemExit) as cm:
            main(["extract", "gmail", "--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_extract_outlook_help(self):
        """Test extract outlook --help."""
        from metals.__main__ import main
        with self.assertRaises(SystemExit) as cm:
            main(["extract", "outlook", "--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_spot_fetch_help(self):
        """Test spot fetch --help."""
        from metals.__main__ import main
        with self.assertRaises(SystemExit) as cm:
            main(["spot", "fetch", "--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_premium_calc_help(self):
        """Test premium calc --help."""
        from metals.__main__ import main
        with self.assertRaises(SystemExit) as cm:
            main(["premium", "calc", "--help"])
        self.assertEqual(cm.exception.code, 0)


class TestMetalsInit(unittest.TestCase):
    """Tests for metals package init."""

    def test_app_id(self):
        """Test APP_ID is set correctly."""
        from metals import APP_ID
        self.assertEqual(APP_ID, "metals")

    def test_purpose(self):
        """Test PURPOSE is set correctly."""
        from metals import PURPOSE
        self.assertIn("Precious metals", PURPOSE)


class TestMetalsExtractCommands(unittest.TestCase):
    """Tests for metals extract commands."""

    @patch("metals.pipeline.GmailExtractProcessor")
    @patch("metals.pipeline.ExtractProducer")
    def test_cmd_extract_gmail_success(self, mock_producer_class, mock_processor_class):
        """Test extract gmail command with mocked processor."""
        from metals.__main__ import cmd_extract_gmail
        from metals.pipeline import ExtractResult, Result
        from metals.extractors import MetalsAmount

        mock_processor = MagicMock()
        mock_processor_class.return_value = mock_processor
        mock_producer = MagicMock()
        mock_producer_class.return_value = mock_producer

        payload = ExtractResult(
            total=MetalsAmount(gold_oz=1.0),
            orders=[],
            message_count=1,
        )
        mock_processor.process.return_value = Result(payload=payload)

        args = MagicMock()
        args.profile = "test"
        args.days = 30
        result = cmd_extract_gmail(args)

        self.assertEqual(result, 0)
        mock_processor.process.assert_called_once()
        mock_producer.produce.assert_called_once()

    @patch("metals.pipeline.OutlookExtractProcessor")
    @patch("metals.pipeline.ExtractProducer")
    def test_cmd_extract_outlook_success(self, mock_producer_class, mock_processor_class):
        """Test extract outlook command with mocked processor."""
        from metals.__main__ import cmd_extract_outlook
        from metals.pipeline import ExtractResult, Result
        from metals.extractors import MetalsAmount

        mock_processor = MagicMock()
        mock_processor_class.return_value = mock_processor
        mock_producer = MagicMock()
        mock_producer_class.return_value = mock_producer

        payload = ExtractResult(
            total=MetalsAmount(silver_oz=10.0),
            orders=[],
            message_count=1,
        )
        mock_processor.process.return_value = Result(payload=payload)

        args = MagicMock()
        args.profile = "test"
        args.days = 30
        result = cmd_extract_outlook(args)

        self.assertEqual(result, 0)
        mock_processor.process.assert_called_once()
        mock_producer.produce.assert_called_once()

    @patch("metals.pipeline.GmailExtractProcessor")
    @patch("metals.pipeline.ExtractProducer")
    def test_cmd_extract_gmail_failure(self, mock_producer_class, mock_processor_class):
        """Test extract gmail command returns 1 on error."""
        from metals.__main__ import cmd_extract_gmail
        from metals.pipeline import Result

        mock_processor = MagicMock()
        mock_processor_class.return_value = mock_processor
        mock_producer = MagicMock()
        mock_producer_class.return_value = mock_producer

        mock_processor.process.return_value = Result(error="Auth failed")

        args = MagicMock()
        args.profile = "test"
        args.days = 30
        result = cmd_extract_gmail(args)

        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
