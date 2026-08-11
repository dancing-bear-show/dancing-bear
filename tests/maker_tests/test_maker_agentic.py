"""Tests for maker/agentic.py emit signature."""

import unittest

from tests.fixtures import capture_stdout


class TestEmitAgenticContext(unittest.TestCase):
    def test_returns_0(self):
        from maker.agentic import emit_agentic_context
        with capture_stdout():
            rc = emit_agentic_context()
        self.assertEqual(rc, 0)

    def test_accepts_fmt_and_compact_positionally(self):
        """Signature must match the (fmt, compact) contract CLIApp calls with.

        Previously maker took no params, so callers relied on BaseAssistant's
        blind `except TypeError: emit_func()` retry.
        """
        from maker.agentic import emit_agentic_context
        for fmt in ("text", "yaml", "json"):
            with capture_stdout():
                self.assertEqual(emit_agentic_context(fmt, False), 0)

    def test_prints_agentic_content(self):
        from maker.agentic import emit_agentic_context
        with capture_stdout() as buf:
            emit_agentic_context("text", False)
        self.assertIn("agentic: maker", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
