"""LinkedIn profile parsing helpers for resumes.

Extracted from resume.parsing. Provides:
  - _meta_prop / _meta_name: extract HTML meta tag content
  - _parse_linkedin_name_headline: extract name/headline from meta fields
  - _parse_linkedin_desc: parse description into (summary, location)
  - _parse_linkedin_meta_from_html: parse LinkedIn HTML page meta tags
  - parse_linkedin_text: parse LinkedIn plain text or HTML export
"""
from __future__ import annotations

import re
from typing import Any

from resume.parsing_experience import (
    _split_lines,
    _extract_contact,
    _extract_sections,
    _parse_experience,
    _parse_education,
    _parse_skills,
)


def _meta_prop(html_text: str, prop: str) -> str:
    m = re.search(rf"<meta[^>]+property=\"{re.escape(prop)}\"[^>]+content=\"([^\"]+)\"", html_text, re.I)
    return m.group(1).strip() if m else ""


def _meta_name(html_text: str, name: str) -> str:
    m = re.search(rf"<meta[^>]+name=\"{re.escape(name)}\"[^>]+content=\"([^\"]+)\"", html_text, re.I)
    return m.group(1).strip() if m else ""


def _parse_linkedin_name_headline(first: str, last: str, og_title: str) -> tuple[str, str]:
    """Extract name and headline from LinkedIn meta fields."""
    name = (first + " " + last).strip()
    headline = ""
    if not name and og_title:
        if " - " in og_title:
            name = og_title.split(" - ", 1)[0].strip()
            headline = og_title.split(" - ", 1)[1].split("|")[0].strip()
        else:
            name = og_title.split("|")[0].strip()
    if name and og_title and not headline and " - " in og_title:
        headline = og_title.split(" - ", 1)[1].split("|")[0].strip()
    return name, headline


def _parse_linkedin_desc(desc: str) -> tuple[str, str]:
    """Parse description into (summary, location)."""
    if not desc:
        return "", ""
    parts = [p.strip() for p in desc.split("·")]
    summary = parts[0].strip() if parts else ""
    location = ""
    for p in parts[1:]:
        if p.lower().startswith("location:"):
            location = p.split(":", 1)[1].strip()
    return summary, location


def _parse_linkedin_meta_from_html(html_text: str) -> dict[str, Any]:
    """Extract name/headline/location/summary from meta tags in public profile HTML."""
    title_tag = ""
    m = re.search(r"<title>([^<]+)</title>", html_text, re.I)
    if m:
        title_tag = m.group(1).strip()

    og_title = _meta_prop(html_text, "og:title") or title_tag
    desc = _meta_name(html_text, "og:description") or _meta_name(html_text, "description")
    name, headline = _parse_linkedin_name_headline(
        _meta_prop(html_text, "profile:first_name"),
        _meta_prop(html_text, "profile:last_name"),
        og_title,
    )
    summary, location = _parse_linkedin_desc(desc)

    out: dict[str, Any] = {
        "name": name,
        "headline": headline,
        "email": "",
        "phone": "",
        "location": location,
        "summary": summary,
        "skills": [],
        "experience": [],
        "education": [],
    }
    if any(out.get(k) for k in ("name", "summary", "headline")):
        return out
    return {}


def parse_linkedin_text(text: str) -> dict[str, Any]:
    """Parse LinkedIn plain-text or HTML export into a profile dict."""
    if "<html" in text.lower() or "<meta" in text.lower():
        meta = _parse_linkedin_meta_from_html(text)
        if meta:
            return meta
    lines = _split_lines(text)
    sections = _extract_sections(lines)
    head = lines[0] if lines else ""
    name = head.strip()
    contact = _extract_contact(lines)
    summary = " ".join(sections.get("summary", [])).strip()
    experience = _parse_experience(sections.get("experience", []))
    education = _parse_education(sections.get("education", []))
    skills = _parse_skills(sections.get("skills", []))
    return {
        "name": name,
        "headline": "",
        **contact,
        "summary": summary,
        "skills": skills,
        "experience": experience,
        "education": education,
    }
