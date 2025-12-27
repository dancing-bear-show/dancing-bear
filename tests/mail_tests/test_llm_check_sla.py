import os
import sys
import unittest
from pathlib import Path


class TestLLMCheckSLA(unittest.TestCase):
    def setUp(self) -> None:
        pkg_parent = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(pkg_parent))

    def test_check_passes_with_high_sla(self):
        import mail.llm_cli as mod  # type: ignore
        old_env = os.environ.get('LLM_SLA')
        try:
            os.environ['LLM_SLA'] = 'Root:9999,mail:9999,bin:9999,.llm:9999,config:9999,tests:9999'
            rc = mod.main(['check', '--root', '.', '--limit', '10'])
        finally:
            if old_env is None:
                os.environ.pop('LLM_SLA', None)
            else:
                os.environ['LLM_SLA'] = old_env
        self.assertEqual(rc, 0)

    def test_stale_fails_with_low_sla(self):
        import io
        import mail.llm_cli as mod  # type: ignore

        # First check if any files are actually stale (they won't be in CI fresh checkout)
        buf = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buf
            mod.main(['stale', '--format', 'json', '--limit', '5'])
        finally:
            sys.stdout = old_stdout

        import json
        stats = json.loads(buf.getvalue())
        if not stats or all(s.get('staleness_days', 0) < 0.01 for s in stats):
            self.skipTest('Skipped in CI: fresh checkout has no stale files')

        old_env = os.environ.get('LLM_SLA')
        try:
            os.environ['LLM_SLA'] = 'mail:0,Root:0,bin:0,config:0,tests:0,.llm:0'
            # Include --with-priority to use code path that returns non-zero on fail
            rc = mod.main(['stale', '--with-status', '--with-priority', '--fail-on-stale', '--limit', '5'])
        finally:
            if old_env is None:
                os.environ.pop('LLM_SLA', None)
            else:
                os.environ['LLM_SLA'] = old_env
        self.assertEqual(rc, 2)
