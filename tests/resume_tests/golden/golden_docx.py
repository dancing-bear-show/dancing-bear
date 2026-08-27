"""Deterministic canonical representation of a rendered .docx.

A .docx is an OPC (ZIP) package. Hashing the raw archive bytes is the obvious
approach and it is WRONG here — measured, not assumed. Rendering the same
fixture twice a second apart produces archives of identical length whose bytes
differ, from two independent clock-driven sources:

  1. ZIP entry metadata: every member carries a ``date_time`` stamped from the
     wall clock at save time.
  2. ``docProps/core.xml``: python-docx writes ``dcterms:created`` and
     ``dcterms:modified`` as W3CDTF timestamps at save time.

Every content-bearing part — ``word/document.xml``, ``word/header1.xml``,
``word/styles.xml``, ``word/numbering.xml``, and the rest — is byte-identical
across runs. So the fix is not to loosen the comparison but to strip exactly
those two clock-driven fields and keep everything else byte-exact.

WHAT THIS REPRESENTATION CATCHES
    Any change to the XML of any archive member: run text and run ordering,
    bold/italic/size/color, paragraph spacing and indentation, alignment,
    shading, table structure and column widths, hyperlink relationships,
    section/header wiring, numbering definitions, style definitions, and the
    document metadata python-docx writes (title, author, subject, keywords).
    It also catches a member appearing or disappearing, since the member list
    is part of the digest.

WHAT IT DOES NOT CATCH
    Byte-level packaging concerns deliberately normalized away: ZIP entry
    timestamps, compression level, and member ordering within the archive
    (members are sorted before hashing). It cannot catch anything that never
    reaches the file — it renders through the public writer entry point, so a
    change with no XML effect is invisible by construction. It does not
    validate the document against the OOXML schema or check that Word renders
    it sensibly; it only asserts the output has not *changed*.

Timestamp scrubbing is scoped to the two ``dcterms`` elements in
``docProps/core.xml``. It is deliberately not a global regex over every part:
a date that legitimately appears in resume body text (an employment span, a
presentation year) must stay in the digest, because losing it would blind the
harness to the exact field-dropping regressions the migration risks.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass, field

# python-docx writes both as <dcterms:created ...>VALUE</dcterms:created>.
# Anchored to the dcterms element names so body text is never touched.
_TIMESTAMP_ELEMENT_RE = re.compile(
    rb"(<dcterms:(?:created|modified)\b[^>]*>)[^<]*(</dcterms:(?:created|modified)>)"
)
_TIMESTAMP_PLACEHOLDER = rb"\g<1>SCRUBBED\g<2>"

# The only archive member whose bytes vary run-to-run once ZIP metadata is
# excluded. Listed explicitly so that a future python-docx that starts stamping
# a clock into some other part shows up as a spurious failure to investigate,
# rather than being silently normalized away.
CLOCK_BEARING_MEMBERS = ("docProps/core.xml",)


def _scrub(name: str, payload: bytes) -> bytes:
    """Strip clock-driven fields from one archive member."""
    if name in CLOCK_BEARING_MEMBERS:
        return _TIMESTAMP_ELEMENT_RE.sub(_TIMESTAMP_PLACEHOLDER, payload)
    return payload


@dataclass(frozen=True)
class DocxFingerprint:
    """Canonical, reproducible fingerprint of one rendered .docx."""

    members: tuple[str, ...]
    digests: dict[str, str] = field(default_factory=dict)

    @property
    def digest(self) -> str:
        """A single digest over the whole package."""
        h = hashlib.sha256()
        for name in self.members:
            h.update(name.encode("utf-8"))
            h.update(b"\0")
            h.update(self.digests[name].encode("ascii"))
            h.update(b"\0")
        return h.hexdigest()

    def to_golden(self) -> dict:
        """Serializable form written to (and read back from) a golden file."""
        return {
            "digest": self.digest,
            "members": {name: self.digests[name] for name in self.members},
        }


def fingerprint_docx(path: str) -> DocxFingerprint:
    """Build a deterministic fingerprint of the .docx at ``path``.

    Members are sorted so archive write order never affects the result.
    """
    with zipfile.ZipFile(path) as zf:
        names = sorted(zf.namelist())
        digests = {
            name: hashlib.sha256(_scrub(name, zf.read(name))).hexdigest()
            for name in names
        }
    return DocxFingerprint(members=tuple(names), digests=digests)


def describe_mismatch(expected: dict, actual: DocxFingerprint) -> str:
    """Explain *what* changed, not merely *that* something changed.

    A golden failure that reports only "hash mismatch" gets regenerated
    blindly, which turns the safety net into a rubber stamp. This names the
    added, removed, and modified parts so a reviewer can decide whether a
    change was intended before accepting it.
    """
    expected_members = expected.get("members", {})
    added = [n for n in actual.members if n not in expected_members]
    removed = [n for n in expected_members if n not in actual.digests]
    changed = [
        n
        for n in actual.members
        if n in expected_members and expected_members[n] != actual.digests[n]
    ]

    lines = [
        "Rendered DOCX does not match its golden fingerprint.",
        f"  expected digest: {expected.get('digest')}",
        f"  actual digest:   {actual.digest}",
    ]
    for label, names in (
        ("changed parts", changed),
        ("parts added by this render", added),
        ("parts missing from this render", removed),
    ):
        if names:
            lines.append(f"  {label}: {', '.join(names)}")
    if "word/document.xml" in changed:
        lines.append(
            "  note: word/document.xml changed — the document body differs "
            "(text, ordering, or formatting)."
        )
    lines.append(
        "  If this change is intended, inspect the rendered file, then "
        "regenerate: RESUME_GOLDEN_UPDATE=1 make test"
    )
    return "\n".join(lines)
