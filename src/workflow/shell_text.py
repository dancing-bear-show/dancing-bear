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
path ending in ``/python3`` or ``/qlty``, or a word from :data:`_STRONG_COMMANDS`.
Words that are also common English (``make``, ``test``, ``find``, ``for``, ...)
count only when the next token looks like shell -- an option, a path, a
quote, or a ``$`` expansion -- and a loop head (``for``/``while``/``until``)
only with a ``do`` on the same line. A line whose unquoted ``)`` closes
nothing is prose wrapped mid-parenthesis. Everything else, including a label
before a command ("2. Server: curl ..."), is treated as prose: precision over
recall.

Quoting is resolved with :func:`quote_context`, a small lexer, rather than by
regex over the shell text.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

__all__ = [
    "ShellSegment",
    "extract_shell_segments",
    "quote_context",
    "split_tokens",
]

_STRONG_COMMANDS: frozenset[str] = frozenset({
    "gh", "git", "jq", "curl", "python", "python3", "grep", "rg", "sed", "awk",
    "mkdir", "rm", "cp", "mv", "ls", "cat", "printf", "echo", "cd", "ollama",
    "launchctl", "qlty", "xargs", "wc", "mktemp", "shasum", "du", "df",
    "vm_stat", "uv", "pip", "npm", "chmod", "PYTHONPATH",
})

_WEAK_COMMANDS: frozenset[str] = frozenset({
    "make", "test", "find", "sort", "head", "tail", "diff", "touch", "export",
    "command", "for", "while", "until", "read", "set",
})

# A loop head counts only with a ``do`` on the same line: Python's
# ``for x in y:`` and prose "for R in $ROOTS" have none.
_LOOP_WORDS: frozenset[str] = frozenset({"for", "while", "until"})

_SHELL_FENCE_LANGS: frozenset[str] = frozenset({"", "sh", "bash", "shell", "zsh", "console"})

_FENCE_RE = re.compile(r"^\s*```\s*([A-Za-z0-9_+-]*)\s*$")
_ASSIGN_START_RE = re.compile(r"^[A-Z_][A-Z0-9_]*=")
_BACKTICK_SPAN_RE = re.compile(r"`([^`\n]+)`")
_PROMPT_PREFIX = "$ "
_SHELLISH_ARG_PREFIXES = ("-", '"', "'", "$", ".", "/", "~", "{")
# A stray apostrophe in a trailing comment would otherwise pull prose in until
# the next quote; a blank line or this many lines ends a continuation.
_MAX_CONTINUATION_LINES = 30


@dataclass(frozen=True)
class ShellSegment:
    """One contiguous run of shell text found in a description."""

    text: str
    origin: str  # "fence" | "line" | "span"


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


def split_tokens(text: str) -> list[str]:
    """Tokenise shell *text* with :mod:`shlex`, separating ``; | & ( )``.

    Falls back to whitespace splitting when shlex rejects the input (an
    unbalanced quote in a fragment of prose, for instance).
    """
    # POSIX sh deletes a backslash-newline; shlex would keep the newline and
    # glue it onto the next token ("\n--check").
    text = text.replace("\\\n", " ")
    lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|()")
    lexer.whitespace_split = True  # noqa - read by shlex itself; vulture cannot see it
    lexer.commenters = ""  # noqa - "#" inside shell words is not a comment here
    try:
        return list(lexer)
    except ValueError:
        return text.split()


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
    """True for a repo wrapper path, a python/qlty path, or a strong command."""
    word = word.lstrip("(")
    if word.startswith(("./bin/", "bin/", "~/.qlty/bin/")):
        return True
    if word.endswith(("/python3", "/python", "/qlty")):
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
    if first in _LOOP_WORDS:
        return "do" in split_tokens(line)
    return second.startswith(_SHELLISH_ARG_PREFIXES) or "/" in second


def is_command_line(line: str) -> bool:
    """True when *line* starts with a command or an upper-case assignment."""
    first, second = _first_words(line)
    if not first or _closes_unopened_paren(line):
        return False
    if _ASSIGN_START_RE.match(first) or _is_command_word(first):
        return True
    return first in _WEAK_COMMANDS and _weak_word_is_command(first, second, line)


def _fence_segments(lines: list[str]) -> tuple[list[ShellSegment], set[int]]:
    """Shell fences and the indexes of every line inside ANY fence."""
    segments: list[ShellSegment] = []
    consumed: set[int] = set()
    i = 0
    while i < len(lines):
        m = _FENCE_RE.match(lines[i])
        if m is None:
            i += 1
            continue
        end = next((j for j in range(i + 1, len(lines)) if _FENCE_RE.match(lines[j])), len(lines))
        body = lines[i + 1:end]
        consumed.update(range(i, min(end + 1, len(lines))))
        if _fence_is_shell(m.group(1).lower(), body):
            segments.append(ShellSegment(text="\n".join(body), origin="fence"))
        i = end + 1
    return segments, consumed


def _fence_is_shell(lang: str, body: list[str]) -> bool:
    """A shell-labelled fence, or an unlabelled one that opens with a command."""
    if lang not in _SHELL_FENCE_LANGS:
        return False
    if lang:
        return True
    first = next((ln for ln in body if ln.strip()), "")
    return is_command_line(first)


def _line_segments(lines: list[str], consumed: set[int]) -> list[ShellSegment]:
    """Command lines outside fences, each extended over its continuations."""
    segments: list[ShellSegment] = []
    i = 0
    while i < len(lines):
        if i in consumed or not is_command_line(lines[i]):
            i += 1
            continue
        chunk = [lines[i].strip()]
        while _can_continue(chunk, lines, i + 1, consumed):
            i += 1
            chunk.append(lines[i].strip())
        segments.append(ShellSegment(text="\n".join(chunk), origin="line"))
        i += 1
    return segments


def _can_continue(chunk: list[str], lines: list[str], nxt: int, consumed: set[int]) -> bool:
    """True when *chunk* is still open and line *nxt* may be pulled into it."""
    if len(chunk) >= _MAX_CONTINUATION_LINES or nxt >= len(lines) or nxt in consumed:
        return False
    return bool(lines[nxt].strip()) and _ends_open("\n".join(chunk))


def _span_segments(lines: list[str], consumed: set[int]) -> list[ShellSegment]:
    """Inline backtick spans in prose lines whose first word is a command."""
    segments: list[ShellSegment] = []
    for idx, line in enumerate(lines):
        if idx in consumed or is_command_line(line):
            continue
        for m in _BACKTICK_SPAN_RE.finditer(line):
            if is_command_line(m.group(1)):
                segments.append(ShellSegment(text=m.group(1).strip(), origin="span"))
    return segments


def extract_shell_segments(description: str) -> list[ShellSegment]:
    """Return every run of shell text in *description*, per the module rules."""
    lines = description.splitlines()
    fences, consumed = _fence_segments(lines)
    return fences + _line_segments(lines, consumed) + _span_segments(lines, consumed)
