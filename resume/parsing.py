"""Resume text and structured document parsing.

Thin re-export shim. Implementation lives in:
  - resume.parsing_experience: shared utilities, experience/education/skills parsing,
    DOCX helpers, PDF helpers, parse_resume_text, merge_profiles
  - resume.parsing_linkedin: LinkedIn profile parsing, HTML meta extraction

All public symbols are re-exported for backwards compatibility.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Re-exports from parsing_experience
# ---------------------------------------------------------------------------
from resume.parsing_experience import (  # noqa: F401
    SECTION_PATTERNS,
    _STYLE_TITLE_STYLES,
    _STYLE_HEADING_2,
    _DATE_PART,
    _DATE_RANGE_PAT,
    _split_date_range,
    _parse_experience_entry,
    _parse_education_entry,
    _split_lines,
    _match_first,
    _match_website,
    _extract_contact,
    _extract_sections,
    _parse_experience,
    _parse_experience_block,
    _parse_h2_education,
    _parse_h2_experience,
    _process_exp_paragraph,
    _parse_education,
    _parse_skills,
    _filter_summary_lines,
    _key_from_heading,
    _looks_like_company_line,
    _looks_like_section_heading,
    _DocxParaHelper,
    _docx_find_sections,
    _docx_try_extract_name,
    _docx_try_extract_headline,
    _docx_extract_name_headline,
    _docx_extract_summary,
    _docx_extract_experience,
    _docx_extract_education,
    _pdf_empty_result,
    _pdf_extract_name_headline,
    _pdf_looks_like_headline,
    _pdf_looks_like_name,
    _pdf_find_sections,
    _pdf_get_section_lines,
    _pdf_extract_summary,
    _pdf_extract_experience,
    _pdf_extract_education,
    parse_resume_docx,
    parse_resume_pdf,
    parse_resume_text,
    merge_profiles,
)

# ---------------------------------------------------------------------------
# Re-exports from parsing_linkedin
# ---------------------------------------------------------------------------
from resume.parsing_linkedin import (  # noqa: F401
    _meta_prop,
    _meta_name,
    _parse_linkedin_name_headline,
    _parse_linkedin_desc,
    _parse_linkedin_meta_from_html,
    parse_linkedin_text,
)
