"""Resume pipeline tests — shim re-exporting split test modules."""
from tests.resume_tests.pipeline.test_pipeline_filters import (  # noqa: F401
    TestFilterPipelineInit,
    TestFilterPipelineChaining,
    TestWithProfileOverlays,
    TestWithSynonymsFromJob,
    TestWithSkillFilter,
    TestWithExperienceFilter,
    TestWithPriorityFilter,
)
from tests.resume_tests.pipeline.test_pipeline_execute import (  # noqa: F401
    TestExecute,
    TestExtractMatchedKeywords,
    TestCreatePipeline,
    TestApplyFiltersFromArgs,
)

if __name__ == "__main__":
    import unittest
    unittest.main()
