#!/usr/bin/env python3
"""Decide whether a Bash command opens a PR, and if so, whether a sweep record allows it.

Invoked by require-concern-sweep.sh as::

    python3 -I -S _pr_create_targets.py < <PreToolUse payload JSON>

Exit 0 allows, exit 2 blocks with the reason on stderr. Any other exit (a crash, a
missing interpreter) is treated as a block by the hook -- this process dying must
never read as approval.

``-I -S`` is mandatory: hooks run with the session's environment, and a foreign
``PYTHONPATH`` would otherwise execute that tree's ``sitecustomize.py`` before a line
of this file runs. Stdlib only, and nothing from the repo is imported, for the same
reason. The record location and fields mirror src/workflow/sweep_record.py; keep the
two in step.

HOW A COMMAND IS READ
---------------------
A small quote-aware lexer (``_Lexer``) splits the text into words and control
operators the way the shell does: a quoted or escaped ``;`` is part of a word, never
a separator. Each word records whether the shell expands it at run time and the
bodies of any command substitutions (``$(...)``, backticks, ``<(...)``) and unquoted
here-documents inside it. Comments and here-document bodies are skipped as the shell
skips them.

Each simple command has one program word, found by stripping reserved words,
assignments, redirections and a short allowlist of transparent wrappers (``command``,
``builtin``, ``exec``, ``nohup``, ``env`` with plain options, ``timeout``, ``nice``,
``python -m``, ``./bin/assistant``). Only that word is treated as the program.

ALLOWLIST, NOT DENYLIST
-----------------------
The parser allows a command only when it has modelled every simple command in it.
Anything it does not model fails CLOSED (exit 2, "cannot be checked") rather than
being guessed at:

* a command substitution whose body opens a PR (``URL="$(gh pr create)"``);
* a PR entry point that is not the program word (``xargs gh pr create``,
  ``find . -exec gh pr create \\;``, ``echo gh pr create``);
* a program word built at run time (``$CMD``, ``"$(printf gh)"``, ``g{h,}``);
* ``eval`` of run-time text, or any ``eval`` in a command that mentions PR words;
* ``bash|sh|zsh|... -c`` whose script is built at run time (``bash -c "$CMD"``);
  a shell reading a script from stdin in a command that mentions PR words;
* ``env`` with an option other than ``-i``/``-u``/``-0``/``-v`` (``-S``, ``-C``);
* ``source``/``.``, ``alias``, ``trap`` or a function definition in a command that
  mentions PR words; ``xargs``/``find``/``sudo``/... whose own words mention them;
* a ``cd``/``pushd`` this does not model (more than one operand, stack forms,
  unknown options), inside a compound command, or after ``&&``/``||``;
* ``gh api graphql`` with ``--input``, a ``@file`` query or a run-time query; a
  ``--head`` / ``cd`` target known only at run time; a ``--head`` that does not
  resolve; a checkout git cannot read; text that will not tokenise.

KNOWN GAPS (listed in the hook header too)
------------------------------------------
Command semantics this cannot see: a script file or Makefile target that runs
``gh pr create``; ``python3 -c`` / any program calling the GitHub API itself;
``curl`` to api.github.com; user-defined ``gh alias`` names; ``git`` aliases; a
quoted command string handed to a program outside the shells and runners above.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess  # nosec B404 - fixed git argv lists, never a shell
import sys
from dataclasses import dataclass, field
from pathlib import Path

RECORD_SUBDIR = ("dancing-bear", "concern-sweeps")
MODES = ("swept", "waived")
MAX_DEPTH = 8

_SEPARATOR_CHARS = frozenset("();|&\n")
_OPCHARS = frozenset("();<>|&\n")
_BLANKS = frozenset(" \t\r")
_SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh", "fish"})
_GITHUB_CLI = frozenset({"github", "github_assistant", "github_assistant.cli"})
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_PULLS_ENDPOINT = re.compile(r"(?:^|/)repos/[^/\s]+/[^/\s]+/pulls/?(?:[?#].*)?$", re.IGNORECASE)
_GIT_ENV_OVERRIDES = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM",
)
_UNKNOWN_CWD = None
_REFUSE_HINT = "Run a plain `gh pr create` from the checkout instead"


class Unverifiable(Exception):
    """A fact that decides the verdict is not knowable before the shell runs."""


@dataclass
class Target:
    """One PR-create found in the command."""

    entry: str            # e.g. "gh pr create"
    cwd: Path | None      # the directory it runs in; None = unknown
    head: str | None      # branch named by --head, else None for HEAD


@dataclass
class Tok:
    """One word or operator of a command line."""

    text: str                 # quotes removed; `$...` constructs kept verbatim
    op: bool = False          # a control or redirection operator
    quoted: bool = False      # some part was quoted or escaped
    expands: bool = False     # the shell expands part of it at run time
    fd: bool = False          # digits glued to a redirection (`2>`)
    subs: list[str] = field(default_factory=list)  # command-substitution bodies


# ---------------------------------------------------------------------------
# Tokenising
# ---------------------------------------------------------------------------


_ANSI_SIMPLE = {"a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "n": "\n",
                "r": "\r", "t": "\t", "v": "\v", "\\": "\\", "'": "'", '"': '"', "?": "?"}
_ANSI_RADIX = {"x": (16, 2), "u": (16, 4), "U": (16, 8)}
_HEX = frozenset("0123456789abcdefABCDEF")


def _ansi_escape(body: str, i: int) -> tuple[str, int]:
    """Decode the escape at ``body[i]`` (just past a backslash); return (text, next index)."""
    ch = body[i]
    if ch in _ANSI_SIMPLE:
        return _ANSI_SIMPLE[ch], i + 1
    if ch in _ANSI_RADIX:
        _, width = _ANSI_RADIX[ch]
        j = i + 1
        while j < len(body) and j - i - 1 < width and body[j] in _HEX:
            j += 1
        if j == i + 1:
            return "\\" + ch, i + 1
        return chr(int(body[i + 1:j], 16)), j
    if ch in "01234567":
        j = i
        while j < len(body) and j - i < 3 and body[j] in "01234567":
            j += 1
        return chr(int(body[i:j], 8) & 0xFF), j
    if ch == "c" and i + 1 < len(body):
        return chr(ord(body[i + 1]) & 0x1F), i + 2
    return "\\" + ch, i + 1


def _read_ansi_c(command: str, start: int) -> tuple[str, int]:
    """Decode a ``$'...'`` body starting after its opening quote; ValueError if unterminated."""
    out: list[str] = []
    i = start
    while i < len(command):
        ch = command[i]
        if ch == "'":
            return "".join(out), i + 1
        if ch == "\\" and i + 1 < len(command):
            text, i = _ansi_escape(command, i + 1)
            out.append(text)
            continue
        out.append(ch)
        i += 1
    raise ValueError("unterminated $'...' string")


def expand_ansi_c(command: str) -> str:
    """Rewrite bash ``$'...'`` as the plain single-quoted text it means, and ``$"..."`` as ``"..."``.

    Used to flatten text before looking for PR words (``_mentions_pr``), so
    ``gh $'\\x70'r create`` still reads as mentioning ``pr``.
    """
    out: list[str] = []
    state = ""  # "", "'" or '"'
    i = 0
    while i < len(command):
        text, i, state = _ansi_step(command, i, state)
        out.append(text)
    return "".join(out)


def _ansi_step(command: str, i: int, state: str) -> tuple[str, int, str]:
    """One step of expand_ansi_c: (text to emit, next index, next quote state)."""
    ch = command[i]
    if state == "'":
        return ch, i + 1, ("" if ch == "'" else state)
    if ch == "\\" and i + 1 < len(command):
        return command[i:i + 2], i + 2, state
    if state == '"':
        return ch, i + 1, ("" if ch == '"' else state)
    if command.startswith("$'", i):
        text, nxt = _read_ansi_c(command, i + 2)
        return "'" + text.replace("'", "'\\''") + "'", nxt, state
    if command.startswith('$"', i):
        return "", i + 1, state  # locale quoting: $"..." reads as "..." without a catalog
    return ch, i + 1, (ch if ch in "'\"" else state)


_PROC_SUB = ("<(", ">(")


class _Lexer:
    """Quote-aware shell lexer: words keep their quoting provenance.

    shlex flattens ``--title ';'`` into the same token as a real ``;``. Here a
    quoted or escaped operator character is part of a word, and only unquoted
    ``();<>|&`` and newline form operators.
    """

    def __init__(self, s: str) -> None:
        self.s = s
        self.i = 0
        self.pending: list[tuple[Tok, bool]] = []  # here-docs awaiting their body
        self.want_delim: bool | None = None  # strip-tabs flag of a `<<` awaiting its word

    def run(self, in_sub: bool = False) -> list[Tok]:
        toks: list[Tok] = []
        depth = 0
        while self.i < len(self.s):
            ch = self.s[self.i]
            if ch in _BLANKS:
                self.i += 1
            elif ch == "#":  # a comment: `#` at the start of a word
                nl = self.s.find("\n", self.i)
                self.i = len(self.s) if nl < 0 else nl
            elif self._at_operator():
                depth, closed = self._emit_operator(toks, depth, in_sub)
                if closed:
                    return toks
            else:
                toks.append(self._emit_word(in_sub))
        if in_sub:
            raise ValueError("unterminated command substitution")
        return toks

    def _at_operator(self) -> bool:
        return (self.i < len(self.s) and self.s[self.i] in _OPCHARS
                and not self.s.startswith(_PROC_SUB, self.i))

    def _emit_operator(self, toks: list[Tok], depth: int, in_sub: bool) -> tuple[int, bool]:
        text, depth, closed = self._operator(depth, in_sub)
        if text:
            toks.append(Tok(text, op=True))
            if text.endswith("<<") and not text.endswith("<<<"):
                self.want_delim = self.s.startswith("-", self.i)
                self.i += int(self.want_delim)
        return depth, closed

    def _emit_word(self, in_sub: bool) -> Tok:
        tok = self._word()
        if in_sub and tok.text == "case" and not tok.quoted:
            # `case x in a)` would close the substitution early.
            raise ValueError("case inside a command substitution is not modelled")
        if self.want_delim is not None:
            self.pending.append((tok, self.want_delim))
            self.want_delim = None
        return tok

    def _operator(self, depth: int, in_sub: bool) -> tuple[str, int, bool]:
        """(operator run, paren depth, closed the enclosing substitution)."""
        out: list[str] = []
        while self._at_operator():
            ch = self.s[self.i]
            self.i += 1
            if ch == ")" and in_sub and depth == 0:
                return "".join(out), depth, True
            depth += (ch == "(") - (ch == ")")
            out.append(ch)
            if ch == "\n" and self.pending:
                self._heredocs()
                break
        return "".join(out), depth, False

    def _heredocs(self) -> None:
        """Consume the here-document bodies queued on the line just ended."""
        for tok, strip in self.pending:
            body = self._heredoc_body(tok.text, strip)
            if not tok.quoted:  # an unquoted delimiter: the body is expanded
                _Lexer(body)._expanding(tok, None)  # records subs on tok
        self.pending = []

    def _heredoc_body(self, delim: str, strip: bool) -> str:
        s = self.s
        body: list[str] = []
        while self.i < len(s):
            nl = s.find("\n", self.i)
            end = len(s) if nl < 0 else nl
            line = s[self.i:end]
            self.i = end + 1 if nl >= 0 else end
            if (line.lstrip("\t") if strip else line) == delim:
                break
            body.append(line)
        return "\n".join(body)

    def _word(self) -> Tok:
        tok = Tok("")
        parts: list[str] = []
        while self.i < len(self.s) and self.s[self.i] not in _BLANKS:
            part = self._word_part(tok)
            if part is None:
                break
            parts.append(part)
        tok.text = "".join(parts)
        tok.fd = tok.text.isdigit() and not tok.quoted and self.s[self.i:self.i + 1] in ("<", ">")
        return tok

    def _word_part(self, tok: Tok) -> str | None:
        """The next piece of the word at ``self.i``, or None where the word ends."""
        s = self.s
        ch = s[self.i]
        if ch in _OPCHARS:
            if not s.startswith(_PROC_SUB, self.i):
                return None
            start = self.i
            tok.subs.append(self._sub(self.i + 2))
            tok.expands = True
            return s[start:self.i]
        if ch == "\\":
            tok.quoted = True
            self.i += 2
            return s[self.i - 1:self.i]
        if ch == "'":
            end = s.find("'", self.i + 1)
            if end < 0:
                raise ValueError("unterminated single quote")
            tok.quoted = True
            start, self.i = self.i + 1, end + 1
            return s[start:end]
        if ch == '"':
            tok.quoted = True
            self.i += 1
            return self._expanding(tok, '"')
        if ch == "$":
            return self._dollar(tok, in_dquote=False)
        if ch == "`":
            return self._backtick(tok)
        self.i += 1
        return ch

    def _sub(self, start: int) -> str:
        """Lex a ``$(``/``<(`` body from ``start`` to its ``)``; return the body text."""
        saved = self.pending, self.want_delim
        self.pending, self.want_delim = [], None
        self.i = start
        self.run(in_sub=True)
        self.pending, self.want_delim = saved
        return self.s[start:self.i - 1]

    def _dollar(self, tok: Tok, in_dquote: bool) -> str:
        s = self.s
        i = self.i
        nxt = s[i + 1:i + 2]
        if nxt == "(":
            tok.subs.append(self._sub(i + 2))
            tok.expands = True
            return s[i:self.i]
        if nxt == "{":
            self.i = i + 2
            self._brace(tok)
            tok.expands = True
            return s[i:self.i]
        if not in_dquote and nxt == "'":
            text, self.i = _read_ansi_c(s, i + 2)
            tok.quoted = True
            return text
        if not in_dquote and nxt == '"':
            self.i = i + 2
            tok.quoted = True
            return self._expanding(tok, '"')
        self.i = i + 1
        if nxt and (nxt.isalnum() or nxt in "_@*#?$!-"):
            tok.expands = True
        return "$"

    def _expanding(self, tok: Tok, term: str | None) -> str:
        """Double-quoted text (``term='"'``) or a here-doc body (``term=None``)."""
        s = self.s
        parts: list[str] = []
        escapable = '$`"\\\n' if term else "$`\\\n"
        while self.i < len(s):
            ch = s[self.i]
            if term is not None and ch == term:
                self.i += 1
                return "".join(parts)
            if ch == "\\" and self.i + 1 < len(s):
                nxt = s[self.i + 1]
                parts.append(nxt if nxt in escapable else ch + nxt)
                self.i += 2
            elif ch == "$":
                parts.append(self._dollar(tok, in_dquote=True))
            elif ch == "`":
                parts.append(self._backtick(tok))
            else:
                parts.append(ch)
                self.i += 1
        if term is not None:
            raise ValueError("unterminated double quote")
        return "".join(parts)

    def _backtick(self, tok: Tok) -> str:
        s = self.s
        start = self.i
        j = start + 1
        body: list[str] = []
        while j < len(s):
            ch = s[j]
            if ch == "\\" and j + 1 < len(s):
                nxt = s[j + 1]
                body.append(nxt if nxt in "$`\\" else ch + nxt)
                j += 2
                continue
            if ch == "`":
                self.i = j + 1
                tok.subs.append("".join(body))
                tok.expands = True
                return s[start:self.i]
            body.append(ch)
            j += 1
        raise ValueError("unterminated backtick")

    def _brace(self, tok: Tok) -> None:
        """Skip a ``${...}`` body (after ``${``), collecting substitutions inside it."""
        s = self.s
        depth = 1
        while self.i < len(s):
            ch = s[self.i]
            if ch == "\\":
                self.i += 2
            elif ch == "'":
                end = s.find("'", self.i + 1)
                if end < 0:
                    raise ValueError("unterminated single quote")
                self.i = end + 1
            elif ch == '"':
                self.i += 1
                self._expanding(tok, '"')
            elif ch == "$":
                self._dollar(tok, in_dquote=True)
            elif ch == "`":
                self._backtick(tok)
            else:
                depth += (ch == "{") - (ch == "}")
                self.i += 1
                if depth == 0:
                    return
        raise ValueError("unterminated ${...}")


def tokenize(command: str) -> list[Tok]:
    """Words and control operators of ``command``; ValueError if it will not tokenise."""
    return _Lexer(command.replace("\\\n", "")).run()


def is_separator(tok: Tok) -> bool:
    return tok.op and set(tok.text) <= _SEPARATOR_CHARS


def split_with_operators(toks: list[Tok]) -> list[tuple[list[tuple[int, Tok]], str]]:
    """(simple command, the separator text that ends it); the last ends with "".

    A command may be empty when separators are adjacent (`(cd x)`, `a; (b)`), so
    the parentheses still reach the caller even with no words between them.
    """
    out: list[tuple[list[tuple[int, Tok]], str]] = []
    cur: list[tuple[int, Tok]] = []
    for idx, tok in enumerate(toks):
        if is_separator(tok):
            out.append((cur, tok.text))
            cur = []
        else:
            cur.append((idx, tok))
    out.append((cur, ""))
    return out


#: Words that can name a PR entry point or its payload. Used to decide whether a
#: construct this parser refuses to model (eval, source, a shell reading stdin, a
#: function definition) "could involve" PR creation.
_PR_WORDS = re.compile(
    r"(?<![a-z0-9_])(?:gh|hub|pr|pulls|pull-request|github\w*|graphql|createpullrequest)(?![a-z0-9_])"
)


def _mentions_pr(text: str) -> bool:
    """Whether ``text``, with quoting and escapes flattened, names any PR word."""
    try:
        text = expand_ansi_c(text)
    except ValueError:
        pass  # an unterminated $'...': search the raw text instead
    return bool(_PR_WORDS.search(re.sub(r"[\"'\\]", "", text.lower())))


def _cd_applies(op: str) -> bool | None:
    """Whether a cd ended by separator ``op`` moves the commands after it.

    True for `&&`, `;`, newline and end of a group: the next command runs in the
    same shell after the cd. False for `|` and `&`: the cd ran in a pipeline or
    background subshell, so the shell's cwd is unchanged. None for `||`: the
    next command runs only if the cd FAILED, so the cwd is not knowable.
    """
    core = op.replace("(", "").replace(")", "")
    if core in ("", "&&", ";", "\n") or set(core) <= {";", "\n"}:
        return True
    if "||" in core:
        return None
    return False


#: Shell reserved words that can precede a command in the same shell. Without
#: stripping them, `{ cd /x; } && gh pr create` and `if cd /x; then ...` hid the cd.
_RESERVED = frozenset({"{", "}", "!", "if", "then", "else", "elif", "fi", "do", "done",
                       "while", "until", "time"})

#: Shell keywords that open a compound command and increment the nesting depth used
#: to detect conditional ``cd``/``pushd``/``popd`` calls.  Any such call inside a
#: compound command (nesting depth > 0) may or may not execute, so we fail closed.
_NEST_OPENERS = frozenset({"if", "while", "until", "for", "case", "select"})

#: Openers whose header (``for x in ...``, ``case w in``) fills the rest of the
#: simple command: nothing after them in it is a program.
_HEADER_OPENERS = frozenset({"for", "case", "select"})

#: Shell keywords that close a compound command and decrement the nesting depth.
_NEST_CLOSERS = frozenset({"fi", "done", "esac"})

#: Short options (the single letter after ``-`` or ``+``) that take the next word
#: as a value and must be skipped when scanning bash/sh for a ``-c`` script.
#: ``-O``/``+O`` set/unset a shell option (bash), ``-o`` sets an option (most shells).
_SHELL_VALUED_SHORT_OPTS = frozenset({"O", "o"})
_SHELL_VALUED_LONG_OPTS = frozenset({"--rcfile", "--init-file"})


def _apply_parens(op: str, cwd: Path | None, stack: list[Path | None]) -> Path | None:
    """`(` starts a subshell that inherits cwd; `)` ends it and restores the outer one."""
    for ch in op:
        if ch == "(":
            stack.append(cwd)
        elif ch == ")":
            cwd = stack.pop() if stack else _UNKNOWN_CWD
    return cwd


def _prog(word: str) -> str:
    return os.path.basename(word).lower()


def _dynamic(tok: str) -> bool:
    return "$" in tok or "`" in tok


def _literal(value: str, what: str) -> str:
    if _dynamic(value):
        raise Unverifiable(f"{what} is not known until the shell runs")
    return value


# Characters that make bash build a word at run time: parameter and command
# substitution, brace expansion, globbing. The lexer has already removed quotes and
# backslashes, so `p''r` and `p\r` arrive here as `pr`; these cannot be resolved.
_EXPANDS = frozenset("$`{}*?[")


def _decisive(words: list[str], j: int, what: str) -> str | None:
    """``words[j]``, which decides whether this is a PR-create, if it is literal.

    A word bash expands at run time (``gh $S create``, ``gh p${X}r create``,
    ``gh {pr,} create``, ``gh p? create``) cannot be told apart from ``pr``, so it
    fails closed instead of reading as some other subcommand.
    """
    if j >= len(words):
        return None
    if _EXPANDS & set(words[j]):
        raise Unverifiable(f"{what} {words[j]!r} is not known until the shell runs")
    return words[j]


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def _skip_options(words: list[str], j: int, valued: frozenset[str] = frozenset()) -> int:
    while j < len(words) and words[j].startswith("-"):
        j += 2 if words[j] in valued else 1
    return j


def _next_word(words: list[str], k: int, flag: str) -> str:
    if k + 1 >= len(words):
        raise Unverifiable(f"{flag} has no value")
    return words[k + 1]


def _option_at(words: list[str], k: int, long: str, short: str | None, abbrev: bool) -> tuple[str | None, int]:
    """(value, words consumed) if ``words[k]`` sets ``long``/``short``, else (None, 1)."""
    w = words[k]
    name, eq, inline = w.partition("=")
    if name.startswith("--") and (name == long or (abbrev and len(name) >= 4 and long.startswith(name))):
        return (inline, 1) if eq else (_next_word(words, k, long), 2)
    if short and w == short:
        return _next_word(words, k, short), 2
    if short and w.startswith(short) and not w.startswith("--"):
        return w[len(short):], 1
    return None, 1


def _option_toks(toks: list[Tok], long: str, short: str | None, *, abbrev: bool = False) -> list[tuple[str, bool]]:
    """Every (value, expands-at-run-time) given to ``long`` / ``short``."""
    words = [t.text for t in toks]
    values: list[tuple[str, bool]] = []
    k = 0
    while k < len(words):
        value, used = _option_at(words, k, long, short, abbrev)
        if value is not None:
            values.append((value, toks[k + used - 1].expands))
        k += used
    return values


def _flag_values(words: list[str], long: str, short: str | None, *, abbrev: bool = False) -> list[str]:
    """Every value given to ``long`` (``--head X``, ``--head=X``) or ``short`` (``-H X``, ``-HX``)."""
    return [v for v, _ in _option_toks([Tok(w) for w in words], long, short, abbrev=abbrev)]


def _flag_value(words: list[str], long: str, short: str | None, *, abbrev: bool = False) -> str | None:
    """The last value given to the flag (the one the program uses), or None."""
    values = _flag_values(words, long, short, abbrev=abbrev)
    return values[-1] if values else None


# Global options that take a value, so the word after them is not a subcommand.
# Without these, `gh --repo o/r pr create` read `o/r` as gh's subcommand.
_GH_GLOBAL_VALUED = frozenset({"-R", "--repo"})
_GITHUB_GLOBAL_VALUED = frozenset({"--agentic-format", "--agentic-domain", "--repo"})
# git options hub accepts before its verb. -C / --git-dir / --work-tree move the
# repository being opened, which this analyser does not follow, so they fail closed.
_HUB_GLOBAL_VALUED = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"})
_HUB_MOVES_REPO = frozenset({"-C", "--git-dir", "--work-tree"})


def _gh(toks: list[Tok], pr_indices: set[int], gidx: list[int]) -> tuple[str, str | None] | None:
    words = [t.text for t in toks]
    j = _skip_options(words, 1, _GH_GLOBAL_VALUED)
    sub = _decisive(words, j, "gh subcommand")
    if sub == "pr":
        pr_at = j
        j = _skip_options(words, j + 1, frozenset({"-R", "--repo"}))
        if _decisive(words, j, "gh pr subcommand") in ("create", "new"):
            pr_indices.add(gidx[pr_at])
            return "gh pr create", _flag_value(words[j + 1:], "--head", "-H")
        return None
    if sub == "api":
        return _gh_api(toks[j + 1:])
    return None


# gh api's body-field flags: --raw-field/-f and --field/-F.
_FIELD_FLAGS = (("--raw-field", "-f"), ("--field", "-F"))
# gh api options that take the next word as their value.
_API_VALUED = frozenset({"-X", "--method", "-f", "--raw-field", "-F", "--field", "-H", "--header",
                         "--input", "-q", "--jq", "-t", "--template", "--hostname", "--cache",
                         "-p", "--preview"})


def _api_endpoint(words: list[str]) -> str | None:
    k = 0
    while k < len(words):
        w = words[k]
        if w in _API_VALUED:
            k += 2
        elif w.startswith("-") and w != "-":
            k += 1
        else:
            return w
    return None


def _posts(rest: list[str]) -> bool:
    """True when this gh api call may be a POST, explicitly or implied by a body."""
    fields = [v for long, short in _FIELD_FLAGS for v in _flag_values(rest, long, short)]
    method = _flag_value(rest, "--method", "-X")
    if method is not None and _EXPANDS & set(method):
        return True  # a method chosen at run time may be POST
    # gh api defaults to POST once a body is given (a field or --input).
    implied_post = method is None and bool(fields or _flag_values(rest, "--input", None))
    return (method or "").upper() == "POST" or implied_post


def _check_graphql(rest: list[Tok]) -> None:
    """Refuse a GraphQL call whose query is not a literal this can read, or that creates a PR."""
    words = [t.text for t in rest]
    if _flag_values(words, "--input", None):
        raise Unverifiable("gh api graphql --input sends a body this hook cannot read")
    for long, short in _FIELD_FLAGS:
        for value, expands in _option_toks(rest, long, short):
            _check_graphql_field(value, expands, reads_files=short == "-F")


def _check_graphql_field(value: str, expands: bool, reads_files: bool) -> None:
    """One ``key=value`` field of a GraphQL call; only ``query`` carries the operation."""
    key, _, body = value.partition("=")
    if expands and (_dynamic(key) or key == "query"):
        raise Unverifiable("gh api graphql query is not known until the shell runs")
    if key != "query":
        return
    if reads_files and body.startswith("@"):
        raise Unverifiable(f"gh api graphql reads its query from {body!r}, which this hook cannot read")
    if "createpullrequest" in body.lower():
        raise Unverifiable("gh api graphql createPullRequest cannot be matched to a commit")


def _gh_api(rest_toks: list[Tok]) -> tuple[str, str | None] | None:
    rest = [t.text for t in rest_toks]
    endpoint = _api_endpoint(rest)
    if endpoint is None:
        return None
    if endpoint.lower().rstrip("/").endswith("graphql"):
        _check_graphql(rest_toks)
        return None
    if not _PULLS_ENDPOINT.search(endpoint):
        # An endpoint built at run time (repos/o/r/$E, "$E") could be .../pulls or graphql.
        if _EXPANDS & set(endpoint) and _posts(rest):
            raise Unverifiable(f"gh api endpoint {endpoint!r} is not known until the shell runs")
        return None
    if not _posts(rest):
        return None
    fields = [v for long, short in _FIELD_FLAGS for v in _flag_values(rest, long, short)]
    heads = {f[len("head="):] for f in fields if f.startswith("head=")}
    if len(heads) != 1:
        raise Unverifiable("gh api POST .../pulls without exactly one literal head= field")
    return "gh api POST pulls", heads.pop()


def _github(words: list[str], pr_indices: set[int], gidx: list[int]) -> tuple[str, str | None] | None:
    j = _skip_options(words, 1, _GITHUB_GLOBAL_VALUED)
    if _decisive(words, j, "github subcommand") == "pr":
        pr_at = j
        j = _skip_options(words, j + 1, _GITHUB_GLOBAL_VALUED)
        if _decisive(words, j, "github pr subcommand") == "create":
            pr_indices.add(gidx[pr_at])
            return "github pr create", _flag_value(words[j + 1:], "--head", None, abbrev=True)
    return None


def _pr_assistant(words: list[str]) -> tuple[str, str | None] | None:
    rest = words[1:]
    if "--dry-run" in rest or "-h" in rest or "--help" in rest:
        return None
    create = True  # argparse default; the last of --create / --no-create wins
    for w in rest:
        if w == "--create":
            create = True
        elif w == "--no-create":
            create = False
    return ("pr-assistant (creates a PR when none exists)", None) if create else None


def _hub(words: list[str]) -> tuple[str, str | None] | None:
    j = _skip_options(words, 1, _HUB_GLOBAL_VALUED)
    if _decisive(words, j, "hub subcommand") != "pull-request":
        return None
    moved = [w.split("=", 1)[0] for w in words[1:j] if w.split("=", 1)[0] in _HUB_MOVES_REPO]
    if moved:
        raise Unverifiable(f"hub {moved[0]} opens a PR from another repository; it cannot be checked")
    return "hub pull-request", _flag_value(words[j + 1:], "--head", "-h")


# ---------------------------------------------------------------------------
# Finding the program word
# ---------------------------------------------------------------------------


_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*\+?=.*", re.DOTALL)
_PYTHON = re.compile(r"python[0-9.]*")
#: env options that neither run a string nor change directory.
_ENV_FLAGS = frozenset({"-", "-i", "--ignore-environment", "-0", "--null", "-v", "--debug"})
_TIMEOUT_VALUED = frozenset({"-s", "--signal", "-k", "--kill-after"})
_TIMEOUT_FLAGS = frozenset({"--preserve-status", "--foreground", "-v", "--verbose", "-f", "-p"})
#: Programs that run other commands from their arguments or stdin. Refused when
#: their own words mention PR words or name a shell.
_RUNNERS = frozenset({"xargs", "find", "parallel", "watch", "su", "script", "flock",
                      "sudo", "doas", "tmux", "screen"})
#: Builtins whose effect on the rest of the command this does not model. Refused
#: when the command mentions PR words.
_OPAQUE_BUILTINS = frozenset({"source", ".", "alias", "function", "trap"})


def _env_options(words: list[str], k: int) -> int:
    while k < len(words) and words[k].startswith("-"):
        w = words[k]
        if w == "--":
            return k + 1
        if w in _ENV_FLAGS or w.startswith("--unset=") or (w.startswith("-u") and len(w) > 2):
            k += 1
        elif w in ("-u", "--unset"):
            k += 2
        elif not w.startswith("--") and set(w[1:]) <= set("i0v"):
            k += 1
        else:
            raise Unverifiable(f"env {w} is not modelled (it can run a string or change directory)")
    return k


def _timeout_options(words: list[str], k: int) -> int:
    while k < len(words) and words[k].startswith("-"):
        w = words[k]
        if w == "--":
            k += 1
            break
        if w in _TIMEOUT_VALUED:
            k += 2
        elif w in _TIMEOUT_FLAGS or w.startswith(("--signal=", "--kill-after=")) or w[:2] in ("-s", "-k"):
            k += 1
        else:
            raise Unverifiable(f"timeout {w} is not modelled")
    return k + 1  # the duration


def _nice_options(words: list[str], k: int) -> int:
    while k < len(words) and words[k].startswith("-"):
        w = words[k]
        if w in ("-n", "--adjustment"):
            k += 2
        elif w.startswith(("-n", "--adjustment=")) or w[1:].lstrip("-").isdigit():
            k += 1
        else:
            raise Unverifiable(f"nice {w} is not modelled")
    return k


def _python_module(words: list[str], k: int) -> int | None:
    """Index of the module word in ``python -m MOD``, or None when not -m."""
    j = k + 1
    while j < len(words) and words[j].startswith("-"):
        w = words[j]
        if w == "-m":
            return j + 1 if j + 1 < len(words) else None
        if w == "-c":
            return None
        j += 2 if w in ("-W", "-X") else 1
    return None


def _lead(toks: list[Tok]) -> tuple[int | None, bool]:
    """(index of the program word, whether a wrapper runs it), or (None, _) for none.

    Strips reserved words, assignments and the transparent wrappers this models.
    A compound-command header (``for x in ...``) has no program word.
    """
    words = [t.text for t in toks]
    k: int | None = _after_reserved(toks)
    wrapped = False
    while k is not None and k < len(words):
        prog = _prog(words[k])
        if not toks[k].quoted and _ASSIGNMENT.fullmatch(words[k]):
            k += 1
        elif prog in ("command", "builtin"):
            k = _command_options(words, k + 1)
        elif prog in _WRAPPERS:
            wrapped = True
            k = _wrapper_end(prog, words, k + 1)
        else:
            idx = _program_index(prog, words, k)
            return idx, wrapped or idx != k
    return None, wrapped


_WRAPPERS = frozenset({"exec", "nohup", "env", "timeout", "nice"})


def _after_reserved(toks: list[Tok]) -> int | None:
    """Index after the leading reserved words; None for a compound-command header."""
    k = 0
    while k < len(toks) and not toks[k].quoted and (toks[k].text in _RESERVED or toks[k].text in _NEST_OPENERS):
        if toks[k].text in _HEADER_OPENERS:
            return None
        k += 1
    return k


def _command_options(words: list[str], k: int) -> int | None:
    """Index after ``command``/``builtin`` options; None for ``-v``/``-V`` (a lookup only)."""
    while k < len(words) and words[k].startswith("-"):
        if words[k] in ("-v", "-V"):
            return None
        k += 1
    return k


def _program_index(prog: str, words: list[str], k: int) -> int:
    """``words[k]`` is the program; a launcher (``python -m``, ``./bin/assistant``) moves it on."""
    if _PYTHON.fullmatch(prog):
        return _python_module(words, k) or k
    if prog == "assistant" and k + 1 < len(words):
        return k + 1
    return k


def _wrapper_end(prog: str, words: list[str], k: int) -> int:
    if prog == "exec":
        return _skip_options(words, k, frozenset({"-a"}))
    if prog == "env":
        return _env_options(words, k)
    if prog == "timeout":
        return _timeout_options(words, k)
    if prog == "nice":
        return _nice_options(words, k)
    return k  # nohup


def _program_unknown(tok: Tok) -> bool:
    """A program word whose name the shell builds at run time."""
    base = os.path.basename(tok.text)
    return base not in ("[", "[[") and bool(_EXPANDS & set(base))


# ---------------------------------------------------------------------------
# Walking the command
# ---------------------------------------------------------------------------


_CD_OPTION_LETTERS = frozenset("LPe@")


def _cd_target(prog: str, words: list[str], cwd: Path | None) -> Path | None:
    """The directory after ``cd``/``pushd`` ``words[1:]``; None when not knowable.

    Only the forms bash runs as a plain directory change are modelled: options
    from ``-LPe@`` and exactly one operand (none for ``cd``, meaning HOME).
    ``cd a b`` fails in bash and leaves the cwd unchanged; ``pushd`` with no
    operand or ``+N``/``-N`` rotates the stack. Those are unknown.
    """
    operands = _cd_operands(prog, words[1:])
    if operands is None or len(operands) > 1 or (prog == "pushd" and not operands):
        return _UNKNOWN_CWD
    if not operands:
        return Path.home()
    arg = operands[0]
    if _dynamic(arg) or arg == "-" or (arg.startswith("~") and not (arg == "~" or arg.startswith("~/"))):
        return _UNKNOWN_CWD
    target = Path(os.path.expanduser(arg))
    if target.is_absolute():
        return target
    return cwd / target if cwd is not None else _UNKNOWN_CWD


def _cd_operands(prog: str, args: list[str]) -> list[str] | None:
    """Operands of ``cd``/``pushd``; None for an option this does not model."""
    operands: list[str] = []
    options_done = False
    for w in args:
        if options_done or len(w) < 2 or w[0] not in "-+" or (w[0] == "+" and prog != "pushd"):
            operands.append(w)
        elif w == "--":
            options_done = True
        elif not (prog == "cd" and w[0] == "-" and set(w[1:]) <= _CD_OPTION_LETTERS):
            return None  # pushd -n / +N / -N, or an unknown option
    return operands


def _shell_script(toks: list[Tok]) -> tuple[bool, Tok | None]:
    """(saw ``-c``, the first operand) of ``bash [options] ...``.

    Options may be clustered (``-lc``). Options that consume a value (``-O extglob``,
    ``+O extglob``, ``--rcfile F``) are skipped with their value so it is not taken
    for the script.
    """
    saw_c = False
    k = 1
    while k < len(toks):
        width, sets_c = _shell_option_width(toks[k].text)
        if width == 0:
            break
        saw_c = saw_c or sets_c
        k += width
        if toks[k - width].text == "--":
            break
    return saw_c, (toks[k] if k < len(toks) else None)


def _shell_option_width(w: str) -> tuple[int, bool]:
    """(words the option takes, whether it sets ``-c``); width 0 means an operand."""
    if w.startswith("--"):
        return (2 if w in _SHELL_VALUED_LONG_OPTS else 1), False
    if w[:1] in ("-", "+") and len(w) > 1:
        valued = len(w) == 2 and w[1] in _SHELL_VALUED_SHORT_OPTS
        return (2 if valued else 1), (w[0] == "-" and "c" in w[1:])
    return 0, False


def _update_nest(cmd: list[tuple[int, Tok]], nest: int) -> int:
    """Return the nesting depth after the leading reserved-word prefix of ``cmd``.

    Walks the prefix while it holds reserved words or openers, counting every
    opener and closer in it: ``then for x in 1``, ``else case w in``, ``do select``.
    ``for``/``case``/``select`` end the walk, because their header fills the rest
    of the simple command. A plain program ends it too, so ``echo fi`` does not
    count its argument as a closer.
    """
    for _idx, tok in cmd:
        w = "" if tok.quoted else tok.text
        if w in _NEST_OPENERS:
            nest += 1
        elif w in _NEST_CLOSERS:
            nest = max(0, nest - 1)
        if w in _HEADER_OPENERS or not (w in _RESERVED or w in _NEST_OPENERS):
            break
    return nest


def _defines_function(toks: list[Tok]) -> bool:
    """``name() ...`` or ``name ( ) ...``: a function body runs later, not here."""
    for a, b in zip(toks, toks[1:]):
        if a.op and "()" in a.text:
            return True
        if a.op and a.text.endswith("(") and b.op and b.text.startswith(")"):
            return True
    return bool(toks) and toks[-1].op and "()" in toks[-1].text


@dataclass
class _Walk:
    """State shared across the simple commands of one ``find_targets`` call."""

    depth: int
    vocab: bool                 # the command text mentions PR words
    targets: list[Target] = field(default_factory=list)
    pr_indices: set[int] = field(default_factory=set)


def find_targets(command: str, cwd: Path | None, depth: int = 0) -> list[Target]:
    if depth > MAX_DEPTH:
        raise Unverifiable("commands nested too deeply to check")
    try:
        toks = tokenize(command)
    except ValueError:
        low = command.lower()
        if ("pr" in low and "create" in low) or "pull-request" in low or _mentions_pr(command):
            raise Unverifiable("the command cannot be tokenised (unbalanced quote?)") from None
        return []
    walk = _Walk(depth=depth, vocab=_mentions_pr(command))
    if walk.vocab and _defines_function(toks):
        raise Unverifiable("a shell function definition may redefine a command; it is not modelled")
    stack: list[Path | None] = []
    nest = 0  # compound-command nesting depth (if/while/until/for/case/select → fi/done/esac)
    prev_op = ""  # separator that ended the previous simple command
    for cmd, op in split_with_operators(toks):
        # Update nesting BEFORE processing so that ``if cd /x; then ...`` is already
        # at depth 1 when the cd is evaluated (fail-closed; see _update_nest).
        nest = _update_nest(cmd, nest)
        # The separator follows its command: `cd x)` moves, then `)` restores.
        if cmd:
            cwd = _walk_command(cmd, op, cwd, walk, nest, prev_op)
        cwd = _apply_parens(op, cwd, stack)
        prev_op = op
    _check_dynamic([t.text for t in toks], walk.pr_indices)
    return walk.targets


def _strip_redirects(cmd: list[tuple[int, Tok]]) -> list[tuple[int, Tok]]:
    """Drop redirection operators, their target words and glued fd numbers."""
    out: list[tuple[int, Tok]] = []
    skip = False
    for idx, tok in cmd:
        if skip:
            skip = False
        elif tok.op:
            skip = True
        elif not tok.fd:
            out.append((idx, tok))
    return out


def _walk_command(
    cmd: list[tuple[int, Tok]], op: str, cwd: Path | None, walk: _Walk,
    nest: int = 0, prev_op: str = "",
) -> Path | None:
    """Collect targets in one simple command; return the cwd for the commands after it.

    ``nest`` is the compound-command nesting depth (>0 inside if/while/for/case/…);
    ``prev_op`` is the separator that ended the preceding simple command.  A
    cd/pushd/popd inside a compound command (nest > 0) may or may not execute, so
    we fail closed and return ``_UNKNOWN_CWD``.  Likewise, a cd whose preceding
    operator is ``&&`` or ``||`` only runs when the prior command succeeded or failed
    (respectively), which we cannot evaluate statically.
    """
    _check_substitutions(cmd, cwd, walk)
    kept = _strip_redirects(cmd)
    gidx = [i for i, _ in kept]
    toks = [t for _, t in kept]
    words = [t.text for t in toks]
    lead, wrapped = _lead(toks)
    if lead is not None:
        if _program_unknown(toks[lead]):
            raise Unverifiable(f"the program {words[lead]!r} is not known until the shell runs")
        prog = _prog(words[lead])
        if prog in ("cd", "pushd", "popd"):
            conditional = wrapped or nest > 0 or "&&" in prev_op or "||" in prev_op
            return _cd_effect(prog, words[lead:], op, cwd, conditional)
        _check_opaque(prog, toks, lead, walk)
    for i in range(len(words)):
        found = _targets_at(toks, i, gidx, cwd, walk, i == lead)
        if found and i != lead:
            runner = repr(words[lead]) if lead is not None else "no program"
            raise Unverifiable(f"{found[0].entry} runs under {runner}, which this hook does not model")
        walk.targets.extend(found)
    return cwd


def _check_substitutions(cmd: list[tuple[int, Tok]], cwd: Path | None, walk: _Walk) -> None:
    """Refuse a command whose ``$(...)``, backtick, ``<(...)`` or here-doc body opens a PR."""
    for _, tok in cmd:
        for body in tok.subs:
            if find_targets(body, cwd, walk.depth + 1):
                raise Unverifiable(
                    "a command substitution ($(...) or backticks) opens a PR, and its result "
                    "is not modelled"
                )


def _cd_effect(prog: str, words: list[str], op: str, cwd: Path | None, conditional: bool) -> Path | None:
    """The cwd after a ``cd``/``pushd``/``popd`` ended by separator ``op``.

    ``conditional`` covers a cd that may not run (inside a compound command, after
    ``&&``/``||``) or that runs as a separate program (``env cd``, ``nohup cd``).
    """
    if prog == "popd":
        return _UNKNOWN_CWD
    applies = _cd_applies(op)
    if applies is None or conditional:
        return _UNKNOWN_CWD
    return _cd_target(prog, words, cwd) if applies else cwd


def _check_opaque(prog: str, toks: list[Tok], lead: int, walk: _Walk) -> None:
    """Refuse a program word whose effect this does not model when PR creation could be involved."""
    words = [t.text for t in toks]
    if prog in _OPAQUE_BUILTINS and walk.vocab:
        raise Unverifiable(f"`{words[lead]}` runs code or changes the shell in ways this hook does not model")
    if prog in _RUNNERS and (
        _mentions_pr(" ".join(words[lead:])) or any(_prog(w) in _SHELLS for w in words[lead + 1:])
    ):
        raise Unverifiable(f"`{words[lead]}` runs a command this hook cannot read")
    if prog == "eval":
        operands = toks[lead + 1:]
        if any(t.expands for t in operands):
            raise Unverifiable("eval runs text that is not known until the shell runs")
        if walk.vocab:
            raise Unverifiable("eval re-parses its arguments; this hook does not model it")


def _targets_at(
    toks: list[Tok], i: int, gidx: list[int], cwd: Path | None, walk: _Walk, is_lead: bool,
) -> list[Target]:
    words = [t.text for t in toks]
    prog = _prog(words[i])
    tail = words[i:]
    found: tuple[str, str | None] | None = None
    if prog == "gh":
        found = _gh(toks[i:], walk.pr_indices, gidx[i:])
    elif prog in _GITHUB_CLI:
        found = _github(tail, walk.pr_indices, gidx[i:])
    elif prog == "pr-assistant":
        found = _pr_assistant(tail)
    elif prog == "hub":
        found = _hub(tail)
    elif prog in _SHELLS:
        return _shell_targets(toks[i:], cwd, walk, is_lead)
    elif prog == "eval" and is_lead and i + 1 < len(words):
        if find_targets(" ".join(words[i + 1:]), cwd, walk.depth + 1):
            raise Unverifiable("eval re-parses its arguments; this hook does not model it")
        return []
    if found is None:
        return []
    return [Target(entry=found[0], cwd=cwd, head=found[1])]


def _shell_targets(toks: list[Tok], cwd: Path | None, walk: _Walk, is_lead: bool) -> list[Target]:
    saw_c, operand = _shell_script(toks)
    if saw_c:
        if operand is None:
            return []
        if operand.expands:
            raise Unverifiable(
                f"{toks[0].text} -c runs {operand.text!r}, which is not known until the shell runs"
            )
        return find_targets(operand.text, cwd, walk.depth + 1)
    if is_lead and walk.vocab and (operand is None or operand.text == "-"):
        raise Unverifiable(f"{toks[0].text} reads its commands from stdin, which this hook cannot read")
    return []


def _check_dynamic(words: list[str], pr_indices: set[int]) -> None:
    """Refuse `pr ... create|new` that no entry point accounted for, if anything is dynamic."""
    if not any(_dynamic(t) for t in words):
        return
    for k, w in enumerate(words):
        if w == "pr" and k not in pr_indices and any(x in ("create", "new") for x in words[k + 1:]):
            raise Unverifiable("a program name is not known until the shell runs")


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_OVERRIDES}
    try:
        proc = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
            ["git", *args], cwd=str(cwd), env=env, capture_output=True, text=True, check=False,
        )
    except OSError as exc:
        raise Unverifiable(f"git could not run in {cwd}: {exc}") from None
    if proc.returncode != 0:
        raise Unverifiable(f"git {' '.join(args)} failed in {cwd}")
    return proc.stdout.strip()


def resolve_commit(target: Target) -> tuple[Path, str]:
    """(directory, commit id) of the PR head ``target`` would open."""
    if target.cwd is None:
        raise Unverifiable("the directory it runs in is not known until the shell runs")
    if target.head is None:
        rev = "HEAD"
    else:
        branch = _literal(target.head, "--head")
        if ":" in branch:  # gh accepts owner:branch
            branch = branch.split(":", 1)[1]
        if not branch or branch.startswith("-"):
            raise Unverifiable(f"--head {target.head!r} is not a usable branch name")
        rev = branch
    sha = _git(target.cwd, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    if not _SHA_RE.fullmatch(sha):
        raise Unverifiable(f"{rev} did not resolve to a 40-hex commit id")
    return target.cwd, sha


def record_path(cwd: Path, sha: str) -> Path:
    common = Path(_git(cwd, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = cwd / common
    # .resolve(), as sweep_record.records_dir does, so both name the same path.
    return common.resolve().joinpath(*RECORD_SUBDIR, f"{sha}.json")


def has_record(path: Path, sha: str) -> bool:
    try:
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode):
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("head_sha") == sha and data.get("mode") in MODES


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _block(message: str) -> int:
    print(f"Blocked: {message}", file=sys.stderr)
    return 2


def _advice(sha: str | None) -> str:
    head = sha or "<40-hex sha>"
    return (
        "Run the local concern swarm first (via /open-pr), or record a waiver:\n"
        f"  ./bin/workflow sweep-record waive --head {head} --reason \"<why>\""
    )


def evaluate(payload: dict) -> int:
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return 0
    raw_cwd = payload.get("cwd")
    cwd = Path(raw_cwd) if isinstance(raw_cwd, str) and raw_cwd else Path.cwd()
    try:
        targets = find_targets(command, cwd)
    except Unverifiable as exc:
        return _block(
            f"this command may open a PR and cannot be checked: {exc}.\n"
            f"{_REFUSE_HINT}; the hook refuses forms it does not fully model.\n{_advice(None)}"
        )
    for target in targets:
        try:
            cwd, sha = resolve_commit(target)
            path = record_path(cwd, sha)
        except Unverifiable as exc:
            return _block(f"{target.entry}: cannot determine the commit being opened: {exc}.\n{_advice(None)}")
        if not has_record(path, sha):
            return _block(
                f"{target.entry} would open a PR for {sha}, which has no concern-sweep "
                f"record ({path}).\n{_advice(sha)}"
            )
    return 0


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except ValueError:
        return _block("the hook payload is not JSON; failing closed.")
    if not isinstance(payload, dict):
        return _block("the hook payload is not a JSON object; failing closed.")
    return evaluate(payload)


if __name__ == "__main__":
    sys.exit(main())
