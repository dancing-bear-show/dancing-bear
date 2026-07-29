"""Shim: re-exports all TranscriptProvider tests from the split modules.

Preserves `python -m unittest tests.telemetry_tests.test_transcript_provider` discovery.
"""
from __future__ import annotations

from tests.telemetry_tests.test_transcript_parse import (  # noqa: F401
    TestComputeTokenCost,
    TestParseAssistantRecord,
    TestParseSessionWithAgents,
    TestParseUserRecord,
)
from tests.telemetry_tests.test_transcript_sessions import (  # noqa: F401
    TestAggregateAgents,
    TestFindSessionFile,
    TestGetCurrentSessionId,
    TestGetSessions,
    TestGetWindowedTotals,
    TestIterJsonlFiles,
    TestProviderConstructor,
    TestSessionSummaryFromFile,
    TestSessionSummaryFromOldFormat,
)

if __name__ == "__main__":
    import unittest
    unittest.main()
