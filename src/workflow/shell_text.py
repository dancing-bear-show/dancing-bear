"""Locate the shell an agent is told to run inside workflow stage prose.

Stage descriptions mix prose with commands. The shell rules in
``linter_shell`` only make sense on the commands, and a rule that fires on
prose mentioning ``{param}`` is noise, so "shell text" is defined narrowly:

* a fenced code block whose info string is empty or a shell language
  (``sh``, ``bash``, ``shell``, ``zsh``, ``console``); an unlabelled fence
  counts only when its first non-blank line is itself a command line;
* an inline backtick span whose first word is a command (see below);
* a line whose first word is a command, or an upper-case variable assignment
  (``HOST=$(...)``). A line ending in ``\\`` or inside an unclosed quote pulls
  the following lines in with it.

A "command" is a path to a repo wrapper (``./bin/<cli>``, ``bin/<cli>``), a
bare or path-prefixed ``python``/``python3`` interpreter (optionally version-
suffixed, e.g. ``python3.11``), a path ending in ``/qlty``, or a word from
:data:`_STRONG_COMMANDS`.
Words that are also common English (``make``, ``test``, ``find``, ``for``, ...)
count only when the next token looks like shell -- an option, a path, a
quote, a ``$`` expansion, or a ``NAME=`` assignment -- a loop head
(``for``/``while``/``until``) only with a ``do`` on the same line, and ``if``
only with a ``then``. A line whose unquoted ``)`` closes
nothing is prose wrapped mid-parenthesis. Everything else, including a label
before a command ("2. Server: curl ..."), is treated as prose: precision over
recall.

Quoting is resolved with :func:`quote_context`, a small lexer, rather than by
regex over the shell text.

The command parser (:func:`parse_shell` and its supporting types) lives in
:mod:`shell_parse`.  This module re-exports the public symbols for backwards
compatibility and uses :data:`shell_parse._Lexer` internally for
:func:`_heredoc_delimiters`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .shell_parse import (
    Heredoc,
    Redirect,
    ShellScript,
    ShellToken,
    SimpleCommand,
    _Lexer,
    _heredoc_delimiters,
    parse_shell,
)

__all__ = [
    "Heredoc",
    "Redirect",
    "ShellScript",
    "ShellSegment",
    "ShellToken",
    "SimpleCommand",
    "extract_labelled_assignments",
    "extract_shell_segments",
    "parse_shell",
    "quote_context",
]

_STRONG_COMMANDS: frozenset[str] = frozenset({
    "gh", "git", "jq", "curl", "python", "python3", "grep", "rg", "sed", "awk",
    "mkdir", "rm", "cp", "mv", "ls", "cat", "printf", "echo", "cd", "ollama",
    "launchctl", "qlty", "xargs", "wc", "mktemp", "shasum", "du", "df",
    "vm_stat", "uv", "pip", "npm", "chmod", "PYTHONPATH",
})

_WEAK_COMMANDS: frozenset[str] = frozenset({
    "make", "test", "find", "sort", "head", "tail", "diff", "touch", "export",
    "command", "for", "while", "until", "if", "read", "set", "local", "declare",
    "readonly", "typeset",
})

# A compound-command head counts only with its body keyword on the same line:
# Python's ``for x in y:`` / ``if x:`` and prose "for R in $ROOTS" have none.
_COMPOUND_HEADS: dict[str, str] = {"for": "do", "while": "do", "until": "do", "if": "then"}

_SHELL_FENCE_LANGS: frozenset[str] = frozenset({"", "sh", "bash", "shell", "zsh", "console"})

_FENCE_RE = re.compile(r"^\s*```\s*([A-Za-z0-9_+-]*)\s*$")
# A YAML folded scalar (``description: >``) collapses adjacent lines onto
# one, so a fence's opening marker and its first command can arrive as a
# single line ("```bash echo setup"). _FENCE_RE requires the marker alone on
# its line and would miss that; this variant captures the whitespace after
# the marker (group 1), the word after it (group 2) and whatever trailing
# text follows (group 3), so the trailing text can be recovered as the
# fence's first body line instead of the whole block being skipped. Group 1
# is what tells a language tag from a body word: folding "```python" onto
# its first line leaves the tag glued to the marker, while folding an
# unlabelled "```" leaves a space -- see _fence_lang_and_first_line.
_FENCE_OPEN_RE = re.compile(r"^\s*```([ \t]*)([A-Za-z0-9_+-]*)[ \t]*(\S.*)?$")
_ASSIGN_START_RE = re.compile(r"^[A-Z_][A-Z0-9_]*=")
_BACKTICK_SPAN_RE = re.compile(r"`([^`\n]+)`")
# A prose label before an assignment ("Bash tool: F=..."): the label ends at
# the first colon, and the assignment word must follow it directly.
_LABEL_RE = re.compile(r"^[^`:]*:[ \t]+(?=[A-Za-z_]\w*=)")
# Mirrors linter_shell.py's _PYTHON_WORD_RE: a bare or path-prefixed
# interpreter name, optionally version-suffixed (python3.11, python3.12, ...).
# _is_command_word previously only recognised the exact names "python"/
# "python3" or a path ending in "/python3", so a versioned interpreter line
# was never extracted as shell at all -- the isolation-not-set rule in
# linter_shell never got a segment to see it in.
_PYTHON_WORD_RE = re.compile(r"^(?:.*/)?python3?(?:\.\d+)?$")
_PROMPT_PREFIX = "$ "
_SHELLISH_ARG_PREFIXES = ("-", '"', "'", "$", ".", "/", "~", "{")
# A stray apostrophe in a trailing comment would otherwise pull prose in until
# the next quote; a blank line or this many lines ends a continuation.
_MAX_CONTINUATION_LINES = 30


@dataclass(frozen=True)
class ShellSegment:
    """One contiguous run of shell text found in a description.

    ``start`` is the character offset of this segment's first line within the
    full *description* it was extracted from -- not merely a rank among
    same-origin segments. Callers that need "does A happen before B in the
    real source" (the position-aware unvalidated-param check in
    ``linter_shell``) must compare ``start``, not list index: segments are
    extracted per-origin (fences, then lines, then spans) and concatenated,
    so their list order does not reflect source order on its own.
    """

    text: str
    origin: str  # "fence" | "line" | "span" | "label" (extract_labelled_assignments only)
    start: int = 0


def quote_context(text: str) -> list[str]:
    """Return, per character of *text*, the quote it sits inside.

    Each entry is ``"'"``, ``'"'``, or ``""`` (unquoted); an opening quote
    character is reported with the context outside it. A backslash outside
    single quotes escapes the next character, as in POSIX sh. A ``$(...)``
    opens a fresh quoting level, even inside double quotes, so the inner
    quotes of ``"$(jq -r '.x' "$F")"`` do not close the outer ones.
    """
    return _scan(text).ctx


@dataclass
class _Scan:
    """Result of lexing a piece of shell text for quotes and parentheses."""

    ctx: list[str]
    stack: list[str]  # levels still open at the end: "'", '"', or "("
    stray_close: bool = False  # an unquoted ")" that closed nothing


def _scan(text: str) -> _Scan:
    """Lex *text* for quoting; see :func:`quote_context`."""
    result = _Scan(ctx=[], stack=[])
    escaped = False
    for i, ch in enumerate(text):
        top = result.stack[-1] if result.stack else ""
        result.ctx.append(top if top in _QUOTES else "")
        if escaped:
            escaped = False
        elif ch == "\\" and top != "'":
            escaped = True
        elif top == "'":
            if ch == "'":
                result.stack.pop()
        else:
            _advance(result, top, ch, text[i - 1:i])
    return result


_QUOTES = ("'", '"')


def _advance(result: _Scan, top: str, ch: str, prev: str) -> None:
    """Apply one character outside single quotes to the quoting stack.

    Inside double quotes only ``$(`` opens a level; elsewhere any ``(`` does,
    so a subshell ``(cd x && y)`` balances.
    """
    stack = result.stack
    if ch == "(" and (prev == "$" or top != '"'):
        stack.append("(")
    elif ch == ")" and top == "(":
        stack.pop()
    elif ch == ")" and not top:
        result.stray_close = True
    elif ch == '"' and top == '"':
        stack.pop()
    elif ch in _QUOTES and top != '"':
        stack.append(ch)


def _ends_open(text: str) -> bool:
    """True when *text* ends inside an unclosed quote or with a line continuation."""
    if text.rstrip().endswith("\\"):
        return True
    return bool(_scan(text).stack)


def _first_words(line: str) -> tuple[str, str]:
    """The first two whitespace-separated words of *line*, prompt stripped."""
    body = line.strip()
    if body.startswith(_PROMPT_PREFIX):
        body = body[len(_PROMPT_PREFIX):]
    words = body.split(None, 2)
    first = words[0] if words else ""
    second = words[1] if len(words) > 1 else ""
    return first, second


def _is_command_word(word: str) -> bool:
    """True for a repo wrapper path, a python/qlty path, a versioned interpreter, or a strong command."""
    word = word.lstrip("(")
    if word.startswith(("./bin/", "bin/", "~/.qlty/bin/")):
        return True
    if word.endswith("/qlty") or _PYTHON_WORD_RE.match(word):
        return True
    return word in _STRONG_COMMANDS


def _closes_unopened_paren(line: str) -> bool:
    """True when an unquoted ``)`` on *line* closes nothing.

    That is a prose line wrapped mid-parenthesis ("git add -A) and run ...");
    as shell it would be a syntax error.
    """
    return _scan(line).stray_close


def _weak_word_is_command(first: str, second: str, line: str) -> bool:
    """A common-English command word counts only with shell-looking context."""
    if first in _COMPOUND_HEADS:
        return any(tok.raw == _COMPOUND_HEADS[first] for tok in _Lexer(line).tokens())
    if _ASSIGN_START_RE.match(second):
        return True  # export FOO=..., local BAR=...
    return second.startswith(_SHELLISH_ARG_PREFIXES) or "/" in second


def is_command_line(line: str) -> bool:
    """True when *line* starts with a command or an upper-case assignment."""
    first, second = _first_words(line)
    if not first or _closes_unopened_paren(line):
        return False
    if _ASSIGN_START_RE.match(first) or _is_command_word(first):
        return True
    return first in _WEAK_COMMANDS and _weak_word_is_command(first, second, line)


def _fence_segments(
    lines: list[str], line_starts: list[int]
) -> tuple[list[ShellSegment], set[int]]:
    """Shell fences and the indexes of every line inside ANY fence."""
    segments: list[ShellSegment] = []
    consumed: set[int] = set()
    i = 0
    while i < len(lines):
        m = _FENCE_OPEN_RE.match(lines[i])
        if m is None:
            i += 1
            continue
        end = next((j for j in range(i + 1, len(lines)) if _FENCE_RE.match(lines[j])), len(lines))
        body = lines[i + 1:end]
        lang, first_line = _fence_lang_and_first_line(m.group(1), m.group(2), m.group(3))
        # The folded-scalar fallback recovers a body line that was collapsed
        # onto the opening marker's own line -- it has no line of its own to
        # anchor to, so the fence's start (the marker line itself) is the
        # closest real offset for it.
        start = line_starts[i]
        if first_line:
            body = [first_line] + body
        consumed.update(range(i, min(end + 1, len(lines))))
        if _fence_is_shell(lang, body):
            segments.append(ShellSegment(text="\n".join(body), origin="fence", start=start))
        i = end + 1
    return segments, consumed


def _fence_lang_and_first_line(gap: str, tag: str, trailing: str | None) -> tuple[str, str]:
    """Split a folded fence-open match into its real language tag and body line.

    A folded scalar joins lines with one space, so the whitespace after the
    marker (*gap*) says what *tag* is. Folding a labelled fence leaves the
    tag glued to the marker ("```python python3 -c ..."): *tag* is the
    language and *trailing* the first body line. Folding an unlabelled
    fence leaves a space ("``` python -c ..."): *tag* is the body's first
    word, whatever language it happens to name. A spaced shell tag
    ("``` bash echo x") stays a shell fence either way, and a marker with
    no trailing text ("``` python") keeps its tag.
    """
    lang = tag.lower()
    if gap and trailing and lang not in _SHELL_FENCE_LANGS:
        return "", f"{tag} {trailing}"
    return lang, trailing or ""


def _fence_is_shell(lang: str, body: list[str]) -> bool:
    """A shell-labelled fence, or an unlabelled one that opens with a command."""
    if lang not in _SHELL_FENCE_LANGS:
        return False
    if lang:
        return True
    first = next((ln for ln in body if ln.strip()), "")
    return is_command_line(first)


def _line_segments(
    lines: list[str], consumed: set[int], line_starts: list[int]
) -> list[ShellSegment]:
    """Command lines outside fences, each extended over its continuations and any heredoc body."""
    segments: list[ShellSegment] = []
    i = 0
    while i < len(lines):
        if i in consumed or not is_command_line(lines[i]):
            i += 1
            continue
        start = line_starts[i]
        chunk = [lines[i].strip()]
        while _can_continue(chunk, lines, i + 1, consumed):
            i += 1
            chunk.append(lines[i].strip())
        i = _absorb_heredoc_body(chunk, lines, i, consumed)
        segments.append(ShellSegment(text="\n".join(chunk), origin="line", start=start))
        i += 1
    return segments


def _absorb_heredoc_body(chunk: list[str], lines: list[str], i: int, consumed: set[int]) -> int:
    """Consume a heredoc's body lines up to its closer; append them only if unquoted.

    A heredoc opener (``cat <<EOF``) has no unclosed quote or trailing
    backslash, so :func:`_can_continue` stops right after it -- the body is
    otherwise never part of any segment's text, and a placeholder substituted
    into an unquoted (shell-expanding) body line never reaches a caller
    scanning segment text for ``{param}`` uses. An unquoted delimiter's body
    is live shell, so it is appended to *chunk*. A quoted one
    (``<<'EOF'``/``<<"EOF"``) makes the body inert data, never shell-expanded,
    so it must not be appended -- but its lines still need to be marked
    *consumed* here, or :func:`_line_segments` revisits a command-looking body
    line (``echo "$UNBOUND"``) as its own independent segment and a caller
    wrongly treats inert heredoc text as live shell. Several heredocs opened
    on one line (``cat <<A <<B``) have their bodies one after another.
    """
    for delimiter in _heredoc_delimiters("\n".join(chunk)):
        end = next((k for k in range(i + 1, len(lines)) if lines[k].strip() == delimiter.text), None)
        if end is None:
            return i
        for k in range(i + 1, end + 1):
            if not delimiter.quoted:
                chunk.append(lines[k].strip())
            consumed.add(k)
        i = end
    return i


def _can_continue(chunk: list[str], lines: list[str], nxt: int, consumed: set[int]) -> bool:
    """True when *chunk* is still open and line *nxt* may be pulled into it."""
    if len(chunk) >= _MAX_CONTINUATION_LINES or nxt >= len(lines) or nxt in consumed:
        return False
    return bool(lines[nxt].strip()) and _ends_open("\n".join(chunk))


def _span_segments(
    lines: list[str], consumed: set[int], line_starts: list[int]
) -> list[ShellSegment]:
    """Inline backtick spans in prose lines whose first word is a command."""
    segments: list[ShellSegment] = []
    for idx, line in enumerate(lines):
        if idx in consumed or is_command_line(line):
            continue
        for m in _BACKTICK_SPAN_RE.finditer(line):
            if is_command_line(m.group(1)):
                segments.append(ShellSegment(
                    text=m.group(1).strip(), origin="span", start=line_starts[idx] + m.start(1),
                ))
    return segments


def _line_starts(lines: list[str]) -> list[int]:
    """Character offset of each line's first character within the joined text.

    ``description.splitlines()`` discards the line-ending characters, so a
    plain running sum of ``len(line)`` would drift from real offsets in
    *description* once more than one line is involved. Reconstructing with a
    single ``"\\n".join`` and measuring from there keeps this in step with
    however ``extract_shell_segments`` itself joins lines back into text
    (also ``"\\n".join``), which is what a caller's offset is actually used
    to index into.
    """
    starts = [0]
    for line in lines[:-1]:
        starts.append(starts[-1] + len(line) + 1)
    return starts


def extract_shell_segments(description: str) -> list[ShellSegment]:
    """Return every run of shell text in *description*, in real source order.

    Segments are found per extraction method (fences, then command lines,
    then backtick spans) but are sorted by each segment's ``start`` offset
    before returning, so the returned order -- and therefore list index --
    reflects where each run actually sits in *description*, not which method
    happened to find it. A caller comparing "does A happen before B" (the
    position-aware unvalidated-param check in ``linter_shell``) needs that
    guarantee: without it, a same-stage check that is extracted as a line
    segment could sort ahead of a use extracted as a fence segment even when
    the use appears earlier in the real text.
    """
    return _extract(description)[0]


def extract_labelled_assignments(description: str) -> list[ShellSegment]:
    """Assignments written behind a prose label, outside every shell segment.

    "Bash tool: F=..." tells the agent to run ``F=...``; its label keeps the
    line out of :func:`extract_shell_segments`, yet it binds ``F`` for the
    shell text that follows. Each result holds the text after the label
    (origin ``"label"``). Lines inside fences, heredoc bodies, or a command
    line's continuation are never read as labels.
    """
    return _extract(description)[1]


def _extract(description: str) -> tuple[list[ShellSegment], list[ShellSegment]]:
    lines = description.splitlines()
    line_starts = _line_starts(lines)
    fences, consumed = _fence_segments(lines, line_starts)
    line_segments = _line_segments(lines, consumed, line_starts)
    segments = fences + line_segments + _span_segments(lines, consumed, line_starts)
    covered = set(consumed)
    for seg in line_segments:
        first = line_starts.index(seg.start)
        covered.update(range(first, first + seg.text.count("\n") + 1))
    labels = [
        ShellSegment(text=line[m.end():].strip(), origin="label", start=line_starts[idx] + m.end())
        for idx, line in enumerate(lines)
        if idx not in covered and (m := _LABEL_RE.match(line)) is not None
    ]
    return sorted(segments, key=lambda seg: seg.start), labels
