"""Re-import shim — keeps 'python3 -m unittest tests.metals_tests.costs.test_cost_extractor' green."""
from tests.metals_tests.costs.test_cost_extractor_base import (  # noqa: F401
    MockCostExtractor,
    TestCostExtractorBaseClass,
    TestMessageInfo,
    TestOrderData,
)
from tests.metals_tests.costs.test_cost_extractor_gmail import (  # noqa: F401
    TestOutlookCostExtractorHelpers,
    TestGmailCostExtractorIntegration,
)

if __name__ == '__main__':
    import unittest
    unittest.main()
