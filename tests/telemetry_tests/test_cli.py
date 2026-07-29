"""Shim: re-exports all CLI tests from the split test modules.

Preserves `python -m unittest tests.telemetry_tests.test_cli` discovery.
"""
from __future__ import annotations

from tests.telemetry_tests.test_cli_formatters import (  # noqa: F401
    TestFmtDuration,
    TestFmtTokens,
    TestParseSinceCli,
    TestTruncateId,
)
from tests.telemetry_tests.test_cli_sessions import (  # noqa: F401
    TestAgentRowToDict,
    TestBreakdownByAgent,
    TestBreakdownByDay,
    TestBuildAgentsTable,
    TestBuildBreakdownTable,
    TestBuildSessionsTable,
    TestPrintAgentsCsv,
    TestPrintAgentsJson,
    TestPrintCostCsv,
    TestSessionToDict,
    TestSessionsJsonPayload,
)
from tests.telemetry_tests.test_cli_rules import (  # noqa: F401
    TestAgentsCommand,
    TestCostBreakdownCommand,
    TestHistoryCommand,
    TestMainCLI,
    TestOtelCommand,
    TestRulesCommand,
    TestRulesExplain,
    TestRulesInit,
    TestRulesList,
    TestRulesValidate,
    TestSessionsCommand,
)

if __name__ == "__main__":
    import unittest
    unittest.main()
