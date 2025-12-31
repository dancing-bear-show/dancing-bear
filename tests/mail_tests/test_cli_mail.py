import unittest

from tests.fixtures import capture_stdout


class TestAgenticFlag(unittest.TestCase):
    def test_agentic_outputs_capsule(self):
        import mail.__main__ as mod

        with capture_stdout() as buf:
            rc = mod.main(["--agentic"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("agentic: mail", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
