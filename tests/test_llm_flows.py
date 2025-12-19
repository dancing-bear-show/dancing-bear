import io
import unittest
from contextlib import redirect_stdout


class TestLlmFlowsCLI(unittest.TestCase):
    def test_flows_list_stdout(self):
        from mail_assistant import llm_cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = llm_cli.main(['flows', '--list', '--stdout'])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        # Expect at least one core flow id present
        self.assertTrue(
            ('gmail.filters.plan-apply-verify' in out) or ('unified.derive' in out) or ('gmail.labels.plan-apply-verify' in out),
            msg=f"unexpected flows output: {out[:200]}"
        )

    def test_flows_get_by_id_md(self):
        from mail_assistant import llm_cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = llm_cli.main(['flows', '--id', 'gmail.filters.plan-apply-verify', '--stdout'])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        # Should render markdown with commands or a not found message
        self.assertIn('id:', out)

    def test_flows_list_by_tags(self):
        from mail_assistant import llm_cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = llm_cli.main(['flows', '--list', '--tags', 'gmail,plan', '--stdout'])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        # Should include only gmail+plan-related flows if available
        self.assertIn('gmail', out)


if __name__ == '__main__':
    unittest.main()

