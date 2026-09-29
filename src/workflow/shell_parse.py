"""Shell command parser: tokenise shell text into simple-command values.

:func:`parse_shell` turns shell text into :class:`SimpleCommand` values -- the
one model of "which word is the program" every rule in ``linter_shell`` asks
about. It splits on control operators (``;``, ``&&``, ``||``, ``|``, ``&``,
newline, ``(``, ``)``), passes over reserved words (``if``, ``then``, ``do``,
``!``, ``{``, ``time`` ...) and leading ``NAME=value`` words, sees through
wrappers (``env``, ``sudo``, ``xargs``, ``timeout N`` ...; see
:data:`WRAPPER_NAMES`), recurses into
``$(...)``, backticks and ``<(...)``, and reads heredoc bodies as data rather
than as commands. shlex cannot do this: it reports no offsets, strips the
quotes that tell ``"rm"`` from ``rm``, and has no notion of heredocs.

Each command and loop variable records the child shell it runs in
(:attr:`SimpleCommand.subshell`), so a binding made inside ``$(...)`` or
``( ... )`` is not mistaken for one the enclosing shell can see.

This module is a pure extraction of the parser that previously lived in
``shell_text``; ``shell_text`` imports the public symbols back for its own
internal use (``_Lexer`` for :func:`_heredoc_delimiters`).
"""

from __future__ import annotations

import re
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
    """Every simple command, heredoc, and loop variable in a piece of shell text."""

    commands: tuple[SimpleCommand, ...]
    heredocs: tuple[Heredoc, ...]
    loop_variables: tuple[LoopVariable, ...]

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
# The wrapper vocabulary, derived from the table above so the segment
# extractor in shell_text recognises exactly the wrappers this parser sees
# through -- one list, not two that drift apart.
WRAPPER_NAMES: frozenset[str] = frozenset(_WRAPPERS)


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


def command_from_words(words: tuple[ShellToken, ...], in_loop: bool = False) -> SimpleCommand:
    """A :class:`SimpleCommand` for *words* that some other command runs.

    For argv a command hands on rather than shell text -- ``find -exec``'s
    body. Wrappers are resolved exactly as for a parsed command; there are no
    redirects, since the shell never sees these words as a command line.
    """
    index, env_assignments = _resolve_command(words)
    return SimpleCommand(words, tuple(env_assignments), (), index, in_loop)


class _CommandSplitter:
    """Group a token stream into :class:`SimpleCommand` values.

    Tracks just enough shell grammar to know where each command word sits:
    reserved words, ``for``/``case`` headers, ``[[ ]]`` tests (whose ``<``
    and ``>`` compare rather than redirect), subshells, and loop bodies.
    """

    def __init__(self, in_loop: bool, subshell: Span | None) -> None:
        self.outer_loop = in_loop
        self.subshell = subshell
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
            self.nested.append(parse_shell(body, offset, self.inside_loop, (offset, offset + len(body))))
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
            index, env_assignments = _resolve_command(words)
            self.commands.append(SimpleCommand(
                words, tuple(self._assignments + env_assignments), tuple(self._redirects),
                index, self._in_loop, self.subshell,
            ))
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
        self.finish()
        if op == ")":
            self._close_group(tok.start + 1)
            self.state = "after"
        else:
            self.state = "case_pattern" if op in _CASE_ENDS else "start"

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
            self.state = "after"

    def _function_name_word(self, tok: ShellToken) -> None:
        self.state = "start"


def parse_shell(
    text: str, base: int = 0, in_loop: bool = False, subshell: Span | None = None
) -> ShellScript:
    """Every simple command in shell *text*, including those in substitutions.

    Offsets in the result are positions in *text* plus *base*. *in_loop*
    marks every command as inside a loop body (a substitution within one);
    *subshell* is the child shell *text* runs in, None for the outermost.
    """
    lexer = _Lexer(text, base)
    splitter = _CommandSplitter(in_loop, subshell)
    for tok in lexer.tokens():
        splitter.feed(tok)
    splitter.finish()
    nested = list(splitter.nested)
    for doc in lexer.heredocs:
        nested.extend(
            parse_shell(body, offset, in_loop, (offset, offset + len(body))) for body, offset in doc.subs
        )
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
