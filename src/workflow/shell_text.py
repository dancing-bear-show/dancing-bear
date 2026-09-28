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

:func:`parse_shell` turns shell text into :class:`SimpleCommand` values -- the
one model of "which word is the program" every rule in ``linter_shell`` asks
about. It splits on control operators (``;``, ``&&``, ``||``, ``|``, ``&``,
newline, ``(``, ``)``), passes over reserved words (``if``, ``then``, ``do``,
``!``, ``{``, ``time`` ...) and leading ``NAME=value`` words, sees through
wrappers (``env``, ``sudo``, ``xargs``, ``timeout N`` ...), recurses into
``$(...)``, backticks and ``<(...)``, and reads heredoc bodies as data rather
than as commands. shlex cannot do this: it reports no offsets, strips the
quotes that tell ``"rm"`` from ``rm``, and has no notion of heredocs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

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


# ---------------------------------------------------------------------------
# Tokens and simple commands
# ---------------------------------------------------------------------------

_METACHARS = frozenset(" \t\n;&|<>()")
_CONTROL_OPS = (";;&", ";;", ";&", "&&", "||", "|&", ";", "&", "|", "(", ")", "\n")
_REDIRECT_OPS = ("&>>", "&>", "<<<", "<<-", "<<", "<>", "<&", ">>", ">|", ">&", "<", ">")
_HEREDOC_OPS = frozenset({"<<", "<<-"})
_WRITE_REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>", "<>", ">&"})
_FD_PREFIX_RE = re.compile(r"\d+(?=[<>])")
# ``2>&1`` / ``>&-`` duplicate or close a descriptor; they write no file.
_FD_TARGET_RE = re.compile(r"\d+-?|-")
_ASSIGNMENT_WORD_RE = re.compile(r"([A-Za-z_]\w*)(?:\[[^\]]*\])?\+?=")
_DQUOTE_ESCAPABLE = frozenset('$`"\\\n')

# Reserved words that open or continue a compound command: the next word is
# still in command position. ``do rm x`` runs ``rm``, not a program ``do``.
_KEEP_START = frozenset({"!", "{", "then", "do", "else", "elif", "if", "while", "until", "time", "coproc"})
_COMPOUND_CLOSERS = frozenset({"}", "fi", "done", "esac"})
# Reserved word -> the parser state it opens when met in command position.
_START_STATES = {
    "for": "loop_var", "select": "loop_var",  # the header is not a command
    "case": "case_subject",
    "function": "function_name",
    "[[": "test",                             # < and > compare inside [[ ]]
}
_CASE_ENDS = frozenset({";;", ";&", ";;&"})


@dataclass(frozen=True)
class ShellToken:
    """One lexed unit of shell text: a word, an operator, a redirect, or ``(( ))``."""

    kind: str  # "word" | "op" | "redirect" | "arith"
    text: str  # a word's value with quoting removed; an operator's own spelling
    start: int  # offset within the text given to parse_shell, plus its base
    raw: str = ""  # a word's source spelling, quotes included
    subs: tuple[tuple[str, int], ...] = ()  # (body, offset) of each $(...), `...`, <(...)

    @property
    def quoted(self) -> bool:
        """True when any part of the word was quoted or escaped."""
        return any(ch in self.raw for ch in "'\"\\")

    @property
    def assigned_name(self) -> str:
        """``NAME`` for an unquoted ``NAME=value`` word, else ``""``."""
        m = _ASSIGNMENT_WORD_RE.match(self.raw)
        return m.group(1) if m else ""


@dataclass(frozen=True)
class Redirect:
    """A redirection operator and the word it applies to."""

    op: str
    target: str

    @property
    def writes(self) -> bool:
        """True when this redirect opens a file for writing."""
        if self.op not in _WRITE_REDIRECTS:
            return False
        return not (self.op == ">&" and _FD_TARGET_RE.fullmatch(self.target))


@dataclass(frozen=True)
class Heredoc:
    """A heredoc body: data fed to a command, never commands itself."""

    delimiter: str
    quoted: bool  # a quoted delimiter makes the body inert: nothing expands
    body: str
    start: int
    subs: tuple[tuple[str, int], ...] = ()  # substitutions an unquoted body runs


@dataclass(frozen=True)
class SimpleCommand:
    """One simple command, with the word that selects its program identified."""

    words: tuple[ShellToken, ...]  # every word after the leading assignments
    assignments: tuple[ShellToken, ...]  # leading NAME=value words, and any env sets
    redirects: tuple[Redirect, ...]
    command_index: int  # index in *words* of the program that runs; -1 for none
    in_loop: bool = False  # inside a for/while/until body (do ... done)

    @property
    def word(self) -> ShellToken | None:
        """The word naming the program, after any wrappers; None when nothing runs."""
        return self.words[self.command_index] if self.command_index >= 0 else None

    @property
    def name(self) -> str:
        """The program's basename, as the guard resolves it (``/bin/rm`` -> ``rm``)."""
        word = self.word
        return word.text.rsplit("/", 1)[-1] if word is not None else ""

    @property
    def arguments(self) -> tuple[ShellToken, ...]:
        """The words after the program word: this command's operands and options only."""
        return self.words[self.command_index + 1:] if self.command_index >= 0 else ()

    @property
    def args(self) -> list[str]:
        return [tok.text for tok in self.arguments]


@dataclass(frozen=True)
class ShellScript:
    """Every simple command, heredoc, and loop variable in a piece of shell text."""

    commands: tuple[SimpleCommand, ...]
    heredocs: tuple[Heredoc, ...]
    loop_variables: tuple[str, ...]

    def inert_spans(self) -> list[tuple[int, int]]:
        """(start, end) of each quoted heredoc body: text the shell never expands."""
        return [(d.start, d.start + len(d.body)) for d in self.heredocs if d.quoted]


@dataclass
class _WordParts:
    """Accumulates one word's unquoted value and the substitutions inside it."""

    parts: list[str] = field(default_factory=list)
    subs: list[tuple[str, int]] = field(default_factory=list)


def _match_op(text: str, pos: int, ops: tuple[str, ...]) -> str | None:
    return next((op for op in ops if text.startswith(op, pos)), None)


def _arith_end(text: str, i: int) -> int:
    """Index just past the ``))`` closing an arithmetic body that starts at *i*."""
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")" and depth:
            depth -= 1
        elif text[j] == ")":
            return j + 2 if text.startswith("))", j) else j + 1
    return len(text)


def _brace_end(text: str, i: int) -> int:
    """Index just past the ``}`` closing a ``${...}`` body that starts at *i*."""
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}" and depth:
            depth -= 1
        elif text[j] == "}":
            return j + 1
    return len(text)


class _Lexer:
    """Split shell text into :class:`ShellToken` values, reading heredoc bodies as data.

    Never raises: an unclosed quote or substitution in a fragment of prose
    simply runs to the end of the text.
    """

    def __init__(self, text: str, base: int = 0, pos: int = 0) -> None:
        self.text = text
        self.base = base
        self.pos = pos
        self.heredocs: list[Heredoc] = []
        self._pending: list[ShellToken] = []  # heredoc delimiters awaiting their body
        self._want_delimiter = False

    def tokens(self) -> list[ShellToken]:
        out = []
        while (tok := self.next_token()) is not None:
            out.append(tok)
        return out

    def next_token(self) -> ShellToken | None:
        self._skip_blanks()
        if self.pos >= len(self.text):
            return None
        start = self.pos
        if self.text.startswith("((", start):
            self.pos = _arith_end(self.text, start + 2)
            return ShellToken("arith", self.text[start:self.pos], self.base + start)
        return self._operator() or self._word()

    def closing_paren(self) -> int:
        """Index of the ``)`` that closes a substitution whose body starts at ``self.pos``."""
        depth = 0
        while (tok := self.next_token()) is not None:
            if tok.kind != "op" or tok.text not in "()":
                continue
            if tok.text == "(":
                depth += 1
            elif depth:
                depth -= 1
            else:
                return tok.start - self.base
        return len(self.text)

    def expanding_subs(self) -> list[tuple[str, int]]:
        """Substitutions in the whole text read as an unquoted heredoc body."""
        parts = _WordParts()
        self._double(0, parts, closer=None)
        return parts.subs

    def _skip_blanks(self) -> None:
        text = self.text
        while self.pos < len(text):
            if text[self.pos] in " \t":
                self.pos += 1
            elif text.startswith("\\\n", self.pos):
                self.pos += 2
            elif text[self.pos] == "#":
                eol = text.find("\n", self.pos)
                self.pos = len(text) if eol < 0 else eol
            else:
                return

    def _operator(self) -> ShellToken | None:
        text, pos = self.text, self.pos
        if text[pos] in "<>" and text.startswith("(", pos + 1):
            return None  # <(...) / >(...): a process substitution is a word
        fd = _FD_PREFIX_RE.match(text, pos)
        at = fd.end() if fd else pos
        redirect = _match_op(text, at, _REDIRECT_OPS)
        if redirect is not None:
            self.pos = at + len(redirect)
            self._want_delimiter = redirect in _HEREDOC_OPS
            return ShellToken("redirect", redirect, self.base + pos)
        op = _match_op(text, pos, _CONTROL_OPS)
        if op is None:
            return None
        self.pos = pos + len(op)
        self._want_delimiter = False
        if op == "\n":
            self._read_heredoc_bodies()
        return ShellToken("op", op, self.base + pos)

    def _word(self) -> ShellToken:
        text, start = self.text, self.pos
        parts = _WordParts()
        i = start
        if text[i] in "<>":
            i = self._command_sub(i, i + 2, parts)
        while i < len(text) and text[i] not in _METACHARS:
            i = self._word_char(i, parts)
        i = max(i, start + 1)
        self.pos = i
        tok = ShellToken("word", "".join(parts.parts), self.base + start, text[start:i], tuple(parts.subs))
        if self._want_delimiter:
            self._want_delimiter = False
            self._pending.append(tok)
        return tok

    def _word_char(self, i: int, parts: _WordParts) -> int:
        ch = self.text[i]
        if ch == "\\":
            parts.parts.append(self.text[i + 1:i + 2].replace("\n", ""))
            return i + 2
        if ch == "'":
            end = self.text.find("'", i + 1)
            end = len(self.text) if end < 0 else end
            parts.parts.append(self.text[i + 1:end])
            return end + 1
        if ch == '"':
            return self._double(i + 1, parts, closer='"')
        return self._expansion(i, parts)

    def _expansion(self, i: int, parts: _WordParts) -> int:
        """Read the ``$...`` or backtick construct at *i*, or one plain character."""
        text = self.text
        if text.startswith("$((", i):
            end = _arith_end(text, i + 3)
        elif text.startswith("$(", i):
            return self._command_sub(i, i + 2, parts)
        elif text.startswith("${", i):
            end = _brace_end(text, i + 2)
        elif text[i] == "`":
            return self._backtick(i, parts)
        else:
            end = i + 1
        parts.parts.append(text[i:end])
        return end

    def _double(self, i: int, parts: _WordParts, closer: str | None) -> int:
        """Read double-quoted text from *i* up to *closer* (None: the end of the text)."""
        text = self.text
        while i < len(text) and text[i] != closer:
            if text[i] == "\\" and text[i + 1:i + 2] in _DQUOTE_ESCAPABLE:
                parts.parts.append(text[i + 1].replace("\n", ""))
                i += 2
            elif text[i] in "$`":
                i = self._expansion(i, parts)
            else:
                parts.parts.append(text[i])
                i += 1
        return i + 1 if closer is not None else i

    def _command_sub(self, open_at: int, body_start: int, parts: _WordParts) -> int:
        end = _Lexer(self.text, self.base, body_start).closing_paren()
        parts.subs.append((self.text[body_start:end], self.base + body_start))
        parts.parts.append(self.text[open_at:end + 1])
        return min(end + 1, len(self.text))

    def _backtick(self, i: int, parts: _WordParts) -> int:
        text = self.text
        j = i + 1
        while j < len(text) and text[j] != "`":
            j += 2 if text[j] == "\\" else 1
        j = min(j, len(text))
        parts.subs.append((text[i + 1:j], self.base + i + 1))
        parts.parts.append(text[i:j + 1])
        return min(j + 1, len(text))

    def _read_heredoc_bodies(self) -> None:
        pending, self._pending = self._pending, []
        for delimiter in pending:
            self._read_heredoc_body(delimiter)

    def _read_heredoc_body(self, delimiter: ShellToken) -> None:
        text, start = self.text, self.pos
        i, end, resume = start, len(text), len(text)
        while i < len(text):
            eol = text.find("\n", i)
            eol = len(text) if eol < 0 else eol
            if text[i:eol].strip() == delimiter.text:
                end, resume = i, min(eol + 1, len(text))
                break
            i = eol + 1
        body = text[start:end]
        subs = () if delimiter.quoted else tuple(_Lexer(body, self.base + start).expanding_subs())
        self.heredocs.append(Heredoc(delimiter.text, delimiter.quoted, body, self.base + start, subs))
        self.pos = resume


@dataclass(frozen=True)
class _Wrapper:
    """How a wrapper command's own options are laid out before the command it runs."""

    value_opts: str = ""  # short options whose value is attached or the next word
    long_value_opts: tuple[str, ...] = ()  # long options whose value may be the next word
    lookup_opts: str = ""  # options that make it run nothing (``command -v``)
    leading_operands: int = 0  # operands before the command (``timeout``'s duration)
    takes_assignments: bool = False  # ``env NAME=value cmd``


_TIMEOUT = _Wrapper(value_opts="sk", long_value_opts=("signal", "kill-after"), leading_operands=1)
# Mirrors the wrapper handlers in .claude/hooks/_bash_write_targets.py, which
# the Bash guard uses to find the command a wrapper runs.
_WRAPPERS: dict[str, _Wrapper] = {
    "env": _Wrapper(value_opts="uCSP", long_value_opts=("unset", "chdir", "split-string"),
                    takes_assignments=True),
    "command": _Wrapper(lookup_opts="vV"),
    "builtin": _Wrapper(),
    "nohup": _Wrapper(),
    "exec": _Wrapper(value_opts="a"),
    "nice": _Wrapper(value_opts="n", long_value_opts=("adjustment",)),
    "stdbuf": _Wrapper(value_opts="ioe", long_value_opts=("input", "output", "error")),
    "time": _Wrapper(value_opts="of", long_value_opts=("output", "format")),
    "timeout": _TIMEOUT,
    "gtimeout": _TIMEOUT,
    "sudo": _Wrapper(value_opts="ugCDhprtTUc", lookup_opts="lvK",
                     long_value_opts=("user", "group", "chdir", "host", "prompt", "role", "type",
                                      "other-user")),
    "doas": _Wrapper(value_opts="uC"),
    "xargs": _Wrapper(value_opts="IELnPsda",
                      long_value_opts=("arg-file", "delimiter", "max-args", "max-procs",
                                       "max-chars", "process-slot-var")),
}


def _short_option_width(word: str, spec: _Wrapper) -> int | None:
    """Words consumed by the short-option cluster *word*; None when it runs nothing."""
    for k, ch in enumerate(word[1:], start=1):
        if ch in spec.lookup_opts:
            return None
        if ch in spec.value_opts:
            return 1 if k + 1 < len(word) else 2
    return 1


def _option_width(word: str, spec: _Wrapper) -> int | None:
    """Words the wrapper option *word* consumes: 0 when it is not an option."""
    if word == "-":
        return 1
    if word.startswith("--"):
        name, eq, _ = word[2:].partition("=")
        return 2 if not eq and name in spec.long_value_opts else 1
    if word.startswith("-"):
        return _short_option_width(word, spec)
    return 0


def _skip_wrapper(
    words: tuple[ShellToken, ...], i: int, spec: _Wrapper
) -> tuple[int | None, list[ShellToken]]:
    """Index of the command a wrapper at ``words[i - 1]`` runs, plus any env assignments."""
    while i < len(words) and words[i].text != "--":
        width = _option_width(words[i].text, spec)
        if width is None:
            return None, []
        if not width:
            break
        i += width
    if i < len(words) and words[i].text == "--":
        i += 1
    assigned = []
    while spec.takes_assignments and i < len(words) and words[i].assigned_name:
        assigned.append(words[i])
        i += 1
    i += spec.leading_operands
    return (i if i < len(words) else None), assigned


def _resolve_command(words: tuple[ShellToken, ...]) -> tuple[int, list[ShellToken]]:
    """Index of the program word after any wrappers (-1 for none), and env's assignments."""
    i: int | None = 0
    assigned: list[ShellToken] = []
    while i is not None and i < len(words):
        spec = _WRAPPERS.get(words[i].text.rsplit("/", 1)[-1])
        if spec is None:
            return i, assigned
        i, more = _skip_wrapper(words, i + 1, spec)
        assigned.extend(more)
    return -1, assigned


class _CommandSplitter:
    """Group a token stream into :class:`SimpleCommand` values.

    Tracks just enough shell grammar to know where each command word sits:
    reserved words, ``for``/``case`` headers, ``[[ ]]`` tests (whose ``<``
    and ``>`` compare rather than redirect), subshells, and loop bodies.
    """

    def __init__(self, in_loop: bool) -> None:
        self.outer_loop = in_loop
        self.loop_depth = 0
        self.state = "start"
        self.commands: list[SimpleCommand] = []
        self.loop_variables: list[str] = []
        self.nested: list[ShellScript] = []
        self._words: list[ShellToken] = []
        self._assignments: list[ShellToken] = []
        self._redirects: list[Redirect] = []
        self._redirect_op: str | None = None
        self._in_loop = in_loop
        self._after_time = False
        self._on_word = {
            "start": self._start_word, "after": self._start_word, "args": self._words.append,
            "test": self._test_word, "loop_var": self._loop_var_word, "loop_head": self._loop_head_word,
            "case_subject": self._case_subject_word, "case_pattern": self._case_pattern_word,
            "function_name": self._function_name_word,
        }

    @property
    def inside_loop(self) -> bool:
        return self.outer_loop or self.loop_depth > 0

    def feed(self, tok: ShellToken) -> None:
        for body, offset in tok.subs:
            self.nested.append(parse_shell(body, offset, self.inside_loop))
        if tok.kind == "word" and self._redirect_op is not None:
            self._redirects.append(Redirect(self._redirect_op, tok.text))
            self._redirect_op = None
        elif tok.kind == "word":
            self._on_word[self.state](tok)
        elif tok.kind == "redirect" and self.state != "test":
            self._redirect_op = tok.text
        elif tok.kind == "op":
            self._operator(tok.text)
        elif tok.kind == "arith":
            self.state = "loop_head" if self.state == "loop_var" else self.state

    def finish(self) -> None:
        if self._words or self._assignments or self._redirects:
            words = tuple(self._words)
            index, env_assignments = _resolve_command(words)
            self.commands.append(SimpleCommand(
                words, tuple(self._assignments + env_assignments), tuple(self._redirects),
                index, self._in_loop,
            ))
        self._words.clear()
        self._assignments = []
        self._redirects = []
        self._redirect_op = None
        self._in_loop = self.inside_loop
        self._after_time = False

    def _operator(self, op: str) -> None:
        if self.state == "test" and op != "\n":
            return  # && || ( ) are test logic inside [[ ]]
        if self.state == "case_pattern":
            self.state = "start" if op == ")" else self.state
            return
        if op == "(" and self.state == "args" and len(self._words) == 1:
            self._words.clear()  # name ( ): a function definition
            self.state = "start"
            return
        if op == "(":
            return
        self.finish()
        if op == ")":
            self.state = "after"
        else:
            self.state = "case_pattern" if op in _CASE_ENDS else "start"

    def _start_word(self, tok: ShellToken) -> None:
        word = tok.raw  # only an unquoted word can be a reserved word
        if self._after_time and word == "-p":
            self._after_time = False
            return
        self._after_time = word == "time"
        if word in _KEEP_START:
            self.loop_depth += word == "do"
            self._in_loop = self.inside_loop
        elif word in _COMPOUND_CLOSERS:
            self.loop_depth -= word == "done" and self.loop_depth > 0
            self.state = "after"  # a redirect after `done` still belongs to the loop
        elif word in _START_STATES:
            self.state = _START_STATES[word]
        elif tok.assigned_name and not self._words:
            self._assignments.append(tok)
        else:
            self._words.append(tok)
            self.state = "args"

    def _test_word(self, tok: ShellToken) -> None:
        if tok.raw == "]]":
            self.state = "after"

    def _loop_var_word(self, tok: ShellToken) -> None:
        self.loop_variables.append(tok.text)
        self.state = "loop_head"

    def _loop_head_word(self, tok: ShellToken) -> None:
        if tok.raw == "do":  # `for f do ...` needs no separator before `do`
            self.state = "start"
            self._start_word(tok)

    def _case_subject_word(self, tok: ShellToken) -> None:
        if tok.raw == "in":
            self.state = "case_pattern"

    def _case_pattern_word(self, tok: ShellToken) -> None:
        if tok.raw == "esac":
            self.state = "after"

    def _function_name_word(self, tok: ShellToken) -> None:
        self.state = "start"


def parse_shell(text: str, base: int = 0, in_loop: bool = False) -> ShellScript:
    """Every simple command in shell *text*, including those in substitutions.

    Offsets in the result are positions in *text* plus *base*. *in_loop*
    marks every command as inside a loop body (a substitution within one).
    """
    lexer = _Lexer(text, base)
    splitter = _CommandSplitter(in_loop)
    for tok in lexer.tokens():
        splitter.feed(tok)
    splitter.finish()
    nested = list(splitter.nested)
    for doc in lexer.heredocs:
        nested.extend(parse_shell(body, offset, in_loop) for body, offset in doc.subs)
    return ShellScript(
        commands=tuple(splitter.commands) + tuple(c for s in nested for c in s.commands),
        heredocs=tuple(lexer.heredocs) + tuple(d for s in nested for d in s.heredocs),
        loop_variables=tuple(splitter.loop_variables) + tuple(v for s in nested for v in s.loop_variables),
    )


def _heredoc_delimiters(text: str) -> list[ShellToken]:
    """The delimiter word of each heredoc opened in *text*, in order."""
    tokens = _Lexer(text).tokens()
    return [
        nxt for tok, nxt in zip(tokens, tokens[1:])
        if tok.kind == "redirect" and tok.text in _HEREDOC_OPS and nxt.kind == "word"
    ]


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
