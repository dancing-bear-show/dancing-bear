"""Re-import shim — keeps 'python3 -m unittest tests.metals_tests.excel.test_metals_excel_all' green."""
from tests.metals_tests.excel.test_excel_io import (  # noqa: F401
    TestColLetter,
    TestReadCsv,
    TestToRecords,
    TestMergeAll,
    TestToValuesAll,
    TestSetSheetPosition,
    TestSetSheetVisibility,
    TestFillDateGaps,
    TestListWorksheets,
    TestGetUsedRangeValues,
    TestEnsureSheet,
    TestWriteRange,
    TestWorkbookContextBaseUrl,
    TestPadRows,
    TestPollAsyncOperation,
    TestSumifFormula,
    TestAvgcostFormula,
    TestSummaryRow,
)
from tests.metals_tests.excel.test_excel_chart import (  # noqa: F401
    TestBuildSummaryValues,
    TestAddChart,
    TestWriteFilterView,
    TestSpotCadSeries,
    TestBuildProfitSeries,
)

if __name__ == '__main__':
    import unittest
    unittest.main()
