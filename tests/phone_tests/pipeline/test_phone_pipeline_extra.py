"""Tests for phone/pipeline.py — re-import shim.

Implementation has moved to:
  - test_pipeline_processors.py  (Processor/Request tests + helper function tests)
  - test_pipeline_producers.py   (Producer tests + standalone helper tests)
"""

from __future__ import annotations

from tests.phone_tests.pipeline.test_pipeline_processors import (  # noqa: F401
    TestAnalyzeProcessorWithPlanPath,
    TestBuildInstallCmd,
    TestChecklistProcessorFileNotFound,
    TestIconmapProcessorEcidResolution,
    TestIdentityVerifyNoLabelNoUdid,
    TestIdentityVerifyProcessorBranches,
    TestManifestFromDeviceProcessorEmptyExport,
    TestManifestFromExportValidation,
    TestManifestInstallProcessor,
    TestPlanFromLayout,
    TestProcessPage,
    TestPruneProcessorCandidateLine,
)
from tests.phone_tests.pipeline.test_pipeline_producers import (  # noqa: F401
    TestAnalyzeProducerBranches,
    TestBaseProducer,
    TestIdentityVerifyProducerBranches,
    TestManifestFromDeviceProducer,
    TestManifestInstallProducer,
    TestParsePingRttLine,
    TestReadLinesFile,
    TestReadLinesFileError,
)

if __name__ == "__main__":
    import unittest
    unittest.main()
