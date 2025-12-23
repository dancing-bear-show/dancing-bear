import io
import sys
import unittest

from tests.fixtures import repo_root


class TestCalendarAgentic(unittest.TestCase):
    def test_agentic_flag_outputs_capsule(self):
        # Ensure parent of repo is importable
        root = repo_root()
        sys.path.insert(0, str(root.parent))
        import calendars.__main__ as mod  # type: ignore
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            rc = mod.main(["--agentic"])  # should exit early and return 0
        finally:
            sys.stdout = old
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("agentic: calendar", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
