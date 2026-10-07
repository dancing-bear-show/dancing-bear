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
so the parser's names are importable from here only. The lexer it reads
tokens from -- :class:`shell_lex.ShellToken`, heredocs, and the nesting
bounds -- lives in :mod:`shell_lex`, imported here the same way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .shell_lex import MAX_DEPTH as _MAX_DEPTH
from .shell_lex import Heredoc as _Heredoc
from .shell_lex import ShellToken as _ShellToken
from .shell_lex import Span as _Span
from .shell_lex import _Lexer

__all__ = [
    "LoopVariable",
    "Redirect",
    "ShellScript",
    "SimpleCommand",
    "WRAPPER_NAMES",
    "command_from_words",
    "parse_shell",
]

# ---------------------------------------------------------------------------
# Simple commands
# ---------------------------------------------------------------------------

_WRITE_REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>", "<>", ">&"})
# ``2>&1`` / ``>&-`` duplicate or close a descriptor; they write no file.
_FD_TARGET_RE = re.compile(r"\d+-?|-")

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
class SimpleCommand:
    """One simple command, with the word that selects its program identified."""

    words: tuple[_ShellToken, ...]  # every word after the leading assignments
    assignments: tuple[_ShellToken, ...]  # leading NAME=value words, and any env sets
    redirects: tuple[Redirect, ...]
    command_index: int  # index in *words* of the program that runs; -1 for none
    in_loop: bool = False  # inside a for/while/until body (do ... done)
    # The innermost child shell this command runs in -- the body of a $(...),
    # backtick, <(...)/>(...) substitution, or a ( ... ) group -- or None for
    # the shell the text runs in. Pipeline members are not modelled as child
    # shells (bash's default, lastpipe off, forks every member): treating
    # them as the parent errs toward seeing a binding, never toward inventing
    # a missing one.
    subshell: _Span | None = None
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
    def word(self) -> _ShellToken | None:
        """The word naming the program, after any wrappers; None when nothing runs."""
        return self.words[self.command_index] if self.command_index >= 0 else None

    @property
    def name(self) -> str:
        """The program's basename, as the guard resolves it (``/bin/rm`` -> ``rm``)."""
        word = self.word
        return word.text.rsplit("/", 1)[-1] if word is not None else ""

    @property
    def arguments(self) -> tuple[_ShellToken, ...]:
        """The words after the program word: this command's operands and options only."""
        return self.words[self.command_index + 1:] if self.command_index >= 0 else ()

    @property
    def args(self) -> list[str]:
        return [tok.text for tok in self.arguments]


@dataclass(frozen=True)
class LoopVariable:
    """The variable a ``for``/``select`` header binds, and the child shell it is bound in."""

    name: str
    subshell: _Span | None = None  # as for SimpleCommand.subshell


@dataclass(frozen=True)
class ShellScript:
    """Every simple command, heredoc, loop variable, and comment in a piece of shell text."""

    commands: tuple[SimpleCommand, ...]
    heredocs: tuple[_Heredoc, ...]
    loop_variables: tuple[LoopVariable, ...]
    # (start, end) of each comment: a ``#`` that begins a word, outside quotes
    # and heredoc bodies, through the end of its line. ``a#b`` and ``${#x}``
    # are not comments.
    comments: tuple[_Span, ...] = ()
    # The deepest nesting level parsed (see SimpleCommand.depth). Past
    # MAX_DEPTH parsing stops, and this records that it did.
    max_depth: int = 0
    # Lexical nesting passed MAX_EXPANSION_NEST, so the rest was not read.
    too_nested: bool = False

    @property
    def too_deep(self) -> bool:
        """True when nesting exceeds the guard's MAX_DEPTH, which it refuses outright."""
        return self.max_depth > _MAX_DEPTH

    def inert_spans(self) -> list[_Span]:
        """(start, end) of each quoted heredoc body: text the shell never expands."""
        return [(d.start, d.start + len(d.body)) for d in self.heredocs if d.quoted]

    def heredoc_spans(self) -> list[_Span]:
        """(start, end) of every heredoc body, quoted or not: data, where quotes are literal."""
        return [(d.start, d.start + len(d.body)) for d in self.heredocs]


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
    assigned: list[_ShellToken]  # env's NAME=value operands
    split_string: bool = False  # a wrapper splits a string into the command line


def _skip_wrapper(words: tuple[_ShellToken, ...], i: int, spec: _Wrapper) -> _Resolved:
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


def _resolve_command(words: tuple[_ShellToken, ...]) -> _Resolved:
    """The program word after any wrappers (index -1 for none), and env's assignments."""
    i = 0
    assigned: list[_ShellToken] = []
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
    words: tuple[_ShellToken, ...], in_loop: bool = False, depth: int = 0
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

    def __init__(self, in_loop: bool, subshell: _Span | None, depth: int = 0) -> None:
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
        self._words: list[_ShellToken] = []
        self._assignments: list[_ShellToken] = []
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

    def feed(self, tok: _ShellToken) -> None:
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

    def _operator(self, tok: _ShellToken) -> None:
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

    def _start_word(self, tok: _ShellToken) -> None:
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

    def _test_word(self, tok: _ShellToken) -> None:
        if tok.raw == "]]":
            self.state = "after"

    def _loop_var_word(self, tok: _ShellToken) -> None:
        self.loop_variables.append(LoopVariable(tok.text, self.subshell))
        self.state = "loop_head"

    def _loop_head_word(self, tok: _ShellToken) -> None:
        if tok.raw == "do":  # `for f do ...` needs no separator before `do`
            self.state = "start"
            self._start_word(tok)

    def _case_subject_word(self, tok: _ShellToken) -> None:
        if tok.raw == "in":
            self.state = "case_pattern"

    def _case_pattern_word(self, tok: _ShellToken) -> None:
        if tok.raw == "esac":
            self._close_compound()
            self.state = "after"

    def _close_compound(self) -> None:
        self._compound = max(self._compound - 1, 0)

    def _function_name_word(self, tok: _ShellToken) -> None:
        self.state = "start"


def parse_shell(
    text: str, base: int = 0, in_loop: bool = False, subshell: _Span | None = None, depth: int = 0
) -> ShellScript:
    """Every simple command in shell *text*, including those in substitutions.

    Offsets in the result are positions in *text* plus *base*. *in_loop*
    marks every command as inside a loop body (a substitution within one);
    *subshell* is the child shell *text* runs in, None for the outermost.
    *depth* is how many parsers enclose *text* (see SimpleCommand.depth).
    Past :data:`shell_lex.MAX_DEPTH` nothing is parsed and the result's ``too_deep``
    is set: the guard refuses there, so the text is reported, not dropped.
    The lexer sets it too when substitutions nest past that bound within
    *text*, and sets ``too_nested`` when any construct, ``${...}`` and
    arithmetic included, nests past :data:`shell_lex.MAX_EXPANSION_NEST` (see
    :class:`shell_lex._Lexer`), so no input recurses without limit.
    """
    if depth > _MAX_DEPTH:
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
        max_depth=max((_MAX_DEPTH + 1 if lexer.overflow else depth, *(s.max_depth for s in nested))),
        too_nested=lexer.too_nested or any(s.too_nested for s in nested),
    )
