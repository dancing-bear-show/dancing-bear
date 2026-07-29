"""Re-import shim — keeps 'python3 -m unittest tests.metals_tests.vendors.test_metals_vendors' green."""
from tests.metals_tests.vendors.test_vendors_parse import (  # noqa: F401
    TestTDParser,
    TestCostcoParser,
    TestRCMParser,
    TestFindQtyNear,
    TestInferMetalFromContext,
    TestExtractBasicLineItems,
    TestDedupeLineItems,
    TestDataclasses,
    TestIterNearbyLines,
    TestExtractPriceFromLines,
    TestParseWeightMatch,
    TestFindBundleQty,
    TestRCMParserExtractWeights,
    TestRCMParserClassifyEmailLookup,
    TestRCMParserSubjectRank,
    TestWeightPatternsList,
    TestExtractBasicLineItemsConsolidated,
)
from tests.metals_tests.vendors.test_vendors_search import (  # noqa: F401
    TestVendorLists,
    TestGetVendorForSender,
)

if __name__ == '__main__':
    import unittest
    unittest.main()
