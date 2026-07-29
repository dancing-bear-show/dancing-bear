# metals domain split summary

## Phase 1 — Source file splits

| Original file | Lines | Submodule | Lines | Contents |
|---|---|---|---|---|
| `metals/excel_all.py` | 746 | `metals/excel_io.py` | 201 | I/O helpers: `_read_csv`, `_list_worksheets`, `_get_used_range_values`, `_to_records`, `_merge_all`, `_poll_async_operation`, `_ensure_sheet`, `_set_sheet_position`, `_set_sheet_visibility`, `_to_values_all`, `_read_existing_workbook_recs` |
| | | `metals/excel_chart.py` | 499 | Chart/summary helpers: `AVG_COST_HDR`, `TOTAL_OZ_HDR`, `_add_chart`, `_write_filter_view`, `_sumif_formula`, `_avgcost_formula`, `_summary_row`, aggregation helpers, `_fill_date_gaps`, `_fetch_yahoo_series`, `_spot_cad_series`, `MetalPosition`, profit series helpers |
| `metals/gmail_costs.py` | 834 | `metals/gmail_costs_qty.py` | 449 | Quantity/price extraction primitives: `LineItemContext`, `ExtractionContext`, `PriceLineContext`, all extraction helpers, `_PAT_FRAC`, `_PAT_G`, `_PAT_OZ`, `_PAT_QTY_LIST` |
| | | `metals/gmail_costs_extract.py` | 388 | `OrderRowData`, order patterns, `_classify_vendor`, `_is_order_confirmation`, `_is_cancelled`, order processing, `GmailCostExtractor` |
| `metals/vendors.py` | 655 | `metals/vendors_parse.py` | 613 | All dataclasses, `VendorParser` ABC, `TDParser`, `CostcoParser`, `RCMParser`, shared utilities |
| | | `metals/vendors_search.py` | 25 | `ALL_VENDORS`, `GMAIL_VENDORS`, `OUTLOOK_VENDORS`, `get_vendor_for_sender` |

Originals rewritten as thin re-export shims (unchanged public API).

## Phase 2 — Test file splits

| Original file | New split file | Line count | Test classes |
|---|---|---|---|
| `tests/metals_tests/excel/test_metals_excel_all.py` | `test_excel_io.py` | 481 | TestColLetter, TestReadCsv, TestToRecords, TestMergeAll, TestToValuesAll, TestSetSheetPosition, TestSetSheetVisibility, TestFillDateGaps, TestListWorksheets, TestGetUsedRangeValues, TestEnsureSheet, TestWriteRange, TestWorkbookContextBaseUrl, TestPadRows, TestPollAsyncOperation, TestSumifFormula, TestAvgcostFormula, TestSummaryRow |
| | `test_excel_chart.py` | 235 | TestBuildSummaryValues, TestAddChart, TestWriteFilterView, TestSpotCadSeries, TestBuildProfitSeries |
| `tests/metals_tests/spot/test_metals_spot.py` | `test_spot_fetch.py` | 412 | TestTodayIso, TestFetchYahooSeries, TestFetchStooqSeries, TestAutoStartDate |
| | `test_spot_run.py` | 122 | TestRun, TestMain |
| `tests/metals_tests/vendors/test_metals_vendors.py` | `test_vendors_parse.py` | 639 | TestTDParser, TestCostcoParser, TestRCMParser, TestFindQtyNear, TestInferMetalFromContext, TestExtractBasicLineItems, TestDedupeLineItems, TestDataclasses, TestIterNearbyLines, TestExtractPriceFromLines, TestParseWeightMatch, TestFindBundleQty, TestRCMParserExtractWeights, TestRCMParserClassifyEmailLookup, TestRCMParserSubjectRank, TestWeightPatternsList, TestExtractBasicLineItemsConsolidated |
| | `test_vendors_search.py` | 66 | TestVendorLists, TestGetVendorForSender |
| `tests/metals_tests/costs/test_cost_extractor.py` | `test_cost_extractor_base.py` | 168 | MockCostExtractor, TestCostExtractorBaseClass, TestMessageInfo, TestOrderData |
| | `test_cost_extractor_gmail.py` | 450 | TestOutlookCostExtractorHelpers, TestGmailCostExtractorIntegration |
| `tests/metals_tests/costs/test_metals_gmail_costs.py` | `test_gmail_costs_extract.py` | 352 | TestExtractLineItems, TestExtractOrderAmount, TestClassifyVendor, TestIsOrderConfirmation, TestIsCancelled, TestParseMatchFunctions |
| | `test_gmail_costs_qty.py` | 415 | TestExtractAmountNearLine, TestBundleAndSKUDetection, TestExtractAmountNearLineAdvanced, TestExtractFirstMatchGroup, TestExplicitQtyNear, TestBundleQtyNear, TestUnitOzOverrideNear |
| | `test_gmail_costs_build.py` | 249 | TestBuildUozPatterns, TestTryAnchoredExtraction, TestDeterminePriceKind, TestComputeLineCosts, TestAllocateCosts, TestBuildOrderRows |
| `tests/metals_tests/costs/test_metals_outlook_costs.py` | `test_outlook_costs_extract.py` | 296 | TestClassifySubject, TestHtmlToText, TestExtractOrderId, TestExtractLineItems, TestExtractOrderAmount, TestAmountNearItem, TestExtractConfirmationItemTotals |
| | `test_outlook_costs_compute.py` | 490 | TestMergeWrite, TestTrimDisclaimerLines, TestSummarizeOunces, TestComputeConfirmationLineCosts, TestComputeProximityLineCosts, TestBuildGoldRow, TestRcmQueries, TestFetchRcmMessageIds, TestFilterAndGroupByOrder, TestTryUpgradeToConfirmation |

Originals rewritten as re-import shims (backwards-compatible with `python3 -m unittest <original_path>`).

## Test suite result

- Total tests: 1039
- Status: OK (all passing)
