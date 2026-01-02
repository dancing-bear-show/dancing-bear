import unittest

from tests.fixtures import capture_stdout


class TestCalendarFamiliarVerbose(unittest.TestCase):
    def test_calendar_familiar_verbose_includes_outlook_steps(self):
        import calendars.llm_cli as mod

        with capture_stdout() as buf:
            rc = mod.main(["familiar", "--stdout", "--verbose"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("outlook auth ensure", out)
        self.assertIn("outlook auth validate", out)
