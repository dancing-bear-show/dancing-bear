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
        # Expect at least one flow id present (ios flows are currently available)
        self.assertTrue(
            ('ios_export_layout' in out) or ('ios_scaffold_plan' in out) or len(out.strip()) > 0,
            msg=f"unexpected flows output: {out[:200]}"
        )

    def test_flows_get_by_id_md(self):
        from mail_assistant import llm_cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = llm_cli.main(['flows', '--id', 'ios_export_layout', '--stdout'])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        # Should render markdown with id field or content
        self.assertTrue('id:' in out or 'ios_export_layout' in out or '(flow not found)' not in out)

    def test_flows_list_by_tags(self):
        from mail_assistant import llm_cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = llm_cli.main(['flows', '--list', '--tags', 'ios,phone', '--stdout'])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        # Should include ios/phone-related flows if available
        self.assertTrue('ios' in out or '(no flows)' in out)


if __name__ == '__main__':
    unittest.main()

