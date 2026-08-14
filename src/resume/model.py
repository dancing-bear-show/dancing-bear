from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Type alias for the unified candidate/resume data dictionary produced by merge_profiles()
# and consumed by pipeline, summarizer, and renderer stages.
CandidateData = dict[str, Any]


@dataclass
class Experience:
    title: str = ""
    company: str = ""
    start: str = ""
    end: str = ""
    location: str = ""
    bullets: list[str] = field(default_factory=list)


@dataclass
class Education:
    degree: str = ""
    institution: str = ""
    year: str = ""


@dataclass
class Resume:
    name: str = ""
    headline: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    summary: str = ""
    skills: list[str] = field(default_factory=list)
    experience: list[Experience] = field(default_factory=list)
    education: list[Education] = field(default_factory=list)

