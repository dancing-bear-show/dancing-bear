"""Tests for maker/cli/main.py CLI registration and commands."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from maker.cli.main import main


class TestMakerCLIMain(unittest.TestCase):
    """Tests for maker CLI main function."""

    def test_main_with_no_args_shows_help(self):
        """main() with no args should show help and return 0."""
        with patch('sys.stdout'):
            result = main([])
        self.assertEqual(result, 0)

    @patch('maker.cli.main.assistant.maybe_emit_agentic')
    def test_main_handles_agentic_flags(self, mock_agentic):
        """main() should handle agentic flags when present."""
        mock_agentic.return_value = 0
        result = main(['--agentic'])
        mock_agentic.assert_called_once()
        self.assertEqual(result, 0)

    @patch('maker.cli.main.ToolCatalogConsumer')
    @patch('maker.cli.main.ConsoleProducer')
    def test_list_tools_command(self, mock_producer, mock_consumer):
        """list-tools command should execute successfully."""
        mock_catalog = MagicMock()
        mock_consumer.return_value.consume.return_value = mock_catalog

        result = main(['list-tools'])

        mock_consumer.assert_called_once()
        mock_consumer.return_value.consume.assert_called_once()
        mock_producer.assert_called_once()
        self.assertEqual(result, 0)

    @patch('maker.cli.main.ToolResultProducer')
    @patch('maker.cli.main.ToolRunnerProcessor')
    def test_card_command_success(self, mock_runner, mock_producer):
        """card command should execute and return 0 on success."""
        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = True
        mock_runner.return_value.process.return_value = mock_envelope

        result = main(['card'])

        mock_runner.assert_called_once()
        mock_producer.assert_called_once()
        self.assertEqual(result, 0)

    @patch('maker.cli.main.ToolResultProducer')
    @patch('maker.cli.main.ToolRunnerProcessor')
    def test_card_command_failure(self, mock_runner, mock_producer):
        """card command should return error code on failure."""
        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = False
        mock_envelope.payload.return_code = 42
        mock_runner.return_value.process.return_value = mock_envelope

        result = main(['card'])

        self.assertEqual(result, 42)

    @patch('maker.cli.main.ToolResultProducer')
    @patch('maker.cli.main.ToolRunnerProcessor')
    def test_tp_rod_command_success(self, mock_runner, mock_producer):
        """tp-rod command should execute and return 0 on success."""
        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = True
        mock_runner.return_value.process.return_value = mock_envelope

        result = main(['tp-rod'])

        mock_runner.assert_called_once()
        mock_producer.assert_called_once()
        self.assertEqual(result, 0)

    @patch('maker.cli.main.ToolResultProducer')
    @patch('maker.cli.main.ToolRunnerProcessor')
    def test_print_send_command_success(self, mock_runner, mock_producer):
        """print-send command should execute and return 0 on success."""
        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = True
        mock_runner.return_value.process.return_value = mock_envelope

        result = main(['print-send'])

        mock_runner.assert_called_once()
        mock_producer.assert_called_once()
        self.assertEqual(result, 0)

    @patch('maker.cli.main.ToolResultProducer')
    @patch('maker.cli.main.ToolRunnerProcessor')
    def test_command_failure_without_payload(self, mock_runner, mock_producer):
        """Command should return 1 if envelope fails with no payload."""
        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = False
        mock_envelope.payload = None
        mock_runner.return_value.process.return_value = mock_envelope

        result = main(['card'])

        self.assertEqual(result, 1)


if __name__ == '__main__':
    unittest.main()
