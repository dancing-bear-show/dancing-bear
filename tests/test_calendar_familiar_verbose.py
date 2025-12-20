import io
import sys
import unittest

from tests.fixtures import repo_root


class TestCalendarFamiliarVerbose(unittest.TestCase):
    def test_calendar_familiar_verbose_includes_outlook_steps(self):
        root = repo_root()
        # Ensure repo root is importable for calendar_assistant
        sys.path.insert(0, str(root))
        sys.path.insert(0, str(root.parent))
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
