import sys
import unittest
from unittest.mock import patch

from tests.fixtures import bin_path, repo_root, run


class TestPhoneMain(unittest.TestCase):
    """Test phone/__main__.py module entry point."""

    def test_main_import_exists(self):
        """Test that main function can be imported from __main__."""
        from phone.__main__ import main

        self.assertIsNotNone(main)
        self.assertTrue(callable(main))

    def test_main_returns_zero_with_help(self):
        """Test that main returns 0 when showing help."""
        from phone.__main__ import main

        # Help exits with 0
        with self.assertRaises(SystemExit) as ctx:
            main(["--help"])
        self.assertEqual(ctx.exception.code, 0)


class PhoneCLITests(unittest.TestCase):
    def test_help_via_module_invocation(self):
        proc = run([sys.executable, '-m', 'phone', '--help'])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Phone Assistant CLI', proc.stdout)

    def test_help_via_executable_script(self):
        root = repo_root()
        wrapper = bin_path('phone')
        self.assertTrue(wrapper.exists(), 'bin/phone not found')
        proc = run([sys.executable, str(wrapper), '--help'], cwd=str(root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Phone Assistant CLI', proc.stdout)

    def test_help_via_legacy_script(self):
        root = repo_root()
        wrapper = bin_path('phone-assistant')
        self.assertTrue(wrapper.exists(), 'bin/phone-assistant not found')
        proc = run([sys.executable, str(wrapper), '--help'], cwd=str(root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Phone Assistant CLI', proc.stdout)

    def test_agentic_flag(self):
        proc = run([sys.executable, '-m', 'phone', '--agentic'])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('agentic: phone', proc.stdout)


class PhoneMainTests(unittest.TestCase):
    """Tests for phone/cli/main.py main() function."""

    def test_main_returns_zero_for_agentic(self):
        """Test main() returns 0 for agentic output."""
        from phone.cli.main import main

        result = main(['--agentic'])
        self.assertEqual(result, 0)

    def test_main_no_command_shows_help(self):
        """Test main() shows help when no command provided."""
        from phone.cli.main import main

        result = main([])
        self.assertEqual(result, 0)

    @patch('core.secrets.install_output_masking_from_env')
    def test_main_handles_masking_failure(self, mock_install):
        """Test main() continues when output masking fails."""
        from phone.cli.main import main

        # Simulate masking failure
        mock_install.side_effect = RuntimeError("Masking unavailable")

        result = main(['--agentic'])
        self.assertEqual(result, 0)

    def test_lazy_agentic_loader(self):
        """Test _lazy_agentic() loads agentic emit function."""
        from phone.cli.main import _lazy_agentic

        emit_func = _lazy_agentic()
        self.assertIsNotNone(emit_func)
        self.assertTrue(callable(emit_func))


