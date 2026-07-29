"""Tests for phone/layout.py — re-import shim.

Implementation has moved to:
  - test_layout_normalize.py  (TestExtractBundleId, TestIsFolder, TestIsAppItem, etc.)
  - test_layout_plan.py       (TestScaffoldPlan, TestChecklistFromPlan, TestAnalyzeLayout, etc.)
"""

from __future__ import annotations

from tests.phone_tests.layout.test_layout_normalize import (  # noqa: F401
    TestExtractBundleId,
    TestFlattenFolderIconlists,
    TestGetAppId,
    TestGetFolderApps,
    TestGetFolderName,
    TestIsAppItem,
    TestIsFolder,
    TestIsFolderItem,
    TestNormalizeIconstate,
    TestNormalizedLayoutDataclass,
    TestToYamlExport,
)
from tests.phone_tests.layout.test_layout_plan import (  # noqa: F401
    TestAnalyzeLayout,
    TestAutoFolderize,
    TestChecklistFromPlan,
    TestComputeFolderPageMap,
    TestComputeLocationMap,
    TestComputeRootAppPageMap,
    TestDistributeFoldersAcrossPages,
    TestListAllApps,
    TestRankUnusedCandidates,
    TestScaffoldPlan,
)

if __name__ == "__main__":
    import unittest
    unittest.main()
