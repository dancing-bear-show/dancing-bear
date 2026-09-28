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
    A ``kind: validate`` stage's description instructs writing a file (any
    write-shaped verb -- ``Write``, ``Save``, ``Create``, ``Emit``, ``Output``,
    ``Produce`` -- naming a ``{workspace}``-rooted path with any extension).
    The validate prompt is built from ``validation:`` alone and appends a
    findings-array format, so the instruction never reaches the agent.
``shell-guard-refused``
    An unquoted-delimiter heredoc (``<<EOF``, not ``<<'EOF'``), whose body the
    Bash guard hook cannot inspect because ``$(...)`` and backticks in it expand
    before the guard ever sees the result; or a ``for``/``while``/``until`` loop
    whose body contains a command the guard's write-target scan would refuse.
    A quoted-delimiter heredoc and a read-only loop are both things the guard's
    own contract (``.claude/hooks/README.md``, ``.claude/hooks/tests/guard-contract.yaml``)
    explicitly allows, so this rule does not fire on either.

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
# even though its label keeps that line out of the shell segments. A leading
# word character immediately before the match (no separator/whitespace boundary)
# is excluded by _is_assignment_position below: an assignment word is only a
# binding in assignment position -- the first word of a command, or right after
# export/local/declare -- not merely preceded by whitespace or a separator.
# ``echo FOO=literal`` must not bind FOO; ``export FOO=literal`` must.
_ASSIGNMENT_RE = re.compile(r"(?:^|[\s;(&|`])([A-Z_][A-Z0-9_]*)=")
_ASSIGNMENT_KEYWORDS = frozenset({"export", "local", "declare"})
_BINDING_WORDS = frozenset({"for", "read"})
_PYTHON_WORD_RE = re.compile(r"^(?:.*/)?python3?(?:\.\d+)?$")
# Group 1 captures a quoting character on the delimiter, when there is one, so
# a caller can tell a quoted heredoc (body is inert data, no expansions occur)
# from an unquoted one (body undergoes $(...)/backtick/$VAR expansion). Group 2
# captures the delimiter word itself, so the matching close line can be found.
_HEREDOC_RE = re.compile(r"<<-?\s*(['\"])?([A-Za-z_]\w*)")
_SUBSTITUTION_RE = re.compile(r"\$\(|`")
_WRITE_INSTRUCTION_RE = re.compile(
    r"\b(?:Write|write|Save|save|Create|create|Emit|emit|Output|output|Produce|produce)\s+"
    r"(?:it\s+to:?\s+|to:?\s+|the\s+\S+\s+to:?\s+)?"
    r"\"?\{workspace\}/\S+\.[A-Za-z0-9]+\b"
)

# Set by the shell, the OS, or the harness -- never assigned in stage text.
_ENVIRONMENT_VARS: frozenset[str] = frozenset({
    "HOME", "PWD", "OLDPWD", "PATH", "USER", "SHELL", "TMPDIR", "IFS",
    "PYTHONPATH", "RANDOM", "LINENO", "SECONDS", "CI", "EDITOR", "LANG",
})
_ENVIRONMENT_PREFIXES = ("BASH_", "CLAUDE_", "GITHUB_", "GH_", "RUNNER_", "DANCING_BEAR_")

_LOOP_HEADS = frozenset({"for", "while", "until"})
# Commands the real destructive-bash guard treats as write targets (see the
# "Written" table in .claude/hooks/README.md). A loop whose body calls none of
# these, and contains no output redirection, is read-only and the guard allows
# it outright (guard-contract.yaml: "for f in src/*.py; do wc -l "$f"; done").
# `sed` and `patch` are handled separately in _loop_body_is_mutating because
# the guard's own contract for them is conditional on their flags, not on the
# bare command name -- see the "Written" table's `sed` and `patch` rows.
_MUTATING_COMMANDS = frozenset({
    "rm", "rmdir", "unlink", "shred", "chmod", "chown", "chgrp", "mv", "cp",
    "ln", "install", "touch", "tee", "truncate", "dd", "mkdir",
})
_REDIRECT_RE = re.compile(r"(?<![<>])>>?(?!>)")
# The guard refuses `patch` unless one of these is present (it writes the
# files named *inside the diff*, so the guard cannot resolve a write target
# without one of these).
_PATCH_SAFE_FLAGS = ("--dry-run", "-o")
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


def _check_specs(tail: str) -> list[str]:
    """Every ``--check <spec>``/``--check=<spec>`` value in a check-params call's tail."""
    tokens = split_tokens(tail)
    specs = []
    for i, tok in enumerate(tokens):
        if tok == "--check" and i + 1 < len(tokens):
            specs.append(tokens[i + 1])
        elif tok.startswith("--check="):
            specs.append(tok[len("--check="):])
    return specs


def _checked_param_positions(
    segments: Iterable[ShellSegment],
) -> dict[str, tuple[int, int]]:
    """Param name -> (segment index, char offset) of its earliest check-params call.

    The position is what lets a caller distinguish "checked before this use" from
    "checked after it" within the same stage: a ``{param}`` substituted into shell
    text before the stage's own ``check-params --check`` call has already reached
    shell by the time the check runs, so only uses at or after that position may be
    credited to a same-stage check.
    """
    positions: dict[str, tuple[int, int]] = {}
    for seg_index, seg in enumerate(segments):
        for m in re.finditer(r"\S+", seg.text):
            if not m.group(0).endswith("check-params"):
                continue
            for spec in _check_specs(seg.text[m.end():]):
                name, sep, _ = spec.partition("=")
                if sep and name and name not in positions:
                    positions[name] = (seg_index, m.start())
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
    own_positions = {p.stage.name: _checked_param_positions(p.segments) for p in parsed}
    own = {name: set(pos) for name, pos in own_positions.items()}
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
        for m in _PLACEHOLDER_RE.finditer(seg.text):
            name = m.group(1)
            if name not in caller:
                continue
            if name in validated:
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


def _is_assignment_position(text: str, start: int) -> bool:
    """True when the ``NAME=`` match at *start* sits in assignment position.

    A shell assignment word binds only as the first word of a command, or right
    after ``export``/``local``/``declare`` -- not merely because whitespace or a
    separator precedes it. ``echo FOO=literal`` is an argument to ``echo``, not a
    binding: the character immediately before ``FOO`` (skipping whitespace) is
    ``o``, a word character, so this is preceded by another word, not a command
    boundary. ``export FOO=literal`` binds because that preceding word is one of
    the assignment keywords. A prose label ending in a non-word character
    (``Bash tool: F=...``) is also a boundary -- the ':' is not a word character.
    """
    i = start
    while i > 0 and text[i - 1] in " \t":
        i -= 1
    if i == 0 or not text[i - 1].isalnum() and text[i - 1] != "_":
        return True
    word_end = i
    word_start = word_end
    while word_start > 0 and (text[word_start - 1].isalnum() or text[word_start - 1] == "_"):
        word_start -= 1
    return text[word_start:word_end] in _ASSIGNMENT_KEYWORDS


def _assigned_names(description: str, segments: Iterable[ShellSegment]) -> set[str]:
    """Upper-case names bound by ``NAME=`` in assignment position, or ``for``/``read`` in shell.

    Matched outside quotes only: an assignment-looking literal inside a quoted
    string (``echo "example FOO=literal"``) is quoted text, not a binding, and
    must not suppress ``shell-unbound-variable`` for a real, later ``$FOO``.
    Quote context is computed over the whole description -- not just the shell
    segments -- so the intentional "label before a command" case (``Bash tool:
    F=...``) still binds: the assignment token there sits outside any quote,
    only the value is quoted. An unquoted ``NAME=`` that is merely an argument
    to another command (``echo FOO=literal``) is excluded by
    :func:`_is_assignment_position` -- only the shell grammar's assignment
    position is a real binding.
    """
    ctx = quote_context(description)
    names = {
        m.group(1)
        for m in _ASSIGNMENT_RE.finditer(description)
        if ctx[m.start(1)] == "" and _is_assignment_position(description, m.start(1))
    }
    for seg in segments:
        tokens = split_tokens(seg.text)
        for i, tok in enumerate(tokens):
            if tok in _BINDING_WORDS:
                names.update(t for t in tokens[i + 1:i + 4] if t.isidentifier())
    return names


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


def _expanded_names(seg: ShellSegment) -> list[str]:
    """Upper-case ``$NAME`` expansions outside single quotes, in order."""
    ctx = quote_context(seg.text)
    return [
        m.group(1) or m.group(2)
        for m in _EXPANSION_RE.finditer(seg.text)
        if ctx[m.start()] != "'" and not _is_escaped(seg.text, m.start())
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
    """True when the word is followed by an option or a script operand -- not prose.

    A script operand need not end in ``.py``: ``python3 tools/run_checks`` and
    ``python3 "$SCRIPT"`` both start the interpreter just as surely. Treat a
    path-like operand (contains ``/``) or a variable reference (``$NAME`` --
    shlex already stripped the quotes off ``"$SCRIPT"``) as an invocation too;
    a single bare word (``is``, ``required``) stays prose.
    """
    if not args:
        return False
    first = args[0]
    return bool(
        first.startswith("-") or first.endswith(".py") or "/" in first or first.startswith("$")
    )


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


def _heredoc_body_has_substitution(text: str, delimiter: str, body_start: int) -> bool:
    """True when the heredoc body up to the matching *delimiter* line contains a substitution.

    Finds the first line, from *body_start* on, whose stripped content equals
    *delimiter* -- the closing line -- and scans everything before it for
    ``$(...)`` or a backtick. A static body (plain literal lines) has neither,
    and the guard's contract only refuses an unquoted heredoc because those
    constructs expand before the guard can inspect the result; a body with
    no substitution is not something the guard refuses.
    """
    close = re.search(rf"^[ \t]*{re.escape(delimiter)}[ \t]*$", text[body_start:], re.MULTILINE)
    body = text[body_start:body_start + close.start()] if close else text[body_start:]
    return bool(_SUBSTITUTION_RE.search(body))


def _has_heredoc(text: str, full_text: str | None = None) -> bool:
    """True for an unquoted-delimiter heredoc whose body actually substitutes.

    A quoted delimiter (``<<'EOF'`` or ``<<"EOF"``) makes the body inert: POSIX sh
    performs no expansion inside it at all, so ``$(...)`` in a quoted heredoc body
    is literal text, not a command to run. The guard's own contract allows this
    shape explicitly (guard-contract.yaml: "quoted heredoc data" -> allow), so it
    must not be flagged here as refused. An unquoted delimiter whose body is
    static (no ``$(...)`` or backtick) is also something the guard accepts: the
    guard can only fail to inspect a substitution that is actually there.

    *full_text* is the whole stage description to scan for the body in, when it
    differs from *text*: ``extract_shell_segments`` stops a "line" segment at
    the heredoc opener, so the body lines never appear in the segment text
    itself and must be located in the surrounding description instead.
    """
    ctx = quote_context(text)
    for m in _HEREDOC_RE.finditer(text):
        if ctx[m.start()] != "" or text[m.start() - 1:m.start()] == "<" or m.group(1) is not None:
            continue
        if full_text is not None:
            anchor = full_text.find(text)
            body_start = anchor + m.end() if anchor != -1 else m.end()
            search_text = full_text if anchor != -1 else text
        else:
            body_start, search_text = m.end(), text
        if _heredoc_body_has_substitution(search_text, m.group(2), body_start):
            return True
    return False


def _as_command_separators(text: str) -> str:
    """Replace unquoted newlines with ``;`` so a line boundary is a separator.

    ``split_tokens`` treats a newline as ordinary whitespace, so a loop head
    that merely follows setup text on the previous line -- not a command
    separator -- reads as glued onto that text: ``echo setup\\nfor p in
    items; do ...; done`` tokenizes with ``for`` immediately after ``setup``.
    A newline still inside quotes (a multi-line string argument) is left
    alone; only a line boundary between commands counts.
    """
    ctx = quote_context(text)
    return "".join(";" if ch == "\n" and ctx[i] == "" else ch for i, ch in enumerate(text))


def _has_sed_in_place(tokens: list[str], sed_index: int) -> bool:
    """True when the ``sed`` invocation at *sed_index* carries ``-i``/``--in-place``.

    The guard's "Written" table blocks `sed` operands only with `-i`/`--in-place`
    present -- a plain `sed -n ...` is a read. `-i` can appear bare, clustered
    with other short flags (`-ie`), or with an attached suffix (`-i.bak`).
    """
    for tok in tokens[sed_index + 1:]:
        if tok in ("--in-place",) or tok.startswith("--in-place="):
            return True
        if tok.startswith("-") and not tok.startswith("--") and "i" in tok[1:]:
            return True
    return False


def _has_unsafe_patch(tokens: list[str], patch_index: int) -> bool:
    """True when the ``patch`` invocation at *patch_index* lacks a safe flag.

    The guard refuses `patch` unless `--dry-run` or `-o FILE` is present, because
    otherwise it writes the files named *inside the diff* -- a write target the
    guard cannot resolve from the command line alone.
    """
    rest = tokens[patch_index + 1:]
    return not any(tok.startswith(_PATCH_SAFE_FLAGS) for tok in rest)


def _loop_body_is_mutating(tokens: list[str], do_index: int) -> bool:
    """True when the loop body (after ``do``) writes anything, by the guard's own test.

    The guard allows a loop outright when its body is read-only (guard-contract.yaml:
    "loop variable in a read" -> allow) and refuses one whose body calls a command from
    the guard's own "Written" table, or redirects output (`>`, `>>`). This is
    deliberately narrower than the guard's full write-target parser -- it is enough to
    stop flagging the read-only loops the guard actually allows, not a reimplementation
    of the guard itself. `sed` and `patch` are checked separately because the guard's
    own contract for them is conditional on flags, not on the bare command name: `sed`
    is refused only with `-i`/`--in-place`, and `patch` is refused unless `--dry-run`
    or `-o FILE` is present.
    """
    body = tokens[do_index + 1:]
    if any(tok in _MUTATING_COMMANDS for tok in body):
        return True
    if any(_REDIRECT_RE.search(tok) for tok in body):
        return True
    for i, tok in enumerate(body):
        if tok == "sed" and _has_sed_in_place(body, i):
            return True
        if tok == "patch" and _has_unsafe_patch(body, i):
            return True
    return False


def _has_loop(text: str) -> bool:
    tokens = split_tokens(_as_command_separators(text))
    for i, tok in enumerate(tokens):
        if i and tokens[i - 1] not in _COMMAND_SEPARATORS:
            continue
        if tok in _LOOP_HEADS and "do" in tokens[i + 1:]:
            do_index = tokens.index("do", i + 1)
            if _loop_body_is_mutating(tokens, do_index):
                return True
    return False


def _refused_construct(text: str, full_text: str) -> str:
    """Name the guard-refused construct in *text*, or "" when there is none."""
    if _has_heredoc(text, full_text):
        return "heredoc"
    if _has_loop(text):
        return "loop"
    return ""


def _guard_refused(item: _StageShell) -> list[LintWarning]:
    for seg in item.segments:
        what = _refused_construct(seg.text, item.stage.description)
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
