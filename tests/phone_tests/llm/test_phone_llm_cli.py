import unittest

from tests.fixtures import capture_stdout


class TestPhoneLlmCli(unittest.TestCase):
    def test_agentic_stdout(self):
        import phone.llm_cli as mod

        with capture_stdout() as buf:
            rc = mod.main(["agentic", "--stdout"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("agentic: phone", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
