"""Resume parsing tests — shim re-exporting split test modules."""
from tests.resume_tests.parsing.test_parsing_experience import (  # noqa: F401
    PdfSectionTestCase,
    TestSectionPatterns,
    TestParseExperienceEntry,
    TestParseEducationEntry,
    TestSplitLines,
    TestExtractContact,
    TestExtractSections,
    TestParseExperience,
    TestParseExperienceBlock,
    TestParseEducation,
    TestParseSkills,
    TestSplitDateRange,
    TestFilterSummaryLines,
    TestKeyFromHeading,
    TestLooksLikeCompanyLine,
    TestLooksLikeSectionHeading,
    TestParseResumeText,
    TestMergeProfiles,
)
from tests.resume_tests.parsing.test_parsing_linkedin import (  # noqa: F401
    TestPdfEmptyResult,
    TestPdfExtractNameHeadline,
    TestPdfFindSections,
    TestPdfGetSectionLines,
    TestPdfExtractSummary,
    TestPdfExtractExperience,
    TestPdfExtractEducation,
    TestParseLinkedinMetaFromHtml,
    TestParseLinkedinText,
)

if __name__ == "__main__":
    import unittest
    unittest.main()
