"""Tests for maker/agentic.py emit signature."""

import unittest

from tests.agentic_builder_contract import AgenticBuilderContractMixin
from tests.fixtures import capture_stdout


class TestMakerAgenticContract(AgenticBuilderContractMixin, unittest.TestCase):
    """The shared agentic builder contract."""

    MODULE_PATH = "maker.agentic"
    APP_ID = "maker"
    EXPECT_CLI_TREE = False


class TestEmitAgenticContext(unittest.TestCase):
    def test_accepts_fmt_and_compact_positionally(self):
        """Signature must match the (fmt, compact) contract CLIApp calls with.

        Previously maker took no params, so callers relied on BaseAssistant's
        blind `except TypeError: emit_func()` retry.
        """
        from maker.agentic import emit_agentic_context
        for fmt in ("text", "yaml", "json"):
            with capture_stdout():
                self.assertEqual(emit_agentic_context(fmt, False), 0)


if __name__ == "__main__":
    unittest.main()
