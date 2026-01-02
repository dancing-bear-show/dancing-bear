import unittest

from tests.fixtures import capture_stdout


class TestMakerLLMCLI(unittest.TestCase):
    def test_llm_maker_agentic(self):
        import maker.llm_cli as mod

        with capture_stdout() as buf:
            rc = mod.main(["agentic", "--stdout"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("agentic: maker", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
