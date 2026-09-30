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

from core.github.authors import COPILOT_LOGIN, normalize_login

OVERVIEW_MARKER = "<!-- ccr-overview-v2 -->"
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


#: Reason a path was refused because it leaves the repository (or can't be
#: trusted to stay in it): absolute, home-relative, backslashed, control
#: characters, or climbing out with "..".
ESCAPES_REPO = "escapes-repo"
#: Reason a path was refused although it is inside the repository: it names
#: infrastructure an unattended fixer must never edit.
PROTECTED_PATH = "protected-path"

#: Any path segment equal to one of these is protected. ``.git`` anywhere
#: covers submodule git dirs too; a ``.git/hooks`` edit runs code on the next
#: git command. ``.envrc`` anywhere, because direnv sources the file in
#: whichever directory a shell enters.
_PROTECTED_ANY_SEGMENT = frozenset({".git", ".envrc"})
#: Top-level directories holding CI and agent configuration and hooks.
_PROTECTED_TOP_LEVEL = frozenset({".github", ".claude"})


def _normalise_in_repo(candidate: str) -> str | None:
    """Normalise ``candidate``, or None when it is not a safe relative path."""
    if not candidate or "\\" in candidate:
        return None
    if any(ord(ch) < 32 for ch in candidate):
        return None
    if candidate.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", candidate):
        return None
    normalised = posixpath.normpath(candidate)
    if normalised in (".", "..") or ".." in normalised.split("/"):
        return None
    return normalised


def _is_protected(normalised: str) -> bool:
    # casefold: macOS's default filesystem is case-insensitive, so `.GIT/hooks`
    # is the same directory as `.git/hooks`.
    parts = [p.casefold() for p in normalised.split("/")]
    return parts[0] in _PROTECTED_TOP_LEVEL or any(
        p in _PROTECTED_ANY_SEGMENT for p in parts
    )


def classify_repo_path(path: str) -> tuple[str | None, str | None]:
    """Return ``(normalised, reason)`` for a reviewer-cited path.

    ``reason`` is None for a path a fixer may edit, ESCAPES_REPO when the path
    cannot be trusted at all (``normalised`` is then None), or PROTECTED_PATH
    when it is inside the repo but names infrastructure — ``normalised`` is
    kept so the finding keeps a stable id and the report can say where.
    """
    normalised = _normalise_in_repo(strip_zwsp(path).strip())
    if normalised is None:
        return None, ESCAPES_REPO
    if _is_protected(normalised):
        return normalised, PROTECTED_PATH
    return normalised, None


def safe_repo_path(path: str) -> str | None:
    """Return ``path`` normalised if a fixer may be pointed at it, else None.

    An unlinked finding's path is parsed out of review-body HTML, and the
    workflow hands it to a fixer agent that can edit files — and whose edits
    are committed and pushed before verification runs. Treat it as
    adversarial: refuse anything that escapes the repository and anything
    protected inside it (see classify_repo_path). A refused path is reported,
    never dispatched.
    """
    normalised, reason = classify_repo_path(path)
    return normalised if reason is None else None


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
    path_rejected_reason: str | None = None
    # The normalised path this finding's id was built from — `path` for a safe
    # one, the withheld path for a protected one. Never dispatched; only used
    # to match same-file findings for prior_same_path.
    id_path: str | None = None
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

    def as_dict(self, *, current: bool = False,
                prior_same_path: list[str] | None = None) -> dict[str, Any]:
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
            # The path the reviewer text cited when classify_repo_path()
            # refused it (zero-width spaces stripped). Set means "report,
            # never dispatch". The reason says why: ESCAPES_REPO or
            # PROTECTED_PATH.
            "path_rejected": self.path_rejected,
            "path_rejected_reason": self.path_rejected_reason,
            "file_id": _file_id(self.id),
            "source_review_id": self.source_review_id,
            "source_submitted_at": self.source_submitted_at,
            # True iff this finding's source_review_id equals the newest
            # overview's review_id. Stale findings came from an earlier run
            # and are no longer listed by Copilot.
            "current": current,
            # For a CURRENT unlinked finding: sorted ids of non-current
            # unlinked findings that cite the same path (a re-raise with a
            # reworded title). Empty for linked findings and for non-current
            # ones.
            "prior_same_path": sorted(prior_same_path) if prior_same_path else [],
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


def _norm_title(title: str | None) -> str:
    """A title compared for identity: zero-width spaces gone, spaces collapsed."""
    return re.sub(r"\s+", " ", strip_zwsp(title or "")).strip()


def _dedupe_key(entry: Finding) -> tuple[str, str] | None:
    """Unlinked findings keyed on path+title, since line numbers drift.

    A fix round moves the line an unlinked finding cites, so the same finding
    arrives under two keys across two reviews and splits its own
    repeat-offender history.
    """
    if entry.linked or not entry.path:
        return None
    title = _norm_title(entry.title)
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
    path_rejected_reason: str | None = None
    # The normalised form of a PROTECTED path: never exposed as `path` (so it
    # can't be dispatched) but still used for the id, keeping it stable.
    id_path: str | None = None
    lines: list[str] = field(default_factory=list)

    def absorb(self, raw: str) -> None:
        """Take a path line if we still need one, otherwise body text."""
        match = _PATH_LINE.match(strip_zwsp(raw).strip())
        if match and self.line is None:
            normalised, reason = classify_repo_path(match.group(1))
            if reason is None:
                self.path = normalised
            else:
                self.path_rejected = strip_zwsp(match.group(1)).strip()
                self.path_rejected_reason = reason
                self.id_path = normalised
            self.line = int(match.group(2))
        elif raw.strip():
            self.lines.append(strip_zwsp(raw))

    @property
    def finding_id(self) -> str:
        located = self.path or self.id_path
        if located:
            return f"unlinked:{located}:{self.line}"
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


def _unlinked_slot(findings: dict[str, Finding], base: str, title: str | None,
                   taken: set[str]) -> str:
    """Pick the id an unlinked finding records under.

    ``path:line`` alone is not an identity. Two different findings can cite
    one line in the same review, and across reviews a NEW finding can land on
    the line an old one cited (a fix frees it, the next finding takes it). A
    bare path:line key made the newcomer overwrite the old entry and inherit
    its section history — losing the old finding and falsely marking the new
    one "previously missed". So walk ``base``, ``base#2``, ``base#3`` … and
    take the first slot not already used by this review whose existing
    occupant, if any, has the same title. Matching on title rather than on
    position also keeps ids stable when a later review lists the same
    findings in a different order.
    """
    wanted = _norm_title(title)
    n = 1
    while True:
        fid = base if n == 1 else f"{base}#{n}"
        if fid not in taken:
            occupant = findings.get(fid)
            if occupant is None or _norm_title(occupant.title) == wanted:
                return fid
        n += 1


def _record_unlinked(findings: dict[str, Finding], pending: _Pending,
                     review: dict[str, Any], taken: set[str]) -> None:
    """Record a finished unlinked block under its identity slot."""
    fid = _unlinked_slot(findings, pending.finding_id, pending.title, taken)
    taken.add(fid)
    _record(
        findings, fid, pending.section, review,
        title=pending.title, severity=pending.severity,
        linked=False, path=pending.path, line=pending.line,
        body=pending.body, path_rejected=pending.path_rejected,
        path_rejected_reason=pending.path_rejected_reason,
        id_path=pending.path or pending.id_path,
    )


def parse_body(review: dict[str, Any], findings: dict[str, Finding]) -> None:
    """Fold one overview review body into ``findings``, newest call winning."""
    section: str | None = None
    pending: _Pending | None = None
    taken: set[str] = set()  # unlinked ids already recorded by this review

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
            _record_unlinked(findings, pending, review, taken)
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

    A line whose content (after stripping whitespace and inline HTML) is the
    word "None" (case-insensitive) returns 0 rather than None. "None" is an
    explicit zero from the reviewer and enables the ``parse_shortfall``
    tripwire, while ``None`` (the Python value) means the line was absent and
    the tripwire is disabled. A line with no parseable number and not "None"
    returns None.
    """
    line = _CLAIMED_LINE.search(review.get("body") or "")
    if not line:
        return None
    content = line.group(1)
    # Strip HTML tags to get the visible text, then check for the word "None".
    visible = re.sub(r"<[^>]+>", "", content).strip()
    if visible.lower() == "none":
        return 0
    counts = [int(n) for n in _CLAIMED_COUNT.findall(content)]
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


def _parsed_section_counts(findings: dict[str, Finding],
                           newest_review_id: Any) -> dict[str, int]:
    """How many entries the newest review actually parsed into each section.

    Counts both linked and unlinked findings — a declared ``Previously missed``
    block with no ``#discussion_r`` anchor is exactly the case a headline-only
    check cannot see, since unlinked findings never touch the ``Findings:``
    count in the first place.
    """
    counts: dict[str, int] = {}
    for f in findings.values():
        if f.source_review_id != newest_review_id:
            continue
        key = " ".join((f.section or "").lower().split())
        counts[key] = counts.get(key, 0) + 1
    return counts


def _shortfall(claimed: int | None, findings: dict[str, Finding],
               newest_review_id: Any, declared_sections: dict[str, int]) -> int:
    """How much the newest overview declared but we did not parse.

    Two independent checks, and the worse of the two wins:

    1. The headline vs. ``Open``. The ``Findings:`` count matches the ``Open``
       section — on PR #395 ``Findings: 4`` sits beside ``Open (4)`` while
       ``Resolved since last review (2)`` is extra — so counting every parsed
       finding from every section would let resolved entries mask a genuinely
       missing open one.
    2. Every declared section (``Previously missed``, ``Resolved since last
       review``, and ``Open`` too) against how many entries actually parsed into it
       from the newest review. This is the only way to notice a section whose
       entries are unlinked and therefore invisible to the headline count: an
       explicit ``Findings: None`` can never produce a shortfall under check 1
       alone, so a ``Previously missed (1)`` block that fails to parse would
       report ``status: ok`` with zero evidence anything broke.

    A section whose declared count matches its parsed count contributes no
    shortfall — a fully-parsed ``Resolved since last review (4)`` is not
    penalised for not being ``Open``.
    """
    parsed = _parsed_section_counts(findings, newest_review_id)
    open_shortfall = 0 if claimed is None else max(
        0, claimed - _open_findings(findings, newest_review_id)
    )

    section_shortfall = 0
    for name, declared_count in declared_sections.items():
        key = " ".join(name.lower().split())
        gap = declared_count - parsed.get(key, 0)
        section_shortfall = max(section_shortfall, gap)

    return max(open_shortfall, section_shortfall)


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


def _stale_unlinked_by_path(findings: dict[str, Finding],
                             newest_review_id: Any) -> dict[str, list[str]]:
    """Path → sorted list of stale unlinked finding ids that cite it.

    "Stale" means the finding is unlinked and not from the newest review.
    Used by ``_reconcile`` to fill ``prior_same_path`` for current findings.
    """
    by_path: dict[str, list[str]] = {}
    for fid, entry in findings.items():
        if entry.linked or entry.source_review_id == newest_review_id:
            continue
        id_path = entry.id_path
        if id_path:
            by_path.setdefault(id_path, []).append(fid)
    return by_path


def _reconcile(findings: dict[str, Finding], comment_to_thread: dict[str, str],
               newest_review_id: Any,
               ) -> tuple[dict[str, Any], list[dict[str, Any]], set[str], list[str]]:
    """Attach thread ids to findings and collect the citations that miss.

    Also computes per-finding ``current`` and ``prior_same_path`` fields and
    returns a sorted ``stale_unlinked`` list of non-current unlinked ids.
    """
    by_path = _stale_unlinked_by_path(findings, newest_review_id)
    out: dict[str, Any] = {}
    cited_not_found: list[dict[str, Any]] = []
    cited_threads: set[str] = set()
    stale_unlinked: list[str] = []

    for fid, entry in findings.items():
        is_current = entry.source_review_id == newest_review_id
        thread_id = comment_to_thread.get(fid) if entry.linked else None
        prior = _prior_same_path(entry, is_current, by_path)
        record = entry.as_dict(current=is_current, prior_same_path=prior)
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

        if not entry.linked and not is_current:
            stale_unlinked.append(fid)

    return out, cited_not_found, cited_threads, sorted(stale_unlinked)


def _prior_same_path(entry: Finding, is_current: bool,
                     by_path: dict[str, list[str]]) -> list[str]:
    """Stale unlinked finding ids on the same path as ``entry``, if current."""
    if not is_current or entry.linked:
        return []
    id_path = entry.id_path
    return by_path.get(id_path, []) if id_path else []


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
            "stale_unlinked": [],
        }

    findings: dict[str, Finding] = {}
    for body in overviews:
        parse_body(body, findings)
    findings = _merge_drifted(findings)

    newest = overviews[-1]
    newest_review_id = newest.get("review_id")
    claimed = _claimed_count(newest)
    declared_sections = _section_counts(newest)
    shortfall = _shortfall(claimed, findings, newest_review_id, declared_sections)
    comment_to_thread = _comment_index(threads or [])
    out, cited_not_found, cited_threads, stale_unlinked = _reconcile(
        findings, comment_to_thread, newest_review_id
    )

    return {
        "pr_number": pr_number,
        "present": True,
        "status": "partial" if shortfall else "ok",
        "parse_shortfall": shortfall,
        "newest": {
            "review_id": newest_review_id,
            "submitted_at": newest.get("submitted_at"),
            "verdict": _verdict(newest),
            "findings_claimed": claimed,
            "sections": declared_sections,
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
        # Sorted ids of unlinked findings that are NOT from the newest review.
        # These were raised in an earlier run and the newest overview no
        # longer lists them — either fixed, or re-raised under a new title.
        "stale_unlinked": stale_unlinked,
    }
