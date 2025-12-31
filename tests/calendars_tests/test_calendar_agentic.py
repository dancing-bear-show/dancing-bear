import unittest

from tests.fixtures import capture_stdout


class TestCalendarAgentic(unittest.TestCase):
    def test_agentic_flag_outputs_capsule(self):
        import calendars.__main__ as mod

        with capture_stdout() as buf:
            rc = mod.main(["--agentic"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("agentic: calendar", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
