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
``shlex`` in POSIX mode with the shell's control operators as punctuation, so the
stream splits into simple commands on ``&& || ; | & ( )`` and newlines. Every word in
a simple command -- not only the first -- is tried as a program name, by basename and
case-insensitively (macOS resolves ``GH`` to ``gh``). That covers ``VAR=1 gh``,
``env gh``, ``command gh``, ``builtin gh``, and wrappers such as ``timeout 5 gh``,
``xargs gh``, ``nohup gh`` or ``sudo gh`` with one rule, at the price of a false
positive when ``gh pr create`` appears as bare unquoted arguments to something else.
A quoted string (``echo "gh pr create"``) is one word and is not a program.

``bash|sh|zsh|dash|ksh -c '<script>'`` and ``eval <words>`` are re-parsed.

FAIL CLOSED
-----------
* unbalanced quotes (shlex cannot tokenise) and the text mentions pr + create;
* a ``$`` or backtick anywhere, plus a ``pr ... create|new`` word pair that no known
  entry point accounted for (``$GH pr create``, ``$(echo gh) pr create``);
* a ``--head`` / ``cd`` target known only at run time, a ``--head`` that does not
  resolve to a local commit, a checkout git cannot read, a GraphQL createPullRequest.

KNOWN GAPS (listed in the hook header too)
------------------------------------------
Command semantics this cannot see: a script file or Makefile target that runs
``gh pr create``; ``python3 -c`` / any program calling the GitHub API itself;
``curl`` to api.github.com; user-defined ``gh alias`` names; ``git`` aliases.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import stat
import subprocess  # nosec B404 - fixed git argv lists, never a shell
import sys
from dataclasses import dataclass
from pathlib import Path

RECORD_SUBDIR = ("dancing-bear", "concern-sweeps")
MODES = ("swept", "waived")
MAX_DEPTH = 8

_SEPARATOR_CHARS = frozenset("();|&\n")
_SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
_GITHUB_CLI = frozenset({"github", "github_assistant", "github_assistant.cli"})
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_PULLS_ENDPOINT = re.compile(r"(?:^|/)repos/[^/\s]+/[^/\s]+/pulls/?$")
_GIT_ENV_OVERRIDES = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM",
)
_UNKNOWN_CWD = None


class Unverifiable(Exception):
    """A fact that decides the verdict is not knowable before the shell runs."""


@dataclass
class Target:
    """One PR-create found in the command."""

    entry: str            # e.g. "gh pr create"
    cwd: Path | None      # the directory it runs in; None = unknown
    head: str | None      # branch named by --head, else None for HEAD


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

    shlex has no ANSI-C quoting, so ``gh $'\\x70'r create`` would otherwise tokenise
    as ``$\\x70r`` while bash runs ``gh pr create``. Only a ``$`` outside quotes starts
    one, matching bash.
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


def tokenize(command: str) -> list[str]:
    """Words and control operators of ``command``; ValueError if it will not tokenise."""
    lexer = shlex.shlex(expand_ansi_c(command.replace("\\\n", "")), posix=True, punctuation_chars="();<>|&\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    # No comment handling: shlex would end a word at `#` where bash does not
    # (`x#; gh pr create` runs gh), which hides commands. A real comment that
    # mentions gh pr create is a false positive instead -- the safe direction.
    lexer.commenters = ""
    return list(lexer)


def is_separator(token: str) -> bool:
    return bool(token) and set(token) <= _SEPARATOR_CHARS


def split_commands(tokens: list[str]) -> list[list[tuple[int, str]]]:
    """Simple commands as lists of (global index, word)."""
    return [cmd for cmd, _ in split_with_operators(tokens) if cmd]


def split_with_operators(tokens: list[str]) -> list[tuple[list[tuple[int, str]], str]]:
    """(simple command, the separator token that ends it); the last ends with "".

    A command may be empty when separators are adjacent (`(cd x)`, `a; (b)`), so
    the parentheses still reach the caller even with no words between them.
    """
    out: list[tuple[list[tuple[int, str]], str]] = []
    cur: list[tuple[int, str]] = []
    for idx, tok in enumerate(tokens):
        if is_separator(tok):
            out.append((cur, tok))
            cur = []
        else:
            cur.append((idx, tok))
    out.append((cur, ""))
    return out


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

#: Shell keywords that close a compound command and decrement the nesting depth.
_NEST_CLOSERS = frozenset({"fi", "done", "esac"})

#: Short options (the single letter after ``-`` or ``+``) that take the next word
#: as a value and must be skipped when scanning bash/sh for a ``-c`` script.
#: ``-O``/``+O`` set/unset a shell option (bash), ``-o`` sets an option (most shells).
_SHELL_VALUED_SHORT_OPTS = frozenset({"O", "o"})


def _strip_reserved(words: list[str]) -> list[str]:
    k = 0
    while k < len(words) and words[k] in _RESERVED:
        k += 1
    return words[k:]


def _apply_parens(op: str, cwd: Path | None, stack: list[Path | None]) -> Path | None:
    """`(` starts a subshell that inherits cwd; `)` ends it and restores the outer one."""
    for ch in op:
        if ch == "(":
            stack.append(cwd)
        elif ch == ")":
            cwd = stack.pop() if stack else _UNKNOWN_CWD
    return cwd


def _word(tok: str) -> str:
    """A word with command-substitution backticks at its edges removed."""
    return tok.strip("`")


def _prog(tok: str) -> str:
    return os.path.basename(_word(tok)).lower()


def _dynamic(tok: str) -> bool:
    return "$" in tok or "`" in tok


def _literal(value: str, what: str) -> str:
    if _dynamic(value):
        raise Unverifiable(f"{what} is not known until the shell runs")
    return value


# Characters that make bash build a word at run time: parameter and command
# substitution, brace expansion, globbing. shlex has already removed quotes and
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


def _flag_values(words: list[str], long: str, short: str | None, *, abbrev: bool = False) -> list[str]:
    """Every value given to ``long`` (``--head X``, ``--head=X``) or ``short`` (``-H X``, ``-HX``)."""
    values: list[str] = []
    k = 0
    while k < len(words):
        value, used = _option_at(words, k, long, short, abbrev)
        if value is not None:
            values.append(value)
        k += used
    return values


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


def _gh(words: list[str], pr_indices: set[int], gidx: list[int]) -> tuple[str, str | None] | None:
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
        return _gh_api(words[j + 1:])
    return None


# gh api's body-field flags: --raw-field/-f and --field/-F.
_FIELD_FLAGS = (("--raw-field", "-f"), ("--field", "-F"))


def _posts(rest: list[str]) -> bool:
    """True when this gh api call is a POST, explicitly or implied by a body."""
    fields = [v for long, short in _FIELD_FLAGS for v in _flag_values(rest, long, short)]
    method = _flag_value(rest, "--method", "-X")
    # gh api defaults to POST once a body is given (a field or --input).
    implied_post = method is None and bool(fields or _flag_values(rest, "--input", None))
    return (method or "").upper() == "POST" or implied_post


def _gh_api(rest: list[str]) -> tuple[str, str | None] | None:
    if any("createpullrequest" in w.lower() for w in rest):
        raise Unverifiable("gh api graphql createPullRequest cannot be matched to a commit")
    if not any(_PULLS_ENDPOINT.search(w) for w in rest):
        # An endpoint built at run time (repos/o/r/$E) could be .../pulls.
        endpoint = next((w for w in rest if not w.startswith("-") and "/" in w), None)
        if endpoint is not None and _EXPANDS & set(endpoint) and _posts(rest):
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
# Walking the command
# ---------------------------------------------------------------------------


def _cd_target(words: list[str], cwd: Path | None) -> Path | None:
    args = [w for w in words[1:] if not w.startswith("-") or w == "-"]
    if not args:
        return Path.home()
    arg = args[0]
    if _dynamic(arg) or arg == "-" or (arg.startswith("~") and not (arg == "~" or arg.startswith("~/"))):
        return _UNKNOWN_CWD
    target = Path(os.path.expanduser(arg))
    if target.is_absolute():
        return target
    return cwd / target if cwd is not None else _UNKNOWN_CWD


def _strip_prefix(words: list[str]) -> list[str]:
    """Drop leading VAR=value assignments and env / command / builtin."""
    k = 0
    while k < len(words):
        w = words[k]
        if re.fullmatch(r"[A-Za-z_]\w*\+?=.*", w, re.DOTALL) or w in ("env", "command", "builtin"):
            k += 1
        else:
            break
    return words[k:]


def _shell_option(w: str) -> tuple[bool, bool]:
    """(saw_c_flag, consumes_next_word) for a single shell option token.

    ``saw_c_flag`` is True when the token sets the ``-c`` flag (activates script mode).
    ``consumes_next_word`` is True when the token takes the following word as its value
    (e.g. ``-O extglob``), so that word must be skipped rather than treated as the script.
    """
    if w.startswith("--"):
        return False, False
    if not (w.startswith("-") or w.startswith("+")):
        return False, False
    has_c = "c" in w[1:] and w[0] == "-"
    valued = len(w) == 2 and w[1] in _SHELL_VALUED_SHORT_OPTS
    return has_c, valued


def _shell_script(words: list[str]) -> str | None:
    """The script of ``bash -c '<script>'`` (options may be clustered: ``-lc``).

    Options that consume a value (e.g. ``-O extglob``, ``+O extglob``) are skipped
    along with their argument so the scanner is not tricked into treating the option
    value as the script. ``bash -O extglob -c 'gh pr create'`` must find the script,
    not return None at ``extglob``.
    """
    saw_c = False
    it = iter(words[1:])
    for w in it:
        if w.startswith("--"):
            continue
        if w[0:1] in ("-", "+"):
            has_c, valued = _shell_option(w)
            saw_c = saw_c or has_c
            if valued:
                next(it, None)  # skip the option's value word
            continue
        return w if saw_c else None
    return None


def find_targets(command: str, cwd: Path | None, depth: int = 0) -> list[Target]:
    if depth > MAX_DEPTH:
        raise Unverifiable("commands nested too deeply to check")
    try:
        tokens = tokenize(command)
    except ValueError:
        low = command.lower()
        if ("pr" in low and "create" in low) or "pull-request" in low or "createpullrequest" in low:
            raise Unverifiable("the command cannot be tokenised (unbalanced quote?)") from None
        return []
    targets: list[Target] = []
    pr_indices: set[int] = set()
    stack: list[Path | None] = []
    nest = 0  # compound-command nesting depth (if/while/until/for/case/select → fi/done/esac)
    prev_op = ""  # separator that ended the previous simple command
    for cmd, op in split_with_operators(tokens):
        # Update nesting based on the first (un-stripped) word of this simple command.
        # We do this BEFORE processing so that a ``cd`` in ``if cd /x; then ...``
        # is already at depth 1 and therefore fails closed (the coordinator called
        # this acceptable).
        if cmd:
            first = _word(cmd[0][1]).lower()
            if first in _NEST_OPENERS:
                nest += 1
            elif first in _NEST_CLOSERS:
                nest = max(0, nest - 1)
        # The separator follows its command: `cd x)` moves, then `)` restores.
        if cmd:
            cwd = _walk_command(cmd, op, cwd, targets, pr_indices, depth, nest, prev_op)
        cwd = _apply_parens(op, cwd, stack)
        prev_op = op
    _check_dynamic(tokens, pr_indices)
    return targets


def _walk_command(
    cmd: list[tuple[int, str]], op: str, cwd: Path | None,
    targets: list[Target], pr_indices: set[int], depth: int,
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
    gidx = [i for i, _ in cmd]
    words = [_word(t) for _, t in cmd]
    stripped = _strip_reserved(words)
    head_words = _strip_prefix(stripped)
    prog = _prog(head_words[0]) if head_words else ""
    if prog == "popd":
        return _UNKNOWN_CWD
    if prog in ("cd", "pushd"):
        applies = _cd_applies(op)
        if applies is None:
            return _UNKNOWN_CWD
        # Fail closed when the cd/pushd is inside a compound command (if/while/for/…)
        # or its preceding operator is && or || (it only runs when a prior command
        # succeeded or failed, which we cannot evaluate statically).
        if nest > 0 or "&&" in prev_op or "||" in prev_op:
            return _UNKNOWN_CWD
        return _cd_target(head_words, cwd) if applies else cwd
    for i in range(len(words)):
        targets.extend(_targets_at(words, i, gidx, cwd, pr_indices, depth))
    return cwd


def _targets_at(
    words: list[str], i: int, gidx: list[int], cwd: Path | None, pr_indices: set[int], depth: int,
) -> list[Target]:
    prog = _prog(words[i])
    tail = words[i:]
    found: tuple[str, str | None] | None = None
    if prog == "gh":
        found = _gh(tail, pr_indices, gidx[i:])
    elif prog in _GITHUB_CLI:
        found = _github(tail, pr_indices, gidx[i:])
    elif prog == "pr-assistant":
        found = _pr_assistant(tail)
    elif prog == "hub":
        found = _hub(tail)
    elif prog in _SHELLS:
        script = _shell_script(tail)
        return find_targets(script, cwd, depth + 1) if script is not None else []
    elif prog == "eval" and i + 1 < len(words):
        return find_targets(" ".join(words[i + 1:]), cwd, depth + 1)
    if found is None:
        return []
    return [Target(entry=found[0], cwd=cwd, head=found[1])]


def _check_dynamic(tokens: list[str], pr_indices: set[int]) -> None:
    """Refuse `pr ... create|new` that no entry point accounted for, if anything is dynamic."""
    if not any(_dynamic(t) for t in tokens):
        return
    words = [_word(t) for t in tokens]
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
        return _block(f"this command may open a PR and cannot be checked: {exc}.\n{_advice(None)}")
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
