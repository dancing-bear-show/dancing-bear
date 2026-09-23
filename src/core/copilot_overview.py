"""Parse Copilot's ``ccr-overview-v2`` review bodies into structured findings.

Copilot states each finding twice. The inline review thread carries the finding
itself; the summary review body carries the reviewer's own severity, its own
count, and the section (``Open``, ``Previously missed``) that says whether it
has raised the concern before and been ignored.

Two classes of finding live only in that body:

* **Unlinked findings.** ``Previously missed`` entries are written inline with
  no ``#discussion_r`` anchor and no review thread anywhere on the PR, so no
  thread query reaches them.
* **Zero-width-space paths.** GitHub injects U+200B into rendered file paths,
  so a path used verbatim matches no file on disk and the mismatch is invisible
  in a terminal.

The parse is deliberately line-oriented: the ``<details>`` blocks nest, so a
``(?s)<details>.*?</details>`` pattern spans section boundaries and attributes
findings to the wrong section.
"""

from __future__ import annotations

import hashlib
import posixpath
import re
from dataclasses import dataclass, field
from typing import Any

OVERVIEW_MARKER = "<!-- ccr-overview-v2 -->"
COPILOT_LOGIN = "copilot-pull-request-reviewer"
ZERO_WIDTH_SPACE = "​"

#: Section naming findings the reviewer already raised and saw go unaddressed.
PREVIOUSLY_MISSED = "previously missed"
#: Section holding findings still outstanding in the newest overview.
OPEN_SECTION = "open"

_SECTION = re.compile(r"<summary><strong>(.*?)\s*\((\d+)\)</strong></summary>")
#: Greedy title so a `]` inside it — `list[str]`, `foo[bar]` — does not end
#: the capture early. The literal `](#discussion_r` suffix anchors the split.
_LINK = re.compile(r"\[(.+)\]\(#discussion_r(\d+)\)")
_SEVERITY = re.compile(r'alt="([^"]*?)\s*severity"', re.IGNORECASE)
_SUMMARY_TITLE = re.compile(r"</picture>\s*(.+?)\s*</summary>")
_PATH_LINE = re.compile(r"^`([^`]+):(\d+)`$")
_CLAIMED_LINE = re.compile(r"\*\*Findings:\*\*(.*)")
_CLAIMED_COUNT = re.compile(r"(\d+)\s*<picture")
#: `### 🟡 Changes recommended` — the emoji is optional and is stripped.
_VERDICT = re.compile(r"^###\s*(.+?)\s*$", re.MULTILINE)


def strip_zwsp(text: str) -> str:
    """Remove the zero-width spaces GitHub injects into rendered paths."""
    return text.replace(ZERO_WIDTH_SPACE, "")


def normalize_login(login: str | None) -> str:
    """Strip a trailing ``[bot]`` so both API spellings compare equal.

    GraphQL returns ``copilot-pull-request-reviewer`` and REST returns
    ``copilot-pull-request-reviewer[bot]`` for the same account.
    """
    if not login:
        return ""
    return login[:-5] if login.endswith("[bot]") else login


def is_copilot_overview(body: dict[str, Any]) -> bool:
    """True when this review body is an overview *written by Copilot*.

    The author check is not decoration. Review bodies from humans are preserved
    alongside bot ones, and downstream triage trusts this output over a thread's
    own resolution state — so selecting on the HTML marker alone would let
    anyone who pastes that string decide which threads get reopened.
    """
    text = body.get("body") or ""
    if OVERVIEW_MARKER not in text:
        return False
    if body.get("author_kind") != "bot":
        return False
    return normalize_login(body.get("author")) == COPILOT_LOGIN


def safe_repo_path(path: str) -> str | None:
    """Return ``path`` normalised if it is a safe repo-relative path, else None.

    An unlinked finding's path is parsed out of review-body HTML, and the
    workflow hands it to a fixer agent that can edit files. Treat it as
    adversarial: reject absolute paths, home-relative paths, backslashes,
    control characters, and anything whose normalised form climbs out of the
    repository (``..``). A rejected path is reported, never dispatched.
    """
    candidate = strip_zwsp(path).strip()
    if not candidate or "\\" in candidate:
        return None
    if any(ord(ch) < 32 for ch in candidate):
        return None
    if candidate.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", candidate):
        return None
    normalised = posixpath.normpath(candidate)
    if normalised in (".", "..") or normalised.startswith("../"):
        return None
    if ".." in normalised.split("/"):
        return None
    return normalised


def _sort_key(body: dict[str, Any]) -> tuple[str, int]:
    """Order oldest-to-newest, breaking timestamp ties on review id."""
    return (body.get("submitted_at") or "", int(body.get("review_id") or 0))


def _file_id(finding_id: str) -> str:
    """A filename-safe id that stays unique.

    Character replacement alone is not injective: ``unlinked:a/b.py:10`` and
    ``unlinked:a-b.py:10`` would collide and silently overwrite each other's
    result files, so a hash of the original is appended.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", finding_id)
    digest = hashlib.sha1(finding_id.encode("utf-8")).hexdigest()[:8]  # nosec B324 - filename uniqueness, not security
    return f"{safe}-{digest}"


@dataclass
class Finding:
    """One finding from an overview body, linked to a thread or not."""

    id: str
    title: str | None = None
    severity: str | None = None
    section: str | None = None
    sections: list[str] = field(default_factory=list)
    linked: bool = True
    path: str | None = None
    line: int | None = None
    body: str | None = None
    path_rejected: str | None = None
    source_review_id: int | None = None
    source_submitted_at: str | None = None

    @property
    def previously_missed(self) -> bool:
        """True when this finding has ever sat under "Previously missed".

        Matched on the whole normalised section name, not a substring: a
        section such as "Dismissed" contains "missed" and would otherwise be
        read as the reviewer having raised the finding before — inverting the
        signal, since a dismissed finding is the opposite of a repeat offender.
        """
        return any(
            " ".join(s.lower().split()) == PREVIOUSLY_MISSED for s in self.sections
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "severity": self.severity,
            "section": self.section,
            "sections": list(self.sections),
            "previously_missed": self.previously_missed,
            "linked": self.linked,
            "resolvable": self.linked,
            "path": self.path,
            "line": self.line,
            "body": self.body,
            # The raw path the reviewer text cited when it failed
            # safe_repo_path(). Set means "report, never dispatch".
            "path_rejected": self.path_rejected,
            "file_id": _file_id(self.id),
            "source_review_id": self.source_review_id,
            "source_submitted_at": self.source_submitted_at,
        }


def _record(findings: dict[str, Finding], fid: str, section: str,
            review: dict[str, Any], **attrs: Any) -> Finding:
    """Upsert a finding, unioning its section history.

    ``review`` is the review body being folded, not the finding's own text —
    a finding's ``body`` arrives through ``attrs``.
    """
    entry = findings.setdefault(fid, Finding(id=fid))
    for key, value in attrs.items():
        setattr(entry, key, value)
    entry.section = section
    if section not in entry.sections:
        entry.sections.append(section)
    entry.source_review_id = review.get("review_id")
    entry.source_submitted_at = review.get("submitted_at")
    return entry


def _dedupe_key(entry: Finding) -> tuple[str, str] | None:
    """Unlinked findings keyed on path+title, since line numbers drift.

    A fix round moves the line an unlinked finding cites, so the same finding
    arrives under two keys across two reviews and splits its own
    repeat-offender history.
    """
    if entry.linked or not entry.path:
        return None
    title = re.sub(r"\s+", " ", strip_zwsp(entry.title or "")).strip()
    if not title:
        # No title means no identity beyond the path, and two unrelated
        # findings in one file would merge on (path, ""). Never merge those.
        return None
    return (entry.path, title)


@dataclass
class _Pending:
    """An unlinked finding being accumulated across the lines of its block."""

    section: str
    title: str | None
    severity: str | None
    path: str | None = None
    line: int | None = None
    path_rejected: str | None = None
    lines: list[str] = field(default_factory=list)

    def absorb(self, raw: str) -> None:
        """Take a path line if we still need one, otherwise body text."""
        match = _PATH_LINE.match(strip_zwsp(raw).strip())
        if match and self.path is None and self.path_rejected is None:
            safe = safe_repo_path(match.group(1))
            if safe is None:
                self.path_rejected = match.group(1)
            else:
                self.path = safe
            self.line = int(match.group(2))
        elif raw.strip():
            self.lines.append(strip_zwsp(raw))

    @property
    def finding_id(self) -> str:
        if self.path:
            return f"unlinked:{self.path}:{self.line}"
        seed = f"{self.title or ''}\0{self.path_rejected or ''}"
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]  # nosec B324 - key derivation, not security
        return f"unlinked:{digest}"

    @property
    def body(self) -> str:
        return "\n".join(x for x in self.lines if x.strip())


def _starts_unlinked(raw: str) -> bool:
    """A nested summary carrying a severity badge but no anchor."""
    return "<summary>" in raw and "severity" in raw and "#discussion_r" not in raw


def _open_pending(raw: str, section: str) -> _Pending:
    title = _SUMMARY_TITLE.search(raw)
    severity = _SEVERITY.search(raw)
    return _Pending(
        section=section,
        title=strip_zwsp(title.group(1)) if title else None,
        severity=severity.group(1) if severity else None,
    )


def _record_linked(findings: dict[str, Finding], link: re.Match[str], raw: str,
                   section: str, review: dict[str, Any]) -> None:
    severity = _SEVERITY.search(raw)
    _record(
        findings, link.group(2), section, review,
        title=link.group(1), linked=True,
        severity=severity.group(1) if severity else None,
    )


def _record_unlinked(findings: dict[str, Finding], pending: _Pending,
                     review: dict[str, Any], emitted: dict[str, int]) -> None:
    """Record a finished unlinked block under an id unique within this review.

    Two genuinely different findings can cite the same path:line; without a
    suffix the second would silently overwrite the first. Counting per review
    keeps the ids stable across reviews that list the same findings in the
    same order.
    """
    base = pending.finding_id
    emitted[base] = emitted.get(base, 0) + 1
    fid = base if emitted[base] == 1 else f"{base}#{emitted[base]}"
    _record(
        findings, fid, pending.section, review,
        title=pending.title, severity=pending.severity,
        linked=False, path=pending.path, line=pending.line,
        body=pending.body, path_rejected=pending.path_rejected,
    )


def parse_body(review: dict[str, Any], findings: dict[str, Finding]) -> None:
    """Fold one overview review body into ``findings``, newest call winning."""
    section: str | None = None
    pending: _Pending | None = None
    emitted: dict[str, int] = {}  # unlinked ids already recorded by this review

    for raw in (review.get("body") or "").splitlines():
        header = _SECTION.search(raw)
        if header:
            section, pending = header.group(1), None
            continue

        link = _LINK.search(raw)
        if link and section:
            _record_linked(findings, link, raw, section, review)
            pending = None
        elif section and _starts_unlinked(raw):
            pending = _open_pending(raw, section)
        elif pending is None:
            continue
        elif raw.strip() == "</details>":
            _record_unlinked(findings, pending, review, emitted)
            pending = None
        else:
            pending.absorb(raw)


def _merge_drifted(findings: dict[str, Finding]) -> dict[str, Finding]:
    """Collapse unlinked findings that differ only by a drifted line number."""
    by_key: dict[tuple[str, str], str] = {}
    merged: dict[str, Finding] = {}

    for fid, entry in findings.items():
        key = _dedupe_key(entry)
        if key is None:
            merged[fid] = entry
            continue
        previous = by_key.get(key)
        if previous is None or merged[previous].source_review_id == entry.source_review_id:
            # Line drift is a cross-review phenomenon. Two entries last seen in
            # the SAME review were listed side by side, so they are distinct
            # findings that happen to share a path and title — never merge.
            by_key.setdefault(key, fid)
            merged[fid] = entry
            continue
        kept = merged[previous]
        for section in entry.sections:
            if section not in kept.sections:
                kept.sections.append(section)
        # The later-folded entry is the newer one, so every field describing
        # the finding's CURRENT state comes from it — the body included. It is
        # the text triage and the fixer act on, and keeping the older copy
        # feeds them review prose that the newer occurrence already replaced.
        kept.line, kept.path = entry.line, entry.path
        kept.section, kept.severity = entry.section, entry.severity
        kept.title = entry.title or kept.title
        kept.body = entry.body or kept.body
        kept.source_review_id = entry.source_review_id
        kept.source_submitted_at = entry.source_submitted_at

    return merged


def _claimed_count(review: dict[str, Any]) -> int | None:
    """The reviewer's own headline count, or None when absent.

    The ``**Findings:**`` line is a per-severity breakdown, not one number:
    ``**Findings:** 7 <High picture> · 8 <Medium picture>`` means fifteen.
    Reading only the first number understates it — on PR #400 that was 7
    against 15 — which hides a shortfall the count exists to expose. Sum every
    count on the line.
    """
    line = _CLAIMED_LINE.search(review.get("body") or "")
    if not line:
        return None
    counts = [int(n) for n in _CLAIMED_COUNT.findall(line.group(1))]
    return sum(counts) if counts else None


def _verdict(review: dict[str, Any]) -> str | None:
    """The overview's headline verdict, e.g. "Changes recommended".

    Taken from the first `### ` heading, with any leading status emoji
    stripped so the value is comparable across the 🟡/🔴/🟢 variants.
    """
    match = _VERDICT.search(review.get("body") or "")
    if not match:
        return None
    text = match.group(1)
    # Drop a leading non-alphanumeric run (the status emoji and its space).
    return re.sub(r"^[^\w]+", "", text).strip() or None


def _section_counts(review: dict[str, Any]) -> dict[str, int]:
    """Each section's own declared count, e.g. {"Open": 9}.

    This is what the overview SAYS each section holds, which is not
    necessarily what parsed out of it — the difference is the signal.
    """
    return {
        name: int(count)
        for name, count in _SECTION.findall(review.get("body") or "")
    }


def _open_findings(findings: dict[str, Finding], newest_review_id: Any) -> int:
    """Findings the newest overview listed as still open."""
    return sum(
        1 for f in findings.values()
        if f.source_review_id == newest_review_id
        and " ".join((f.section or "").lower().split()) == OPEN_SECTION
    )


def _shortfall(claimed: int | None, findings: dict[str, Finding],
               newest_review_id: Any) -> int:
    """How many open findings the newest overview claimed but we did not parse.

    Compare like with like. The headline count matches the ``Open`` section —
    on PR #395 ``Findings: 4`` sits beside ``Open (4)`` while
    ``Resolved since last review (2)`` is extra — so counting every parsed
    finding from every section lets resolved and previously-missed entries
    mask a genuinely missing open one and still report ``status: ok``.

    This is the only available evidence that a parse broke rather than the PR
    being clean: a shape change returns zero findings and looks identical to a
    PR with none.
    """
    if claimed is None:
        return 0
    return max(0, claimed - _open_findings(findings, newest_review_id))


def _comment_index(threads: list[dict[str, Any]]) -> dict[str, str]:
    """Map every comment id to its thread, not just each thread's first.

    A ``#discussion_r`` anchor can name a reply inside a thread, so a
    first-comment-only index reports such a citation as unreachable.
    """
    index: dict[str, str] = {}
    for thread in threads:
        thread_id = thread.get("thread_id")
        if not thread_id:
            # A review body or issue comment carries no resolvable thread id;
            # indexing it would map a citation to None and read as a match.
            continue
        for comment in thread.get("comments") or []:
            if comment.get("database_id") is not None:
                index[str(comment["database_id"])] = str(thread_id)
    return index


def _reconcile(findings: dict[str, Finding], comment_to_thread: dict[str, str]
               ) -> tuple[dict[str, Any], list[dict[str, Any]], set[str]]:
    """Attach thread ids to findings and collect the citations that miss."""
    out: dict[str, Any] = {}
    cited_not_found: list[dict[str, Any]] = []
    cited_threads: set[str] = set()

    for fid, entry in findings.items():
        thread_id = comment_to_thread.get(fid) if entry.linked else None
        record = entry.as_dict()
        record["thread_id"] = thread_id
        record["resolvable"] = bool(thread_id)
        out[fid] = record

        if thread_id:
            cited_threads.add(thread_id)
        elif entry.linked:
            # Unlinked findings have no thread by construction, so only a
            # linked citation that misses means the fetch dropped something.
            cited_not_found.append(
                {"database_id": fid, "title": entry.title, "section": entry.section}
            )

    return out, cited_not_found, cited_threads


def parse_overview(review_bodies: list[dict[str, Any]],
                   threads: list[dict[str, Any]] | None = None,
                   pr_number: str = "") -> dict[str, Any]:
    """Parse every Copilot overview body and reconcile against ``threads``."""
    overviews = sorted(
        (b for b in review_bodies if is_copilot_overview(b)), key=_sort_key
    )

    if not overviews:
        return {
            "pr_number": pr_number, "present": False, "status": "ok",
            "parse_shortfall": 0, "findings": {}, "previously_missed": [],
            "cited_not_found": [], "threads_not_cited": [],
        }

    findings: dict[str, Finding] = {}
    for body in overviews:
        parse_body(body, findings)
    findings = _merge_drifted(findings)

    newest = overviews[-1]
    claimed = _claimed_count(newest)
    shortfall = _shortfall(claimed, findings, newest.get("review_id"))
    comment_to_thread = _comment_index(threads or [])
    out, cited_not_found, cited_threads = _reconcile(findings, comment_to_thread)

    return {
        "pr_number": pr_number,
        "present": True,
        "status": "partial" if shortfall else "ok",
        "parse_shortfall": shortfall,
        "newest": {
            "review_id": newest.get("review_id"),
            "submitted_at": newest.get("submitted_at"),
            "verdict": _verdict(newest),
            "findings_claimed": claimed,
            "sections": _section_counts(newest),
        },
        "findings": out,
        "previously_missed": sorted(
            fid for fid, f in findings.items() if f.previously_missed
        ),
        "cited_not_found": cited_not_found,
        # Only real threads can be "uncited": threads.json also carries
        # review-body and issue-comment entries with thread_id null, and
        # sorting those against strings raises TypeError.
        "threads_not_cited": sorted(
            str(t["thread_id"]) for t in (threads or [])
            if t.get("thread_id") and t["thread_id"] not in cited_threads
        ),
    }
