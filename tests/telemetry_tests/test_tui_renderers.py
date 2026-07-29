"""Shim: re-exports all tui renderer tests from the split modules.

Preserves `python -m unittest tests.telemetry_tests.test_tui_renderers` discovery.
"""
from __future__ import annotations

from tests.telemetry_tests.test_tui_render_core import (  # noqa: F401
    TestEventInputDetail,
    TestRenderClsGroup,
    TestRenderHeaderText,
    TestRenderTipsText,
    TestToolEventDetail,
)
from tests.telemetry_tests.test_tui_render_panels import (  # noqa: F401
    TestAgentDetail,
    TestEfficiencyColor,
    TestPrintAgentsPanel,
    TestPrintToolStatsPanel,
    TestRenderStatsCompact,
    TestRenderStatsPanel,
    TestRenderTimelineLine,
    TestStatsDurationStr,
    TestStatsSessionLabel,
    TestTipDetail,
    TestToolStatDetail,
)

if __name__ == "__main__":
    import unittest
    unittest.main()
