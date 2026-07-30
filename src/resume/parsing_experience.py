"""Resume experience, education, skills, and document parsing helpers.

Extracted from resume.parsing. Provides all parsing logic except LinkedIn:
  - SECTION_PATTERNS: section heading regex patterns
  - _split_lines / _extract_contact / _extract_sections: shared utilities
  - _split_date_range / _parse_experience_entry / _parse_education_entry: entry parsers
  - _parse_experience / _parse_experience_block / _parse_education / _parse_skills: section parsers
  - _filter_summary_lines / _key_from_heading / _looks_like_* : heuristics
  - _DocxParaHelper + _docx_*: DOCX parsing helpers
  - parse_resume_docx: DOCX public API
  - _pdf_*: PDF parsing helpers
  - parse_resume_pdf: PDF public API
  - parse_resume_text / merge_profiles: public API

This module is a re-export shim. Implementation lives in:
  - parsing_experience_text: plain-text parser
  - parsing_experience_docx: DOCX parser
  - parsing_experience_pdf: PDF parser
"""
from __future__ import annotations

from .parsing_experience_text import (  # noqa: F401
    SECTION_PATTERNS,
    _DATE_PART,
    _DATE_RANGE_PAT,
    _PAT_EMAIL,
    _PAT_GITHUB,
    _PAT_LINKEDIN,
    _PAT_LOCATION,
    _PAT_PHONE,
    _PAT_WEBSITE,
    _extract_contact,
    _extract_sections,
    _match_first,
    _match_website,
    _parse_education,
    _parse_education_entry,
    _parse_experience,
    _parse_experience_block,
    _parse_experience_entry,
    _parse_skills,
    _split_date_range,
    _split_lines,
    merge_profiles,
    parse_resume_text,
)
from .parsing_experience_docx import (  # noqa: F401
    _STYLE_HEADING_2,
    _STYLE_TITLE_STYLES,
    _DocxParaHelper,
    _docx_extract_education,
    _docx_extract_experience,
    _docx_extract_name_headline,
    _docx_extract_summary,
    _docx_find_sections,
    _docx_try_extract_headline,
    _docx_try_extract_name,
    _filter_summary_lines,
    _key_from_heading,
    _looks_like_company_line,
    _looks_like_section_heading,
    _parse_h2_education,
    _parse_h2_experience,
    _process_exp_paragraph,
    parse_resume_docx,
)
from .parsing_experience_pdf import (  # noqa: F401
    _pdf_empty_result,
    _pdf_extract_education,
    _pdf_extract_experience,
    _pdf_extract_name_headline,
    _pdf_extract_summary,
    _pdf_find_sections,
    _pdf_get_section_lines,
    _pdf_looks_like_headline,
    _pdf_looks_like_name,
    parse_resume_pdf,
)
