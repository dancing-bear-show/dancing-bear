import io
import unittest
from contextlib import redirect_stdout

from calendars import llm_cli


class TestLlmCli(unittest.TestCase):
    def run_cmd(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = llm_cli.main(argv)
        return rc, buf.getvalue()

    def test_inventory_stdout(self):
        rc, out = self.run_cmd(["inventory", "--stdout"]) 
        self.assertEqual(rc, 0)
        self.assertIn("LLM Agent Inventory", out)

    def test_policies_stdout(self):
        rc, out = self.run_cmd(["policies", "--stdout"]) 
        self.assertEqual(rc, 0)
        self.assertIn("policies:", out)

    def test_agentic_stdout(self):
        rc, out = self.run_cmd(["agentic", "--stdout"]) 
        self.assertEqual(rc, 0)
        self.assertIn("agentic:", out)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()

