"""Resume-specific test fixtures.

Docx document fakes, data builders, and sample data for testing.

Structure:
    Docx Fakes:
        FakeRun, FakeParagraph, FakeDocument - Mock python-docx objects

    Data Builders (use defaults, override as needed):
        make_experience_entry() -> dict with title, company, bullets
        make_education_entry()  -> dict with degree, institution, year
        make_candidate()        -> dict with name, email, experience, skills
        make_skills_group()     -> dict with title, items
        make_keyword_spec()     -> dict with required, preferred, nice tiers
        make_empty_profile()    -> dict with all profile fields empty

    Sample Data Constants:
        SAMPLE_EXPERIENCE_ENTRIES  - List of 3 experience dicts
        SAMPLE_SKILLS_GROUPS       - List of 2 skill group dicts
        SAMPLE_CANDIDATE           - Complete candidate with all fields
        SAMPLE_CANDIDATE_WITH_GROUPS - Candidate using skills_groups
        SAMPLE_RESUME_TEXT         - Multi-line resume string
        SAMPLE_CONTACT_LINES       - List of contact info lines
        SAMPLE_PDF_LINES_WITH_SECTIONS - PDF text lines with headers
        SAMPLE_LINKEDIN_HTML       - LinkedIn profile HTML snippet

Usage:
    from tests.resume_tests.fixtures import make_candidate, SAMPLE_EXPERIENCE_ENTRIES

    # Use builder with defaults
    candidate = make_candidate()

    # Override specific fields
    candidate = make_candidate(name="Jane", skills=["Python"])

    # Use sample data directly
    candidate = {"name": "Test", "experience": SAMPLE_EXPERIENCE_ENTRIES[:1]}
"""

from __future__ import annotations

from typing import Any

# Re-export docx fakes from centralized fakes module
from tests.fakes.docx import FakeDocument, FakeParagraph, FakeRun  # noqa: F401

# =============================================================================
# Common Test Values
# =============================================================================

# Define once to avoid duplication across fixtures and tests
SAMPLE_NAME = "John Doe"
SAMPLE_EMAIL = "john@example.com"

# =============================================================================
# Data Builders
# =============================================================================


def make_experience_entry(
    title: str = "Software Developer",
    company: str = "TechCorp",
    start: str = "2020",
    end: str = "2023",
    location: str = "",
    bullets: list[str] | None = None,
) -> dict[str, Any]:
    """Create an experience entry dict for testing.

    Example:
        exp = make_experience_entry(title="Senior Dev", company="BigCo")
        exp = make_experience_entry(bullets=["Built APIs", "Led team"])
    """
    return {
        "title": title,
        "company": company,
        "start": start,
        "end": end,
        "location": location,
        "bullets": bullets if bullets is not None else ["Developed software", "Wrote tests"],
    }


def make_education_entry(
    degree: str = "B.S. Computer Science",
    institution: str = "MIT",
    year: str = "2018",
) -> dict[str, str]:
    """Create an education entry dict for testing."""
    return {
        "degree": degree,
        "institution": institution,
        "year": year,
    }


def make_candidate(
    name: str = SAMPLE_NAME,
    email: str = SAMPLE_EMAIL,
    experience: list[dict] | None = None,
    skills: list[str] | None = None,
    skills_groups: list[dict] | None = None,
    education: list[dict] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Create a candidate/resume dict for testing.

    Example:
        candidate = make_candidate()
        candidate = make_candidate(name="Jane", skills=["Python", "Java"])
        candidate = make_candidate(experience=[make_experience_entry()])
    """
    result: dict[str, Any] = {"name": name, "email": email}
    if experience is not None:
        result["experience"] = experience
    if skills is not None:
        result["skills"] = skills
    if skills_groups is not None:
        result["skills_groups"] = skills_groups
    if education is not None:
        result["education"] = education
    result.update(extra)
    return result


def make_skills_group(
    title: str = "Languages",
    items: list[str | dict] | None = None,
) -> dict[str, Any]:
    """Create a skills group dict for testing.

    Example:
        group = make_skills_group(title="Tools", items=["Docker", "Git"])
        group = make_skills_group(items=[{"name": "Python", "level": "expert"}])
    """
    return {
        "title": title,
        "items": items if items is not None else ["Python", "Java", "Go"],
    }


def make_keyword_spec(
    required: list[str] | None = None,
    preferred: list[str] | None = None,
    nice: list[str] | None = None,
    categories: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Create a keyword spec dict for testing.

    Example:
        spec = make_keyword_spec(required=["Python", "AWS"])
        spec = make_keyword_spec(preferred=["Docker"], nice=["Go"])
    """
    result: dict[str, Any] = {
        "required": required or [],
        "preferred": preferred or [],
        "nice": nice or [],
    }
    if categories:
        result["categories"] = categories
    return result


def make_empty_profile(**overrides: Any) -> dict[str, Any]:
    """Create an empty profile dict with optional overrides.

    Example:
        profile = make_empty_profile(name="John", skills=["Python"])
    """
    profile: dict[str, Any] = {
        "name": "",
        "headline": "",
        "email": "",
        "phone": "",
        "location": "",
        "linkedin": "",
        "github": "",
        "website": "",
        "summary": "",
        "skills": [],
        "experience": [],
        "education": [],
    }
    profile.update(overrides)
    return profile


# =============================================================================
# Sample Data Constants
# =============================================================================

SAMPLE_EXPERIENCE_ENTRIES = [
    {
        "title": "Senior Python Developer",
        "company": "TechCorp",
        "start": "2020",
        "end": "2023",
        "location": "San Francisco",
        "bullets": [
            "Built scalable APIs with Python and FastAPI",
            "Managed PostgreSQL databases",
            "Led team of 5 engineers",
        ],
    },
    {
        "title": "Java Developer",
        "company": "Enterprise Inc",
        "start": "2018",
        "end": "2020",
        "location": "New York",
        "bullets": [
            "Developed Java applications",
            "Used Spring Boot framework",
            "Wrote unit tests",
        ],
    },
    {
        "title": "Frontend Developer",
        "company": "WebAgency",
        "start": "2016",
        "end": "2018",
        "location": "Remote",
        "bullets": [
            "Built React components",
            "Styled with CSS and Tailwind",
            "Implemented responsive designs",
        ],
    },
]

SAMPLE_SKILLS_GROUPS = [
    {
        "title": "Languages",
        "items": [
            {"name": "Python", "level": "expert"},
            {"name": "Java", "level": "intermediate"},
            {"name": "Go", "level": "beginner"},
        ],
    },
    {
        "title": "Tools",
        "items": [
            {"name": "Docker", "desc": "Container orchestration"},
            {"name": "Git", "desc": "Version control"},
        ],
    },
]

SAMPLE_CANDIDATE = {
    "name": SAMPLE_NAME,
    "email": SAMPLE_EMAIL,
    "phone": "(555) 123-4567",
    "location": "San Francisco, CA",
    "headline": "Senior Software Engineer",
    "summary": "10 years of experience building scalable systems",
    "skills": ["Python", "Java", "Docker", "AWS"],
    "experience": SAMPLE_EXPERIENCE_ENTRIES,
    "education": [
        {"degree": "B.S. Computer Science", "institution": "MIT", "year": "2016"},
    ],
}

SAMPLE_CANDIDATE_WITH_GROUPS = {
    "name": SAMPLE_NAME,
    "email": SAMPLE_EMAIL,
    "skills_groups": SAMPLE_SKILLS_GROUPS,
    "experience": SAMPLE_EXPERIENCE_ENTRIES[:2],
}

SAMPLE_RESUME_TEXT = f"""{SAMPLE_NAME}
{SAMPLE_EMAIL}
San Francisco, CA

Summary
Experienced software engineer with 10 years...

Experience
Senior Engineer at TechCorp (2020-2023)
- Built scalable systems

Education
B.S. Computer Science, MIT, 2015

Skills
Python, Java, SQL
"""

SAMPLE_CONTACT_LINES = [
    SAMPLE_NAME,
    "john.doe@example.com",
    "(555) 123-4567",
    "San Francisco, CA",
    "linkedin.com/in/johndoe",
    "github.com/johndoe",
    "https://johndoe.com",
]

SAMPLE_PDF_LINES_WITH_SECTIONS = [
    SAMPLE_NAME,
    "Experience",
    "Senior Dev at Company",
    "Education",
    "BS at University",
    "Skills",
    "Python",
]

SAMPLE_LINKEDIN_HTML = f'''
<html>
<head>
    <meta property="profile:first_name" content="John">
    <meta property="profile:last_name" content="Doe">
    <meta property="og:title" content="{SAMPLE_NAME} - Software Engineer | LinkedIn">
    <meta name="description" content="Senior Engineer · Experience: TechCorp · Location: San Francisco">
    <title>{SAMPLE_NAME} - Software Engineer | LinkedIn</title>
</head>
</html>
'''
