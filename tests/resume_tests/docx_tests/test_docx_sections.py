"""Docx section renderer tests — shim re-exporting split test modules."""
from tests.resume_tests.docx_tests.test_docx_renderers_basic import (  # noqa: F401
    TestBulletRenderer,
    TestHeaderRenderer,
    TestListSectionRenderer,
    TestSectionRenderers,
)
from tests.resume_tests.docx_tests.test_docx_renderers_sections import (  # noqa: F401
    TestSummarySectionRenderer,
    TestSkillsSectionRenderer,
    TestExperienceSectionRenderer,
    TestEducationSectionRenderer,
    TestTechnologiesSectionRenderer,
)

if __name__ == "__main__":
    import unittest
    unittest.main()
