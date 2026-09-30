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


def tokenize(command: str) -> list[str]:
    """Words and control operators of ``command``; ValueError if it will not tokenise."""
    lexer = shlex.shlex(command.replace("\\\n", ""), posix=True, punctuation_chars="();<>|&\n")
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
    out: list[list[tuple[int, str]]] = [[]]
    for idx, tok in enumerate(tokens):
        if is_separator(tok):
            out.append([])
        else:
            out[-1].append((idx, tok))
    return [c for c in out if c]


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


def _gh(words: list[str], pr_indices: set[int], gidx: list[int]) -> tuple[str, str | None] | None:
    j = _skip_options(words, 1)
    if j < len(words) and words[j] == "pr":
        pr_at = j
        j = _skip_options(words, j + 1, frozenset({"-R", "--repo"}))
        if j < len(words) and words[j] in ("create", "new"):
            pr_indices.add(gidx[pr_at])
            return "gh pr create", _flag_value(words[j + 1:], "--head", "-H")
        return None
    if j < len(words) and words[j] == "api":
        return _gh_api(words[j + 1:])
    return None


# gh api's body-field flags: --raw-field/-f and --field/-F.
_FIELD_FLAGS = (("--raw-field", "-f"), ("--field", "-F"))


def _gh_api(rest: list[str]) -> tuple[str, str | None] | None:
    if any("createpullrequest" in w.lower() for w in rest):
        raise Unverifiable("gh api graphql createPullRequest cannot be matched to a commit")
    if not any(_PULLS_ENDPOINT.search(w) for w in rest):
        return None
    fields = [v for long, short in _FIELD_FLAGS for v in _flag_values(rest, long, short)]
    method = _flag_value(rest, "--method", "-X")
    # gh api defaults to POST once a body is given (a field or --input).
    implied_post = method is None and (fields or _flag_values(rest, "--input", None))
    if (method or "").upper() != "POST" and not implied_post:
        return None
    heads = {f[len("head="):] for f in fields if f.startswith("head=")}
    if len(heads) != 1:
        raise Unverifiable("gh api POST .../pulls without exactly one literal head= field")
    return "gh api POST pulls", heads.pop()


def _github(words: list[str], pr_indices: set[int], gidx: list[int]) -> tuple[str, str | None] | None:
    j = _skip_options(words, 1)
    if j < len(words) and words[j] == "pr":
        pr_at = j
        j = _skip_options(words, j + 1)
        if j < len(words) and words[j] == "create":
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
    if len(words) > 1 and words[1] == "pull-request":
        return "hub pull-request", _flag_value(words[2:], "--head", "-h")
    return None


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


def _shell_script(words: list[str]) -> str | None:
    """The script of ``bash -c '<script>'`` (options may be clustered: ``-lc``)."""
    saw_c = False
    for w in words[1:]:
        if w.startswith("-") and not w.startswith("--"):
            saw_c = saw_c or "c" in w[1:]
            continue
        if w.startswith("--"):
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
    for cmd in split_commands(tokens):
        gidx = [i for i, _ in cmd]
        raw = [t for _, t in cmd]
        words = [_word(t) for t in raw]
        head_words = _strip_prefix(words)
        if head_words and _prog(head_words[0]) in ("cd", "pushd"):
            cwd = _cd_target(head_words, cwd)
            continue
        for i in range(len(words)):
            targets.extend(_targets_at(words, i, gidx, cwd, pr_indices, depth))
    _check_dynamic(tokens, pr_indices)
    return targets


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
    return common.joinpath(*RECORD_SUBDIR, f"{sha}.json")


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
