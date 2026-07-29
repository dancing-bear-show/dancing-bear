"""Shim: re-exports all tests from test_classify_bash and test_classify_patterns.

Import from the split modules so `python -m unittest tests.telemetry_tests.test_classify`
continues to work and discovers all test classes.
"""
from __future__ import annotations

from tests.telemetry_tests.test_classify_bash import (  # noqa: F401
    TestApplyCustomRules,
    TestClassifyBash,
    TestDefaultClassification,
    TestFirstPassFailedTool,
    TestRapidReEdit,
    TestRedundantRead,
)
from tests.telemetry_tests.test_classify_patterns import (  # noqa: F401
    TestClassifyAbandonedSearch,
    TestClassifyEndToEnd,
    TestClassifyFruitlessAgent,
)

if __name__ == "__main__":
    import unittest
    unittest.main()
