"""SEARCH/REPLACE edit blocks for the qwen_patch handler.

The model is asked for edit blocks rather than a unified diff: measured
against qwen2.5-coder:14b, every sampled diff had wrong hunk-header line
counts. The handler parses the blocks (parse_edit_blocks), applies them to
the file contents it already read through its confined read path
(apply_edit_blocks), and builds the diff itself (build_unified_diff).

Pure functions: no I/O. Every failure raises EditBlockError whose str() is a
content-free terminal outcome string; worker.qwen turns it into its own
guard error.
"""

from __future__ import annotations

import difflib
import posixpath
import re
from dataclasses import dataclass

NO_EDITS_OUTCOME = "terminal-no-edits-found"
EDIT_MALFORMED_OUTCOME = "terminal-edit-malformed"
EDIT_OUTSIDE_INPUTS_OUTCOME = "terminal-edit-outside-inputs"
EDIT_NOT_FOUND_OUTCOME = "terminal-edit-not-found"
EDIT_AMBIGUOUS_OUTCOME = "terminal-edit-ambiguous"
NO_CHANGE_OUTCOME = "terminal-no-change"

SEARCH_MARKER = "<<<<<<< SEARCH"
DIVIDER_MARKER = "======="
REPLACE_MARKER = ">>>>>>> REPLACE"
BARE_FENCE = "```"
# A marker counts only at column 0: every marker comparison in this module
# (response and target file alike) goes through _marker_text, which drops
# trailing whitespace (a "\r" included) but keeps leading indentation. An
# indented "  =======" or "  >>>>>>> REPLACE" is body content, never
# structure, so a truncated response cannot promote it to a separator.
# The SEARCH and REPLACE markers never appear as body content. A divider
# line can: an RST/Markdown underline reads as "=======". There is no
# escaping in this format, so four guards fail closed as malformed rather
# than guess (a guess can silently truncate the SEARCH or REPLACE body and
# apply a partial edit):
# - parse time: a block with more than one bare "=======" line before its
#   REPLACE marker (_parse_block_body).
# - apply time: a block whose SEARCH match is immediately followed by a bare
#   "=======" line in the file (_find_unique). With one divider the parser
#   cannot tell a cut-off SEARCH of "Title / ======= / old body" from
#   SEARCH "Title", REPLACE "old body"; the target file can.
# - parse time: a REPLACE marker immediately followed by a non-blank,
#   non-structural line (_is_unstructured_line_after_replace). A genuine
#   ">>>>>>> REPLACE" line inside a REPLACE body still closes the block early
#   (the format has no escaping for that), but content that follows can no
#   longer be silently read as inter-block prose and dropped - it is
#   ambiguous with a response truncated right after that in-body marker, so
#   the whole block set is rejected.
# - parse time: after the LAST block's REPLACE marker, every remaining line
#   must be blank or a bare closing ``` fence (_is_truncation_residue).
#   Truncation always
#   leaves its residue after the final block: had another block followed, the
#   real closer left behind by an in-body marker would already be a stray
#   marker. This catches the residue however many blank lines precede it.
# The only undetectable case left is a response cut exactly at a true
# closing REPLACE marker with nothing after it: that is indistinguishable
# from a well-formed response and is accepted.
_BLOCK_MARKERS = frozenset({SEARCH_MARKER, REPLACE_MARKER})
_STRAY_MARKERS = frozenset({DIVIDER_MARKER, REPLACE_MARKER})
# Column 0, like every structural marker: an indented "  FILE: other.py"
# between blocks is prose, so it can never retarget the next block.
_FILE_LINE_RE = re.compile(r"FILE:(.*)")
_NO_NEWLINE_MARKER = "\\ No newline at end of file"

EDIT_FORMAT_EXAMPLE = (
    "FILE: src/worker/example.py\n"
    f"{SEARCH_MARKER}\n"
    "def total(items):\n"
    "    return sum(items)\n"
    f"{DIVIDER_MARKER}\n"
    "def total(items):\n"
    "    return sum(items or [])\n"
    f"{REPLACE_MARKER}"
)


class EditBlockError(ValueError):
    """An edit set that cannot be applied; str(exc) is the terminal outcome."""


@dataclass(frozen=True)
class EditBlock:
    """One SEARCH/REPLACE edit. path is as the model wrote it after FILE:
    (normalised only when applied); search and replace are lines without
    their newline characters."""

    path: str
    search: tuple[str, ...]
    replace: tuple[str, ...]


@dataclass
class _FileLines:
    """A file's text as lines without terminators, plus whether it ended in a
    newline, so an edit can never add or drop the final newline."""

    lines: list[str]
    final_newline: bool

    @classmethod
    def from_text(cls, text: str) -> _FileLines:
        if not text:
            return cls([], True)
        if text.endswith("\n"):
            return cls(text[:-1].split("\n"), True)
        return cls(text.split("\n"), False)

    def to_text(self) -> str:
        if not self.lines:
            return ""
        return "\n".join(self.lines) + ("\n" if self.final_newline else "")


def _marker_text(line: str) -> str:
    """line as compared with a marker: trailing whitespace dropped, leading
    indentation kept, so only a column-0 marker ever matches."""
    return line.rstrip()


def _find_marker(lines: list[str], start: int, marker: str) -> int:
    """Index of the first line from start that is marker at column 0; another
    column-0 block marker first, or no marker at all, is a malformed block."""
    for i in range(start, len(lines)):
        text = _marker_text(lines[i])
        if text == marker:
            return i
        if text in _BLOCK_MARKERS:
            break
    raise EditBlockError(EDIT_MALFORMED_OUTCOME)


def _parse_block_body(lines: list[str], start: int) -> tuple[tuple[str, ...], tuple[str, ...], int]:
    """(search, replace, index after the REPLACE marker) for the block whose
    SEARCH marker is lines[start - 1].

    A second bare (column-0) "=======" line between the divider and the
    REPLACE marker means the body's own divider cannot be told apart from a
    legitimate "=======" line of content (SEARCH or REPLACE side); that block
    is rejected rather than silently truncated. An indented "=======" is
    plain content. A single divider that was really SEARCH content is caught
    at apply time by _find_unique."""
    divider = _find_marker(lines, start, DIVIDER_MARKER)
    end = _find_marker(lines, divider + 1, REPLACE_MARKER)
    if any(_marker_text(lines[i]) == DIVIDER_MARKER for i in range(divider + 1, end)):
        raise EditBlockError(EDIT_MALFORMED_OUTCOME)
    return tuple(lines[start:divider]), tuple(lines[divider + 1 : end]), end + 1


def _is_bare_closing_fence(line: str) -> bool:
    """True when line is a closing ``` fence with no info string, at column 0
    (leading indentation is not a fence; trailing whitespace is dropped - the
    same treatment _marker_text gives every other structural marker).

    An info-string fence such as "```python" or "```diff" does NOT count: a
    response truncated right after an in-body ">>>>>>> REPLACE" can end with
    exactly that line (the model closing what it thinks is a fresh code
    block), and accepting it here would silently truncate the replacement
    instead of failing closed. A bare closing fence is unambiguous - it
    carries no content of its own - so it stays safe both here and before the
    first block, where an opening info-string fence is legitimate and is not
    checked by this helper at all (fences before the first block are
    ordinary ignored text, not a safety check)."""
    return _marker_text(line) == BARE_FENCE


def _is_unstructured_line_after_replace(line: str) -> bool:
    """True when line cannot be told apart from REPLACE body content cut off
    by truncation.

    Legitimate text between blocks - prose, a bare closing ``` fence, the
    next FILE: line, the next block's SEARCH marker - always reaches the line
    right after REPLACE either blank or as one of those structural forms (the
    fences-and-prose fixture never places bare prose directly against a
    REPLACE marker; it is always separated by a blank line or a fence close).
    A non-blank line that is none of those is indistinguishable from a
    REPLACE body whose response was truncated right after an earlier,
    in-body ">>>>>>> REPLACE"-shaped line: failing closed here is the only
    way to avoid silently dropping that trailing content. An info-string
    fence line (for example "```python") is NOT treated as safe: that is
    exactly what a response truncated right after an in-body REPLACE marker
    can look like, so it falls through to the final "unstructured" check
    below and is rejected.

    After the last block _is_truncation_residue is stricter and subsumes
    this check; this one still applies after every non-final block, where
    it rejects prose directly abutting a REPLACE marker.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if _is_bare_closing_fence(line):
        return False
    if _marker_text(line) == SEARCH_MARKER:
        return False
    return _FILE_LINE_RE.fullmatch(line) is None


def _is_truncation_residue(line: str) -> bool:
    """True when line, found after the last block's REPLACE marker, may be
    REPLACE body content left behind by an in-body ">>>>>>> REPLACE"-shaped
    line in a truncated response. Only blank lines and a bare closing ```
    fence are safe there; an info-string fence (for example "```python"),
    prose, FILE: lines and everything else are rejected - an info-string
    fence is exactly what a response cut off right after an in-body REPLACE
    marker can end with, so treating it as safe would silently accept a
    truncated replacement."""
    stripped = line.strip()
    if not stripped:
        return False
    return not _is_bare_closing_fence(line)


def parse_edit_blocks(response_text: str) -> list[EditBlock]:
    """Parse SEARCH/REPLACE blocks from a model response.

    Lines before the first block and between blocks - prose, ``` fences
    (opening, with or without an info string, and closing alike) - are
    ignored, except that a "FILE: <path>" line names the file for every
    block after it until the next FILE line. After the last block only blank
    lines and a bare closing ``` fence (no info string) are allowed. Body
    lines are kept verbatim (only "\\n" splits lines). Markers are recognised
    only at column 0 (trailing whitespace is tolerated); an indented
    marker-shaped line is ordinary text. Raises EditBlockError:
    NO_EDITS_OUTCOME when there is no block, and EDIT_MALFORMED_OUTCOME for a
    block missing a marker (a response cut off at num_predict), a stray
    divider/REPLACE marker, a non-blank, non-structural line immediately
    after any REPLACE marker (see _is_unstructured_line_after_replace), or
    any line other than a blank or bare closing ``` fence after the last
    REPLACE marker (see _is_truncation_residue) - a partial edit set is never
    applied. A response cut exactly at a true closing REPLACE marker, with
    nothing after it, cannot be detected.
    """
    lines = response_text.split("\n")
    blocks: list[EditBlock] = []
    current_file = ""
    last_end = 0
    i = 0
    while i < len(lines):
        text = _marker_text(lines[i])
        if text == SEARCH_MARKER:
            search, replace, i = _parse_block_body(lines, i + 1)
            blocks.append(EditBlock(current_file, search, replace))
            last_end = i
            if i < len(lines) and _is_unstructured_line_after_replace(lines[i]):
                raise EditBlockError(EDIT_MALFORMED_OUTCOME)
            continue
        if text in _STRAY_MARKERS:
            raise EditBlockError(EDIT_MALFORMED_OUTCOME)
        file_match = _FILE_LINE_RE.fullmatch(lines[i])
        if file_match is not None:
            current_file = file_match.group(1).strip()
        i += 1
    if not blocks:
        raise EditBlockError(NO_EDITS_OUTCOME)
    if any(_is_truncation_residue(line) for line in lines[last_end:]):
        raise EditBlockError(EDIT_MALFORMED_OUTCOME)
    return blocks


def _normalise_markdown_path(raw: str) -> str | None:
    """raw as a normalised repo-relative POSIX path, or None when it is empty,
    absolute, or climbs out of the root. Surrounding backticks and quotes
    (markdown habits) are dropped; nothing else is forgiven."""
    name = raw.strip().strip("`\"'")
    if not name or name.startswith("/") or "\\" in name:
        return None
    norm = posixpath.normpath(name)
    if norm in (".", "..") or norm.startswith("../"):
        return None
    return norm


def _resolve_edit_path(raw: str, files: dict[str, str]) -> str:
    """The `files` key raw's FILE line refers to.

    Resolution is two-step so that markdown normalisation can never make one
    input shadow another. (1) Exact: if raw, with only surrounding whitespace
    stripped, is itself a key of files, that key wins outright - an input
    literally named `` `src/a.py` `` is never reinterpreted. (2) Fallback:
    otherwise raw is normalised (backticks/quotes stripped, `./`/`..`
    resolved) and matched against every input's own normalised form. A
    fallback match is used only when it names exactly one input; matching
    none raises EDIT_OUTSIDE_INPUTS_OUTCOME (as for any other unknown path),
    and matching more than one - e.g. `` `src/a.py` `` and a literal
    "src/a.py" both present as inputs - raises EDIT_AMBIGUOUS_OUTCOME: the
    FILE line does not identify a single target, which is the same shape of
    failure _find_unique reports for an ambiguous SEARCH location, not a
    plain "not one of the inputs" miss.
    """
    exact = raw.strip()
    if exact in files:
        return exact
    norm = _normalise_markdown_path(raw)
    if norm is None:
        raise EditBlockError(EDIT_OUTSIDE_INPUTS_OUTCOME)
    matches = [name for name in files if _normalise_markdown_path(name) == norm]
    if not matches:
        raise EditBlockError(EDIT_OUTSIDE_INPUTS_OUTCOME)
    if len(matches) > 1:
        raise EditBlockError(EDIT_AMBIGUOUS_OUTCOME)
    return matches[0]


def _find_unique(lines: list[str], search: tuple[str, ...]) -> int:
    """Start index of the single place search occurs in lines.

    An empty SEARCH matches at every position, so it can never identify a
    location: it is EDIT_AMBIGUOUS_OUTCOME, never an insert-at-top.
    A match directly followed by a bare (column-0) "=======" file line is
    EDIT_MALFORMED_OUTCOME: the block's divider may have been SEARCH content
    from a response cut off before its real divider. An indented "======="
    file line could never have been parsed as a divider, so it is content.
    """
    if not search:
        raise EditBlockError(EDIT_AMBIGUOUS_OUTCOME)
    n, first, wanted = len(search), search[0], list(search)
    hits = [i for i in range(len(lines) - n + 1) if lines[i] == first and lines[i : i + n] == wanted]
    if not hits:
        raise EditBlockError(EDIT_NOT_FOUND_OUTCOME)
    if len(hits) > 1:
        raise EditBlockError(EDIT_AMBIGUOUS_OUTCOME)
    after = hits[0] + n
    if after < len(lines) and _marker_text(lines[after]) == DIVIDER_MARKER:
        raise EditBlockError(EDIT_MALFORMED_OUTCOME)
    return hits[0]


def apply_edit_blocks(blocks: list[EditBlock], files: dict[str, str]) -> dict[str, str]:
    """Apply blocks in order to files (repo-relative path -> content).

    Each SEARCH is matched against the file's CURRENT content, earlier
    blocks' edits included. Returns the new content of every file that
    changed. A block's path is resolved with _resolve_edit_path: an exact
    match against a key of files wins outright, so markdown normalisation
    never makes one input shadow another; otherwise the normalised path must
    name exactly one input. Raises EditBlockError: EDIT_OUTSIDE_INPUTS_OUTCOME
    for a path that is not (and does not normalise to exactly one) key of
    files (no file is ever created), EDIT_AMBIGUOUS_OUTCOME when the
    normalised path names more than one input as well as for the
    _find_unique outcome of the same name, and NO_CHANGE_OUTCOME when nothing
    changed.
    """
    working = {rel: _FileLines.from_text(text) for rel, text in files.items()}
    for block in blocks:
        rel = _resolve_edit_path(block.path, files)
        target = working[rel]
        start = _find_unique(target.lines, block.search)
        target.lines[start : start + len(block.search)] = block.replace
    updated = {rel: target.to_text() for rel, target in working.items()}
    changed = {rel: text for rel, text in updated.items() if text != files[rel]}
    if not changed:
        raise EditBlockError(NO_CHANGE_OUTCOME)
    return changed


def _diff_lines(text: str) -> list[str]:
    """text split after each "\\n" only; the last line keeps no terminator
    when the file has no final newline."""
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


_QUOTE_ESCAPES = {"\a": "\\a", "\b": "\\b", "\t": "\\t", "\n": "\\n", "\v": "\\v", "\f": "\\f", "\r": "\\r", '"': '\\"', "\\": "\\\\"}


def _quote_diff_label(label: str) -> str:
    """label (an "a/<path>" or "b/<path>" diff header value) as git itself
    would write it in a "---"/"+++"/"diff --git" header.

    A byte-identical label needs no quoting and is returned as-is. A label
    carrying a tab, other ASCII control character (< 0x20 or 0x7f), a double
    quote, or a backslash is wrapped whole in double quotes with those bytes
    C-style escaped, matching core.quotePath's default: git quotes the
    complete "a/..."/"b/..." value, not just the path portion. Other bytes
    (including multi-byte UTF-8 sequences) pass through unescaped, matching
    git's default UTF-8 handling. Without this, a control/quote/backslash
    character inside an unquoted header desynchronises git apply's header
    parser and a valid edit is rejected as terminal-patch-does-not-apply.
    """
    if not any(ord(ch) < 0x20 or ord(ch) == 0x7F or ch in ('"', "\\") for ch in label):
        return label
    out = ['"']
    for ch in label:
        code = ord(ch)
        if ch in _QUOTE_ESCAPES:
            out.append(_QUOTE_ESCAPES[ch])
        elif code < 0x20 or code == 0x7F:
            out.append(f"\\{code:03o}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _file_diff(rel: str, old: str, new: str) -> str:
    """One file's unified diff with a/ and b/ headers. A line without a
    newline can only be a file's last line; git needs it followed by the
    "\\ No newline at end of file" marker. Header labels are C-style quoted
    the way git itself would quote them (see _quote_diff_label) so a control
    character, quote, or backslash in the pathname cannot desynchronise git
    apply's header parser."""
    a_label = _quote_diff_label(f"a/{rel}")
    b_label = _quote_diff_label(f"b/{rel}")
    out: list[str] = []
    for line in difflib.unified_diff(_diff_lines(old), _diff_lines(new), a_label, b_label):
        out.append(line if line.endswith("\n") else f"{line}\n{_NO_NEWLINE_MARKER}\n")
    return "".join(out)


def build_unified_diff(original: dict[str, str], updated: dict[str, str]) -> str:
    """A unified diff taking each file in updated from its original content,
    one section per file, in updated's order."""
    return "".join(_file_diff(rel, original[rel], text) for rel, text in updated.items())


def edits_to_diff(response_text: str, files: dict[str, str]) -> str:
    """Parse the response's edit blocks, apply them to files, and return the
    resulting unified diff. Raises EditBlockError with a terminal outcome."""
    updated = apply_edit_blocks(parse_edit_blocks(response_text), files)
    return build_unified_diff(files, updated)
