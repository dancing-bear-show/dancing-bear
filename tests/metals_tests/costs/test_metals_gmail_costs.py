"""Re-import shim — keeps 'python3 -m unittest tests.metals_tests.costs.test_metals_gmail_costs' green."""
from tests.metals_tests.costs.test_gmail_costs_extract import (  # noqa: F401
    TestExtractLineItems,
    TestExtractOrderAmount,
    TestClassifyVendor,
    TestIsOrderConfirmation,
    TestIsCancelled,
    TestParseMatchFunctions,
)
from tests.metals_tests.costs.test_gmail_costs_qty import (  # noqa: F401
    TestExtractAmountNearLine,
    TestBundleAndSKUDetection,
    TestExtractAmountNearLineAdvanced,
    TestExtractFirstMatchGroup,
    TestExplicitQtyNear,
    TestBundleQtyNear,
    TestUnitOzOverrideNear,
)
from tests.metals_tests.costs.test_gmail_costs_build import (  # noqa: F401
    TestBuildUozPatterns,
    TestTryAnchoredExtraction,
    TestDeterminePriceKind,
    TestComputeLineCosts,
    TestAllocateCosts,
    TestBuildOrderRows,
)

if __name__ == '__main__':
    import unittest
    unittest.main()
