import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


class TestLlmCliExclude(unittest.TestCase):
    def setUp(self):
        # Build a tiny sandbox tree to keep tests fast and hermetic
        self.td_ctx = tempfile.TemporaryDirectory()
        self.root = Path(self.td_ctx.name)
        # Areas
        for d in (
            'mail_assistant',  # included
            'proposals',       # to be excluded via env
            'backups',         # heavy dir skipped by default
            '_disasm',         # heavy dir skipped by default
            'out', '_out',     # heavy dirs skipped by default
        ):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        # Minimal files
        (self.root / 'mail_assistant' / 'a.py').write_text('print("hi")\n', encoding='utf-8')
        (self.root / 'proposals' / 'b.py').write_text('print("proposal")\n', encoding='utf-8')
        (self.root / 'backups' / 'old.txt').write_text('old\n', encoding='utf-8')
        (self.root / '_disasm' / 'ref.txt').write_text('ref\n', encoding='utf-8')
        (self.root / 'out' / 'gen.txt').write_text('gen\n', encoding='utf-8')
        (self.root / '_out' / 'gen.txt').write_text('gen\n', encoding='utf-8')

    def tearDown(self):
        self.td_ctx.cleanup()

    def test_stale_excludes_by_env(self):
        from mail_assistant import llm_cli
        buf = io.StringIO()
        env_val = os.environ.get('LLM_EXCLUDE')
        try:
            os.environ['LLM_EXCLUDE'] = 'proposals'
            with redirect_stdout(buf):
                rc = llm_cli.main(['stale', '--root', str(self.root), '--with-status', '--limit', '15', '--format', 'text'])
            self.assertEqual(rc, 0)
            out = buf.getvalue()
            self.assertNotIn('proposals', out)
        finally:
            if env_val is None:
                os.environ.pop('LLM_EXCLUDE', None)
            else:
                os.environ['LLM_EXCLUDE'] = env_val

    def test_stale_default_skips_heavy_dirs(self):
        from mail_assistant import llm_cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = llm_cli.main(['stale', '--root', str(self.root), '--with-status', '--limit', '15', '--format', 'text'])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        # Heavy dirs are skipped by default in scanners
        self.assertNotIn('backups', out)
        self.assertNotIn('_disasm', out)
        self.assertNotIn('\nout\t', out)   # area name 'out'
        self.assertNotIn('\n_out\t', out)  # area name '_out'

    def test_stale_include_only_mail_assistant(self):
        from mail_assistant import llm_cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = llm_cli.main(['stale', '--root', str(self.root), '--with-status', '--limit', '50', '--format', 'text', '--include', 'mail_assistant'])
        self.assertEqual(rc, 0)
        lines = [ln for ln in buf.getvalue().splitlines() if ln and not ln.startswith('|')]
        hits = [ln for ln in lines if ln.split('\t', 1)[0] == 'mail_assistant']
        # Ensure we saw at least one row for mail_assistant and no unrelated areas
        self.assertTrue(hits, msg='Expected mail_assistant in stale output')
        for ln in lines:
            area = ln.split('\t', 1)[0]
            self.assertIn('mail_assistant', area)

    def test_deps_respects_env_exclude(self):
        from mail_assistant import llm_cli
        buf = io.StringIO()
        env_val = os.environ.get('LLM_EXCLUDE')
        try:
            os.environ['LLM_EXCLUDE'] = 'proposals'
            with redirect_stdout(buf):
                rc = llm_cli.main(['deps', '--root', str(self.root), '--format', 'text', '--limit', '50'])
            self.assertEqual(rc, 0)
            out = buf.getvalue()
            self.assertNotIn('proposals', out)
        finally:
            if env_val is None:
                os.environ.pop('LLM_EXCLUDE', None)
            else:
                os.environ['LLM_EXCLUDE'] = env_val


if __name__ == '__main__':
    unittest.main(verbosity=2)
