import io
import sys
import unittest
from pathlib import Path


class TestAgenticFlows(unittest.TestCase):
    def test_agentic_includes_forwarding_and_auto(self):
        # Ensure parent of package dir is importable
        pkg_parent = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(pkg_parent))
        import mail_assistant.__main__ as mod  # type: ignore
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            rc = mod.main(["--agentic"])  # prints capsule
        finally:
            sys.stdout = old
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        # Specific flow entries should be present when CLI supports them
        self.assertIn("Forwarding + Filters", out)
        self.assertIn("Auto (categorize + archive)", out)

    def test_agentic_includes_outlook_categories_and_folders(self):
        pkg_parent = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(pkg_parent))
        import mail_assistant.__main__ as mod  # type: ignore
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            rc = mod.main(["--agentic"])  # prints capsule
        finally:
            sys.stdout = old
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Outlook Categories", out)
        self.assertIn("Outlook Folders", out)
