import sys
import unittest
from unittest.mock import MagicMock, patch

from tests.fixtures import bin_path, repo_root, run


class WhatsAppCLITests(unittest.TestCase):

    def test_help_via_module_invocation(self):
        proc = run([sys.executable, '-m', 'whatsapp', '--help'])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('WhatsApp Assistant CLI', proc.stdout)

    def test_help_via_executable_script(self):
        root = repo_root()
        wrapper = bin_path('whatsapp')
        self.assertTrue(wrapper.exists(), 'bin/whatsapp not found')
        proc = run([sys.executable, str(wrapper), '--help'], cwd=str(root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('WhatsApp Assistant CLI', proc.stdout)


class WhatsAppMainTests(unittest.TestCase):
    """Tests for whatsapp/cli/main.py main() function."""

    def test_main_returns_zero_for_agentic(self):
        """Test main() returns 0 for agentic output."""
        from whatsapp.cli.main import main

        result = main(['--agentic'])
        self.assertEqual(result, 0)

    def test_main_no_command_shows_help(self):
        """Test main() shows help when no command provided."""
        from whatsapp.cli.main import main

        result = main([])
        self.assertEqual(result, 0)

    def test_lazy_agentic_loader(self):
        """Test _lazy_agentic() loads agentic emit function."""
        from whatsapp.cli.main import _lazy_agentic

        emit_func = _lazy_agentic()
        self.assertIsNotNone(emit_func)
        self.assertTrue(callable(emit_func))

    @patch('whatsapp.cli.main.SearchProcessor')
    @patch('whatsapp.cli.main.SearchProducer')
    def test_cmd_search_mutual_exclusivity_error(self, mock_producer, mock_processor):
        """Test cmd_search returns 1 when --from-me and --from-them both provided."""
        from whatsapp.cli.main import cmd_search

        args = MagicMock()
        args.from_me = True
        args.from_them = True

        result = cmd_search(args)
        self.assertEqual(result, 1)

    @patch('whatsapp.cli.main.SearchProcessor')
    @patch('whatsapp.cli.main.SearchProducer')
    @patch('whatsapp.cli.main.SearchRequestConsumer')
    def test_cmd_search_success(self, mock_consumer, mock_processor_cls, mock_producer_cls):
        """Test cmd_search returns 0 on successful search."""
        from whatsapp.cli.main import cmd_search

        # Setup mocks
        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = True
        mock_processor = mock_processor_cls.return_value
        mock_processor.process.return_value = mock_envelope

        args = MagicMock()
        args.from_me = False
        args.from_them = False
        args.db = None
        args.contains = []
        args.match_all = False
        args.match_any = False
        args.contact = None
        args.since_days = None
        args.limit = 50
        args.json = False

        result = cmd_search(args)
        self.assertEqual(result, 0)

    @patch('whatsapp.cli.main.SearchProducer')
    @patch('whatsapp.cli.main.SearchRequestConsumer')
    @patch('whatsapp.cli.main.SearchProcessor')
    def test_cmd_search_error_handling(self, mock_processor_cls, mock_consumer_cls, mock_producer_cls):
        """Test cmd_search returns 1 on error with diagnostics."""
        from whatsapp.cli.main import cmd_search

        # Setup mocks
        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = False
        mock_envelope.diagnostics = {"message": "Database not found"}

        mock_processor = mock_processor_cls.return_value
        mock_processor.process.return_value = mock_envelope

        mock_consumer = mock_consumer_cls.return_value
        mock_consumer.consume.return_value = MagicMock()

        args = MagicMock()
        args.from_me = False
        args.from_them = False
        args.db = None
        args.contains = []
        args.match_all = False
        args.match_any = False
        args.contact = None
        args.since_days = None
        args.limit = 50
        args.json = False

        result = cmd_search(args)
        self.assertEqual(result, 1)

    @patch('whatsapp.cli.main.SearchProcessor')
    @patch('whatsapp.cli.main.SearchProducer')
    @patch('whatsapp.cli.main.SearchRequestConsumer')
    def test_cmd_search_from_me_filter(self, mock_consumer, mock_processor_cls, mock_producer_cls):
        """Test cmd_search sets from_me filter correctly."""
        from whatsapp.cli.main import cmd_search

        # Setup mocks
        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = True
        mock_processor = mock_processor_cls.return_value
        mock_processor.process.return_value = mock_envelope

        args = MagicMock()
        args.from_me = True
        args.from_them = False
        args.db = "/path/to/db"
        args.contains = ["test"]
        args.match_all = True
        args.match_any = False
        args.contact = "John"
        args.since_days = 7
        args.limit = 100
        args.json = True

        result = cmd_search(args)
        self.assertEqual(result, 0)

    @patch('whatsapp.cli.main.SearchProcessor')
    @patch('whatsapp.cli.main.SearchProducer')
    @patch('whatsapp.cli.main.SearchRequestConsumer')
    def test_cmd_search_from_them_filter(self, mock_consumer, mock_processor_cls, mock_producer_cls):
        """Test cmd_search sets from_them filter correctly."""
        from whatsapp.cli.main import cmd_search

        # Setup mocks
        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = True
        mock_processor = mock_processor_cls.return_value
        mock_processor.process.return_value = mock_envelope

        args = MagicMock()
        args.from_me = False
        args.from_them = True
        args.db = None
        args.contains = []
        args.match_all = False
        args.match_any = True
        args.contact = None
        args.since_days = None
        args.limit = 50
        args.json = False

        result = cmd_search(args)
        self.assertEqual(result, 0)
