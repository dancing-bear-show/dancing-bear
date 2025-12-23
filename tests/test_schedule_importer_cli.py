import unittest
import subprocess


class TestScheduleImporterCLI(unittest.TestCase):
    def test_help_contains_schedule_import(self):
        out = subprocess.check_output(["./bin/assistant", "calendar", "--help"], text=True)  # nosec B603
        self.assertIn("schedule-import", out)


if __name__ == "__main__":
    unittest.main()
