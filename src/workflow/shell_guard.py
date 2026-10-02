"""Bash guard parity: which shell constructs the destructive-bash guard refuses.

The ``shell-guard-refused`` rule in ``linter_shell`` asks one question of each
parsed script -- :func:`refused_construct` -- and this module answers it the
way the guard does. It mirrors ``.claude/hooks/_bash_write_targets.py`` (the
write-target scan: shell option parsing, stdin shells, ``sh -c`` strings,
``find -exec`` bodies, and which commands write) and the nested-shell check in
``block-destructive-bash.sh`` (``eval``, ``sh -c`` clusters, ``xargs`` into a
shell). The hooks are the source of truth; each helper names the guard
function it follows.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from .shell_lex import MAX_DEPTH, ShellToken
from .shell_parse import (
    ShellScript,
    SimpleCommand,
    command_from_words,
    parse_shell,
)

__all__ = ["refused_construct"]

# Commands the real destructive-bash guard treats as write targets (see the
# "Written" table in .claude/hooks/README.md), matched by basename as the
# guard resolves them. A loop whose body calls none of these, and contains no
# output redirection, is read-only and the guard allows it outright
# (guard-contract.yaml: "for f in src/*.py; do wc -l "$f"; done"). `sed` and
# `patch` are handled separately in _is_mutating because the guard's own
# contract for them is conditional on their flags, not on the bare command
# name -- see the "Written" table's `sed` and `patch` rows.
_MUTATING_COMMANDS = frozenset({
    "rm", "rmdir", "unlink", "shred", "chmod", "chown", "chgrp", "mv", "cp",
    "ln", "install", "touch", "tee", "truncate", "dd", "mkdir",
})
# The guard refuses `patch` unless one of these is present (it writes the
# files named *inside the diff*, so the guard cannot resolve a write target
# without one of these).
_PATCH_SAFE_FLAGS = ("--dry-run", "-o")
# Shells whose ``-c`` string both guards treat as code: h_shell in
# .claude/hooks/_bash_write_targets.py, and the nested-shell check in
# block-destructive-bash.sh (which adds fish).
_SHELLS = frozenset({"sh", "bash", "zsh", "ksh", "dash", "fish"})
# The shells h_shell handles (its HANDLERS entries): fish is not one, so the
# guard never refuses a fish reading stdin.
_STDIN_CHECKED_SHELLS = _SHELLS - {"fish"}
# h_shell's option spec: short letters and long names that take a value.
_SHELL_SHORT_VALUE = "oO"
_SHELL_LONG_VALUE = ("rcfile", "init-file")
# block-destructive-bash.sh's nested-shell regex: after the shell name, any
# run of letter-only clusters, then one ending in ``c``.
_LETTER_CLUSTER_RE = re.compile(r"-[a-zA-Z]*")
_NESTED_C_CLUSTER_RE = re.compile(r"-[a-zA-Z]*c")
# h_find's actions (_bash_write_targets.py _FIND_OUTPUTS and _FIND_EXECS):
# -delete acts on the roots, -fprint* write a file, -exec* run a command.
_FIND_WRITE_ACTIONS = frozenset({"-delete", "-fprint", "-fprint0", "-fls", "-fprintf"})
_FIND_EXEC_ACTIONS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
_FIND_EXEC_ENDS = frozenset({";", "+"})


def _has_sed_in_place(args: list[str]) -> bool:
    """True when a ``sed`` command's own *args* carry ``-i``/``--in-place``.

    The guard's "Written" table blocks `sed` operands only with `-i`/`--in-place`
    present -- a plain `sed -n ...` is a read. `-i` can appear bare, clustered
    with other short flags (`-ie`), or with an attached suffix (`-i.bak`).
    """
    for tok in args:
        if tok == "--in-place" or tok.startswith("--in-place="):
            return True
        if tok.startswith("-") and not tok.startswith("--") and "i" in tok[1:]:
            return True
    return False


def _patch_mutates(cmd: SimpleCommand) -> bool:
    """`patch` writes the files named inside the diff unless `--dry-run` or `-o FILE`."""
    return not any(arg.startswith(_PATCH_SAFE_FLAGS) for arg in cmd.args)


@dataclass(frozen=True)
class _ShellArgs:
    """What a ``sh``/``bash``/``zsh`` command line asks the shell to run."""

    has_c: bool  # -c: the first operand is shell code
    has_s: bool  # -s: the program comes from stdin; operands are its arguments
    operand: str | None  # the first operand: the -c string, or a script file


def _drop_plus_options(args: list[str]) -> list[str]:
    """*args* without ``+o NAME``/``+O NAME`` pairs and other ``+x`` words.

    Mirrors ``_drop_plus_options`` in _bash_write_targets.py, which removes
    them anywhere in the list before option parsing.
    """
    kept: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("+") and len(arg) > 1:
            i += 2 if arg in ("+o", "+O") else 1
            continue
        kept.append(arg)
        i += 1
    return kept


def _takes_long_value(raw: str) -> bool:
    """True when ``--raw`` (no ``=``) names a value-taking long option.

    GNU getopt accepts a unique prefix, as ``_long_name`` does in the guard.
    """
    if raw in _SHELL_LONG_VALUE:
        return True
    matches = [name for name in _SHELL_LONG_VALUE if raw and name.startswith(raw)]
    return len(matches) == 1


def _cluster_letters(arg: str) -> tuple[str, bool]:
    """Flag letters of the short cluster *arg*, and whether it takes the next word.

    A value letter (``o``/``O``) ends the cluster: the rest of the word is
    its value (``-oc`` sets option ``c``), or the next word is when nothing
    follows it (``-eo pipefail``). Mirrors the guard's ``_OptReader._cluster``.
    """
    for k, ch in enumerate(arg[1:], start=1):
        if ch in _SHELL_SHORT_VALUE:
            return arg[1:k], k == len(arg) - 1
    return arg[1:], False


def _shell_args(args: list[str]) -> _ShellArgs:
    """The ``-c``/``-s`` flags and first operand of a shell's own argument list.

    Reads options the way h_shell does (getopt, stopping at the first
    operand): letters combine in clusters (``-es``, ``-ec``), ``-o``/``-O``
    and ``--rcfile``/``--init-file`` take a value, and ``--`` ends options.
    """
    args = _drop_plus_options(args)
    letters = ""
    i = 0
    while i < len(args) and args[i].startswith("-") and args[i] != "-":
        arg = args[i]
        i += 1
        if arg == "--":
            break
        if arg.startswith("--"):
            raw, eq, _ = arg[2:].partition("=")
            i += 1 if not eq and _takes_long_value(raw) else 0
            continue
        cluster, takes_next = _cluster_letters(arg)
        letters += cluster
        i += 1 if takes_next else 0
    return _ShellArgs("c" in letters, "s" in letters, args[i] if i < len(args) else None)


def _shell_reads_stdin(cmd: SimpleCommand) -> bool:
    """h_shell refuses a shell with no ``-c`` and no script: its program comes from stdin.

    ``-s`` in any cluster (``-s``, ``-es``) says so even with operands, which
    are then the program's arguments; ``-c`` wins when both are given.
    """
    shell = _shell_args(cmd.args)
    return not shell.has_c and (shell.has_s or shell.operand is None)


def _has_nested_c_cluster(args: list[str]) -> bool:
    """block-destructive-bash.sh's test for ``sh -c``: a ``c``-ending letter cluster.

    Its regex accepts only letter clusters before it, so ``bash -ec x``
    matches while ``bash -o pipefail -c x`` and ``bash --norc -c x`` do not
    (h_shell still parses those strings; see :func:`_inner_script`).
    """
    for arg in args:
        if _NESTED_C_CLUSTER_RE.fullmatch(arg):
            return True
        if not _LETTER_CLUSTER_RE.fullmatch(arg):
            return False
    return False


def _find_parts(cmd: SimpleCommand) -> tuple[list[str], list[tuple[ShellToken, ...]]]:
    """A ``find`` expression split into its own words and each ``-exec``-style body.

    Mirrors ``_find_expression``/``_find_exec`` in _bash_write_targets.py: a
    body runs from ``-exec``/``-execdir``/``-ok``/``-okdir`` to its ``;`` or
    ``+``, and its words are not find's own (``-exec grep -delete x \\;``
    deletes nothing).
    """
    args = cmd.arguments
    own: list[str] = []
    bodies: list[tuple[ShellToken, ...]] = []
    i = 0
    while i < len(args):
        word = args[i].text
        i += 1
        if word not in _FIND_EXEC_ACTIONS:
            own.append(word)
            continue
        end = next((j for j in range(i, len(args)) if args[j].text in _FIND_EXEC_ENDS), len(args))
        bodies.append(args[i:end])
        i = end + 1
    return own, bodies


def _find_writes(cmd: SimpleCommand) -> bool:
    """h_find: ``-delete`` acts on the roots, and ``-fprint``-style actions write a file.

    Known approximation: the guard also refuses a find whose root or
    expression word is decided at run time (``find "$p" -name x``), since it
    could be ``-delete``; this rule judges only the literal action words.
    """
    return any(word in _FIND_WRITE_ACTIONS for word in _find_parts(cmd)[0])


# Commands whose arguments, not their name, decide whether they write.
_ARGUMENT_CHECKS: dict[str, Callable[[SimpleCommand], bool]] = {
    "sed": lambda cmd: _has_sed_in_place(cmd.args),
    "gsed": lambda cmd: _has_sed_in_place(cmd.args),
    "patch": _patch_mutates,
    "find": _find_writes,
    **dict.fromkeys(_SHELLS, _shell_reads_stdin),
}


def _is_mutating(cmd: SimpleCommand) -> bool:
    """True when *cmd* writes anything, by the guard's own test.

    The guard refuses a loop whose body calls a command from its "Written"
    table or redirects output (``>``, ``>>``; not ``2>&1``, not a ``>``
    comparison inside ``[[ ]]``). `sed` is refused only with `-i`/`--in-place`,
    `patch` unless `--dry-run` or `-o FILE` is present, `find` with
    ``-delete`` or ``-fprint``, and a shell reading its program from stdin.
    What ``find -exec`` and ``sh -c`` run is judged as commands of its own
    (see :func:`_expanded`). This is deliberately narrower than the
    guard's full write-target parser -- it is enough to stop flagging the
    read-only loops the guard actually allows.
    """
    if any(r.writes for r in cmd.redirects) or cmd.name in _MUTATING_COMMANDS:
        return True
    check = _ARGUMENT_CHECKS.get(cmd.name)
    return check is not None and check(cmd)


def _inner_script(cmd: SimpleCommand) -> ShellScript | None:
    """What *cmd* runs from its arguments: ``find -exec`` bodies and ``sh -c`` strings.

    Mirrors ``_find_exec`` and ``h_shell`` in _bash_write_targets.py, which
    parse and judge both. Each inner command stays in its parent's loop. As
    in the guard, an ``sh -c`` string is one nesting level deeper than the
    command running it, while a ``find -exec`` body is judged at its own.
    """
    if cmd.name == "find":
        bodies = _find_parts(cmd)[1]
        return ShellScript(
            tuple(command_from_words(body, cmd.in_loop, cmd.depth) for body in bodies), (), (),
            max_depth=cmd.depth,
        )
    if cmd.name in _SHELLS:
        shell = _shell_args(cmd.args)
        if shell.has_c and shell.operand is not None:
            return parse_shell(shell.operand, in_loop=cmd.in_loop, depth=cmd.depth + 1)
    return None


def _expanded(script: ShellScript) -> ShellScript:
    """*script*'s commands, each followed by the commands it runs from its arguments.

    ``max_depth`` covers the inner scripts too, so nesting past the guard's
    ``MAX_DEPTH`` -- which :func:`parse_shell` stops at and records rather
    than drops -- surfaces as ``too_deep`` instead of being cut off silently.
    The heredocs of every inner ``sh -c`` string are carried up as well: the
    guard parses that string like any other command line, so an expanding
    heredoc inside it is refused just as one outside it is.
    Iterative, because ``find -exec`` bodies nest without a depth bound.
    """
    commands: list[SimpleCommand] = []
    heredocs = list(script.heredocs)
    max_depth = script.max_depth
    too_nested = script.too_nested
    pending: list[Iterator[SimpleCommand]] = [iter(script.commands)]
    while pending:
        cmd = next(pending[-1], None)
        if cmd is None:
            pending.pop()
            continue
        commands.append(cmd)
        inner = _inner_script(cmd)
        if inner is not None:
            max_depth = max(max_depth, inner.max_depth)
            too_nested = too_nested or inner.too_nested
            heredocs.extend(inner.heredocs)
            pending.append(iter(inner.commands))
    return ShellScript(
        tuple(commands), tuple(heredocs), script.loop_variables, script.comments, max_depth, too_nested
    )


def _is_nested_shell(cmd: SimpleCommand) -> bool:
    """A command block-destructive-bash.sh refuses anywhere, loop or not.

    Its "Nested shell evaluation: fail closed" check blocks ``eval``, a
    bare-named shell with a ``c``-ending option cluster (see
    :func:`_has_nested_c_cluster`), and ``xargs`` into a
    shell, without inspecting the string. A path-qualified ``/bin/sh -c``
    escapes that check (README "Known gaps"); its string is judged through
    :func:`_expanded` instead, as _bash_write_targets.py does.
    """
    word = cmd.word
    if word is None:
        return False
    if cmd.name == "eval":
        return True
    if cmd.name not in _SHELLS:
        return False
    if any(w.text.rsplit("/", 1)[-1] == "xargs" for w in cmd.words[:cmd.command_index]):
        return True
    return "/" not in word.text and _has_nested_c_cluster(cmd.args)


def refused_construct(script: ShellScript) -> str:
    """Name the guard-refused construct in *script*, or "" when there is none.

    A heredoc is refused only when its delimiter is unquoted and its body
    runs a substitution: the guard cannot inspect what that expands to. A
    quoted delimiter (``<<'EOF'``) makes the body inert, and a static body
    has nothing to expand -- the guard's contract allows both. Heredocs
    inside an ``sh -c`` string count too (see :func:`_expanded`).

    ``env -S``/``--split-string`` is refused anywhere: h_env in
    _bash_write_targets.py cannot see the command line that string becomes.

    A shell reading its program from stdin (``bash -s name``, ``/bin/bash <
    script``, ``cmd | sh``) is refused anywhere: h_shell in
    _bash_write_targets.py cannot inspect that program. Inside a loop it is
    reported as the loop, as before.

    Nesting deeper than the guard's ``MAX_DEPTH`` is refused whether or not
    a loop is involved: _bash_write_targets.py raises ``ParseError`` for the
    whole command there, and ``analyse_command`` turns that into a refusal.
    Only substitutions and nested shell strings count toward that bound;
    ``${...}`` and arithmetic do not. Expansions nested past the parser's own
    recursion bound (``MAX_EXPANSION_NEST``) were not read, so they are
    refused too, under a message of their own: the guard fails on
    RecursionError at a similar depth and refuses the command.
    """
    expanded = _expanded(script)
    if any(not doc.quoted and doc.subs for doc in expanded.heredocs):
        return "heredoc"
    if expanded.too_deep:
        return f"nesting deeper than {MAX_DEPTH}"
    if expanded.too_nested:
        return "expansions nested too deeply to parse"
    commands = expanded.commands
    if any(_is_nested_shell(cmd) for cmd in commands):
        return "eval/sh -c"
    if any(cmd.split_string for cmd in commands):
        return "env -S"
    if any(cmd.in_loop and _is_mutating(cmd) for cmd in commands):
        return "loop"
    if any(cmd.name in _STDIN_CHECKED_SHELLS and _shell_reads_stdin(cmd) for cmd in commands):
        return "shell reading its program from stdin"
    return ""

