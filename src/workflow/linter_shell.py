"""Shell-text rules for the workflow linter.

Workflow YAML is the largest source of late review findings, because stage
prose with embedded shell has no executable check. These rules lint the shell
that ``shell_text.extract_shell_segments`` finds in each stage description --
never the surrounding prose -- and emit warnings with stable rule ids:

``shell-unvalidated-param``
    A caller-overridable ``{param}`` is substituted into shell text, and
    neither ``trigger.param_rules`` nor a ``check-params --check`` in this
    stage or an ancestor constrains it. Quoting is not the control: double
    quotes do not stop ``$(...)``.
``shell-unquoted-fan-out-key``
    A fan-out key placeholder -- a value read from a prior stage's JSON, which
    no param rule can constrain -- sits unquoted in shell text.
``shell-unbound-variable``
    ``$NAME`` (upper case) is expanded in shell text but no shell text in the
    same stage assigns it; each stage is a fresh shell. An assignment inside a
    child shell -- ``$(...)``, backticks, ``<(...)``, ``( ... )`` -- binds only
    for expansions inside that same child shell.
``python-not-isolated``
    A ``python``/``python3`` invocation lacks ``-I`` (or ``-E``), so a foreign
    ``PYTHONPATH`` entry's ``sitecustomize`` runs at startup. A command with an
    explicit ``PYTHONPATH=...`` prefix is exempt: its author wants PYTHONPATH
    honoured, which ``-I`` would defeat.
``validate-stage-writes-output``
    A ``kind: validate`` stage's description instructs writing a file (any
    write-shaped verb -- ``Write``, ``Save``, ``Create``, ``Emit``, ``Output``,
    ``Produce`` -- naming a ``{workspace}``-rooted path with any extension).
    The validate prompt is built from ``validation:`` alone and appends a
    findings-array format, so the instruction never reaches the agent.
``shell-guard-refused``
    An unquoted-delimiter heredoc (``<<EOF``, not ``<<'EOF'``), whose body the
    Bash guard hook cannot inspect because ``$(...)`` and backticks in it expand
    before the guard ever sees the result; ``eval``, a bare ``sh -c``/``bash
    -c``, or ``xargs`` into a shell, which the guard blocks anywhere; or a
    ``for``/``while``/``until`` loop whose body contains a command the guard's
    write-target scan would refuse -- including one run by ``find -exec`` or
    inside an ``sh -c`` string, and ``find -delete``.
    A quoted-delimiter heredoc and a read-only loop are both things the guard's
    own contract (``.claude/hooks/README.md``, ``.claude/hooks/tests/guard-contract.yaml``)
    explicitly allows, so this rule does not fire on either.

Every rule that asks "which command runs here" reads the same model:
``shell_parse.parse_shell``, which identifies the program word of each simple
command through separators, reserved words, wrappers, and substitutions, and
keeps heredoc bodies out of it. A rule never matches a bare token or a
substring of the raw text to decide that.

Fragment stages inlined into a workflow get only the context-dependent rule
(``shell-unvalidated-param``) there, because their params are the importer's;
the context-free rules run when the fragment file itself is linted.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .linter_types import LintResult, LintWarning
from .placeholders import PLACEHOLDER_RE
from .shell_parse import ShellScript, ShellToken, SimpleCommand, Span, command_from_words, parse_shell
from .shell_text import (
    ShellSegment,
    extract_labelled_assignments,
    extract_shell_segments,
    quote_context,
)

if TYPE_CHECKING:
    from workflow.models import StageSpec

__all__ = [
    "RULE_GUARD_REFUSED",
    "RULE_PYTHON_NOT_ISOLATED",
    "RULE_UNBOUND_VARIABLE",
    "RULE_UNQUOTED_FAN_OUT_KEY",
    "RULE_UNVALIDATED_PARAM",
    "RULE_VALIDATE_WRITES_OUTPUT",
    "ShellLintContext",
    "check_shell_rules",
]

RULE_UNVALIDATED_PARAM = "shell-unvalidated-param"
RULE_UNQUOTED_FAN_OUT_KEY = "shell-unquoted-fan-out-key"
RULE_UNBOUND_VARIABLE = "shell-unbound-variable"
RULE_PYTHON_NOT_ISOLATED = "python-not-isolated"
RULE_VALIDATE_WRITES_OUTPUT = "validate-stage-writes-output"
RULE_GUARD_REFUSED = "shell-guard-refused"

_FIELD = "description"
_SNIPPET_LEN = 72

# ``$NAME`` or exactly ``${NAME}``. ``${NAME:-default}``, ``${NAME:+x}`` and
# friends handle an unset NAME, so the braced form must close right after it.
_EXPANSION_RE = re.compile(r"\$(?:\{([A-Z_][A-Z0-9_]*)\}|([A-Z_][A-Z0-9_]*))")
_PYTHON_WORD_RE = re.compile(r"^(?:.*/)?python3?(?:\.\d+)?$")
_WRITE_INSTRUCTION_RE = re.compile(
    r"\b(?:Write|write|Save|save|Create|create|Emit|emit|Output|output|Produce|produce)\s+"
    r"(?:it\s+to:?\s+|to:?\s+|the\s+\S+\s+to:?\s+)?"
    r"\"?\{workspace\}/\S+\.[A-Za-z0-9]+\b"
)

# Commands whose NAME=value operands bind NAME in the current shell.
_DECLARING_COMMANDS = frozenset({"export", "local", "declare", "readonly", "typeset"})
# ``read`` options whose value is the next word, not a variable name.
_READ_VALUE_OPTS = frozenset({"-d", "-i", "-n", "-N", "-p", "-t", "-u"})
_CHECK_PARAMS = "check-params"

# Set by the shell, the OS, or the harness -- never assigned in stage text.
_ENVIRONMENT_VARS: frozenset[str] = frozenset({
    "HOME", "PWD", "OLDPWD", "PATH", "USER", "SHELL", "TMPDIR", "IFS",
    "PYTHONPATH", "RANDOM", "LINENO", "SECONDS", "CI", "EDITOR", "LANG",
})
_ENVIRONMENT_PREFIXES = ("BASH_", "CLAUDE_", "GITHUB_", "GH_", "RUNNER_", "DANCING_BEAR_")

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
_SED_COMMANDS = frozenset({"sed", "gsed"})
# The guard refuses `patch` unless one of these is present (it writes the
# files named *inside the diff*, so the guard cannot resolve a write target
# without one of these).
_PATCH_SAFE_FLAGS = ("--dry-run", "-o")
# -I (isolated) and -E both make the interpreter ignore PYTHONPATH, which is
# where a foreign checkout's sitecustomize comes from. -S is not required:
# alone it does not ignore PYTHONPATH, and it would break ``-m pip``.
_PYTHONPATH_IGNORING_FLAGS = frozenset({"I", "E"})
# Shells whose ``-c`` string both guards treat as code: h_shell in
# .claude/hooks/_bash_write_targets.py, and the nested-shell check in
# block-destructive-bash.sh (which adds fish).
_SHELLS = frozenset({"sh", "bash", "zsh", "ksh", "dash", "fish"})
_SHELL_VALUE_OPTS = frozenset({"--rcfile", "--init-file"})
# h_find's actions (_bash_write_targets.py _FIND_OUTPUTS and _FIND_EXECS):
# -delete acts on the roots, -fprint* write a file, -exec* run a command.
_FIND_WRITE_ACTIONS = frozenset({"-delete", "-fprint", "-fprint0", "-fls", "-fprintf"})
_FIND_EXEC_ACTIONS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
_FIND_EXEC_ENDS = frozenset({";", "+"})
_MAX_NESTING = 32  # _bash_write_targets.py MAX_DEPTH


@dataclass(frozen=True)
class ShellLintContext:
    """What the shell rules need to know beyond the stage text itself."""

    caller_params: frozenset[str]
    """Names a caller can override with ``--params`` (``work_dir`` excluded)."""
    ruled_params: frozenset[str]
    """Names constrained by an engine-enforced ``trigger.param_rules`` entry."""
    fragment_stages: frozenset[str] = frozenset()
    """Stages inlined from a fragment: only the context-dependent rule applies."""


@dataclass(frozen=True)
class _ParsedSegment:
    """One shell segment and the commands parsed out of it."""

    segment: ShellSegment
    script: ShellScript

    @property
    def text(self) -> str:
        return self.segment.text

    def live_matches(self, pattern: re.Pattern[str]) -> Iterable[re.Match[str]]:
        """Matches of *pattern* outside quoted heredoc bodies, which never expand."""
        inert = self.script.inert_spans()
        for m in pattern.finditer(self.segment.text):
            if not any(lo <= m.start() < hi for lo, hi in inert):
                yield m


@dataclass(frozen=True)
class _StageShell:
    """A stage's shell segments, parsed once and shared by every rule."""

    stage: StageSpec
    segments: tuple[_ParsedSegment, ...]
    labels: tuple[ShellScript, ...] = ()  # assignments behind a prose label

    @classmethod
    def parse(cls, stage: StageSpec) -> _StageShell:
        segments = tuple(
            _ParsedSegment(seg, parse_shell(seg.text)) for seg in extract_shell_segments(stage.description)
        )
        labels = tuple(parse_shell(seg.text) for seg in extract_labelled_assignments(stage.description))
        return cls(stage, segments, labels)

    def commands(self) -> Iterable[SimpleCommand]:
        for seg in self.segments:
            yield from seg.script.commands


def check_shell_rules(
    stages: tuple[StageSpec, ...], context: ShellLintContext, result: LintResult
) -> None:
    """Append a warning for every shell-text rule violation in *stages*."""
    parsed = [_StageShell.parse(s) for s in stages]
    validated = _validated_by_stage(parsed, context.ruled_params)
    for item in parsed:
        name = item.stage.name
        result.warnings.extend(_unvalidated_params(item, context.caller_params, validated[name]))
        if name in context.fragment_stages:
            continue
        result.warnings.extend(_unquoted_fan_out_keys(item))
        result.warnings.extend(_unbound_variables(item))
        result.warnings.extend(_unisolated_pythons(item))
        result.warnings.extend(_guard_refused(item))
        result.warnings.extend(_validate_writes_output(item.stage))


def _warn(stage: str, rule: str, message: str) -> LintWarning:
    return LintWarning(stage=stage, field=_FIELD, message=f"[{rule}] {message}", rule=rule)


def _snippet(text: str) -> str:
    """The first line of *text*, trimmed for a warning message."""
    first = text.strip().splitlines()[0] if text.strip() else ""
    return first if len(first) <= _SNIPPET_LEN else first[: _SNIPPET_LEN - 3] + "..."


# ---------------------------------------------------------------------------
# shell-unvalidated-param
# ---------------------------------------------------------------------------


def _check_params_call(cmd: SimpleCommand) -> tuple[int, list[str]] | None:
    """(offset, operands) when *cmd* runs check-params, else None.

    Either the program itself is ``check-params`` or a repo wrapper runs it
    as a subcommand (``./bin/workflow check-params ...``). The word
    ``check-params`` as an argument to another command (``echo
    check-params``) is not an invocation. Only this command's own operands
    are returned, so a later command's ``--check`` never donates a spec.
    """
    word = cmd.word
    if word is None:
        return None
    if cmd.name == _CHECK_PARAMS:
        return word.start, cmd.args
    rest = cmd.arguments
    if rest and rest[0].text == _CHECK_PARAMS and (cmd.name == "workflow" or "/" in word.text):
        return rest[0].start, [tok.text for tok in rest[1:]]
    return None


def _check_param_names(operands: list[str]) -> list[str]:
    """Param names named by every ``--check <spec>``/``--check=<spec>`` in *operands*."""
    specs = [nxt for tok, nxt in zip(operands, operands[1:]) if tok == "--check"]
    specs += [tok[len("--check="):] for tok in operands if tok.startswith("--check=")]
    names = []
    for spec in specs:
        name, sep, _ = spec.partition("=")
        if sep and name:
            names.append(name)
    return names


def _checked_param_positions(segments: Iterable[_ParsedSegment]) -> dict[str, tuple[int, int]]:
    """Param name -> (segment index, char offset) of its earliest check-params call.

    The position is what lets a caller distinguish "checked before this use" from
    "checked after it" within the same stage: a ``{param}`` substituted into shell
    text before the stage's own ``check-params --check`` call has already reached
    shell by the time the check runs, so only uses at or after that position may be
    credited to a same-stage check.
    """
    positions: dict[str, tuple[int, int]] = {}
    for seg_index, seg in enumerate(segments):
        for cmd in seg.script.commands:
            call = _check_params_call(cmd)
            if call is None:
                continue
            offset, operands = call
            for name in _check_param_names(operands):
                if (seg_index, offset) < positions.get(name, (seg_index + 1, 0)):
                    positions[name] = (seg_index, offset)
    return positions


def _ancestors(name: str, deps: Mapping[str, tuple[str, ...]]) -> set[str]:
    """Every stage *name* depends on, transitively."""
    seen: set[str] = set()
    stack = list(deps.get(name, ()))
    while stack:
        dep = stack.pop()
        if dep not in seen:
            seen.add(dep)
            stack.extend(deps.get(dep, ()))
    return seen


def _validated_by_stage(
    parsed: list[_StageShell], ruled: frozenset[str]
) -> dict[str, frozenset[str]]:
    """Per stage: params the engine rules or a check-params here or upstream cover.

    Upstream (ancestor-stage) checks validate unconditionally: an ancestor's shell
    text runs to completion before this stage starts, so ordering within it cannot
    leave an unvalidated use reaching this stage's shell. A check in THIS stage is
    different -- the check and the use can appear in either order in the same
    segment sequence -- so it is not folded into this per-stage name set; see
    ``_unvalidated_params``, which applies it only to uses at or after its position.
    """
    own = {p.stage.name: set(_checked_param_positions(p.segments)) for p in parsed}
    deps = {p.stage.name: tuple(p.stage.depends_on) for p in parsed}
    out: dict[str, frozenset[str]] = {}
    for name in own:
        upstream = set().union(*(own.get(a, set()) for a in _ancestors(name, deps)))
        out[name] = frozenset(ruled | upstream)
    return out


def _unvalidated_params(
    item: _StageShell, caller: frozenset[str], validated: frozenset[str]
) -> list[LintWarning]:
    own_checks = _checked_param_positions(item.segments)
    reported: dict[str, str] = {}
    for seg_index, seg in enumerate(item.segments):
        for m in seg.live_matches(PLACEHOLDER_RE):
            name = m.group(1)
            if name not in caller or name in validated:
                continue
            checked_at = own_checks.get(name)
            if checked_at is not None and (seg_index, m.start()) >= checked_at:
                continue
            reported.setdefault(name, seg.text)
    return [
        _warn(
            item.stage.name,
            RULE_UNVALIDATED_PARAM,
            f"'{{{name}}}' reaches shell unvalidated (`{_snippet(text)}`); "
            f"add trigger.param_rules[{name}] or a check-params --check",
        )
        for name, text in sorted(reported.items())
    ]


# ---------------------------------------------------------------------------
# shell-unquoted-fan-out-key
# ---------------------------------------------------------------------------


def _unquoted_fan_out_keys(item: _StageShell) -> list[LintWarning]:
    fan_out = item.stage.fan_out
    if fan_out is None or not fan_out.key:
        return []
    for seg in item.segments:
        ctx = quote_context(seg.text)
        for m in seg.live_matches(PLACEHOLDER_RE):
            if m.group(1) == fan_out.key and ctx[m.start()] == "":
                return [_warn(
                    item.stage.name,
                    RULE_UNQUOTED_FAN_OUT_KEY,
                    f"fan-out key '{{{fan_out.key}}}' is prior-stage data, unquoted in "
                    f"shell (`{_snippet(seg.text)}`); quote it or read it from the file",
                )]
    return []


# ---------------------------------------------------------------------------
# shell-unbound-variable
# ---------------------------------------------------------------------------


def _read_names(args: list[str]) -> list[str]:
    """Variable names a ``read`` command assigns: its operands, skipping option values."""
    names = []
    skip = False
    for arg in args:
        if skip:
            skip = False
        elif arg in _READ_VALUE_OPTS:
            skip = True
        elif arg.isidentifier():
            names.append(arg)
    return names


def _command_bindings(cmd: SimpleCommand) -> Iterable[str]:
    """Names *cmd* binds: leading ``NAME=value`` words, declarations, and ``read``."""
    yield from (tok.assigned_name for tok in cmd.assignments)
    if cmd.name in _DECLARING_COMMANDS:
        yield from (tok.assigned_name for tok in cmd.arguments if tok.assigned_name)
    elif cmd.name == "read":
        yield from _read_names(cmd.args)


def _script_bindings(script: ShellScript) -> Iterator[tuple[str, Span | None]]:
    """Each name *script* binds, with the child shell it is bound in (None: the stage's shell)."""
    for var in script.loop_variables:
        yield var.name, var.subshell
    for cmd in script.commands:
        for name in _command_bindings(cmd):
            yield name, cmd.subshell


def _assigned_names(item: _StageShell) -> set[str]:
    """Names the stage's own shell binds, or an assignment behind a prose label binds.

    Bindings come from parsed commands only, so an assignment-shaped word
    that is quoted text, an argument (``echo FOO=literal``), or heredoc data
    binds nothing. A binding made in a child shell is left out: the stage's
    shell never sees it (see :func:`_child_bindings`).
    """
    names: set[str] = set()
    for script in (*(seg.script for seg in item.segments), *item.labels):
        names.update(name for name, subshell in _script_bindings(script) if subshell is None)
    return names


def _child_bindings(script: ShellScript) -> dict[str, list[Span]]:
    """Name -> the child shells in *script* that bind it, visible only inside those spans."""
    spans: dict[str, list[Span]] = {}
    for name, subshell in _script_bindings(script):
        if subshell is not None:
            spans.setdefault(name, []).append(subshell)
    return spans


def _is_environment(name: str) -> bool:
    return name in _ENVIRONMENT_VARS or name.startswith(_ENVIRONMENT_PREFIXES)


def _is_escaped(text: str, pos: int) -> bool:
    """True when a run of an odd number of backslashes immediately precedes *pos*.

    POSIX sh: a backslash outside single quotes escapes the next character, so
    ``\\$NAME`` expands nothing -- the ``$`` is literal. A *pair* of
    backslashes (``\\\\$NAME``) is itself an escaped backslash, so the ``$``
    is unescaped again; only an odd run counts.
    """
    run = 0
    i = pos - 1
    while i >= 0 and text[i] == "\\":
        run += 1
        i -= 1
    return run % 2 == 1


def _expanded_names(seg: _ParsedSegment) -> list[tuple[str, int]]:
    """Upper-case ``$NAME`` expansions, with offsets, outside single quotes and inert heredoc bodies."""
    ctx = quote_context(seg.text)
    return [
        (m.group(1) or m.group(2), m.start())
        for m in seg.live_matches(_EXPANSION_RE)
        if ctx[m.start()] != "'" and not _is_escaped(seg.text, m.start())
    ]


def _unbound_variables(item: _StageShell) -> list[LintWarning]:
    assigned = _assigned_names(item)
    reported: dict[str, str] = {}
    for seg in item.segments:
        child = _child_bindings(seg.script)
        for name, pos in _expanded_names(seg):
            if name in assigned or _is_environment(name):
                continue
            if not any(lo <= pos < hi for lo, hi in child.get(name, ())):
                reported.setdefault(name, seg.text)
    return [
        _warn(
            item.stage.name,
            RULE_UNBOUND_VARIABLE,
            f"${name} is expanded but never assigned in this stage (`{_snippet(text)}`)",
        )
        for name, text in sorted(reported.items())
    ]


# ---------------------------------------------------------------------------
# python-not-isolated
# ---------------------------------------------------------------------------


_VALUE_TAKING_FLAGS = frozenset({"-X", "-W"})


def _isolation_flags(args: list[str]) -> set[str]:
    """Single-letter interpreter flags given before the program or module.

    ``-X`` and ``-W`` each take the NEXT token as their value (``-X utf8``,
    ``-W error``), not a bundled suffix -- that value token must be skipped
    rather than treated as the end of the flag list, or a later isolation
    flag (``-I``) is never reached: ``python3 -X utf8 -I -c '...'`` would
    otherwise stop scanning at ``utf8`` and report the invocation as
    unisolated even though ``-I`` is present.
    """
    flags: set[str] = set()
    i = 0
    while i < len(args):
        arg = args[i]
        if not arg.startswith("-") or arg.startswith("--"):
            break
        flags.update(arg[1:])
        if "c" in arg or "m" in arg:
            break
        i += 2 if arg in _VALUE_TAKING_FLAGS else 1
    return flags


def _python_offenders(script: ShellScript) -> list[str]:
    """Each unisolated interpreter in *script*, as a short display string.

    Only the program word of a simple command counts: ``echo python3 -c`` runs
    echo. Whatever follows that word -- an option, ``tools/run_checks``, a bare
    ``runner``, or nothing -- the interpreter starts with the ambient
    PYTHONPATH. Prose such as "python3 is required" is kept out upstream:
    ``shell_text.is_command_line`` never extracts it as a segment, so this
    does not re-judge operands. A ``PYTHONPATH=`` assignment exempts the
    command it prefixes (or that an ``env`` wrapper sets it for), never a
    later command.
    """
    offenders: list[str] = []
    for cmd in script.commands:
        word = cmd.word
        if word is None or not _PYTHON_WORD_RE.match(cmd.name):
            continue
        if any(tok.text.startswith("PYTHONPATH=") for tok in cmd.assignments):
            continue  # the author set PYTHONPATH on purpose; -I would ignore it
        args = cmd.args
        if not _isolation_flags(args) & _PYTHONPATH_IGNORING_FLAGS:
            offenders.append(" ".join([word.text, *args[:3]]))
    return offenders


def _unisolated_pythons(item: _StageShell) -> list[LintWarning]:
    for seg in item.segments:
        offenders = _python_offenders(seg.script)
        if offenders:
            return [_warn(
                item.stage.name,
                RULE_PYTHON_NOT_ISOLATED,
                f"`{_snippet(offenders[0])}` lacks -I; a foreign PYTHONPATH "
                f"sitecustomize runs at startup (use python3 -I -S)",
            )]
    return []


# ---------------------------------------------------------------------------
# shell-guard-refused
# ---------------------------------------------------------------------------


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
    operand: str | None  # the first operand: the -c string, or a script file


def _shell_option_width(arg: str) -> int:
    """Words the shell option *arg* consumes; 0 when it is the first operand.

    Mirrors h_shell's option table: ``-o``/``-O`` and ``--rcfile``/
    ``--init-file`` take a value, and ``+o NAME`` unsets an option.
    """
    if arg in ("+o", "+O") or arg in _SHELL_VALUE_OPTS:
        return 2
    if arg.startswith("-") and len(arg) > 1 and not arg.startswith("--"):
        return 2 if arg[-1] in "oO" else 1
    return 1 if arg.startswith(("+", "--")) and len(arg) > 1 else 0


def _shell_args(args: list[str]) -> _ShellArgs:
    """The ``-c`` flag and first operand of a shell's own argument list."""
    has_c = False
    i = 0
    while i < len(args) and (width := _shell_option_width(args[i])):
        has_c = has_c or (not args[i].startswith(("--", "+")) and "c" in args[i][1:])
        i += width
    return _ShellArgs(has_c, args[i] if i < len(args) else None)


def _shell_reads_stdin(cmd: SimpleCommand) -> bool:
    """h_shell refuses a shell with no ``-c`` and no script: its program comes from stdin."""
    shell = _shell_args(cmd.args)
    return not shell.has_c and (shell.operand is None or "-s" in cmd.args)


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
    (see :func:`_expanded_commands`). This is deliberately narrower than the
    guard's full write-target parser -- it is enough to stop flagging the
    read-only loops the guard actually allows.
    """
    if any(r.writes for r in cmd.redirects) or cmd.name in _MUTATING_COMMANDS:
        return True
    check = _ARGUMENT_CHECKS.get(cmd.name)
    return check is not None and check(cmd)


def _inner_commands(cmd: SimpleCommand) -> tuple[SimpleCommand, ...]:
    """Commands *cmd* runs from its arguments: ``find -exec`` bodies and ``sh -c`` strings.

    Mirrors ``_find_exec`` and ``h_shell`` in _bash_write_targets.py, which
    parse and judge both. Each inner command stays in its parent's loop.
    """
    if cmd.name == "find":
        return tuple(command_from_words(body, cmd.in_loop) for body in _find_parts(cmd)[1])
    if cmd.name in _SHELLS:
        shell = _shell_args(cmd.args)
        if shell.has_c and shell.operand is not None:
            return parse_shell(shell.operand, in_loop=cmd.in_loop).commands
    return ()


def _expanded_commands(commands: Iterable[SimpleCommand], depth: int = 0) -> Iterator[SimpleCommand]:
    """*commands*, each followed by the commands it runs from its arguments.

    Nesting stops at the guard's own ``MAX_DEPTH``; past it the guard refuses
    outright, and no workflow prose nests that deep.
    """
    for cmd in commands:
        yield cmd
        if depth < _MAX_NESTING:
            yield from _expanded_commands(_inner_commands(cmd), depth + 1)


def _is_nested_shell(cmd: SimpleCommand) -> bool:
    """A command block-destructive-bash.sh refuses anywhere, loop or not.

    Its "Nested shell evaluation: fail closed" check blocks ``eval``, a
    bare-named shell with a ``-c`` option cluster, and ``xargs`` into a
    shell, without inspecting the string. A path-qualified ``/bin/sh -c``
    escapes that check (README "Known gaps"); its string is judged through
    :func:`_expanded_commands` instead, as _bash_write_targets.py does.
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
    return "/" not in word.text and _shell_args(cmd.args).has_c


def _refused_construct(script: ShellScript) -> str:
    """Name the guard-refused construct in *script*, or "" when there is none.

    A heredoc is refused only when its delimiter is unquoted and its body
    runs a substitution: the guard cannot inspect what that expands to. A
    quoted delimiter (``<<'EOF'``) makes the body inert, and a static body
    has nothing to expand -- the guard's contract allows both.
    """
    if any(not doc.quoted and doc.subs for doc in script.heredocs):
        return "heredoc"
    commands = list(_expanded_commands(script.commands))
    if any(_is_nested_shell(cmd) for cmd in commands):
        return "eval/sh -c"
    if any(cmd.in_loop and _is_mutating(cmd) for cmd in commands):
        return "loop"
    return ""


def _guard_refused(item: _StageShell) -> list[LintWarning]:
    for seg in item.segments:
        what = _refused_construct(seg.script)
        if what:
            return [_warn(
                item.stage.name,
                RULE_GUARD_REFUSED,
                f"{what} in shell (`{_snippet(seg.text)}`) is refused by the Bash guard "
                f"hook; use a script file or one command per call",
            )]
    return []


# ---------------------------------------------------------------------------
# validate-stage-writes-output
# ---------------------------------------------------------------------------


def _validate_writes_output(stage: StageSpec) -> list[LintWarning]:
    from workflow.models import StageKind

    if stage.kind != StageKind.validate:
        return []
    m = _WRITE_INSTRUCTION_RE.search(stage.description)
    if m is None:
        return []
    return [_warn(
        stage.name,
        RULE_VALIDATE_WRITES_OUTPUT,
        f"kind: validate drops the description, so `{_snippet(m.group(0))}` never "
        f"reaches the agent; use kind: execute",
    )]
