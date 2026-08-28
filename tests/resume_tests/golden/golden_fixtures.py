"""Synthetic resume fixtures for the golden rendering harness.

Every value here is invented. Nothing is derived from any real profile: the
goldens built from these fixtures are committed to the repository, so a
fixture seeded from real candidate data would publish PII permanently. Names,
addresses, phone numbers and hosts use reserved/example forms (``example.com``,
``.invalid``, the 555-01xx reserved block).

Each fixture pins an input shape the typed-schema migration could break. The
shapes are deliberately mixed *within* fixtures as well as across them, because
real data mixes them — ``skills_groups`` entries that carry ``priority``
alongside entries that omit it is the exact pattern observed in practice.
"""

from __future__ import annotations

from typing import Any

# --- templates -------------------------------------------------------------

_STAFF_ENGINEER = "Staff Engineer"

_SECTIONS = [
    {"key": "summary", "title": "Summary"},
    {"key": "skills", "title": "Skills"},
    {"key": "experience", "title": "Experience"},
    {"key": "education", "title": "Education"},
    {"key": "presentations", "title": "Presentations"},
    {"key": "teaching", "title": "Teaching"},
    {"key": "certifications", "title": "Certifications"},
]


def standard_template() -> dict[str, Any]:
    """Single-column layout template."""
    return {
        "page": {"compact": True, "h1_bg": "#EEF3F8", "body_pt": 10, "meta_pt": 9},
        "sections": [dict(s) for s in _SECTIONS],
    }


def sidebar_template() -> dict[str, Any]:
    """Two-column sidebar layout template over the same section set."""
    return {
        "page": {"compact": True, "body_pt": 10, "meta_pt": 9},
        "layout": {
            "type": "sidebar",
            "sidebar_width": 2.3,
            "main_width": 5.2,
            "sidebar_bg": "#F2F5F8",
        },
        "sidebar_sections": [
            {"key": "summary", "title": "Profile"},
            {"key": "skills", "title": "Skills"},
        ],
        "sections": [dict(s) for s in _SECTIONS],
    }


# --- candidate fixtures ----------------------------------------------------


def candidate_dict_bullets() -> dict[str, Any]:
    """Bullets as dicts with text/priority/desc — the shape real data uses."""
    return {
        "name": "Ada Placeholder",
        "headline": "Staff Reliability Engineer",
        "email": "ada@example.com",
        "phone": "+1-555-0142",
        "location": "Fictional City, ZZ",
        "linkedin": "linkedin.com/in/ada-placeholder",
        "summary": [
            {"text": "Runs imaginary systems at imaginary scale.", "priority": 1},
            {"text": "Mentors an invented team of six.", "priority": 3},
        ],
        "skills_groups": [
            # First group carries priority; second deliberately omits it.
            {"name": "Platform", "items": ["Kubernetes", "Terraform"], "priority": 1},
            {"name": "Languages", "items": ["Python", "Go"]},
        ],
        "experience": [
            {
                "title": _STAFF_ENGINEER,
                "company": "Nonexistent Systems",
                "location": "Fictional City, ZZ",
                "start": "2021",
                "end": "2025",
                "bullets": [
                    {
                        "text": "Cut fictional latency by a made-up amount.",
                        "priority": 1,
                        "desc": "Detail line that must survive the migration.",
                    },
                    {"text": "Wrote a runbook nobody has read.", "priority": 2},
                ],
            }
        ],
        "education": [
            {"degree": "BSc Imaginary Computing", "institution": "Invented University", "year": 2015}
        ],
        "certifications": [{"name": "Certified Fictional Operator", "year": 2022}],
    }


def candidate_string_bullets() -> dict[str, Any]:
    """Legacy shape: bullets and summary entries as bare strings."""
    return {
        "name": "Grace Placeholder",
        "headline": "Principal Engineer",
        "email": "grace@example.com",
        "phone": "+1-555-0177",
        "location": "Imaginary Town, ZZ",
        "summary": ["A plain string summary line.", "A second plain string line."],
        "skills": ["Python", "Distributed Systems", "Observability"],
        "experience": [
            {
                "title": "Principal Engineer",
                "company": "Placeholder Industries",
                "start": "2018",
                "end": "2021",
                "bullets": [
                    "A legacy bare-string bullet.",
                    "Another legacy bare-string bullet.",
                ],
            }
        ],
        "education": [
            {"degree": "MSc Fictional Studies", "institution": "Placeholder College", "year": "2012"}
        ],
        "teaching": ["Intro to Nothing (Placeholder College)"],
    }


def candidate_alias_keys() -> dict[str, Any]:
    """Items keyed by the aliases ``label``/``line`` rather than ``name``/``text``."""
    return {
        "name": "Alan Placeholder",
        "headline": "Systems Engineer",
        "email": "alan@example.com",
        "location": "Nowhere, ZZ",
        "summary": [{"line": "Summary supplied via the 'line' alias."}],
        "skills_groups": [
            {"label": "Infrastructure", "items": ["Linux", "Networking"], "priority": 2},
            {"label": "Tooling", "items": ["Bash"]},
        ],
        "experience": [
            {
                "title": "Systems Engineer",
                "company": "Alias Corp",
                "start": "2016",
                "end": "2018",
                "bullets": [
                    {"line": "Bullet supplied via the 'line' alias.", "priority": 1},
                    {"text": "Bullet supplied via the canonical 'text' key."},
                ],
            }
        ],
        "certifications": [{"label": "Alias-Keyed Certification"}],
    }


def candidate_extra_keys() -> dict[str, Any]:
    """Unknown keys at top level and on nested items; presentations[].year as int.

    ``year`` being an int is what real data does. The migration must not coerce
    it to a string — a golden over the rendered XML is what proves it did not.
    """
    return {
        "name": "Edith Placeholder",
        "headline": "Research Engineer",
        "email": "edith@example.com",
        "phone": "+1-555-0198",
        "location": "Elsewhere, ZZ",
        "unknown_top_level_key": "must not crash the renderer",
        "another_extra": {"nested": ["arbitrary", "payload"]},
        "summary": [{"text": "Summary line.", "priority": 1, "extra": "ignored"}],
        "skills_groups": [
            {"name": "Research", "items": ["Statistics"], "extra": "ignored", "priority": 1},
            {"name": "Writing", "items": ["LaTeX"]},
        ],
        "experience": [
            {
                "title": "Research Engineer",
                "company": "Extra Keys Ltd",
                "start": "2019",
                "end": "2023",
                "unexpected": "field",
                "bullets": [{"text": "A bullet.", "priority": 1, "unexpected": "field"}],
            }
        ],
        "presentations": [
            # int year, not "2019"
            {"title": "A Talk With No Audience", "event": "Imaginary Conf", "year": 2019},
            {"title": "A Second Talk", "event": "Another Conf", "year": 2021, "note": "keynote"},
        ],
        "education": [
            {"degree": "PhD Placeholder Science", "institution": "Extra University", "year": 2018}
        ],
    }


def candidate_contact_block() -> dict[str, Any]:
    """A nested ``contact`` block alongside top-level identity fields.

    Top-level fields win over the contact block; the block supplies what the
    top level omits. Both paths are exercised in one fixture.
    """
    return {
        "name": "Marie Placeholder",
        "email": "top-level@example.com",
        "contact": {
            # Shadowed by the top-level value above.
            "email": "contact-block@example.com",
            # Supplied only here.
            "phone": "+1-555-0123",
            "location": "Contact City, ZZ",
            "github": "github.com/placeholder",
            "links": ["example.com/portfolio"],
        },
        "headline": "Engineering Manager",
        "summary": [{"text": "Summary for the contact-block fixture."}],
        "skills": ["Leadership", "Planning"],
        "experience": [
            {
                "title": "Engineering Manager",
                "company": "Contact Co",
                "start": "2020",
                "end": "2024",
                "bullets": [{"text": "Managed an invented org.", "priority": 1}],
            }
        ],
        "education": [
            {"degree": "BA Placeholder", "institution": "Contact University", "year": 2011}
        ],
    }


def candidate_mixed_shapes() -> dict[str, Any]:
    """Every shape at once — the fixture rendered through BOTH renderers.

    Mixes dict and string bullets in a single list, alias keys beside canonical
    keys, present and absent ``priority``, extra keys, an int presentation year
    and a contact block. If the migration normalizes any of these differently
    from today, this fixture's golden moves.
    """
    return {
        "name": "Jean Placeholder",
        "headline": "Distinguished Engineer",
        "email": "jean@example.com",
        "contact": {"phone": "+1-555-0166", "location": "Mixed City, ZZ"},
        "website": "example.com/jean",
        "top_level_extra": "ignored but must not crash",
        "summary": [
            {"text": "Dict summary entry with priority.", "priority": 1},
            "Bare string summary entry.",
            {"line": "Alias-keyed summary entry."},
        ],
        "skills_groups": [
            {"name": "Canonical", "items": ["Python"], "priority": 1},
            {"label": "Aliased", "items": ["Rust"]},
            {"name": "NoPriority", "items": ["SQL"], "extra": "ignored"},
        ],
        "experience": [
            {
                "title": "Distinguished Engineer",
                "company": "Mixed Shapes Inc",
                "location": "Mixed City, ZZ",
                "start": "2022",
                "end": "",
                "bullets": [
                    {"text": "Dict bullet with priority and desc.", "priority": 1, "desc": "Detail."},
                    "Bare string bullet.",
                    {"line": "Alias bullet without priority."},
                ],
            },
            {
                "title": "Senior Engineer",
                "company": "Earlier Corp",
                "start": "2017",
                "end": "2022",
                "bullets": [{"text": "Bullet with no priority key at all."}],
            },
        ],
        "presentations": [{"title": "Mixed Talk", "event": "Mixed Conf", "year": 2023}],
        "teaching": ["Advanced Placeholding (Mixed University)"],
        "education": [
            {"degree": "BSc Mixed", "institution": "Mixed University", "year": 2014}
        ],
        "certifications": [{"name": "Mixed Certification", "year": 2021}],
    }


def candidate_scalar_summary() -> dict[str, Any]:
    """A bare-string ``summary`` — the shape no other fixture covered.

    Every other fixture supplies ``summary`` as a list, so none of them could
    see that normalizing a scalar into a one-item list moves the summary from
    the renderer's prose-paragraph branch to its bullet branch, which strips the
    terminal period. That regression shipped through a green golden run.

    The trailing periods below are load-bearing: they are what the bullet path
    would remove.
    """
    return {
        "name": "Sam Placeholder",
        "headline": _STAFF_ENGINEER,
        "email": "sam@example.com",
        "phone": "+1-555-0143",
        "location": "Scalar City, ZZ",
        "summary": "Builds reliable systems that outlive their authors.",
        "skills": ["Python", "Postgres", "Terraform"],
        "experience": [
            {
                "title": _STAFF_ENGINEER,
                "company": "Scalar Systems",
                "start": "2019",
                "end": "Present",
                "bullets": [
                    "Reduced deploy time from hours to minutes.",
                    {"text": "Led the storage migration.", "priority": 1},
                ],
            }
        ],
        "education": [
            {
                "degree": "BSc Placeholder Engineering",
                "institution": "Scalar University",
                "year": "2013",
            }
        ],
    }


def candidate_empty_scalar_summary() -> dict[str, Any]:
    """An *empty* bare-string ``summary`` — the shape that suppresses a section.

    ``candidate_scalar_summary`` covers a non-empty scalar, so it cannot see
    what happens when the string is blank. That gap shipped a regression: load
    normalization stores the empty scalar as ``[PriorityItem(text='')]``, which
    is truthy where ``''`` was falsy, so the sidebar renderer emitted a
    ``Profile`` heading above a single empty bullet where it previously drew
    nothing at all.

    ``headline`` is deliberately omitted. The summary section falls back to the
    headline when there is no summary text, so a fixture carrying one would
    render the section anyway and pin nothing about the empty-summary path.
    """
    return {
        "name": "Dana Placeholder",
        "email": "dana@example.com",
        "phone": "+1-555-0177",
        "location": "Blank City, ZZ",
        "summary": "",
        "skills": ["Python", "Kubernetes"],
        "experience": [
            {
                "title": "Platform Engineer",
                "company": "Blank Systems",
                "start": "2020",
                "end": "Present",
                "bullets": ["Kept the section headings honest."],
            }
        ],
        "education": [
            {
                "degree": "BSc Placeholder Studies",
                "institution": "Blank University",
                "year": "2015",
            }
        ],
    }


# name -> (candidate, uses-both-renderers)
CANDIDATE_FIXTURES: dict[str, Any] = {
    "dict_bullets": candidate_dict_bullets,
    "string_bullets": candidate_string_bullets,
    "alias_keys": candidate_alias_keys,
    "extra_keys": candidate_extra_keys,
    "contact_block": candidate_contact_block,
    "mixed_shapes": candidate_mixed_shapes,
    "scalar_summary": candidate_scalar_summary,
    "empty_scalar_summary": candidate_empty_scalar_summary,
}

# Fixtures rendered through both the standard and sidebar layouts. Every
# fixture is exercised in the standard layout; these additionally run through
# the sidebar writer, so the same data is pinned in both renderers.
SIDEBAR_FIXTURES = (
    "mixed_shapes",
    "dict_bullets",
    "extra_keys",
    # The empty-scalar case is now observable in both layouts. It used to be
    # sidebar-only, because the standard writer emitted section headings
    # unconditionally -- which was the bug: ``write_resume_docx`` skipped the
    # ``_section_has_data`` guard that the class-based writer applied, so the
    # CLI rendered a bare "Summary" heading here while the factory path did
    # not. Both layouts now suppress it, and both are pinned.
    "empty_scalar_summary",
)

# --- pipeline fixtures -----------------------------------------------------

# Fixtures rendered through FilterPipeline rather than straight into the writer.
# Rendering a fixture directly cannot see a regression on the path the schema
# migration actually moves, which is how a broken Step 2 passed the goldens.
# These pin the pipeline path itself.
PIPELINE_FIXTURES = ("mixed_shapes", "string_bullets", "scalar_summary")


def alignment_report() -> dict[str, Any]:
    """Alignment report driving the filter-active pipeline case.

    Keywords are chosen to match some fixture content and not all of it, so the
    filters actually remove something. A report that matched everything would
    render identically to the no-op case and pin nothing extra.
    """
    return {
        "matched_keywords": [
            {"skill": "Python"},
            {"skill": "Distributed Systems"},
            {"skill": "storage"},
        ]
    }
