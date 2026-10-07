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
path ending in ``/qlty``, or a word from :data:`_STRONG_COMMANDS`.
Words that are also common English (``make``, ``test``, ``find``, ``for``, ...)
count only when the next token looks like shell -- an option, a path, a
quote, a ``$`` expansion, or a ``NAME=`` assignment -- a loop head
(``for``/``while``/``until``) only with a ``do`` on the same line, and ``if``
only with a ``then``. A wrapper from :data:`shell_parse.WRAPPER_NAMES`
(``env``, ``timeout``, ``sudo``, ``time`` ..., bare or path-qualified as in
``/usr/bin/env``) counts only when the command it runs is itself a command by
these rules, so "timeout to interrupt a handler" stays prose. A bare or
path-prefixed ``python``/``python3`` interpreter (optionally
version-suffixed, e.g. ``python3.11``) counts unless the word after it is
English -- a function word, verb, or version number ("python3 is
required", "python 3.11 or newer"); ``python3 runner input`` is a command.
A shell (``bash``, ``sh``, ``zsh``, ``dash``, ``ksh``, bare or path-qualified)
or ``eval`` counts only when the next word is an option, quote, ``$``
expansion, path, redirect or ``*.sh`` script (``bash -s name``, ``/bin/bash
< script``, ``eval "$CMD"``), so "sh is the default shell" stays prose.
Neither the interpreter, shell nor wrapper exception applies to a line whose
unquoted operator leads into more shell (see :func:`_operator_candidates`):
``python3 is; rm -rf scratch`` runs ``rm`` whatever its first operand says.
That search is iterative and judges at most :data:`_MAX_JUDGED_TEXTS` texts
per line; a line that needs more is treated as shell.
A line whose unquoted ``)`` closes nothing is prose wrapped
mid-parenthesis. Everything else, including a label before a command
("2. Server: curl ..."), is treated as prose: precision over recall.

Quoting is resolved with :func:`quote_context`, a small lexer, rather than by
regex over the shell text.

Indentation is the description's, not the shell's: a fence body loses its
common indentation, and a command line's heredoc body loses the command
line's own, before anything is parsed. A heredoc closer is then matched as
Bash matches it -- exactly, or past leading tabs for ``<<-``.

The command parser (:func:`shell_parse.parse_shell` and its supporting types)
lives in :mod:`shell_parse`, and the lexer beneath it in :mod:`shell_lex`.
"""

from __future__ import annotations

import re
import textwrap
from collections.abc import Callable
from dataclasses import dataclass

from .shell_lex import _heredoc_delimiters, _Lexer
from .shell_parse import WRAPPER_NAMES as _WRAPPER_NAMES
from .shell_parse import parse_shell as _parse_shell

__all__ = [
    "ShellSegment",
    "extract_labelled_assignments",
    "extract_shell_segments",
    "quote_context",
]

_STRONG_COMMANDS: frozenset[str] = frozenset({
    "gh", "git", "jq", "curl", "grep", "rg", "sed", "awk",
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
# Language tags that are also command words. A folded "``` python" with
# nothing after it is ambiguous -- the tag of a Python fence, or an unlabelled
# fence whose first line is `python`. These keep their tag; any other command
# word in that position is read as the first body line (``` echo, ``` python3).
_COMMAND_LIKE_LANG_TAGS: frozenset[str] = frozenset({"python"})

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
# Matching only the exact names "python"/"python3" once left a versioned
# interpreter line unextracted, so the isolation rule in linter_shell never
# saw it. An interpreter word is judged by _interpreter_line_is_command,
# which keeps "python3 is required" out while letting "python3 runner" in.
_PYTHON_WORD_RE = re.compile(r"^(?:.*/)?python3?(?:\.\d+)?$")
# Words that, right after an interpreter name, make the line English rather
# than a command: function words and verbs ("python3 is required", "python3
# and pip"), plus the nouns workflow prose puts there ("a short python3
# script for", "every python invocation", "use python3 inline"). No script
# is plausibly named one of these; any other first operand is a script.
_INTERPRETER_PROSE_WORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "not", "to", "for", "with", "on", "in", "of", "from", "as",
    "is", "are", "was", "must", "should", "will", "can", "may",
    "version", "interpreter", "installed", "required",
    "script", "command", "invocation", "snippet", "inline", "there",
})
_PROSE_TRAILING_PUNCTUATION = ".,;:!?"
# Shells and eval, bare or path-qualified (``/bin/bash``). The guard refuses
# ``eval``, ``sh -c`` and a shell reading stdin anywhere, so lines they lead
# must be extracted -- but each is also an English word ("sh is the default
# shell", "eval is dangerous", "bash scripts should ..."). So, like a weak
# command, one counts only when the next word looks like shell (an option,
# quote, ``$``, path, or redirect) or names a shell script; otherwise only an
# operator leading into more shell makes the line a command.
_SHELL_WORDS: frozenset[str] = frozenset({"bash", "sh", "zsh", "dash", "ksh", "eval"})
_SHELL_SCRIPT_RE = re.compile(r"[\w.-]+\.(?:sh|bash|zsh|ksh)")
_REDIRECT_PREFIXES = ("<", ">")
# "python 3.11 or newer": an all-numeric dotted version, never a script name.
# Matched whole after trailing punctuation is stripped, so "3.11," is a
# version while "3.py", "2026_job.py" and "3x" are scripts.
_VERSION_WORD_RE = re.compile(r"\d+(?:\.\d+)*")
# Operators that join a further command onto a line (see _operator_candidates).
_JOINING_OPS: frozenset[str] = frozenset({";", "&&", "||", "|", "|&"})
_PROMPT_PREFIX = "$ "
_SHELLISH_ARG_PREFIXES = ("-", '"', "'", "$", ".", "/", "~", "{")
# A stray apostrophe in a trailing comment would otherwise pull prose in until
# the next quote; a blank line or this many lines ends a continuation.
_MAX_CONTINUATION_LINES = 30
# is_command_line judges a line, then the texts its operators lead into, and
# so on. Past this many texts it stops and calls the line shell: a line of a
# thousand "python3 is;" joins is not prose, and judging every tail of it
# would take quadratic time.
_MAX_JUDGED_TEXTS = 64


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


def _command_body(line: str) -> str:
    """*line* stripped of surrounding whitespace and a ``$ `` prompt."""
    body = line.strip()
    return body[len(_PROMPT_PREFIX):] if body.startswith(_PROMPT_PREFIX) else body


def _is_command_word(word: str) -> bool:
    """True for a repo wrapper path, a qlty path, or a strong command."""
    word = word.lstrip("(")
    if word.startswith(("./bin/", "bin/", "~/.qlty/bin/")):
        return True
    return word.endswith("/qlty") or word in _STRONG_COMMANDS


def _interpreter_line_is_command(operand: str) -> bool:
    """An interpreter line is a command unless its first operand is English.

    Only the word right after the interpreter decides: ``python3 runner
    input``, ``python3 runner --flag`` and ``python3 -m pkg x`` are commands,
    while "python3 is required" and "python 3.11 or newer" are prose (see
    :data:`_INTERPRETER_PROSE_WORDS`). A bare interpreter (*operand* "") counts.
    """
    word = operand.rstrip(_PROSE_TRAILING_PUNCTUATION).lower()
    return word not in _INTERPRETER_PROSE_WORDS and not _VERSION_WORD_RE.fullmatch(word)


@dataclass(frozen=True)
class _Candidate:
    """A text that makes the line it came from shell when it is a command line itself."""

    text: str
    # False for a tail of an already-scanned text (what follows an operator,
    # or the command a wrapper runs): its operators are that text's too, and
    # are already queued, so scanning them again would only repeat work.
    scan_operators: bool = True


def _wrapper_target(body: str) -> str | None:
    """The text from the command a wrapper line runs, or None when it runs nothing.

    :func:`shell_parse.parse_shell` resolves the wrapper's own options and
    operands exactly as the linter rules will, so ``timeout 5 python3 x`` is
    judged on ``python3 x`` and "timeout to interrupt a handler" on
    "interrupt a handler". A wrapper that runs nothing (``env | grep``,
    ``command -v x``) has no target.
    """
    commands = _parse_shell(body).commands
    word = commands[0].word if commands else None
    if word is None or word.start == 0:
        return None
    return body[word.start:]


def _operator_candidates(body: str) -> tuple[bool, list[_Candidate]]:
    """Whether an unquoted operator in *body* surely introduces more shell, and what else might.

    The interpreter and wrapper prose exceptions judge one word, or the
    first simple command; a line such as ``python3 is; rm -rf scratch``
    still runs everything after the operator. So a line is shell, whatever
    its first operand says, when it joins on a command (``;``, ``&&``,
    ``||``, ``|`` followed by a command line), substitutes one (``$(...)``,
    backticks, ``<(...)`` whose body is a command line), or redirects to a
    path-shaped target (``> /dev/null``, ``< "$F"``). The lexer decides, so
    an operator inside quotes or a comment does not count.

    A path-shaped redirect decides at once (True). Otherwise the texts after
    each joining operator and inside each substitution are returned for
    :func:`is_command_line` to judge in turn, rather than judged here by
    recursion: a long run of joined prose would otherwise exhaust the stack.

    What follows each operator must itself look like shell because workflow
    prose uses the same characters: "python3 script for the aggregation; it
    is deterministic", "timeout to interrupt a handler; read job_runtime
    before", "(>= 3.11)", and Markdown code spans that lex as backticks.
    """
    tokens = _Lexer(body).tokens()
    candidates: list[_Candidate] = []
    for tok, nxt in zip(tokens, [*tokens[1:], None]):
        if tok.kind == "op" and tok.text in _JOINING_OPS:
            candidates.append(_Candidate(body[tok.start + len(tok.text):], scan_operators=False))
        elif tok.kind == "redirect":
            if nxt is not None and nxt.kind == "word" and _is_path_shaped(nxt.raw):
                return True, []
        else:
            candidates.extend(_Candidate(sub) for sub, _ in tok.subs)
    return False, candidates


def _is_path_shaped(word: str) -> bool:
    """A redirect target that reads as a path or an expansion, not an English word."""
    return word.startswith(_SHELLISH_ARG_PREFIXES) or "/" in word


def _closes_unopened_paren(line: str) -> bool:
    """True when an unquoted ``)`` on *line* closes nothing.

    That is a prose line wrapped mid-parenthesis ("git add -A) and run ...");
    as shell it would be a syntax error.
    """
    return _scan(line).stray_close


def _shell_word_is_command(second: str) -> bool:
    """A line led by a shell or ``eval`` is a command when its next word looks like shell.

    ``bash -s name``, ``/bin/bash < script``, ``eval "$CMD"`` and ``sh
    run.sh`` count; "sh is the default shell" and "bash scripts should" do not.
    """
    if second.startswith(_SHELLISH_ARG_PREFIXES + _REDIRECT_PREFIXES) or "/" in second:
        return True
    return bool(_SHELL_SCRIPT_RE.fullmatch(second))


def _weak_word_is_command(first: str, second: str, line: str) -> bool:
    """A common-English command word counts only with shell-looking context."""
    if first in _COMPOUND_HEADS:
        return any(tok.raw == _COMPOUND_HEADS[first] for tok in _Lexer(line).tokens())
    if _ASSIGN_START_RE.match(second):
        return True  # export FOO=..., local BAR=...
    return second.startswith(_SHELLISH_ARG_PREFIXES) or "/" in second


def is_command_line(line: str) -> bool:
    """True when *line* starts with a command or an upper-case assignment.

    Iterative: *line* is judged first, then each text its operators,
    substitutions or wrapper lead into (see :func:`_judge`), until one is a
    command or none are left. Past :data:`_MAX_JUDGED_TEXTS` the line is
    called shell rather than judged further.
    """
    pending = [_Candidate(line)]
    for _ in range(_MAX_JUDGED_TEXTS):
        if not pending:
            return False
        found, more = _judge(pending.pop())
        if found:
            return True
        pending.extend(reversed(more))
    return bool(pending)


def _english_word_operand_test(first: str) -> Callable[[str], bool] | None:
    """How to judge a line led by an interpreter or shell word, which is also English.

    The test decides from the next word alone; when it says prose, only an
    operator leading into more shell makes the line a command. None for any
    other first word.
    """
    word = first.lstrip("(")
    if _PYTHON_WORD_RE.match(word):
        return _interpreter_line_is_command
    if word.rsplit("/", 1)[-1] in _SHELL_WORDS:
        return _shell_word_is_command
    return None


def _judge(candidate: _Candidate) -> tuple[bool, list[_Candidate]]:
    """Whether *candidate* is a command line, or which further texts could make it one."""
    line = candidate.text
    body = _command_body(line)
    words = body.split(None, 3)
    if not words or _closes_unopened_paren(line):
        return False, []
    first = words[0]
    if _ASSIGN_START_RE.match(first) or _is_command_word(first):
        return True, []
    second = words[1] if len(words) > 1 else ""
    operand_test = _english_word_operand_test(first)
    if operand_test is not None:
        if operand_test(second):
            return True, []
        return _operator_candidates(body) if candidate.scan_operators else (False, [])
    if first in _WEAK_COMMANDS and _weak_word_is_command(first, second, line):
        return True, []
    if first.rsplit("/", 1)[-1] not in _WRAPPER_NAMES:
        return False, []
    found, more = _operator_candidates(body) if candidate.scan_operators else (False, [])
    target = _wrapper_target(body)
    if target is not None:
        more.insert(0, _Candidate(target, scan_operators=False))
    return found, more


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
        body = _dedent(body)
        if first_line:
            body = [first_line] + body
        consumed.update(range(i, min(end + 1, len(lines))))
        if _fence_is_shell(lang, body):
            segments.append(ShellSegment(text="\n".join(body), origin="fence", start=start))
        i = end + 1
    return segments, consumed


def _dedent(lines: list[str]) -> list[str]:
    """*lines* with their common leading whitespace removed, as a reader runs an indented block.

    Description prose indents its shell (under a list item, say), and the
    text bash would run is the block with that indentation taken off. A
    heredoc closer must match exactly in *that* text: ``EOF`` indented with
    the rest of the block closes, one indented further does not.
    """
    return textwrap.dedent("\n".join(lines)).split("\n") if lines else []


def _strip_indent(line: str, width: int) -> str:
    """*line* with up to *width* leading blanks removed: the indentation its block shares."""
    blanks = len(line) - len(line.lstrip(" \t"))
    return line[min(blanks, width):]


def _fence_lang_and_first_line(gap: str, tag: str, trailing: str | None) -> tuple[str, str]:
    """Split a folded fence-open match into its real language tag and body line.

    A folded scalar joins lines with one space, so the whitespace after the
    marker (*gap*) says what *tag* is. Folding a labelled fence leaves the
    tag glued to the marker ("```python python3 -c ..."): *tag* is the
    language and *trailing* the first body line. Folding an unlabelled
    fence leaves a space ("``` python -c ..."): *tag* is the body's first
    word, whatever language it happens to name. A spaced shell tag
    ("``` bash echo x") stays a shell fence either way.

    A spaced word with no trailing text is ambiguous: "``` python" is a
    Python fence, but "``` echo" is an unlabelled fence whose first line is a
    one-word command. A word that is a command line on its own is read as that
    body line, unless it is a language tag in :data:`_COMMAND_LIKE_LANG_TAGS`.
    """
    lang = tag.lower()
    if not gap or lang in _SHELL_FENCE_LANGS:
        return lang, trailing or ""
    if trailing:
        return "", f"{tag} {trailing}"
    if lang not in _COMMAND_LIKE_LANG_TAGS and is_command_line(tag):
        return "", tag
    return lang, ""


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
        start, start_index = line_starts[i], i
        chunk = [lines[i].strip()]
        while _can_continue(chunk, lines, i + 1, consumed):
            i += 1
            chunk.append(lines[i].strip())
        indent = len(lines[start_index]) - len(lines[start_index].lstrip(" \t"))
        i = _absorb_heredoc_body(chunk, lines, i, consumed, indent)
        segments.append(ShellSegment(text="\n".join(chunk), origin="line", start=start))
        i += 1
    return segments


def _absorb_heredoc_body(
    chunk: list[str], lines: list[str], i: int, consumed: set[int], indent: int
) -> int:
    """Append a heredoc's body lines, through its closer, to *chunk*.

    A heredoc opener (``cat <<EOF``) has no unclosed quote or trailing
    backslash, so :func:`_can_continue` stops right after it -- the body is
    otherwise never part of any segment's text, and a placeholder in it never
    reaches a caller scanning segment text for ``{param}`` uses.

    The body is appended whether or not the delimiter is quoted. A quoted
    one (``<<'EOF'``) stops the *shell* expanding the body, and the parser
    reports it as inert so the expansion rules skip it; but a ``{param}`` is
    substituted into the text before bash parses it, so a value carrying a
    newline and the delimiter closes the heredoc early (``param_guard``'s
    documented break-out). The pre-shell rule must see that body. Its lines
    are also marked *consumed*, or :func:`_line_segments` revisits a
    command-looking body line (``echo "$UNBOUND"``) as its own live segment.
    Several heredocs opened on one line (``cat <<A <<B``) have their bodies
    one after another.

    Body lines keep their own indentation past the block's: *indent*, the
    command line's, is all that is removed (see :func:`_strip_indent`). The
    closer is then matched as Bash matches it (``_Delimiter.closes``):
    exactly, or after leading tabs for ``<<-`` -- so a closer indented with
    the block ends the body, while one indented further is body data.
    """
    for delimiter in _heredoc_delimiters("\n".join(chunk)):
        body = [_strip_indent(line, indent) for line in lines[i + 1:]]
        end = next((k for k, line in enumerate(body) if delimiter.closes(line)), None)
        if end is None:
            return i
        chunk.extend(body[:end + 1])
        consumed.update(range(i + 1, i + end + 2))
        i += end + 1
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
