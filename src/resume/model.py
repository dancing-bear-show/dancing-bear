from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

# Type alias for the unified candidate/resume data dictionary produced by merge_profiles()
# and consumed by pipeline, summarizer, and renderer stages.
CandidateData = Dict[str, Any]


@dataclass
class Experience:
    title: str = ""
    company: str = ""
    start: str = ""
    end: str = ""
    location: str = ""
    bullets: List[str] = field(default_factory=list)


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
    skills: List[str] = field(default_factory=list)
    experience: List[Experience] = field(default_factory=list)
    education: List[Education] = field(default_factory=list)

