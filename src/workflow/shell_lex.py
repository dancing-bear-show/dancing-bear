"""Shell lexer: split shell text into tokens, reading heredoc bodies as data.

:class:`_Lexer` turns shell text into :class:`ShellToken` values -- words,
operators, redirects and ``(( ))`` -- with each word's quoting removed and
the ``$(...)``, backtick and ``<(...)`` bodies inside it recorded, also where
they sit inside a ``${...}`` or arithmetic body. Heredoc bodies are read as
data (:class:`Heredoc`), their delimiters matched by Bash's rule. Two bounds
keep its recursion finite: :data:`MAX_DEPTH`, the Bash guard's limit on
nested substitutions, and :data:`MAX_EXPANSION_NEST`.

:mod:`shell_parse` groups these tokens into simple commands; ``shell_text``
uses the lexer directly. Both import its names under private aliases, so
they are importable from here only.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

__all__ = [
    "Heredoc",
    "ShellToken",
    "Span",
]

# ---------------------------------------------------------------------------
# Tokens and heredocs
# ---------------------------------------------------------------------------

# _bash_write_targets.py MAX_DEPTH: the guard refuses a command whose
# substitutions and nested shell strings go deeper than this. Only constructs
# the guard reads with a child Parser count: $(...), backticks, <(...)/>(...)
# and sh -c/eval strings -- never ${...} or arithmetic, which it reads in place.
MAX_DEPTH = 32
# Recursion-safety bound on lexical nesting: every ${...}, $((...)), ((...))
# and $(...)/<(...) body read inside another. It is not a guard limit; it keeps
# the recursive reader well inside Python's stack (the worst case at this bound
# needs about 640 frames of the default 1,000). Past it the lexer stops reading
# and the result is ``too_nested``, which the guard rule refuses: the guard
# itself hits RecursionError about 200 levels deep and refuses the command, so
# this fails closed early rather than reading past what it can bound.
MAX_EXPANSION_NEST = 100
_METACHARS = frozenset(" \t\n;&|<>()")
_CONTROL_OPS = (";;&", ";;", ";&", "&&", "||", "|&", ";", "&", "|", "(", ")", "\n")
_REDIRECT_OPS = ("&>>", "&>", "<<<", "<<-", "<<", "<>", "<&", ">>", ">|", ">&", "<", ">")
_HEREDOC_OPS = frozenset({"<<", "<<-"})
_FD_PREFIX_RE = re.compile(r"\d+(?=[<>])")
_ASSIGNMENT_WORD_RE = re.compile(r"([A-Za-z_]\w*)(?:\[[^\]]*\])?\+?=")
_DQUOTE_ESCAPABLE = frozenset('$`"\\\n')
# What a backslash escapes inside a backtick substitution, so the body is
# decoded before it is parsed (``_read_backtick`` in _bash_write_targets.py):
# a backtick, a backslash or a dollar sign, plus a double quote when the
# substitution itself sits inside double quotes.
_BACKTICK_ESCAPABLE = "$`\\"
_BACKTICK_DQUOTE_ESCAPABLE = _BACKTICK_ESCAPABLE + '"'

# (start, end) offsets of a region of the text given to parse_shell, plus its base.
Span = tuple[int, int]


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
class Heredoc:
    """A heredoc body: data fed to a command, never commands itself."""

    delimiter: str
    quoted: bool  # a quoted delimiter makes the body inert: nothing expands
    body: str
    start: int
    subs: tuple[tuple[str, int], ...] = ()  # substitutions an unquoted body runs
    strip_tabs: bool = False  # opened by <<-: leading tabs are stripped before the closer is matched


@dataclass(frozen=True)
class _Delimiter:
    """A heredoc delimiter word and the redirect that opened it (``<<`` or ``<<-``)."""

    token: ShellToken
    strip_tabs: bool  # <<-

    def closes(self, line: str) -> bool:
        """True when *line* ends the body, by Bash's rule.

        ``<<EOF`` needs a line that is exactly the delimiter; ``<<-EOF``
        first strips leading tabs, never spaces. So an indented ``  EOF`` is
        body data under either. Mirrors ``_heredoc_body`` in
        _bash_write_targets.py.
        """
        return (line.lstrip("\t") if self.strip_tabs else line) == self.token.text


@dataclass
class _WordParts:
    """Accumulates one word's unquoted value and the substitutions inside it."""

    parts: list[str] = field(default_factory=list)
    subs: list[tuple[str, int]] = field(default_factory=list)


def _match_op(text: str, pos: int, ops: tuple[str, ...]) -> str | None:
    return next((op for op in ops if text.startswith(op, pos)), None)


class _Lexer:
    """Split shell text into :class:`ShellToken` values, reading heredoc bodies as data.

    Never raises: an unclosed quote or substitution in a fragment of prose
    simply runs to the end of the text.

    Two counters bound the reader. *depth* counts the substitutions
    enclosing the text -- ``$(...)`` and ``<(...)``, which the guard reads
    with a child Parser -- starting from the parse depth; a substitution one
    more than :data:`MAX_DEPTH` deep sets :attr:`overflow`. *nest* counts
    every construct read recursively, ``${...}`` and arithmetic included; one
    more than :data:`MAX_EXPANSION_NEST` deep sets :attr:`too_nested`. Either
    way the rest of the text is consumed unread, so recursion stays bounded
    whatever the input.
    """

    def __init__(self, text: str, base: int = 0, pos: int = 0, depth: int = 0, nest: int = 0) -> None:
        self.text = text
        self.base = base
        self.pos = pos
        self.depth = depth
        self.nest = nest
        self.overflow = False  # a substitution past MAX_DEPTH was met and not read
        self.too_nested = False  # nesting past MAX_EXPANSION_NEST was met and not read
        self.heredocs: list[Heredoc] = []
        self.comments: list[Span] = []
        self._pending: list[_Delimiter] = []  # heredoc delimiters awaiting their body
        self._heredoc_op: str | None = None  # the << or <<- whose delimiter is the next word

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
            parts = _WordParts()
            self.pos = self._nested(self._arith_body, start + 2, parts)
            return ShellToken("arith", self.text[start:self.pos], self.base + start, subs=tuple(parts.subs))
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
                eol = len(text) if eol < 0 else eol
                self.comments.append((self.base + self.pos, self.base + eol))
                self.pos = eol
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
            self._heredoc_op = redirect if redirect in _HEREDOC_OPS else None
            return ShellToken("redirect", redirect, self.base + pos)
        op = _match_op(text, pos, _CONTROL_OPS)
        if op is None:
            return None
        self.pos = pos + len(op)
        self._heredoc_op = None
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
        if self._heredoc_op is not None:
            self._pending.append(_Delimiter(tok, strip_tabs=self._heredoc_op == "<<-"))
            self._heredoc_op = None
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

    def _expansion(self, i: int, parts: _WordParts, in_dquote: bool = False) -> int:
        """Read the ``$...`` or backtick construct at *i*, or one plain character.

        *in_dquote* says the construct sits inside double quotes (or an
        unquoted heredoc body), which widens what a backtick body escapes.
        """
        text = self.text
        if text.startswith("$((", i):
            end = self._nested(self._arith_body, i + 3, parts)
        elif text.startswith("$(", i):
            return self._command_sub(i, i + 2, parts)
        elif text.startswith("${", i):
            end = self._nested(self._brace_body, i + 2, parts)
        elif text[i] == "`":
            return self._backtick(i, parts, in_dquote)
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
                i = self._expansion(i, parts, in_dquote=True)
            else:
                parts.parts.append(text[i])
                i += 1
        return i + 1 if closer is not None else i

    def _nested(
        self, scan: Callable[[int, _WordParts], int], i: int, parts: _WordParts, child: bool = False
    ) -> int:
        """Run *scan* on a body one level deeper, or stop at the end of the text past a bound.

        *child* marks a substitution, which the guard reads with a child
        Parser and so counts toward :data:`MAX_DEPTH`; every body counts
        toward :data:`MAX_EXPANSION_NEST`.
        """
        if child and self.depth >= MAX_DEPTH:
            self.overflow = True
            return len(self.text)
        if self.nest >= MAX_EXPANSION_NEST:
            self.too_nested = True
            return len(self.text)
        self.nest += 1
        self.depth += child
        try:
            return scan(i, parts)
        finally:
            self.nest -= 1
            self.depth -= child

    def _unit(self, i: int, parts: _WordParts) -> int:
        """Read one character, or one quoted or expanded unit, at *i*."""
        ch = self.text[i]
        if ch == "\\":
            return i + 2
        if ch == "'":
            end = self.text.find("'", i + 1)
            return len(self.text) if end < 0 else end + 1
        if ch == '"':
            return self._double(i + 1, parts, closer='"')
        if ch in "$`":
            return self._expansion(i, parts)
        return i + 1

    def _arith_body(self, i: int, parts: _WordParts) -> int:
        """Index just past the ``))`` closing an arithmetic body that starts at *i*.

        Mirrors ``_scan_arith`` in _bash_write_targets.py: the body's value is
        unknown, but a ``$(...)`` or backtick inside it runs, so each one is
        recorded in *parts* as a substitution of this word.
        """
        scratch = _WordParts(subs=parts.subs)
        depth = 0
        while i < len(self.text):
            ch = self.text[i]
            if ch == ")" and not depth:
                return i + 2 if self.text.startswith("))", i) else i + 1
            depth += {"(": 1, ")": -1}.get(ch, 0)
            i = self._unit(i, scratch)
        return len(self.text)

    def _brace_body(self, i: int, parts: _WordParts) -> int:
        """Index just past the ``}`` closing a ``${...}`` body; mirrors ``_scan_param``."""
        scratch = _WordParts(subs=parts.subs)
        while i < len(self.text):
            if self.text[i] == "}":
                return i + 1
            i = self._unit(i, scratch)
        return len(self.text)

    def _command_sub(self, open_at: int, body_start: int, parts: _WordParts) -> int:
        end = self._nested(self._closing_paren_from, body_start, parts, child=True)
        parts.subs.append((self.text[body_start:end], self.base + body_start))
        parts.parts.append(self.text[open_at:end + 1])
        return min(end + 1, len(self.text))

    def _closing_paren_from(self, body_start: int, parts: _WordParts) -> int:
        """Index of the ``)`` closing a substitution body at *body_start*, read by a child lexer."""
        child = _Lexer(self.text, self.base, body_start, self.depth, self.nest)
        end = child.closing_paren()
        self._absorb_limits(child)
        return end

    def _absorb_limits(self, other: _Lexer) -> None:
        """Carry a sub-lexer's bound hits up to this one."""
        self.overflow = self.overflow or other.overflow
        self.too_nested = self.too_nested or other.too_nested

    def _backtick(self, i: int, parts: _WordParts, in_dquote: bool = False) -> int:
        """Read the backtick substitution at *i*, recording its decoded body.

        Mirrors ``_read_backtick`` in _bash_write_targets.py: a backslash
        before ``` ` ```, ``\\`` or ``$`` (and ``"`` inside double quotes) is
        removed before the body is parsed, so an escaped backtick in the body
        opens a nested substitution rather than staying a literal. Offsets in
        the parsed body count decoded characters, so past an escape they sit
        up to one character per escape short of the source position.
        """
        text = self.text
        escapable = _BACKTICK_DQUOTE_ESCAPABLE if in_dquote else _BACKTICK_ESCAPABLE
        body: list[str] = []
        j = i + 1
        while j < len(text) and text[j] != "`":
            if text[j] == "\\" and text[j + 1:j + 2] and text[j + 1] in escapable:
                j += 1
            body.append(text[j])
            j += 1
        j = min(j, len(text))
        parts.subs.append(("".join(body), self.base + i + 1))
        parts.parts.append(text[i:j + 1])
        return min(j + 1, len(text))

    def _read_heredoc_bodies(self) -> None:
        pending, self._pending = self._pending, []
        for delimiter in pending:
            self._read_heredoc_body(delimiter)

    def _read_heredoc_body(self, delimiter: _Delimiter) -> None:
        text, start = self.text, self.pos
        i, end, resume = start, len(text), len(text)
        while i < len(text):
            eol = text.find("\n", i)
            eol = len(text) if eol < 0 else eol
            if delimiter.closes(text[i:eol]):
                end, resume = i, min(eol + 1, len(text))
                break
            i = eol + 1
        body = text[start:end]
        word = delimiter.token
        subs: tuple[tuple[str, int], ...] = ()
        if not word.quoted:
            body_lexer = _Lexer(body, self.base + start, depth=self.depth, nest=self.nest)
            subs = tuple(body_lexer.expanding_subs())
            self._absorb_limits(body_lexer)
        self.heredocs.append(
            Heredoc(word.text, word.quoted, body, self.base + start, subs, delimiter.strip_tabs)
        )
        self.pos = resume


def _heredoc_delimiters(text: str) -> list[_Delimiter]:
    """The delimiter of each heredoc opened in *text*, in order, with its redirect kind."""
    tokens = _Lexer(text).tokens()
    return [
        _Delimiter(nxt, strip_tabs=tok.text == "<<-") for tok, nxt in zip(tokens, tokens[1:])
        if tok.kind == "redirect" and tok.text in _HEREDOC_OPS and nxt.kind == "word"
    ]
