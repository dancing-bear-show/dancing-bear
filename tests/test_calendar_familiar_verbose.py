import io
import sys
import unittest
from pathlib import Path


class TestCalendarFamiliarVerbose(unittest.TestCase):
    def test_calendar_familiar_verbose_includes_outlook_steps(self):
        repo_root = Path(__file__).resolve().parents[1]
        # Ensure repo root is importable for calendar_assistant
        sys.path.insert(0, str(repo_root))
        sys.path.insert(0, str(repo_root.parent))
        import calendar_assistant.llm_cli as mod  # type: ignore
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            rc = mod.main(["familiar", "--stdout", "--verbose"])  # prints YAML
        finally:
            sys.stdout = old
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("outlook auth ensure", out)
        self.assertIn("outlook auth validate", out)
