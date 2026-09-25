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
    same stage assigns it; each stage is a fresh shell.
``python-not-isolated``
    A ``python``/``python3`` invocation lacks ``-I`` (or ``-E``), so a foreign
    ``PYTHONPATH`` entry's ``sitecustomize`` runs at startup. A command with an
    explicit ``PYTHONPATH=...`` prefix is exempt: its author wants PYTHONPATH
    honoured, which ``-I`` would defeat.
``validate-stage-writes-output``
    A ``kind: validate`` stage's description instructs writing a file. The
    validate prompt is built from ``validation:`` alone and appends a
    findings-array format, so the instruction never reaches the agent.
``shell-guard-refused``
    A heredoc or a ``for``/``while``/``until`` loop in shell text; the Bash
    guard hook refuses both as too complex to verify.

Fragment stages inlined into a workflow get only the context-dependent rule
(``shell-unvalidated-param``) there, because their params are the importer's;
the context-free rules run when the fragment file itself is linted.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .linter_types import LintResult, LintWarning
from .shell_text import ShellSegment, extract_shell_segments, quote_context, split_tokens

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

# Same shape as linter._VAR_RE: a single-brace identifier, not {{escaped}}.
_PLACEHOLDER_RE = re.compile(r"(?<!\{)\{([a-z_][a-z0-9_]*)\}(?!\})")
# ``$NAME`` or exactly ``${NAME}``. ``${NAME:-default}``, ``${NAME:+x}`` and
# friends handle an unset NAME, so the braced form must close right after it.
_EXPANSION_RE = re.compile(r"\$(?:\{([A-Z_][A-Z0-9_]*)\}|([A-Z_][A-Z0-9_]*))")
# Searched in the whole description, prose included: "Bash tool: F=..." binds F
# even though its label keeps that line out of the shell segments.
_ASSIGNMENT_RE = re.compile(r"(?:^|[\s;(&|`])([A-Z_][A-Z0-9_]*)=")
_BINDING_WORDS = frozenset({"for", "read"})
_PYTHON_WORD_RE = re.compile(r"^(?:.*/)?python3?(?:\.\d+)?$")
_HEREDOC_RE = re.compile(r"<<-?\s*['\"]?[A-Za-z_]")
_WRITE_INSTRUCTION_RE = re.compile(
    r"\b(?:Write|write|Save|save)\s+(?:it\s+to\s+|to\s+|the\s+\S+\s+to\s+)?"
    r"\"?\{workspace\}/\S+\.(?:json|md|txt|yaml|csv)"
)

# Set by the shell, the OS, or the harness -- never assigned in stage text.
_ENVIRONMENT_VARS: frozenset[str] = frozenset({
    "HOME", "PWD", "OLDPWD", "PATH", "USER", "SHELL", "TMPDIR", "IFS",
    "PYTHONPATH", "RANDOM", "LINENO", "SECONDS", "CI", "EDITOR", "LANG",
})
_ENVIRONMENT_PREFIXES = ("BASH_", "CLAUDE_", "GITHUB_", "GH_", "RUNNER_", "DANCING_BEAR_")

_LOOP_HEADS = frozenset({"for", "while", "until"})
# -I (isolated) and -E both make the interpreter ignore PYTHONPATH, which is
# where a foreign checkout's sitecustomize comes from. -S is not required:
# alone it does not ignore PYTHONPATH, and it would break ``-m pip``.
_PYTHONPATH_IGNORING_FLAGS = frozenset({"I", "E"})
_COMMAND_SEPARATORS = frozenset({";", "&&", "||", "|", "(", "&"})


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
class _StageShell:
    """A stage's shell segments, parsed once and shared by every rule."""

    stage: StageSpec
    segments: tuple[ShellSegment, ...]


def check_shell_rules(
    stages: tuple[StageSpec, ...], context: ShellLintContext, result: LintResult
) -> None:
    """Append a warning for every shell-text rule violation in *stages*."""
    parsed = [_StageShell(s, tuple(extract_shell_segments(s.description))) for s in stages]
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


def _checked_param_names(segments: Iterable[ShellSegment]) -> set[str]:
    """Param names a ``check-params --check name=regex`` call validates."""
    names: set[str] = set()
    for seg in segments:
        tokens = split_tokens(seg.text)
        if not any(t.endswith("check-params") for t in tokens):
            continue
        for i, tok in enumerate(tokens):
            spec = ""
            if tok == "--check" and i + 1 < len(tokens):
                spec = tokens[i + 1]
            elif tok.startswith("--check="):
                spec = tok[len("--check="):]
            name, sep, _ = spec.partition("=")
            if sep and name:
                names.add(name)
    return names


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
    """Per stage: params the engine rules or a check-params here or upstream cover."""
    own = {p.stage.name: _checked_param_names(p.segments) for p in parsed}
    deps = {p.stage.name: tuple(p.stage.depends_on) for p in parsed}
    out: dict[str, frozenset[str]] = {}
    for name, checked in own.items():
        upstream = set().union(*(own.get(a, set()) for a in _ancestors(name, deps)))
        out[name] = frozenset(ruled | checked | upstream)
    return out


def _unvalidated_params(
    item: _StageShell, caller: frozenset[str], validated: frozenset[str]
) -> list[LintWarning]:
    reported: dict[str, str] = {}
    for seg in item.segments:
        for m in _PLACEHOLDER_RE.finditer(seg.text):
            name = m.group(1)
            if name in caller and name not in validated:
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
        for m in _PLACEHOLDER_RE.finditer(seg.text):
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


def _assigned_names(description: str, segments: Iterable[ShellSegment]) -> set[str]:
    """Upper-case names bound by ``NAME=`` anywhere, or ``for``/``read`` in shell."""
    names = set(_ASSIGNMENT_RE.findall(description))
    for seg in segments:
        tokens = split_tokens(seg.text)
        for i, tok in enumerate(tokens):
            if tok in _BINDING_WORDS:
                names.update(t for t in tokens[i + 1:i + 4] if t.isidentifier())
    return names


def _is_environment(name: str) -> bool:
    return name in _ENVIRONMENT_VARS or name.startswith(_ENVIRONMENT_PREFIXES)


def _expanded_names(seg: ShellSegment) -> list[str]:
    """Upper-case ``$NAME`` expansions outside single quotes, in order."""
    ctx = quote_context(seg.text)
    return [
        m.group(1) or m.group(2)
        for m in _EXPANSION_RE.finditer(seg.text)
        if ctx[m.start()] != "'"
    ]


def _unbound_variables(item: _StageShell) -> list[LintWarning]:
    assigned = _assigned_names(item.stage.description, item.segments)
    reported: dict[str, str] = {}
    for seg in item.segments:
        for name in _expanded_names(seg):
            if name not in assigned and not _is_environment(name):
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


def _isolation_flags(args: list[str]) -> set[str]:
    """Single-letter interpreter flags given before the program or module."""
    flags: set[str] = set()
    for arg in args:
        if not arg.startswith("-") or arg.startswith("--"):
            break
        flags.update(arg[1:])
        if "c" in arg or "m" in arg:
            break
    return flags


def _is_invocation(args: list[str]) -> bool:
    """True when the word is followed by an option or a script -- not prose."""
    return bool(args) and (args[0].startswith("-") or args[0].endswith(".py"))


def _python_offenders(seg: ShellSegment) -> list[str]:
    tokens = split_tokens(seg.text)
    offenders: list[str] = []
    for i, tok in enumerate(tokens):
        word = tok.lstrip("$(`")
        if not _PYTHON_WORD_RE.match(word):
            continue
        prefix = tokens[max(0, i - 3):i]
        if any(t.startswith("PYTHONPATH=") for t in prefix):
            continue  # the author set PYTHONPATH on purpose; -I would ignore it
        args = tokens[i + 1:]
        if _is_invocation(args) and not _isolation_flags(args) & _PYTHONPATH_IGNORING_FLAGS:
            offenders.append(" ".join([word, *args[:3]]))
    return offenders


def _unisolated_pythons(item: _StageShell) -> list[LintWarning]:
    for seg in item.segments:
        offenders = _python_offenders(seg)
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


def _has_heredoc(text: str) -> bool:
    ctx = quote_context(text)
    return any(
        ctx[m.start()] == "" and text[m.start() - 1:m.start()] != "<"
        for m in _HEREDOC_RE.finditer(text)
    )


def _has_loop(text: str) -> bool:
    tokens = split_tokens(text)
    for i, tok in enumerate(tokens):
        if i and tokens[i - 1] not in _COMMAND_SEPARATORS:
            continue
        if tok in _LOOP_HEADS and "do" in tokens[i + 1:]:
            return True
    return False


def _refused_construct(text: str) -> str:
    """Name the guard-refused construct in *text*, or "" when there is none."""
    if _has_heredoc(text):
        return "heredoc"
    if _has_loop(text):
        return "loop"
    return ""


def _guard_refused(item: _StageShell) -> list[LintWarning]:
    for seg in item.segments:
        what = _refused_construct(seg.text)
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
