import subprocess  # nosec B404
import sys
import unittest
from pathlib import Path


class TestScheduleImporterCLI(unittest.TestCase):
    def test_help_contains_schedule_import(self):
        # schedule-import is now under the outlook subgroup
        root = Path(__file__).resolve().parents[3]
        wrapper = root / "bin" / "assistant"
        out = subprocess.check_output([sys.executable, str(wrapper), "calendar", "outlook", "--help"], text=True)  # nosec B603 - test code with literal args
        self.assertIn("schedule-import", out)


if __name__ == "__main__":
    unittest.main()
