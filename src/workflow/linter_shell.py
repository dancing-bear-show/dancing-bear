"""Shell-text rules for the workflow linter.

Workflow YAML is the largest source of late review findings, because stage
prose with embedded shell has no executable check. These rules lint the shell
that ``shell_text.extract_shell_segments`` finds in each stage description --
never the surrounding prose -- and emit warnings with stable rule ids:

``shell-unvalidated-param``
    A caller-overridable ``{param}`` is substituted into shell text, and
    neither ``trigger.param_rules`` nor a ``workflow check-params --check`` in
    this stage or an ancestor constrains it. Quoting is not the control: double
    quotes do not stop ``$(...)``. Nor is a shell comment or a quoted
    heredoc (``<<'EOF'``): the value is substituted into the text before the
    shell reads it, so a newline in it ends the comment, and a newline plus
    the delimiter ends the heredoc (the break-out ``param_guard`` documents).
    This rule reads both; the shell-expansion rules below treat them as inert.
``shell-unquoted-fan-out-key``
    A fan-out key placeholder -- a value read from a prior stage's JSON, which
    no param rule can constrain -- sits unquoted in shell text. For a stage
    a worker runs (``fan_out.mode: worker_queue`` or ``executor:
    worker_queue``) the text checked is the script the worker runs
    (``fan_out.script``, and the stage ``script`` it enqueues), not the
    description, which no shell and no agent ever reads in that mode; and
    there every occurrence counts, quoted or in a comment, because no
    allowlist constrains the value before worker dispatch and it is
    substituted before bash parses the script.
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
    before the guard ever sees the result, including one inside an ``sh -c``
    string; ``env -S``, which splits a string into the command line it runs;
    ``eval``, a bare ``sh -c``/``bash
    -c``, or ``xargs`` into a shell, which the guard blocks anywhere; or a
    ``for``/``while``/``until`` loop whose body contains a command the guard's
    write-target scan would refuse -- including one run by ``find -exec`` or
    inside an ``sh -c`` string, and ``find -delete``; or, loop or not, a
    shell reading its program from stdin (``bash -s``, ``bash < file``).
    A quoted-delimiter heredoc and a read-only loop are both things the guard's
    own contract (``.claude/hooks/README.md``, ``.claude/hooks/tests/guard-contract.yaml``)
    explicitly allows, so this rule does not fire on either.
    Which constructs the guard refuses is decided in ``shell_guard``; this
    module only reports them.

Every rule that asks "which command runs here" reads the same model:
``shell_parse.parse_shell``, which identifies the program word of each simple
command through separators, reserved words, wrappers, and substitutions, and
keeps heredoc bodies out of it. A rule never matches a bare token or a
substring of the raw text to decide that. Rules that do scan the raw text for
an expansion (``$NAME``, ``{key}``) skip what the parser reports as comments,
and read quoting from the text with comments and heredoc bodies masked, since
an apostrophe in either opens no quote.

For a stage a worker runs, ``shell-unbound-variable``, ``python-not-isolated``
and ``shell-guard-refused`` check each script field on its own -- each runs
as a separate ``bash FILE`` -- and name that field in the warning; the
description, which never executes in that mode, is not checked.
``shell-unvalidated-param`` still reads only the description: the engine
substitutes caller params into the description, never into a script. A
worker stage's ``check-params`` calls -- in its description or its scripts --
validate nothing, for itself or its descendants (see
:meth:`_StageShell.check_params_segments`); its description is still read for
uses, so an unchecked ``{param}`` there warns rather than passing silently.

Fragment stages inlined into a workflow get only the context-dependent rule
(``shell-unvalidated-param``) there, because their params are the importer's;
the context-free rules run when the fragment file itself is linted.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .linter_types import LintResult, LintWarning
from .placeholders import PLACEHOLDER_RE
from .shell_guard import refused_construct
from .shell_parse import (
    ShellScript,
    SimpleCommand,
    Span,
    parse_shell,
)
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
_WORKFLOW_CLI = "workflow"  # the only program that runs check-params
_WORKER_QUEUE = "worker_queue"  # FanOutMode.WORKER_QUEUE, and the executor of that name

# Set by the shell, the OS, or the harness -- never assigned in stage text.
_ENVIRONMENT_VARS: frozenset[str] = frozenset({
    "HOME", "PWD", "OLDPWD", "PATH", "USER", "SHELL", "TMPDIR", "IFS",
    "PYTHONPATH", "RANDOM", "LINENO", "SECONDS", "CI", "EDITOR", "LANG",
})
_ENVIRONMENT_PREFIXES = ("BASH_", "CLAUDE_", "GITHUB_", "GH_", "RUNNER_", "DANCING_BEAR_")

# -I (isolated) and -E both make the interpreter ignore PYTHONPATH, which is
# where a foreign checkout's sitecustomize comes from. -S is not required:
# alone it does not ignore PYTHONPATH, and it would break ``-m pip``.
_PYTHONPATH_IGNORING_FLAGS = frozenset({"I", "E"})


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
        """Matches of *pattern* outside quoted heredoc bodies and shell comments.

        The shell expands neither. A ``{param}`` substituted into the text
        before the shell reads it escapes both, so the pre-shell rule reads
        the whole text instead (see :func:`_unvalidated_params`).
        """
        dead = self.script.inert_spans() + list(self.script.comments)
        for m in pattern.finditer(self.segment.text):
            if not any(lo <= m.start() < hi for lo, hi in dead):
                yield m

    def quote_context(self) -> list[str]:
        """:func:`shell_text.quote_context` of the text, ignoring comments and heredoc bodies.

        Neither is shell words: an apostrophe in ``# don't`` or in a heredoc
        body opens no quote, and read raw it would mark the rest of the
        segment single-quoted.
        """
        chars = list(self.segment.text)
        for lo, hi in (*self.script.comments, *self.script.heredoc_spans()):
            chars[lo:hi] = " " * (hi - lo)
        return quote_context("".join(chars))


@dataclass(frozen=True)
class _StageShell:
    """A stage's shell segments, parsed once and shared by every rule."""

    stage: StageSpec
    segments: tuple[_ParsedSegment, ...]
    labels: tuple[ShellScript, ...] = ()  # assignments behind a prose label
    # Worker-queue scripts with their field names: whole shell text, no prose.
    scripts: tuple[tuple[str, _ParsedSegment], ...] = ()

    @classmethod
    def parse(cls, stage: StageSpec) -> _StageShell:
        segments = tuple(
            _ParsedSegment(seg, parse_shell(seg.text)) for seg in extract_shell_segments(stage.description)
        )
        labels = tuple(parse_shell(seg.text) for seg in extract_labelled_assignments(stage.description))
        scripts = tuple(
            (field, _ParsedSegment(ShellSegment(text, "script"), parse_shell(text)))
            for field, text in _worker_scripts(stage)
        )
        return cls(stage, segments, labels, scripts)

    def commands(self) -> Iterable[SimpleCommand]:
        for seg in self.segments:
            yield from seg.script.commands

    def units(self) -> tuple[_ShellUnit, ...]:
        """The shell text that runs: each worker script alone, else the description's.

        A stage a worker runs executes its script fields, each as its own
        ``bash FILE``; its description reaches no shell and no agent, so it
        is not checked. Any other stage's description segments share one shell.
        """
        if _is_worker_dispatched(self.stage):
            return tuple(_ShellUnit(field, (seg,)) for field, seg in self.scripts)
        return (_ShellUnit(_FIELD, self.segments, self.labels),)

    def check_params_segments(self) -> tuple[_ParsedSegment, ...]:
        """Segments whose ``check-params`` calls count as validation: none for a worker stage.

        A worker stage's description is not what runs, so a check written
        there proves nothing. Nor does one in its worker script: the engine
        records the stage ``pending`` when it enqueues the job and never reads
        the job's exit status, so a rejected check stops no later stage.
        """
        return () if _is_worker_dispatched(self.stage) else self.segments


@dataclass(frozen=True)
class _ShellUnit:
    """Shell text one shell process runs, and the stage field it comes from."""

    field: str
    segments: tuple[_ParsedSegment, ...]
    labels: tuple[ShellScript, ...] = ()  # assignments behind a prose label


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


def _worker_scripts(stage: StageSpec) -> list[tuple[str, str]]:
    """(field, text) of each script a worker runs through bash for *stage*.

    ``handle_run_shell`` writes the script to a file and runs ``bash FILE``,
    so the whole field is shell text. A worker_queue fan-out substitutes the
    item's key into ``fan_out.script``; the dispatcher enqueues the stage
    ``script`` of an ``executor: worker_queue`` stage.
    """
    fan_out = stage.fan_out
    scripts = []
    if fan_out is not None and fan_out.mode == _WORKER_QUEUE and fan_out.script.strip():
        scripts.append(("fan_out.script", fan_out.script))
    if stage.executor == _WORKER_QUEUE and stage.script.strip():
        scripts.append(("script", stage.script))
    return scripts


def _warn(stage: str, rule: str, message: str, field: str = _FIELD) -> LintWarning:
    return LintWarning(stage=stage, field=field, message=f"[{rule}] {message}", rule=rule)


def _snippet(text: str) -> str:
    """The first line of *text*, trimmed for a warning message."""
    first = text.strip().splitlines()[0] if text.strip() else ""
    return first if len(first) <= _SNIPPET_LEN else first[: _SNIPPET_LEN - 3] + "..."


# ---------------------------------------------------------------------------
# shell-unvalidated-param
# ---------------------------------------------------------------------------


def _check_params_call(cmd: SimpleCommand) -> tuple[int, list[str]] | None:
    """(offset, operands) when *cmd* runs ``workflow check-params``, else None.

    check-params is a subcommand of the workflow CLI, so the program word's
    basename must be ``workflow`` (``./bin/workflow``, an absolute path to
    it, or a bare ``workflow``) and its first operand ``check-params``. Any
    other program runs something else, path-qualified or not:
    ``/tmp/anything check-params --check ...`` validates nothing, and neither
    does ``echo check-params`` or a bare ``check-params``, which names no
    executable. Only this command's own operands are returned, so a later
    command's ``--check`` never donates a spec.
    """
    rest = cmd.arguments
    if cmd.name != _WORKFLOW_CLI or not rest or rest[0].text != _CHECK_PARAMS:
        return None
    return rest[0].start, [tok.text for tok in rest[1:]]


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
    own = {p.stage.name: set(_checked_param_positions(p.check_params_segments())) for p in parsed}
    deps = {p.stage.name: tuple(p.stage.depends_on) for p in parsed}
    out: dict[str, frozenset[str]] = {}
    for name in own:
        upstream = set().union(*(own.get(a, set()) for a in _ancestors(name, deps)))
        out[name] = frozenset(ruled | upstream)
    return out


def _unvalidated_params(
    item: _StageShell, caller: frozenset[str], validated: frozenset[str]
) -> list[LintWarning]:
    own_checks = _checked_param_positions(item.check_params_segments())
    reported: dict[str, str] = {}
    for seg_index, seg in enumerate(item.segments):
        # Every occurrence: the value is substituted before bash parses the
        # text, so a newline in it ends a comment, and a newline plus the
        # delimiter ends a quoted heredoc (param_guard's module docstring).
        for m in PLACEHOLDER_RE.finditer(seg.text):
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


def _is_worker_dispatched(stage: StageSpec) -> bool:
    """True when a worker runs *stage*'s scripts and no agent reads its description."""
    fan_out = stage.fan_out
    return stage.executor == _WORKER_QUEUE or (fan_out is not None and fan_out.mode == _WORKER_QUEUE)


def _unquoted_fan_out_keys(item: _StageShell) -> list[LintWarning]:
    fan_out = item.stage.fan_out
    if fan_out is None or not fan_out.key:
        return []
    if _is_worker_dispatched(item.stage):
        return _worker_key_references(item, fan_out.key)
    for seg in item.segments:
        ctx = seg.quote_context()
        for m in seg.live_matches(PLACEHOLDER_RE):
            if m.group(1) == fan_out.key and ctx[m.start()] == "":
                return [_warn(
                    item.stage.name,
                    RULE_UNQUOTED_FAN_OUT_KEY,
                    f"fan-out key '{{{fan_out.key}}}' is prior-stage data, unquoted in "
                    f"shell (`{_snippet(seg.text)}`); quote it or read it from the file",
                )]
    return []


def _worker_key_references(item: _StageShell, key: str) -> list[LintWarning]:
    """One warning per worker script that names *key* anywhere in its text.

    An agent fan-out's key is held to SKILL.md's ``SAFE_KEY_VALUE`` before
    it is substituted, so quoting and comments are real controls there. No
    such allowlist runs before worker dispatch, and the value is substituted
    into the script before bash parses it: a quote, ``$(...)`` or newline in
    it escapes a quoted string, a comment, or a quoted heredoc alike. So
    every occurrence counts, in whatever shell context it sits.
    """
    warnings = []
    for field, seg in item.scripts:
        count = sum(1 for m in PLACEHOLDER_RE.finditer(seg.text) if m.group(1) == key)
        if count:
            warnings.append(_warn(
                item.stage.name,
                RULE_UNQUOTED_FAN_OUT_KEY,
                f"fan-out key '{{{key}}}' is interpolated into a worker script {count} time(s) "
                f"(`{_snippet(seg.text)}`); it is not allowlisted before worker dispatch and is "
                f"substituted before bash parses the script, so quoting and comments do not "
                f"contain it -- pass it as data (read it from a file or environment variable)",
                field,
            ))
    return warnings


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


def _assigned_names(unit: _ShellUnit) -> set[str]:
    """Names the stage's own shell binds, or an assignment behind a prose label binds.

    Bindings come from parsed commands only, so an assignment-shaped word
    that is quoted text, an argument (``echo FOO=literal``), or heredoc data
    binds nothing. A binding made in a child shell is left out: the stage's
    shell never sees it (see :func:`_child_bindings`).
    """
    names: set[str] = set()
    for script in (*(seg.script for seg in unit.segments), *unit.labels):
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
    """Upper-case ``$NAME`` expansions, with offsets, outside single quotes, comments, and inert heredocs."""
    ctx = seg.quote_context()
    return [
        (m.group(1) or m.group(2), m.start())
        for m in seg.live_matches(_EXPANSION_RE)
        if ctx[m.start()] != "'" and not _is_escaped(seg.text, m.start())
    ]


def _unbound_variables(item: _StageShell) -> list[LintWarning]:
    return [warning for unit in item.units() for warning in _unbound_in_unit(item.stage.name, unit)]


def _unbound_in_unit(stage: str, unit: _ShellUnit) -> list[LintWarning]:
    assigned = _assigned_names(unit)
    reported: dict[str, str] = {}
    for seg in unit.segments:
        child = _child_bindings(seg.script)
        for name, pos in _expanded_names(seg):
            if name in assigned or _is_environment(name):
                continue
            if not any(lo <= pos < hi for lo, hi in child.get(name, ())):
                reported.setdefault(name, seg.text)
    return [
        _warn(
            stage,
            RULE_UNBOUND_VARIABLE,
            f"${name} is expanded but never assigned in this stage (`{_snippet(text)}`)",
            unit.field,
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
    """At most one warning per unit: its first unisolated interpreter."""
    warnings = []
    for unit in item.units():
        offender = next((o for seg in unit.segments for o in _python_offenders(seg.script)), None)
        if offender is not None:
            warnings.append(_warn(
                item.stage.name,
                RULE_PYTHON_NOT_ISOLATED,
                f"`{_snippet(offender)}` lacks -I; a foreign PYTHONPATH "
                f"sitecustomize runs at startup (use python3 -I -S)",
                unit.field,
            ))
    return warnings


# ---------------------------------------------------------------------------
# shell-guard-refused
# ---------------------------------------------------------------------------


def _guard_refused(item: _StageShell) -> list[LintWarning]:
    """At most one warning per unit: its first refused construct."""
    warnings = []
    for unit in item.units():
        hit = next(((what, seg) for seg in unit.segments if (what := refused_construct(seg.script))), None)
        if hit is not None:
            what, seg = hit
            warnings.append(_warn(
                item.stage.name,
                RULE_GUARD_REFUSED,
                f"{what} in shell (`{_snippet(seg.text)}`) is refused by the Bash guard "
                f"hook; use a script file or one command per call",
                unit.field,
            ))
    return warnings


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
