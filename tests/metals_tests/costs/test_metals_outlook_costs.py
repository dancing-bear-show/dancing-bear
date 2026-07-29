"""Re-import shim — keeps 'python3 -m unittest tests.metals_tests.costs.test_metals_outlook_costs' green."""
from tests.metals_tests.costs.test_outlook_costs_extract import (  # noqa: F401
    TestClassifySubject,
    TestHtmlToText,
    TestExtractOrderId,
    TestExtractLineItems,
    TestExtractOrderAmount,
    TestAmountNearItem,
    TestExtractConfirmationItemTotals,
)
from tests.metals_tests.costs.test_outlook_costs_compute import (  # noqa: F401
    TestMergeWrite,
    TestTrimDisclaimerLines,
    TestSummarizeOunces,
    TestComputeConfirmationLineCosts,
    TestComputeProximityLineCosts,
    TestBuildGoldRow,
    TestRcmQueries,
    TestFetchRcmMessageIds,
    TestFilterAndGroupByOrder,
    TestTryUpgradeToConfirmation,
)

if __name__ == '__main__':
    import unittest
    unittest.main()
