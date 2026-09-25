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
# A divider inside a REPLACE body is content (an RST underline, say); the
# SEARCH and REPLACE markers never are.
_BLOCK_MARKERS = frozenset({SEARCH_MARKER, REPLACE_MARKER})
_STRAY_MARKERS = frozenset({DIVIDER_MARKER, REPLACE_MARKER})
_FILE_LINE_RE = re.compile(r"\s*FILE:(.*)")
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


def _find_marker(lines: list[str], start: int, marker: str) -> int:
    """Index of the first line from start that is marker; another block
    marker first, or no marker at all, is a malformed block."""
    for i in range(start, len(lines)):
        stripped = lines[i].strip()
        if stripped == marker:
            return i
        if stripped in _BLOCK_MARKERS:
            break
    raise EditBlockError(EDIT_MALFORMED_OUTCOME)


def _parse_block_body(lines: list[str], start: int) -> tuple[tuple[str, ...], tuple[str, ...], int]:
    """(search, replace, index after the REPLACE marker) for the block whose
    SEARCH marker is lines[start - 1]."""
    divider = _find_marker(lines, start, DIVIDER_MARKER)
    end = _find_marker(lines, divider + 1, REPLACE_MARKER)
    return tuple(lines[start:divider]), tuple(lines[divider + 1 : end]), end + 1


def parse_edit_blocks(response_text: str) -> list[EditBlock]:
    """Parse SEARCH/REPLACE blocks from a model response.

    Lines outside blocks - prose, ``` fences - are ignored, except that a
    "FILE: <path>" line names the file for every block after it until the
    next FILE line. Body lines are kept verbatim (only "\\n" splits lines).
    Raises EditBlockError: NO_EDITS_OUTCOME when there is no block, and
    EDIT_MALFORMED_OUTCOME for a block missing a marker (a response cut off
    at num_predict) or a stray divider/REPLACE marker - a partial edit set
    is never applied.
    """
    lines = response_text.split("\n")
    blocks: list[EditBlock] = []
    current_file = ""
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped == SEARCH_MARKER:
            search, replace, i = _parse_block_body(lines, i + 1)
            blocks.append(EditBlock(current_file, search, replace))
            continue
        if stripped in _STRAY_MARKERS:
            raise EditBlockError(EDIT_MALFORMED_OUTCOME)
        file_match = _FILE_LINE_RE.fullmatch(lines[i])
        if file_match is not None:
            current_file = file_match.group(1).strip()
        i += 1
    if not blocks:
        raise EditBlockError(NO_EDITS_OUTCOME)
    return blocks


def _normalise_edit_path(raw: str) -> str | None:
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


def _find_unique(lines: list[str], search: tuple[str, ...]) -> int:
    """Start index of the single place search occurs in lines.

    An empty SEARCH matches at every position, so it can never identify a
    location: it is EDIT_AMBIGUOUS_OUTCOME, never an insert-at-top.
    """
    if not search:
        raise EditBlockError(EDIT_AMBIGUOUS_OUTCOME)
    n, first, wanted = len(search), search[0], list(search)
    hits = [i for i in range(len(lines) - n + 1) if lines[i] == first and lines[i : i + n] == wanted]
    if not hits:
        raise EditBlockError(EDIT_NOT_FOUND_OUTCOME)
    if len(hits) > 1:
        raise EditBlockError(EDIT_AMBIGUOUS_OUTCOME)
    return hits[0]


def apply_edit_blocks(blocks: list[EditBlock], files: dict[str, str]) -> dict[str, str]:
    """Apply blocks in order to files (repo-relative path -> content).

    Each SEARCH is matched against the file's CURRENT content, earlier
    blocks' edits included. Returns the new content of every file that
    changed. Raises EditBlockError: EDIT_OUTSIDE_INPUTS_OUTCOME for a path
    that is not a key of files (no file is ever created), the _find_unique
    outcomes, and NO_CHANGE_OUTCOME when nothing changed.
    """
    working = {rel: _FileLines.from_text(text) for rel, text in files.items()}
    for block in blocks:
        rel = _normalise_edit_path(block.path)
        if rel is None or rel not in working:
            raise EditBlockError(EDIT_OUTSIDE_INPUTS_OUTCOME)
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


def _file_diff(rel: str, old: str, new: str) -> str:
    """One file's unified diff with a/ and b/ headers. A line without a
    newline can only be a file's last line; git needs it followed by the
    "\\ No newline at end of file" marker."""
    out: list[str] = []
    for line in difflib.unified_diff(_diff_lines(old), _diff_lines(new), f"a/{rel}", f"b/{rel}"):
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
