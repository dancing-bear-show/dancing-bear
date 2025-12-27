import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from core import assistant_cli


class AssistantCLITests(unittest.TestCase):
    def test_dispatch_known_app_forwards_args(self):
        seen: list[list[str]] = []

        def fake_main(argv=None):
            seen.append(argv or [])
            return 0

        mod = types.SimpleNamespace(main=fake_main)
        with patch.dict(sys.modules, {"fake.mod": mod}):
            with patch.dict(assistant_cli.APP_MODULES, {"fake": "fake.mod"}):
                rc = assistant_cli.main(["fake", "--foo", "bar"])
        self.assertEqual(rc, 0)
        self.assertEqual(seen, [["--foo", "bar"]])

    def test_unknown_app_returns_error(self):
        rc = assistant_cli.main(["nope"])
        self.assertEqual(rc, 2)

    def test_help_prints_usage(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = assistant_cli.main(["--help"])
        self.assertEqual(rc, 0)
        self.assertIn("Usage: assistant", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
