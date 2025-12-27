import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch


class EnvSetupTests(unittest.TestCase):
    def test_env_setup_persists_ini_without_venv(self):
        # Redirect INI paths to a temp file to avoid touching user config
        from mail import config_resolver as cr
        td = tempfile.mkdtemp()
        ini_path = os.path.join(td, 'credentials.ini')
        with patch.object(cr, '_INI_PATHS', [ini_path]):
            from mail.config_cli.commands import run_env_setup
            args = SimpleNamespace(
                venv_dir=os.path.join(td, '.venv'),
                no_venv=True,
                skip_install=True,
                profile='unittest',
                credentials=os.path.join(td, 'cred.json'),
                token=os.path.join(td, 'tok.json'),
                outlook_client_id=None,
                tenant=None,
                outlook_token=None,
                copy_gmail_example=False,
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_env_setup(args)
            self.assertEqual(rc, 0)
            # Verify INI written
            import configparser
            cp = configparser.ConfigParser()
            cp.read(ini_path)
            section = 'mail.unittest'
            self.assertTrue(cp.has_section(section))
            self.assertEqual(cp.get(section, 'credentials'), args.credentials)
            self.assertEqual(cp.get(section, 'token'), args.token)


if __name__ == '__main__':
    unittest.main()

