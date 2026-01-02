import unittest
import subprocess


class TestScheduleImporterCLI(unittest.TestCase):
    def test_help_contains_schedule_import(self):
        # schedule-import is now under the outlook subgroup
        out = subprocess.check_output(["./bin/assistant", "calendar", "outlook", "--help"], text=True)  # nosec B603 - test code with literal args
        self.assertIn("schedule-import", out)


if __name__ == "__main__":
    unittest.main()
