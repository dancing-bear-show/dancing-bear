"""Shell command parser: tokenise shell text into simple-command values.

:func:`parse_shell` turns shell text into :class:`SimpleCommand` values -- the
one model of "which word is the program" every rule in ``linter_shell`` asks
about. It splits on control operators (``;``, ``&&``, ``||``, ``|``, ``&``,
newline, ``(``, ``)``), passes over reserved words (``if``, ``then``, ``do``,
``!``, ``{``, ``time`` ...) and leading ``NAME=value`` words, sees through
wrappers (``env``, ``sudo``, ``xargs``, ``timeout N`` ...; see
:data:`WRAPPER_NAMES`), recurses into
``$(...)``, backticks and ``<(...)`` -- also where they sit inside a
``${...}`` or arithmetic body -- and reads heredoc bodies as data rather
than as commands. shlex cannot do this: it reports no offsets, strips the
quotes that tell ``"rm"`` from ``rm``, and has no notion of heredocs.

Each command and loop variable records the child shell it runs in
(:attr:`SimpleCommand.subshell`), so a binding made inside ``$(...)`` or
``( ... )`` is not mistaken for one the enclosing shell can see.

This module is a pure extraction of the parser that previously lived in
``shell_text``; ``shell_text`` imports what it needs under private aliases,
so the parser's names are importable from here only.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace

__all__ = [
    "Heredoc",
    "LoopVariable",
    "Redirect",
    "ShellScript",
    "ShellToken",
    "SimpleCommand",
    "Span",
    "WRAPPER_NAMES",
    "command_from_words",
    "parse_shell",
]

# ---------------------------------------------------------------------------
# Tokens and simple commands
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
_WRITE_REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>", "<>", ">&"})
_FD_PREFIX_RE = re.compile(r"\d+(?=[<>])")
# ``2>&1`` / ``>&-`` duplicate or close a descriptor; they write no file.
_FD_TARGET_RE = re.compile(r"\d+-?|-")
_ASSIGNMENT_WORD_RE = re.compile(r"([A-Za-z_]\w*)(?:\[[^\]]*\])?\+?=")
_DQUOTE_ESCAPABLE = frozenset('$`"\\\n')
# What a backslash escapes inside a backtick substitution, so the body is
# decoded before it is parsed (``_read_backtick`` in _bash_write_targets.py):
# a backtick, a backslash or a dollar sign, plus a double quote when the
# substitution itself sits inside double quotes.
_BACKTICK_ESCAPABLE = "$`\\"
_BACKTICK_DQUOTE_ESCAPABLE = _BACKTICK_ESCAPABLE + '"'

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
# Reserved words that open a compound command; each _COMPOUND_CLOSERS word
# closes one. A command inside may not run, or not decide the exit status.
_COMPOUND_OPENERS = frozenset({"if", "while", "until", "{", "for", "select", "case"})
# Reserved words whose pipeline's exit status the shell list never sees as a failure.
_STATUS_MASKING_WORDS = frozenset({"!", "coproc"})
# Control operators that mask the exit status of the command before them.
_STATUS_MASKING_OPS = frozenset({"|", "|&", "&", "||"})
_PIPE_OPS = frozenset({"|", "|&"})
# After ``||``, these stop the shell, so the failure on the left still ends it.
_EXITING_COMMANDS = frozenset({"exit", "return"})

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


@dataclass(frozen=True)
class SimpleCommand:
    """One simple command, with the word that selects its program identified."""

    words: tuple[ShellToken, ...]  # every word after the leading assignments
    assignments: tuple[ShellToken, ...]  # leading NAME=value words, and any env sets
    redirects: tuple[Redirect, ...]
    command_index: int  # index in *words* of the program that runs; -1 for none
    in_loop: bool = False  # inside a for/while/until body (do ... done)
    # The innermost child shell this command runs in -- the body of a $(...),
    # backtick, <(...)/>(...) substitution, or a ( ... ) group -- or None for
    # the shell the text runs in. Pipeline members are not modelled as child
    # shells (bash's default, lastpipe off, forks every member): treating
    # them as the parent errs toward seeing a binding, never toward inventing
    # a missing one.
    subshell: Span | None = None
    # Parsers the Bash guard nests to reach this command: one per enclosing
    # $(...), backtick, <(...)/>(...) substitution or ``sh -c`` string.
    depth: int = 0
    # A wrapper splits one string into the command line it runs (``env -S``,
    # ``env --split-string``), so what runs cannot be read from the words.
    split_string: bool = False
    # True when this command runs whenever its shell does and nothing masks
    # its exit status there: it is outside every compound command (if, while,
    # until, for, select, case, { } and function bodies), not a pipeline
    # member, not negated by ``!`` or run by ``coproc``, not backgrounded with
    # ``&``, not after ``||``, and not followed by ``||`` unless ``exit`` or
    # ``return`` comes next. Judged within :attr:`subshell`: a command in a
    # ``$(...)`` is unconditional within that child shell. False for words a
    # command hands on (:func:`command_from_words`).
    unconditional: bool = False

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
class LoopVariable:
    """The variable a ``for``/``select`` header binds, and the child shell it is bound in."""

    name: str
    subshell: Span | None = None  # as for SimpleCommand.subshell


@dataclass(frozen=True)
class ShellScript:
    """Every simple command, heredoc, loop variable, and comment in a piece of shell text."""

    commands: tuple[SimpleCommand, ...]
    heredocs: tuple[Heredoc, ...]
    loop_variables: tuple[LoopVariable, ...]
    # (start, end) of each comment: a ``#`` that begins a word, outside quotes
    # and heredoc bodies, through the end of its line. ``a#b`` and ``${#x}``
    # are not comments.
    comments: tuple[Span, ...] = ()
    # The deepest nesting level parsed (see SimpleCommand.depth). Past
    # MAX_DEPTH parsing stops, and this records that it did.
    max_depth: int = 0
    # Lexical nesting passed MAX_EXPANSION_NEST, so the rest was not read.
    too_nested: bool = False

    @property
    def too_deep(self) -> bool:
        """True when nesting exceeds the guard's MAX_DEPTH, which it refuses outright."""
        return self.max_depth > MAX_DEPTH

    def inert_spans(self) -> list[Span]:
        """(start, end) of each quoted heredoc body: text the shell never expands."""
        return [(d.start, d.start + len(d.body)) for d in self.heredocs if d.quoted]

    def heredoc_spans(self) -> list[Span]:
        """(start, end) of every heredoc body, quoted or not: data, where quotes are literal."""
        return [(d.start, d.start + len(d.body)) for d in self.heredocs]


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


@dataclass(frozen=True)
class _Wrapper:
    """How a wrapper command's own options are laid out before the command it runs."""

    value_opts: str = ""  # short options whose value is attached or the next word
    long_value_opts: tuple[str, ...] = ()  # long options whose value may be the next word
    lookup_opts: str = ""  # options that make it run nothing (``command -v``)
    leading_operands: int = 0  # operands before the command (``timeout``'s duration)
    takes_assignments: bool = False  # ``env NAME=value cmd``
    split_opts: str = ""  # value options whose value is the command line (``env -S``)
    long_split_opts: tuple[str, ...] = ()  # the same, spelled long (``--split-string``)


_TIMEOUT = _Wrapper(value_opts="sk", long_value_opts=("signal", "kill-after"), leading_operands=1)
# Mirrors the wrapper handlers in .claude/hooks/_bash_write_targets.py, which
# the Bash guard uses to find the command a wrapper runs.
_WRAPPERS: dict[str, _Wrapper] = {
    "env": _Wrapper(value_opts="uCSP", long_value_opts=("unset", "chdir", "split-string"),
                    takes_assignments=True, split_opts="S", long_split_opts=("split-string",)),
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
# The wrapper vocabulary, derived from the table above so the segment
# extractor in shell_text recognises exactly the wrappers this parser sees
# through -- one list, not two that drift apart.
WRAPPER_NAMES: frozenset[str] = frozenset(_WRAPPERS)


# _option_width's answer for an option whose value is the command line itself.
_SPLITS = -1


def _short_option_width(word: str, spec: _Wrapper) -> int | None:
    """Words consumed by the short-option cluster *word*; None when it runs nothing.

    The first value letter ends the cluster, as in getopt: ``-iS`` is ``-i``
    then ``-S``, while ``-uS`` is ``-u`` with the value ``S``.
    """
    for k, ch in enumerate(word[1:], start=1):
        if ch in spec.lookup_opts:
            return None
        if ch in spec.split_opts:
            return _SPLITS
        if ch in spec.value_opts:
            return 1 if k + 1 < len(word) else 2
    return 1


def _long_option_name(raw: str, spec: _Wrapper) -> str:
    """*raw* resolved as GNU getopt does: a unique prefix of a known long option names it.

    Mirrors ``_long_name`` in _bash_write_targets.py, so ``env --split`` is
    ``--split-string``.
    """
    known = spec.long_value_opts
    if raw in known:
        return raw
    matches = [name for name in known if raw and name.startswith(raw)]
    return matches[0] if len(matches) == 1 else raw


def _option_width(word: str, spec: _Wrapper) -> int | None:
    """Words the wrapper option *word* consumes: 0 when it is not an option.

    :data:`_SPLITS` when the option's value is the command line to run.
    """
    if word == "-":
        return 1
    if word.startswith("--"):
        raw, eq, _ = word[2:].partition("=")
        name = _long_option_name(raw, spec)
        if name in spec.long_split_opts:
            return _SPLITS
        return 2 if not eq and name in spec.long_value_opts else 1
    if word.startswith("-"):
        return _short_option_width(word, spec)
    return 0


@dataclass(frozen=True)
class _Resolved:
    """Where a wrapper chain leads: the program word, and what the wrappers set."""

    index: int  # index of the program word; -1 when nothing runs
    assigned: list[ShellToken]  # env's NAME=value operands
    split_string: bool = False  # a wrapper splits a string into the command line


def _skip_wrapper(words: tuple[ShellToken, ...], i: int, spec: _Wrapper) -> _Resolved:
    """The command a wrapper at ``words[i - 1]`` runs, plus any env assignments."""
    while i < len(words) and words[i].text != "--":
        width = _option_width(words[i].text, spec)
        if width is None:
            return _Resolved(-1, [])
        if width == _SPLITS:
            return _Resolved(-1, [], split_string=True)
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
    return _Resolved(i if i < len(words) else -1, assigned)


def _resolve_command(words: tuple[ShellToken, ...]) -> _Resolved:
    """The program word after any wrappers (index -1 for none), and env's assignments."""
    i = 0
    assigned: list[ShellToken] = []
    while 0 <= i < len(words):
        spec = _WRAPPERS.get(words[i].text.rsplit("/", 1)[-1])
        if spec is None:
            return _Resolved(i, assigned)
        step = _skip_wrapper(words, i + 1, spec)
        assigned.extend(step.assigned)
        if step.split_string:
            return _Resolved(-1, assigned, split_string=True)
        i = step.index
    return _Resolved(-1, assigned)


def command_from_words(
    words: tuple[ShellToken, ...], in_loop: bool = False, depth: int = 0
) -> SimpleCommand:
    """A :class:`SimpleCommand` for *words* that some other command runs.

    For argv a command hands on rather than shell text -- ``find -exec``'s
    body. Wrappers are resolved exactly as for a parsed command; there are no
    redirects, since the shell never sees these words as a command line.
    """
    resolved = _resolve_command(words)
    return SimpleCommand(
        words, tuple(resolved.assigned), (), resolved.index, in_loop,
        depth=depth, split_string=resolved.split_string,
    )


class _CommandSplitter:
    """Group a token stream into :class:`SimpleCommand` values.

    Tracks just enough shell grammar to know where each command word sits:
    reserved words, ``for``/``case`` headers, ``[[ ]]`` tests (whose ``<``
    and ``>`` compare rather than redirect), subshells, and loop bodies.
    """

    def __init__(self, in_loop: bool, subshell: Span | None, depth: int = 0) -> None:
        self.outer_loop = in_loop
        self.subshell = subshell
        self.depth = depth
        self.loop_depth = 0
        self.state = "start"
        self.commands: list[SimpleCommand] = []
        self.loop_variables: list[LoopVariable] = []
        self.nested: list[ShellScript] = []
        # One entry per open "(": (its offset, commands and loop variables
        # recorded before it) for a ( ... ) group; None for a name ( ) definition.
        self._groups: list[tuple[int, int, int] | None] = []
        self._words: list[ShellToken] = []
        self._assignments: list[ShellToken] = []
        self._redirects: list[Redirect] = []
        self._redirect_op: str | None = None
        self._in_loop = in_loop
        self._after_time = False
        # What SimpleCommand.unconditional needs: open compound commands, and
        # how the command being read sits in its list and pipeline.
        self._compound = 0
        self._masked = False  # the current pipeline is negated (!) or run by coproc
        self._piped = False  # the current command follows | or |&
        self._after_or = False  # the current command runs only when the one before failed
        self._or_left: int | None = None  # a command followed by ||, until what comes next is known
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
            self.nested.append(
                parse_shell(body, offset, self.inside_loop, (offset, offset + len(body)), self.depth + 1)
            )
        if tok.kind == "word" and self._redirect_op is not None:
            self._redirects.append(Redirect(self._redirect_op, tok.text))
            self._redirect_op = None
        elif tok.kind == "word":
            self._on_word[self.state](tok)
        elif tok.kind == "redirect" and self.state != "test":
            self._redirect_op = tok.text
        elif tok.kind == "op":
            self._operator(tok)
        elif tok.kind == "arith":
            self.state = "loop_head" if self.state == "loop_var" else self.state

    def finish(self) -> None:
        if self._words or self._assignments or self._redirects:
            words = tuple(self._words)
            resolved = _resolve_command(words)
            unconditional = not (self._compound or self._masked or self._piped or self._after_or)
            self.commands.append(SimpleCommand(
                words, tuple(self._assignments + resolved.assigned), tuple(self._redirects),
                resolved.index, self._in_loop, self.subshell, self.depth, resolved.split_string,
                unconditional,
            ))
            self._settle_or(self.commands[-1])
        self._words.clear()
        self._assignments = []
        self._redirects = []
        self._redirect_op = None
        self._in_loop = self.inside_loop
        self._after_time = False

    def _operator(self, tok: ShellToken) -> None:
        op = tok.text
        if self.state == "test" and op != "\n":
            return  # && || ( ) are test logic inside [[ ]]
        if self.state == "case_pattern":
            self.state = "start" if op == ")" else self.state
            return
        if op == "(" and self.state == "args" and len(self._words) == 1:
            self._words.clear()  # name ( ): a function definition
            self._groups.append(None)
            self.state = "start"
            return
        if op == "(":
            self._groups.append((tok.start, len(self.commands), len(self.loop_variables)))
            return
        before = len(self.commands)
        self.finish()
        self._join(op, before if len(self.commands) > before else None)
        if op == ")":
            self._close_group(tok.start + 1)
            self.state = "after"
        else:
            self.state = "case_pattern" if op in _CASE_ENDS else "start"

    def _join(self, op: str, finished: int | None) -> None:
        """Record what control operator *op* says about the command before it and the next.

        *finished* is the index of the command *op* ended, if it ended one.
        A pipe, ``&`` or ``||`` after a command masks its exit status; a
        ``||`` is settled by what follows it (see :meth:`_settle_or`).
        """
        if finished is not None and op in _STATUS_MASKING_OPS:
            cmd = self.commands[finished]
            self.commands[finished] = replace(cmd, unconditional=False)
            if op == "||" and cmd.unconditional:
                self._or_left = finished
        self._piped = op in _PIPE_OPS
        self._after_or = op == "||" or (self._after_or and self._piped)
        self._masked = self._masked and self._piped  # ! and coproc cover one pipeline

    def _settle_or(self, cmd: SimpleCommand) -> None:
        """``a || exit`` stops the shell when ``a`` fails, so ``a``'s status is not masked."""
        if self._or_left is None:
            return
        if cmd.name in _EXITING_COMMANDS:
            self.commands[self._or_left] = replace(self.commands[self._or_left], unconditional=True)
        self._or_left = None

    def _close_group(self, end: int) -> None:
        """Mark what a closing ( ... ) group recorded as running in that child shell.

        Only entries still at this splitter's own scope move: one already in a
        deeper group, closed earlier, keeps that innermost span.
        """
        group = self._groups.pop() if self._groups else None
        if group is None:
            return
        start, first_command, first_variable = group
        span = (start, end)
        for i in range(first_command, len(self.commands)):
            if self.commands[i].subshell == self.subshell:
                self.commands[i] = replace(self.commands[i], subshell=span)
        for i in range(first_variable, len(self.loop_variables)):
            if self.loop_variables[i].subshell == self.subshell:
                self.loop_variables[i] = replace(self.loop_variables[i], subshell=span)

    def _start_word(self, tok: ShellToken) -> None:
        word = tok.raw  # only an unquoted word can be a reserved word
        if self._after_time and word == "-p":
            self._after_time = False
            return
        self._after_time = word == "time"
        if word in _KEEP_START:
            self.loop_depth += word == "do"
            self._in_loop = self.inside_loop
            self._compound += word in _COMPOUND_OPENERS
            self._masked = self._masked or word in _STATUS_MASKING_WORDS
        elif word in _COMPOUND_CLOSERS:
            self.loop_depth -= word == "done" and self.loop_depth > 0
            self._close_compound()
            self.state = "after"  # a redirect after `done` still belongs to the loop
        elif word in _START_STATES:
            self._compound += word in _COMPOUND_OPENERS
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
        self.loop_variables.append(LoopVariable(tok.text, self.subshell))
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
            self._close_compound()
            self.state = "after"

    def _close_compound(self) -> None:
        self._compound = max(self._compound - 1, 0)

    def _function_name_word(self, tok: ShellToken) -> None:
        self.state = "start"


def parse_shell(
    text: str, base: int = 0, in_loop: bool = False, subshell: Span | None = None, depth: int = 0
) -> ShellScript:
    """Every simple command in shell *text*, including those in substitutions.

    Offsets in the result are positions in *text* plus *base*. *in_loop*
    marks every command as inside a loop body (a substitution within one);
    *subshell* is the child shell *text* runs in, None for the outermost.
    *depth* is how many parsers enclose *text* (see SimpleCommand.depth).
    Past :data:`MAX_DEPTH` nothing is parsed and the result's ``too_deep``
    is set: the guard refuses there, so the text is reported, not dropped.
    The lexer sets it too when substitutions nest past that bound within
    *text*, and sets ``too_nested`` when any construct, ``${...}`` and
    arithmetic included, nests past :data:`MAX_EXPANSION_NEST` (see
    :class:`_Lexer`), so no input recurses without limit.
    """
    if depth > MAX_DEPTH:
        return ShellScript((), (), (), (), max_depth=depth)
    # Every substitution is also a nesting level, so a body parsed at *depth*
    # sat at least that many levels deep in the text that contained it.
    lexer = _Lexer(text, base, depth=depth, nest=depth)
    splitter = _CommandSplitter(in_loop, subshell, depth)
    for tok in lexer.tokens():
        splitter.feed(tok)
    splitter.finish()
    nested = list(splitter.nested)
    for doc in lexer.heredocs:
        nested.extend(
            parse_shell(body, offset, in_loop, (offset, offset + len(body)), depth + 1)
            for body, offset in doc.subs
        )
    return ShellScript(
        commands=tuple(splitter.commands) + tuple(c for s in nested for c in s.commands),
        heredocs=tuple(lexer.heredocs) + tuple(d for s in nested for d in s.heredocs),
        loop_variables=tuple(splitter.loop_variables) + tuple(v for s in nested for v in s.loop_variables),
        comments=tuple(lexer.comments) + tuple(c for s in nested for c in s.comments),
        max_depth=max((MAX_DEPTH + 1 if lexer.overflow else depth, *(s.max_depth for s in nested))),
        too_nested=lexer.too_nested or any(s.too_nested for s in nested),
    )


def _heredoc_delimiters(text: str) -> list[_Delimiter]:
    """The delimiter of each heredoc opened in *text*, in order, with its redirect kind."""
    tokens = _Lexer(text).tokens()
    return [
        _Delimiter(nxt, strip_tabs=tok.text == "<<-") for tok, nxt in zip(tokens, tokens[1:])
        if tok.kind == "redirect" and tok.text in _HEREDOC_OPS and nxt.kind == "word"
    ]
