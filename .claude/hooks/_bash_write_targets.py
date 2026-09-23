#!/usr/bin/env python3
"""Parse a Bash command and report what it writes, for block-readonly-role-writes.sh.

Invoked by the hook as::

    python3 -I -S _bash_write_targets.py <repo-root> < <PreToolUse payload JSON>

``-I -S`` is mandatory, not a style choice: hooks run with the session's environment,
and a foreign ``PYTHONPATH`` would otherwise execute that tree's ``sitecustomize.py``
before a line of this file runs. Stdlib only, for the same reason.

WHY A PARSER
------------
The Bash branch this replaces judged the command by substituting characters in the raw
string and word-splitting the result. PR #395 spent fourteen review rounds on it, and
every round found the same defect in a new spelling -- `>&`, a separator glued to a
redirect target, `--target-directory=src`, `-tsrc`, the `s` inside `-tsrc` read as
`-s`, the `0` of `truncate -s 0`. Patching spellings does not converge; parsing does,
because each of those is ONE rule of the shell grammar rather than one case of it.

OUTPUT: NUL-terminated records on stdout
    T1<path>   strict write target: a name the shell is about to create (redirect
               operand, touch/tee/truncate operand, cp/install/ln destination)
    T0<path>   non-strict write target: acts on something that must already exist
    U<reason>  a fact that decides the verdict cannot be known before the shell runs
               (a variable, a command substitution, an unparseable construct). The
               hook BLOCKS on any U record -- fail closed, never guess.
    OK         always the final record. Its absence means this process died, and the
               hook treats that as a block too.

Paths are reported exactly as the shell would see them after quote removal, tilde and
brace expansion. Judging them -- tracked source or artifact -- stays in the hook's
classify_path, so the Write/Edit and Bash branches cannot disagree about what counts.

WHAT IS STILL OUT OF REACH (the hook's header lists these too)
    * What a program does once it runs: `python3 -c "open(...)"`, `make`, `git
      checkout -- src/x`, a script file. This is command SEMANTICS, not shell grammar;
      no tokenizer can see it. Only the commands in HANDLERS below are judged.
    * sed script commands that write (`w FILE`) or execute (`e`).
    * The harness may run commands under zsh. The grammar modelled is bash's; zsh-only
      syntax generally fails to parse here and is therefore blocked.
"""

from __future__ import annotations

import json
import os
import re
import sys

MAX_DEPTH = 32          # nested substitutions / eval before we refuse
MAX_BRACE_WORDS = 256   # brace-expansion fan-out before we refuse
MAX_GLOB_MATCHES = 200  # glob matches classified before we refuse

# Kinds of run-time value, as they appear in refusal messages.
CMD_SUBST = "a command substitution"
ARITH = "an arithmetic expansion"
PROCSUB = "a process substitution"
UNTERMINATED_SQUOTE = "unterminated single quote"
NOT_KNOWN = "is not known until the shell runs"


class ParseError(Exception):
    """The command is not something this parser understands. Always a block."""


class Unknown:
    """A slot in a word whose text is decided at run time ($x, $(...), ...)."""

    __slots__ = ("kind",)

    def __init__(self, kind: str) -> None:
        self.kind = kind


# A word is a list of items: (char, quoted) for literal text, or Unknown.
# `quoted` matters because only UNquoted characters take part in brace, tilde and
# glob expansion -- `'src'` and `src` name the same file, `'*'` and `*` do not.


def unknown_kind(items):
    for it in items:
        if isinstance(it, Unknown):
            return it.kind
    return None


def text_of(items):
    """The literal text of a word, or None if any part of it is unknown."""
    if unknown_kind(items) is not None:
        return None
    return "".join(ch for ch, _ in items)


def bare(it):
    """The character of an UNQUOTED literal item, else None."""
    if isinstance(it, Unknown) or it[1]:
        return None
    return it[0]


def reserved(items):
    """The text of an unquoted literal word -- the only form a keyword can take."""
    t = text_of(items)
    if t is None or any(q for _, q in items):
        return None
    return t


def is_procsub(items) -> bool:
    """`<(cmd)` / `>(cmd)` alone: a /dev/fd pipe, never an option or a repo path.

    Its body was already parsed and judged where it was lexed.
    """
    return len(items) == 1 and isinstance(items[0], Unknown) and items[0].kind == PROCSUB


_ASSIGN = re.compile(r"[A-Za-z_]\w*(\[[^\]]*\])?\+?=", re.ASCII)


def is_assignment(items) -> bool:
    prefix = []
    for it in items:
        ch = bare(it)
        if ch is None:
            break
        prefix.append(ch)
        if ch == "=":
            break
    return bool(_ASSIGN.fullmatch("".join(prefix)))


def literal_prefix(items) -> str:
    out = []
    for it in items:
        if isinstance(it, Unknown):
            break
        out.append(it[0])
    return "".join(out)


# ---------------------------------------------------------------------------
# Expansion of literal words
# ---------------------------------------------------------------------------


def _match_brace(items, start):
    """Return (end, alternatives) for a brace expression opening at `start`."""
    depth = 0
    commas = []
    for j in range(start, len(items)):
        ch = bare(items[j])
        if ch == "{":
            depth += 1
        elif ch == "," and depth == 1:
            commas.append(j)
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return j, _brace_alternatives(items, start, j, commas)
    return None, None


def _brace_alternatives(items, start, end, commas):
    if not commas:
        return _brace_sequence(items[start + 1:end])
    bounds = [start] + commas + [end]
    return [items[a + 1:b] for a, b in zip(bounds, bounds[1:])]


_SEQ_INT = re.compile(r"(-?\d+)\.\.(-?\d+)(?:\.\.(-?\d+))?")
_SEQ_CHR = re.compile(r"([A-Za-z])\.\.([A-Za-z])(?:\.\.(-?\d+))?")


def _seq_range(lo: int, hi: int, step):
    step = abs(int(step or 1)) or 1
    rng = range(lo, hi + 1, step) if lo <= hi else range(lo, hi - 1, -step)
    if len(rng) > MAX_BRACE_WORDS:
        raise ParseError("a brace sequence expands to too many words to check")
    return rng


def _brace_sequence(inner):
    """`{1..3}` / `{a..c}` alternatives, or None if `inner` is not a sequence."""
    text = reserved(inner)
    if text is None:
        return None
    m = _SEQ_INT.fullmatch(text)
    if m:
        a, b = m.group(1), m.group(2)
        padded = a.lstrip("-").startswith("0") or b.lstrip("-").startswith("0")
        width = max(len(a), len(b)) if padded else 0
        return [[(c, True) for c in str(n).zfill(width)] for n in _seq_range(int(a), int(b), m.group(3))]
    m = _SEQ_CHR.fullmatch(text)
    if m:
        return [[(chr(n), True)] for n in _seq_range(ord(m.group(1)), ord(m.group(2)), m.group(3))]
    return None


def brace_expand(items):
    """Bash brace expansion: `{src,tests}` is two words, `{rm,-rf,src}` is three."""
    for i, it in enumerate(items):
        if bare(it) != "{":
            continue
        end, alts = _match_brace(items, i)
        if alts is None:
            continue
        out = []
        for alt in alts:
            out.extend(brace_expand(items[:i] + alt + items[end + 1:]))
            if len(out) > MAX_BRACE_WORDS:
                raise ParseError("brace expansion produces too many words to check")
        return out
    return [items]


def _home_of(login: str):
    if login == "":
        return os.environ.get("HOME")
    try:
        import pwd  # noqa: PLC0415 - absent on some platforms; only needed for ~user

        return pwd.getpwnam(login).pw_dir
    except (ImportError, KeyError):
        return None


def tilde_expand(items):
    """`~` and `~user` at the start of a word, unquoted, as bash does."""
    if not items or bare(items[0]) != "~":
        return items
    name = []
    k = 1
    while k < len(items) and bare(items[k]) not in (None, "/"):
        name.append(items[k][0])
        k += 1
    if k < len(items) and bare(items[k]) is None:
        return items              # a quoted tilde-prefix is not expanded
    login = "".join(name)
    if login in ("+", "-"):
        return [Unknown("a ~+ / ~- directory")] + items[k:]
    home = _home_of(login)
    if home is None:
        # No such user: bash leaves the word as written. No $HOME: unknowable.
        return items if login else [Unknown("a home directory that is not set")] + items[k:]
    return [(c, True) for c in home] + items[k:]


def has_glob(items) -> bool:
    for i, it in enumerate(items):
        ch = bare(it)
        if ch in ("*", "?"):
            return True
        if ch == "[" and any(bare(x) == "]" for x in items[i + 1:]):
            return True
    return False


def glob_pattern(items) -> str:
    """The word as a glob.glob pattern, with QUOTED metacharacters escaped."""
    import glob  # noqa: PLC0415 - 3.5 ms of startup, paid only when a target globs

    return "".join(glob.escape(ch) if quoted else ch for ch, quoted in items)


# ---------------------------------------------------------------------------
# Result sink
# ---------------------------------------------------------------------------


class Sink:
    def __init__(self, repo_root: str) -> None:
        self.repo_root = repo_root
        self.records = []
        self.unknowns = []

    def emit(self, strict: bool, path: str) -> None:
        self.records.append(("T1" if strict else "T0") + path)

    def refuse(self, reason: str) -> None:
        self.unknowns.append(reason)

    def target(self, items, strict: bool, what: str) -> None:
        """Report `items` as a write target, after every static expansion bash does."""
        if is_procsub(items):
            return
        for word in brace_expand(items):
            word = tilde_expand(word)
            kind = unknown_kind(word)
            if kind is not None:
                self.refuse(f"{what} contains {kind}, whose value {NOT_KNOWN}")
                continue
            text = "".join(ch for ch, _ in word)
            if text == "":
                continue          # the shell errors out on an empty name
            if bare(word[0]) == "=":
                # zsh expands a leading `=cmd` to that command's path.
                self.refuse(f"{what} starts with '=', which zsh expands to a command path")
            elif has_glob(word):
                self._glob_target(word, text, what)
            else:
                self.emit(strict, text)

    def _glob_target(self, word, text: str, what: str) -> None:
        """A glob in a write position: judge the directory it lives in AND its matches.

        The directory is the literal text before the first metacharacter, so `s*` is
        judged as the current directory -- which for a relative path is the repo root,
        and `rm -rf s*` there deletes src/. Matches are judged too, because a glob in a
        middle segment (`out/*/mail`) can pass through a symlink into source.
        """
        first = next(i for i, it in enumerate(word) if bare(it) in ("*", "?", "["))
        literal = text[:first]
        self.emit(False, literal[: literal.rfind("/") + 1] if "/" in literal else ".")
        pattern = glob_pattern(word)
        if not os.path.isabs(pattern):
            if not self.repo_root:
                return
            pattern = os.path.join(self.repo_root, pattern)
        import glob  # noqa: PLC0415 - see glob_pattern

        for count, match in enumerate(glob.iglob(pattern, recursive=True)):
            if count >= MAX_GLOB_MATCHES:
                self.refuse(f"{what} is a glob matching more than {MAX_GLOB_MATCHES} paths")
                return
            self.emit(False, match)


# ---------------------------------------------------------------------------
# Lexer + parser
# ---------------------------------------------------------------------------

_METACHARS = " \t\n;&|<>()"
_REDIR_OPS = ("&>>", "&>", "<<<", "<<-", "<<", "<>", "<&", ">>", ">|", ">&", "<", ">")
_CONTROL_OPS = (";;&", ";;", ";&", "&&", "||", "|&", ";", "&", "|", "(", ")")
_CASE_ENDS = (";;", ";&", ";;&")
_FD_PREFIX = re.compile(r"\d+(?=[<>])|\{[A-Za-z_]\w*\}(?=[<>])", re.ASCII)
_NAME = re.compile(r"[A-Za-z_]\w*", re.ASCII)
_OCTAL = re.compile(r"[0-7]{1,3}")
_HEX = {e: re.compile(r"[0-9A-Fa-f]{1,%d}" % n) for e, n in (("x", 2), ("u", 4), ("U", 8))}
_ANSI_SIMPLE = {"a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "n": "\n",
                "r": "\r", "t": "\t", "v": "\v", "\\": "\\", "'": "'", '"': '"', "?": "?"}

# Words that, at the start of a command, open or continue a compound command rather
# than naming a program. `do rm -rf src` is `rm`, not a command called `do`.
_KEEP_START = {"!", "{", "then", "do", "else", "elif", "if", "while", "until", "time", "coproc"}
# Keyword -> parser state it moves to when met at the start of a command.
_START_STATES = {
    "}": "after", "fi": "after", "done": "after",
    "for": "skip", "select": "skip",       # header words are not commands
    "case": "casesubj",
    "function": "skipone",                 # the function's name
    "[[": "dbracket",                      # < and > compare inside [[ ]]
}

WRITE_REDIRECTS = {">", ">>", ">|", "&>", "&>>", "<>", ">&"}


class Word:
    __slots__ = ("items", "start", "end")

    def __init__(self, start: int) -> None:
        self.items = []
        self.start = start
        self.end = start


class Parser:
    """One pass over one shell program: lexes, tracks command position, and hands each
    simple command to `analyse`. Command substitutions, backticks, process
    substitutions and eval'd strings are parsed by a nested Parser -- their contents
    RUN whatever position they sit in, so `cat $(rm -rf src)` is judged like `rm -rf src`.

    States: start (expecting a command word), args, skip (for/select header), skipone
    (function name), after (a compound command just closed), dbracket, casesubj.
    """

    def __init__(self, src: str, sink: Sink, depth: int = 0, pos: int = 0, closer=None) -> None:
        if depth > MAX_DEPTH:
            raise ParseError("substitutions are nested too deeply to check")
        self.s = src
        self.n = len(src)
        self.i = pos
        self.sink = sink
        self.depth = depth
        self.closer = closer
        self.heredocs = []      # (delimiter, strip_tabs, quoted) awaiting the next newline
        self.case_stack = []    # "pattern" | "body"
        self.paren_depth = 0
        self.words = []
        self.state = "start"
        self.time_seen = False

    def _nested(self, pos: int, closer=None) -> "Parser":
        return Parser(self.s, self.sink, self.depth + 1, pos, closer)

    def parse_string(self, code: str) -> None:
        Parser(code, self.sink, self.depth + 1).parse()

    # -- lexing: tokens -----------------------------------------------------

    def next_token(self):
        self._skip_blanks()
        if self.i >= self.n:
            return ("eof", None)
        if self.s[self.i] == "\n":
            self.i += 1
            self._read_heredocs()
            return ("op", "\n")
        return self._try_redirect() or self._try_operator() or ("word", self._read_word())

    def _skip_blanks(self) -> None:
        s = self.s
        while True:
            while self.i < self.n and s[self.i] in " \t":
                self.i += 1
            if s.startswith("\\\n", self.i):
                self.i += 2
            elif self.i < self.n and s[self.i] == "#":
                nl = s.find("\n", self.i)
                self.i = self.n if nl == -1 else nl
            else:
                return

    def _try_redirect(self):
        s = self.s
        m = _FD_PREFIX.match(s, self.i)
        fd = m.group(0) if m else None
        j = m.end() if m else self.i
        for op in _REDIR_OPS:
            if not s.startswith(op, j):
                continue
            if op in ("<", ">") and fd is None and s.startswith("(", j + 1):
                return None       # <(...) / >(...) is process substitution, a word
            self.i = j + len(op)
            return ("redir", op)
        return None

    def _try_operator(self):
        if self.s.startswith("((", self.i):
            self.i = self._scan_arith(self.i + 2)
            return ("arith", None)
        for op in _CONTROL_OPS:
            if self.s.startswith(op, self.i):
                self.i += len(op)
                return ("op", op)
        return None

    # -- lexing: words ------------------------------------------------------

    def _read_word(self) -> Word:
        w = Word(self.i)
        items = w.items
        while self.i < self.n:
            c = self.s[self.i]
            if c in "<>" and not items and self.s.startswith("(", self.i + 1):
                sub = self._nested(self.i + 2, ")")
                sub.parse()
                self.i = sub.i
                items.append(Unknown(PROCSUB))
            elif c == "(" and self._at_array_open(items):
                self.i += 1
                self._skip_array()
                items.append(Unknown("an array"))
            elif c in _METACHARS:
                break
            else:
                self.i = self._read_word_char(self.i, items)
        w.end = self.i
        return w

    @staticmethod
    def _at_array_open(items) -> bool:
        t = text_of(items)
        return bool(t) and t.endswith("=") and is_assignment(items)

    def _read_word_char(self, j: int, items) -> int:
        c = self.s[j]
        if c == "\\":
            return self._read_backslash(j, items)
        if c == "'":
            return self._read_squote(j + 1, items)
        if c == '"':
            return self._read_dquote(j + 1, items)
        if c == "`":
            return self._read_backtick(j + 1, items, in_dquote=False)
        if c == "$":
            return self._read_dollar(j, items, in_dquote=False)
        items.append((c, False))
        return j + 1

    def _read_backslash(self, j: int, items) -> int:
        if self.s.startswith("\n", j + 1):
            return j + 2          # line continuation
        if j + 1 < self.n:
            items.append((self.s[j + 1], True))
            return j + 2
        items.append(("\\", True))
        return j + 1

    def _read_squote(self, j: int, items) -> int:
        end = self.s.find("'", j)
        if end == -1:
            raise ParseError(UNTERMINATED_SQUOTE)
        items.extend((ch, True) for ch in self.s[j:end])
        return end + 1

    def _skip_array(self) -> None:
        """`a=( ... )`: the elements are words, lexed so their substitutions are seen."""
        while True:
            kind, val = self.next_token()
            if kind == "eof":
                raise ParseError("unterminated array assignment")
            if kind == "op" and val == ")":
                return
            if kind == "op" and val != "\n":
                raise ParseError(f"unexpected {val!r} in an array assignment")

    def _read_dquote(self, j: int, items) -> int:
        while j < self.n:
            c = self.s[j]
            if c == '"':
                return j + 1
            if c == "\\":
                j = self._dquote_backslash(j, items)
            elif c == "$":
                j = self._read_dollar(j, items, in_dquote=True)
            elif c == "`":
                j = self._read_backtick(j + 1, items, in_dquote=True)
            else:
                items.append((c, True))
                j += 1
        raise ParseError("unterminated double quote")

    def _dquote_backslash(self, j: int, items) -> int:
        nxt = self.s[j + 1:j + 2]
        if nxt == "\n":
            return j + 2
        if nxt in ("$", "`", '"', "\\"):
            items.append((nxt, True))
            return j + 2
        items.append(("\\", True))
        return j + 1

    def _read_backtick(self, j: int, items, in_dquote: bool) -> int:
        s = self.s
        escapable = "$`\\\"" if in_dquote else "$`\\"
        body = []
        while j < self.n and s[j] != "`":
            if s[j] == "\\" and j + 1 < self.n and s[j + 1] in escapable:
                j += 1
            body.append(s[j])
            j += 1
        if j >= self.n:
            raise ParseError("unterminated backtick substitution")
        self.parse_string("".join(body))
        items.append(Unknown(CMD_SUBST))
        return j + 1

    def _read_dollar(self, j: int, items, in_dquote: bool) -> int:
        """Everything that can follow `$`. `j` is the index of the `$` itself."""
        opener = self._dollar_opener(j, in_dquote)
        if opener is not None:
            return opener(j, items)
        nxt = self.s[j + 1:j + 2]
        m = _NAME.match(self.s, j + 1)
        if m:
            kind, end = "a variable", m.end()
        elif nxt and nxt in "@*#?-$!0123456789":
            kind, end = "a special parameter", j + 2
        else:
            items.append(("$", in_dquote))   # a lone `$` is literal
            return j + 1
        items.append(Unknown(kind))
        return end

    def _dollar_opener(self, j: int, in_dquote: bool):
        if self.s.startswith("$((", j):
            return self._dollar_arith
        nxt = self.s[j + 1:j + 2]
        if in_dquote and nxt in ("'", '"'):
            return None                         # `$'` inside "..." is literal
        return {
            "(": self._dollar_command,
            "{": self._dollar_param,
            "[": self._dollar_bracket,
            "'": self._dollar_ansi_c,
            '"': self._dollar_locale,
        }.get(nxt)

    def _dollar_arith(self, j: int, items) -> int:
        items.append(Unknown(ARITH))
        return self._scan_arith(j + 3)

    def _dollar_command(self, j: int, items) -> int:
        sub = self._nested(j + 2, ")")
        sub.parse()
        items.append(Unknown(CMD_SUBST))
        return sub.i

    def _dollar_param(self, j: int, items) -> int:
        items.append(Unknown("a parameter expansion"))
        return self._scan_param(j + 2)

    def _dollar_bracket(self, j: int, items) -> int:
        items.append(Unknown(ARITH))
        return self._scan_until_close(j + 2)

    def _dollar_ansi_c(self, j: int, items) -> int:
        return self._read_ansi_c(j + 2, items)

    def _dollar_locale(self, j: int, items) -> int:
        return self._read_dquote(j + 2, items)   # $"..." is a translatable "..."

    def _read_ansi_c(self, j: int, items) -> int:
        """`$'...'` -- decoded, because `$'\\x73rc'` is `src` to the shell."""
        while j < self.n:
            c = self.s[j]
            if c == "'":
                return j + 1
            if c == "\\" and j + 1 < self.n:
                chars, j = self._ansi_escape(j + 1)
            else:
                chars, j = c, j + 1
            items.extend((ch, True) for ch in chars)
        raise ParseError("unterminated $'...' string")

    def _ansi_escape(self, j: int):
        """Decode the escape whose letter is at `j`; return (text, next index)."""
        e = self.s[j]
        if e in _ANSI_SIMPLE:
            return _ANSI_SIMPLE[e], j + 1
        if e in "01234567":
            m = _OCTAL.match(self.s, j)
            return chr(int(m.group(0), 8) & 0xFF), m.end()
        if e in _HEX:
            m = _HEX[e].match(self.s, j + 1)
            if m and int(m.group(0), 16) <= sys.maxunicode:
                return chr(int(m.group(0), 16)), m.end()
        if e == "c" and j + 1 < self.n:
            return chr(ord(self.s[j + 1]) & 0x1F), j + 2
        return "\\" + e, j + 1

    # -- lexing: skipping bodies whose value is unknown -----------------------

    def _skip_unit(self, j: int, scratch) -> int:
        """Advance past one character, or one quoted/substituted unit starting at `j`.

        Used where only the SUBSTITUTIONS inside a body matter ($((...)), ${...}): the
        body's value is unknown anyway, but a `$(...)` inside it still runs.
        """
        c = self.s[j]
        if c == "\\":
            return j + 2
        if c == "'":
            return self._read_squote(j + 1, scratch)
        if c == '"':
            return self._read_dquote(j + 1, scratch)
        if c == "$":
            return self._read_dollar(j, scratch, in_dquote=True)
        if c == "`":
            return self._read_backtick(j + 1, scratch, in_dquote=False)
        return j + 1

    def _scan_arith(self, j: int) -> int:
        """Skip an arithmetic body up to its closing `))`, parsing any substitutions."""
        depth = 0
        scratch = []
        while j < self.n:
            c = self.s[j]
            if c == ")" and depth == 0:
                if self.s.startswith("))", j):
                    return j + 2
                raise ParseError("unbalanced parenthesis in arithmetic")
            depth += {"(": 1, ")": -1}.get(c, 0)
            j = self._skip_unit(j, scratch)
        raise ParseError("unterminated arithmetic")

    def _scan_param(self, j: int) -> int:
        """Skip a `${...}` body, parsing substitutions nested inside it."""
        scratch = []
        while j < self.n:
            if self.s[j] == "}":
                return j + 1
            j = self._skip_unit(j, scratch)
        raise ParseError("unterminated ${...}")

    def _scan_until_close(self, j: int) -> int:
        """Skip an old-style `$[...]` arithmetic body."""
        depth = 1
        while j < self.n:
            depth += {"[": 1, "]": -1}.get(self.s[j], 0)
            j += 1
            if depth == 0:
                return j
        raise ParseError("unterminated $[...]")

    def _read_heredocs(self) -> None:
        """Consume the bodies of heredocs opened on the line that just ended.

        A quoted delimiter (`<<'EOF'`) makes the body literal data. An unquoted one
        expands `$(...)` and backticks inside the body, and those RUN -- so the body is
        scanned for them.
        """
        pending, self.heredocs = self.heredocs, []
        for delim, strip_tabs, quoted in pending:
            body = self._heredoc_body(delim, strip_tabs)
            if not quoted:
                Parser(body, self.sink, self.depth + 1).scan_expansions()

    def _heredoc_body(self, delim: str, strip_tabs: bool) -> str:
        lines = []
        while self.i < self.n:
            nl = self.s.find("\n", self.i)
            line = self.s[self.i:] if nl == -1 else self.s[self.i:nl]
            self.i = self.n if nl == -1 else nl + 1
            if (line.lstrip("\t") if strip_tabs else line) == delim:
                break
            lines.append(line)
        return "\n".join(lines)

    def scan_expansions(self) -> None:
        """Heredoc body: quotes are literal text here; only $ and ` expand."""
        scratch = []
        while self.i < self.n:
            c = self.s[self.i]
            if c == "\\":
                self.i += 2
            elif c == "$":
                self.i = self._read_dollar(self.i, scratch, in_dquote=True)
            elif c == "`":
                self.i = self._read_backtick(self.i + 1, scratch, in_dquote=True)
            else:
                self.i += 1

    # -- parsing ------------------------------------------------------------

    def parse(self) -> None:
        while True:
            kind, val = self.next_token()
            if kind == "eof":
                self._at_eof()
                return
            if self._feed(kind, val):
                return

    def _at_eof(self) -> None:
        if self.closer:
            raise ParseError("unterminated $( ... ) or ( ... )")
        if self.case_stack or self.paren_depth:
            raise ParseError("unterminated compound command")
        if self.heredocs:
            self._read_heredocs()
        self._end_command()

    def _feed(self, kind, val) -> bool:
        """Consume one token. True when this parser's closing `)` has been reached."""
        if self.state == "dbracket":
            self._in_dbracket(kind, val)
        elif self.case_stack and self.case_stack[-1] == "pattern":
            self._in_case_pattern(kind, val)
        elif kind == "redir":
            self._redirect(val)
        elif kind == "arith":
            self._arith_command()
        elif kind == "op":
            return self._operator(val)
        else:
            self._word(val.items)
        return False

    def _in_dbracket(self, kind, val) -> None:
        # Inside [[ ]], `<` and `>` compare strings and `&&`/`(` are logic.
        if kind == "word" and reserved(val.items) == "]]":
            self.state = "after"
        elif kind == "op" and val == "\n":
            raise ParseError("newline inside [[ ]]")

    def _in_case_pattern(self, kind, val) -> None:
        if kind == "word":
            if reserved(val.items) == "esac":
                self.case_stack.pop()
                self.state = "after"
        elif kind == "op" and val == ")":
            self.case_stack[-1] = "body"
            self.state = "start"
        elif kind != "op" or val not in ("(", "|", "\n"):
            raise ParseError("unexpected token in a case pattern")

    def _arith_command(self) -> None:
        if self.state == "start":
            self.state = "after"
        elif self.state != "skip":        # `for ((...))` keeps its header state
            raise ParseError("unexpected (( in the middle of a command")

    def _operator(self, op: str) -> bool:
        if op == ")":
            return self._close_paren()
        if op == "(":
            self._open_paren()
            return False
        self._end_command()
        if op in _CASE_ENDS:
            if not self.case_stack:
                raise ParseError(f"{op} outside a case statement")
            self.case_stack[-1] = "pattern"
        return False

    def _close_paren(self) -> bool:
        if self.paren_depth == 0:
            if self.closer == ")":
                self._end_command()
                return True
            raise ParseError("unbalanced )")
        self.paren_depth -= 1
        self._end_command()
        self.state = "after"
        return False

    def _open_paren(self) -> None:
        if self.state == "start":
            self.paren_depth += 1         # a subshell
            return
        if self.state == "args" and len(self.words) == 1:
            # name ( ) -- a function definition; its body follows.
            if self.next_token() != ("op", ")"):
                raise ParseError("unexpected (")
            self.words = []
            self.state = "start"
            return
        raise ParseError("unexpected (")

    def _word(self, items) -> None:
        state = self.state
        if state == "start":
            self._word_at_start(items)
        elif state == "args":
            self.words.append(items)
        elif state == "casesubj":
            if reserved(items) == "in":
                self.case_stack.append("pattern")
                self.state = "start"
        elif state == "skipone":
            self.state = "start"
        elif state == "after":
            raise ParseError("unexpected word after the end of a compound command")
        # "skip": for/select header words. Their substitutions were parsed when lexed.

    def _word_at_start(self, items) -> None:
        word = reserved(items)
        if self.time_seen and word == "-p":
            self.time_seen = False
            return
        self.time_seen = word == "time"
        if word in _KEEP_START:
            return
        if word == "esac":
            if not self.case_stack:
                raise ParseError("esac outside a case statement")
            self.case_stack.pop()
            self.state = "after"
        elif word in _START_STATES:
            self.state = _START_STATES[word]
        elif not is_assignment(items):
            self.words = [items]
            self.state = "args"

    def _redirect(self, op: str) -> None:
        kind, word = self.next_token()
        if kind != "word":
            raise ParseError(f"redirect {op} has no target")
        if op in ("<<", "<<-"):
            raw = self.s[word.start:word.end]
            quoted = any(ch in raw for ch in "'\"\\")
            delim = re.sub(r"\\(.)", r"\1", raw).replace("'", "").replace('"', "")
            self.heredocs.append((delim, op == "<<-", quoted))
            return
        if op not in WRITE_REDIRECTS:
            return                    # <, <<<, <& read
        if op == ">&" and re.fullmatch(r"\d+-?|-", text_of(word.items) or ""):
            return                    # 2>&1, >&-: duplicates or closes a descriptor
        self.sink.target(word.items, strict=True, what=f"the target of '{op}'")

    def _end_command(self) -> None:
        words, self.words = self.words, []
        self.state = "start"
        if not words:
            return
        argv = []
        for items in words:
            argv.extend(brace_expand(items))
        analyse(argv, self)


# ---------------------------------------------------------------------------
# Option parsing
# ---------------------------------------------------------------------------


class ParsedArgs:
    """A getopt-style reading of one command's arguments."""

    def __init__(self) -> None:
        self.opts = []      # (name, value items or None)
        self.operands = []  # item lists
        self.opaque = []    # unknown words that could be options: `"$X"` may be `-t`

    def has(self, *names) -> bool:
        return any(n in names for n, _ in self.opts)

    def value(self, *names):
        for n, v in reversed(self.opts):
            if n in names and v is not None:
                return v
        return None


def _could_be_option(items) -> bool:
    return bool(items) and (isinstance(items[0], Unknown) or items[0][0] == "-")


def _long_name(given: str, known) -> str:
    """GNU accepts any unambiguous prefix: `--target=src` is `--target-directory=src`."""
    if given in known:
        return given
    matches = [k for k in known if k.startswith(given)] if given else []
    return matches[0] if len(matches) == 1 else given


class _OptReader:
    """GNU getopt_long, including permutation, clusters and unique long-name prefixes.

    short_val    letters taking a value, attached (`-tsrc`) or separated (`-t src`)
    attached_opt letters taking an OPTIONAL value, attached only (`sed -i.bak`)
    long_val     long names taking a value (`--name=v` or `--name v`)
    long_opt     long names taking an optional value (`--name=v` only)
    posix        stop at the first operand (xargs, env, timeout: the rest is a command)
    """

    def __init__(self, args, short_val="", long_val=(), long_opt=(), attached_opt="", posix=False):
        self.args = args
        self.short_val = short_val
        self.long_val = long_val
        self.known_long = tuple(long_val) + tuple(long_opt)
        self.attached_opt = attached_opt
        self.posix = posix
        self.i = 0
        self.ended = False
        self.out = ParsedArgs()

    def read(self) -> ParsedArgs:
        while self.i < len(self.args):
            a = self.args[self.i]
            self.i += 1
            self._one(a)
        return self.out

    def _one(self, a) -> None:
        t = text_of(a)
        if self.ended or is_procsub(a):
            self._operand(a)
        elif t is None:
            self._unknown(a)
        elif t == "--":
            self.ended = True
        elif t.startswith("--"):
            self._long(a, t)
        elif t.startswith("-") and t != "-":
            self._cluster(a, t)
        else:
            self._operand(a)

    def _operand(self, a) -> None:
        self.out.operands.append(a)
        if self.posix:
            self.ended = True

    def _next_value(self):
        value = self.args[self.i] if self.i < len(self.args) else None
        self.i += 1
        return value

    def _unknown(self, a) -> None:
        lit = literal_prefix(a)
        if lit.startswith("--") and "=" in lit:
            raw = lit[2:].split("=", 1)[0]
            self.out.opts.append(("--" + _long_name(raw, self.known_long), a[len(raw) + 3:]))
        elif _could_be_option(a):
            self.out.opaque.append(a)
        else:
            self._operand(a)

    def _long(self, a, t: str) -> None:
        raw, eq, _ = t[2:].partition("=")
        name = _long_name(raw, self.known_long)
        if eq:
            value = a[len(raw) + 3:]
        elif name in self.long_val:
            value = self._next_value()
        else:
            value = None
        self.out.opts.append(("--" + name, value))

    def _cluster(self, a, t: str) -> None:
        for k in range(1, len(t)):
            ch = t[k]
            if ch in self.short_val:
                value = a[k + 1:] if k + 1 < len(t) else self._next_value()
                self.out.opts.append(("-" + ch, value))
                return
            if ch in self.attached_opt:
                self.out.opts.append(("-" + ch, a[k + 1:]))
                return
            self.out.opts.append(("-" + ch, None))


def parse_opts(args, **spec) -> ParsedArgs:
    return _OptReader(args, **spec).read()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def command_name(items):
    """The basename that selects the program, or None if it is decided at run time.

    `"$ROOT/bin/workflow"` still names `workflow`: only the segment after the last
    slash picks the program, and here that segment is literal.
    """
    last_slash = -1
    for k, it in enumerate(items):
        if not isinstance(it, Unknown) and it[0] == "/":
            last_slash = k
    tail = items[last_slash + 1:]
    t = text_of(tail)
    if t is None or has_glob(tail) or (last_slash == -1 and text_of(items) is None):
        return None
    return t


def analyse(argv, parser: Parser) -> None:
    if not argv:
        return
    name = command_name(argv[0])
    if name is None:
        kind = unknown_kind(argv[0]) or "a glob"
        parser.sink.refuse(f"the command name contains {kind}, so which program runs is not known")
        return
    handler = HANDLERS.get(name)
    if handler is not None:
        handler(name, argv[1:], parser)


def _refuse_opaque(name, o: ParsedArgs, sink: Sink) -> bool:
    if o.opaque:
        sink.refuse(f"an argument to {name} {NOT_KNOWN}, and could be an option or a path")
        return True
    return False


def _targets(name, operands, sink, strict):
    for items in operands:
        sink.target(items, strict, f"an operand of {name}")


# Creating mutators: each operand is a file the command brings into existence, so it is
# judged strictly -- a new repo-root name counts, exactly as a Write file_path does.
_CREATE_SPECS = {
    "touch": dict(short_val="drtA", long_val=("date", "reference", "time")),
    "tee": dict(long_opt=("output-error",)),
    "truncate": dict(short_val="sr", long_val=("size", "reference")),
}


def h_create(name, args, parser):
    o = parse_opts(args, **_CREATE_SPECS[name])
    if not _refuse_opaque(name, o, parser.sink):
        _targets(name, o.operands, parser.sink, strict=True)


# Non-creating mutators: they act on something that must already exist, so a bare word
# like `srcfoo` is not refused as a new root file. Every operand is acted on -- for
# chmod/chown that includes the mode/owner word, which is harmless to classify and
# avoids guessing whether `-w` was a mode or a flag.
_ACT_SPECS = {
    "rm": dict(long_opt=("interactive",)),
    "rmdir": {},
    "unlink": {},
    "shred": dict(short_val="ns", long_val=("iterations", "size", "random-source")),
    "chmod": dict(long_val=("reference",)),
    "chown": dict(long_val=("reference", "from")),
    "chgrp": dict(long_val=("reference",)),
}


def h_act(name, args, parser):
    o = parse_opts(args, **_ACT_SPECS[name])
    if not _refuse_opaque(name, o, parser.sink):
        _targets(name, o.operands, parser.sink, strict=False)


_TDIR = ("-t", "--target-directory")


def h_mv(name, args, parser):
    # mv REMOVES its sources, so every operand is a target, not only the destination.
    o = parse_opts(args, short_val="St", long_val=("suffix", "target-directory"), long_opt=("backup",))
    if _refuse_opaque(name, o, parser.sink):
        return
    tdir = o.value(*_TDIR)
    if tdir is not None:
        parser.sink.target(tdir, True, "the target directory of mv")
    _targets(name, o.operands, parser.sink, strict=False)


def _dest(name, o: ParsedArgs, sink: Sink) -> None:
    """cp/install/ln -s: -t names the destination, else the last operand does."""
    tdir = o.value(*_TDIR)
    if tdir is not None:
        sink.target(tdir, True, f"the target directory of {name}")
    elif len(o.operands) >= 2:
        sink.target(o.operands[-1], True, f"the destination of {name}")


def h_cp(name, args, parser):
    o = parse_opts(args, short_val="St",
                   long_val=("suffix", "target-directory", "sparse", "no-preserve"),
                   long_opt=("backup", "reflink", "preserve", "context"))
    if not _refuse_opaque(name, o, parser.sink):
        _dest(name, o, parser.sink)


def h_install(name, args, parser):
    # Union of GNU and BSD value-taking letters. Over-reading a flag as taking a value
    # can only move a word from "operand" to "value"; the -t/last-operand rule still
    # finds the destination.
    o = parse_opts(args, short_val="gmoStBfhlNT",
                   long_val=("mode", "owner", "group", "suffix", "target-directory", "strip-program"),
                   long_opt=("backup", "context"))
    if _refuse_opaque(name, o, parser.sink):
        return
    if o.has("-d", "--directory"):
        _targets(name, o.operands, parser.sink, strict=True)   # creates each directory
    else:
        _dest(name, o, parser.sink)


def h_ln(name, args, parser):
    o = parse_opts(args, short_val="St", long_val=("suffix", "target-directory"), long_opt=("backup",))
    sink = parser.sink
    if _refuse_opaque(name, o, sink):
        return
    if len(o.operands) == 1 and o.value(*_TDIR) is None:
        # `ln SRC` creates ./basename(SRC).
        t = text_of(o.operands[0])
        if t is None:
            sink.refuse(f"the single operand of ln {NOT_KNOWN}")
            return
        sink.emit(True, t.rstrip("/").rsplit("/", 1)[-1] or t)
    if o.has("-s", "--symbolic"):
        # A symlink writes only the link; a later write THROUGH it is caught by
        # classify_path's resolver. So only the destination is a target.
        _dest(name, o, sink)
        return
    # A HARD link is a second name for the same inode: the source is as much a target
    # as the destination, since writing either name edits the tracked file.
    tdir = o.value(*_TDIR)
    if tdir is not None:
        sink.target(tdir, True, "the target directory of ln")
    _targets(name, o.operands, sink, strict=False)


def h_sed(name, args, parser):
    o = parse_opts(args, short_val="efl", attached_opt="i",
                   long_val=("expression", "file", "line-length"), long_opt=("in-place",))
    if not o.has("-i", "--in-place") and not o.opaque:
        return                          # sed without -i reads and prints
    files = list(o.operands)
    if not o.opaque and not o.has("-e", "-f", "--expression", "--file") and files:
        first = text_of(files[0])
        if o.value("-i") == [] and len(files) >= 2 and (first == "" or (first or "").startswith(".")):
            files = files[1:]           # BSD `sed -i '' ...` / `-i .bak`: the suffix
        files = files[1:]               # the script
    # With an opaque word, it may be `-i` and it may be the script; judge every operand.
    _targets(name, files, parser.sink, strict=False)


def h_dd(name, args, parser):
    sink = parser.sink
    for items in args:
        t = text_of(items[:3])
        if t == "of=":
            sink.target(tilde_expand(items[3:]), True, "dd's of= operand")
        elif t is None:
            sink.refuse(f"an operand of dd {NOT_KNOWN}, and could be of=")


def h_patch(name, args, parser):
    o = parse_opts(args, short_val="BdDFgioprVYz",
                   long_val=("directory", "input", "output", "strip", "reject-file",
                             "prefix", "basename-prefix", "suffix", "fuzz", "ifdef"),
                   long_opt=("backup-if-mismatch",))
    sink = parser.sink
    if o.has("--dry-run"):
        return
    out = o.value("-o", "--output")
    if out is None:
        sink.refuse("patch writes the files named INSIDE the diff, which the command line does not show")
        return
    sink.target(out, True, "patch's output file")
    rej = o.value("-r", "--reject-file")
    if rej is not None:
        sink.target(rej, True, "patch's reject file")


# -- wrappers: the program they run is the command that matters -------------------


def _run_rest(rest, parser, wrapper):
    if not rest:
        return
    if command_name(rest[0]) is None:
        parser.sink.refuse(f"the command run by {wrapper} {NOT_KNOWN}")
        return
    analyse(rest, parser)


def _wrapped(args, parser, wrapper, **spec):
    o = parse_opts(args, posix=True, **spec)
    if o.opaque:
        parser.sink.refuse(f"an argument to {wrapper} {NOT_KNOWN}")
        return None
    return o


def h_env(name, args, parser):
    o = _wrapped(args, parser, name, short_val="uCSP", long_val=("unset", "chdir", "split-string"))
    if o is None:
        return
    if o.has("-S", "--split-string"):
        parser.sink.refuse("env -S splits a string into a command line")
        return
    rest = o.operands
    while rest and is_assignment(rest[0]):
        rest = rest[1:]
    _run_rest(rest, parser, name)


_SIMPLE_WRAPPERS = {
    "nohup": {},
    "builtin": {},
    "exec": dict(short_val="a"),
    "nice": dict(short_val="n", long_val=("adjustment",)),
    "stdbuf": dict(short_val="ioe", long_val=("input", "output", "error")),
    "command": {},
}


def h_simple_wrapper(name, args, parser):
    o = _wrapped(args, parser, name, **_SIMPLE_WRAPPERS[name])
    if o is None:
        return
    if name == "command" and o.has("-v", "-V"):
        return                          # lookup only
    _run_rest(o.operands, parser, name)


def h_timeout(name, args, parser):
    o = _wrapped(args, parser, name, short_val="sk", long_val=("signal", "kill-after"))
    if o is not None:
        _run_rest(o.operands[1:], parser, name)   # first operand is the duration


def h_time(name, args, parser):
    o = _wrapped(args, parser, name, short_val="of", long_val=("output", "format"))
    if o is None:
        return
    out = o.value("-o", "--output")
    if out is not None:
        parser.sink.target(out, True, "the output file of time")
    _run_rest(o.operands, parser, name)


def h_sudo(name, args, parser):
    o = _wrapped(args, parser, name, short_val="ugCDhprtTUc",
                 long_val=("user", "group", "chdir", "host", "prompt", "role", "type", "other-user"))
    if o is None:
        return
    if o.has("-e", "--edit") or name == "sudoedit":
        _targets(name, o.operands, parser.sink, strict=True)
        return
    _run_rest(o.operands, parser, name)


def h_xargs(name, args, parser):
    o = _wrapped(args, parser, name, short_val="IELnPsda", attached_opt="eil",
                 long_val=("arg-file", "delimiter", "max-args", "max-procs", "max-chars",
                           "process-slot-var"),
                 long_opt=("eof", "replace", "max-lines"))
    if o is None:
        return
    rest = list(o.operands) or [[(c, False) for c in "echo"]]
    repl = o.value("-I", "--replace")
    if repl is None and o.has("-i", "--replace"):
        repl = o.value("-i") or [(c, False) for c in "{}"]
    stdin_word = [Unknown("an argument xargs reads from stdin")]
    if repl is None:
        rest = rest + [stdin_word]
    else:
        r = text_of(repl) or "{}"
        rest = [rest[0]] + [stdin_word if r in (text_of(w) or "") else w for w in rest[1:]]
    _run_rest(rest, parser, name)


_FIND_EXPR_START = ("(", "!", ")", ",")
_FIND_OUTPUTS = ("-fprint", "-fprint0", "-fls", "-fprintf")
_FIND_EXECS = ("-exec", "-execdir", "-ok", "-okdir")


def h_find(name, args, parser):
    i = 0
    while i < len(args) and text_of(args[i]) in ("-H", "-L", "-P"):
        i += 1
    roots, i = _find_roots(args, i, parser.sink)
    if roots is not None:
        _find_expression(args, i, roots or [[(".", False)]], parser)


def _find_roots(args, i, sink):
    roots = []
    while i < len(args):
        a = args[i]
        t = text_of(a)
        if t is not None and (t.startswith("-") or t in _FIND_EXPR_START):
            break
        if t is None and _could_be_option(a):
            sink.refuse(f"a find argument {NOT_KNOWN}, and could be an action")
            return None, i
        roots.append(a)
        i += 1
    return roots, i


def _find_expression(args, i, roots, parser):
    while i < len(args):
        t = text_of(args[i])
        i += 1
        if t is None:
            parser.sink.refuse(f"a find expression word {NOT_KNOWN}, and could be -delete or -exec")
            return
        if t == "-delete":
            _targets("find -delete", roots, parser.sink, strict=False)
        elif t in _FIND_OUTPUTS:
            if i < len(args):
                parser.sink.target(args[i], True, f"the output file of find {t}")
            i += 2 if t == "-fprintf" else 1
        elif t in _FIND_EXECS:
            i = _find_exec(args, i, t, roots, parser)


def _find_exec(args, i, action, roots, parser) -> int:
    sub = []
    while i < len(args) and text_of(args[i]) not in (";", "+"):
        sub.append(args[i])
        i += 1
    # `{}` ranges over files under the roots: judge each root in its place.
    for root in roots:
        _run_rest([_find_placeholder(w, root) for w in sub], parser, "find " + action)
    return i + 1


def _find_placeholder(word, root):
    t = text_of(word)
    if t == "{}":
        return root
    if t is not None and "{}" in t:
        return [Unknown("a find {} substitution")]
    return word


def h_eval(name, args, parser):
    texts = [text_of(a) for a in args]
    if any(t is None for t in texts):
        parser.sink.refuse(f"eval runs a string that {NOT_KNOWN}")
        return
    parser.parse_string(" ".join(texts))


def h_trap(name, args, parser):
    o = parse_opts(args)
    if not o.operands:
        return
    code = text_of(o.operands[0])
    if code is None:
        parser.sink.refuse(f"trap installs a handler that {NOT_KNOWN}")
    elif code != "-":
        parser.parse_string(code)


def _drop_plus_options(args):
    """`+o NAME` / `+O NAME` unset shell options. Not starting with `-`, they would
    otherwise read as the script operand and hide a later `-c`."""
    kept = []
    i = 0
    while i < len(args):
        t = text_of(args[i]) or ""
        if t.startswith("+") and len(t) > 1:
            i += 2 if t in ("+o", "+O") else 1
            continue
        kept.append(args[i])
        i += 1
    return kept


def h_shell(name, args, parser):
    """`bash -c 'STRING'` is shell code in a string: parse the string."""
    o = _wrapped(_drop_plus_options(args), parser, name,
                 short_val="oO", long_val=("rcfile", "init-file"))
    if o is None:
        return
    if not o.has("-c"):
        if o.has("-s") or not o.operands:
            parser.sink.refuse(f"{name} with no script reads its program from stdin, "
                               "which cannot be inspected here")
        # `bash script.sh` runs a file: command semantics, out of reach (module doc).
        return
    if not o.operands:
        return
    code = text_of(o.operands[0])
    if code is None:
        parser.sink.refuse(f"{name} -c runs a string that {NOT_KNOWN}")
    else:
        parser.parse_string(code)


HANDLERS = {}
for _n in _CREATE_SPECS:
    HANDLERS[_n] = h_create
for _n in _ACT_SPECS:
    HANDLERS[_n] = h_act
for _n in _SIMPLE_WRAPPERS:
    HANDLERS[_n] = h_simple_wrapper
HANDLERS.update({
    "mv": h_mv, "cp": h_cp, "install": h_install, "ln": h_ln, "sed": h_sed, "gsed": h_sed,
    "dd": h_dd, "patch": h_patch,
    "env": h_env, "timeout": h_timeout, "gtimeout": h_timeout, "time": h_time,
    "sudo": h_sudo, "sudoedit": h_sudo, "doas": h_sudo, "xargs": h_xargs, "find": h_find,
    "eval": h_eval, "trap": h_trap,
    "sh": h_shell, "bash": h_shell, "zsh": h_shell, "dash": h_shell, "ksh": h_shell,
})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def analyse_command(command: str, repo_root: str) -> Sink:
    sink = Sink(repo_root)
    try:
        Parser(command, sink).parse()
    except ParseError as exc:
        sink.refuse(f"the command could not be parsed ({exc})")
    except RecursionError:
        sink.refuse("the command is nested too deeply to parse")
    return sink


def _records(raw: bytes, repo_root: str):
    payload = json.loads(raw.decode("utf-8", "surrogateescape"))
    command = payload["tool_input"]["command"]
    if not isinstance(command, str):
        return ["U.tool_input.command is not a string"]
    sink = analyse_command(command, repo_root)
    return ["U" + u for u in sink.unknowns] + sink.records


def main(argv) -> int:
    repo_root = argv[1] if len(argv) > 1 else ""
    try:
        records = _records(sys.stdin.buffer.read(), repo_root)
    except Exception as exc:  # nosec B110 - reported as a U record: the hook blocks on it
        records = [f"Uthe command analyser failed ({type(exc).__name__}: {exc})"]
    out = sys.stdout.buffer
    for rec in records + ["OK"]:
        out.write(rec.encode("utf-8", "surrogateescape") + b"\0")
    out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
