"""Workflow YAML linter.

Validates DAG structure without executing the workflow. Runs the full parser
(which handles YAML syntax, required fields, depends_on references, and cycle
detection), then performs additional checks.

Additional checks beyond the parser:
- Variable references ``{param}`` in stage descriptions that are not declared
  in ``trigger.params`` are surfaced as warnings.
- Fragment files referenced in ``include:`` that do not exist are surfaced
  as errors.
- ``./bin/<cli> <subcommand>`` patterns in stage descriptions are validated
  against the actual CLI binaries when ``check_commands=True``.
- ``agent.access`` is cross-checked against the role's agent definition, because
  the field restricts nothing at runtime. See ``_check_agent_access``.
"""

from __future__ import annotations

import re
import subprocess  # nosec B404 - subprocess imported deliberately; individual call sites carry their own B602/B603 review
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from workflow.models import StageSpec, WorkflowDefinition

from .include import extract_include_entries, resolve_fragment_path

__all__ = [
    "LintError",
    "LintWarning",
    "LintResult",
    "lint_workflow",
    "_check_fan_out_worker_queue",
    "_check_inline_executor",
]

_CLI_CMD_RE = re.compile(r"\./bin/([a-z-]+)\s+([a-z-]+)")

# CLIs whose subcommands don't support --help after the subcommand.
_CLI_NO_HELP_ALLOWLIST: dict[str, set[str]] = {
    "docs": {"search", "get-page", "publish-markdown"},
    "telemetry": {"sessions", "history", "summary"},
    "llm": {"familiarize", "auth-verify"},
}

_GLOBAL_STAGE = "<global>"

_VAR_RE = re.compile(r"(?<!\{)\{([a-z_][a-z0-9_]*)\}(?!\})")

_RUNTIME_BUILTIN_VARS: frozenset[str] = frozenset({"workspace"})


@dataclass(frozen=True)
class LintError:
    """A fatal structural error that makes the workflow invalid."""

    stage: str  # stage name, or "<global>" for top-level errors
    field: str  # YAML field where the error was found
    message: str


@dataclass(frozen=True)
class LintWarning:
    """A non-fatal issue that may indicate a misconfiguration."""

    stage: str
    field: str
    message: str


@dataclass
class LintResult:
    """Aggregated output of a lint run."""

    file: str
    valid: bool = True
    errors: list[LintError] = field(default_factory=list)
    warnings: list[LintWarning] = field(default_factory=list)
    stages: int = 0
    dag_depth: int = 0

    def as_dict(self) -> dict[str, object]:
        """Render as a flat dict suitable for emit_one / emit_rows."""
        return {
            "file": self.file,
            "valid": self.valid,
            "errors": [
                {"stage": e.stage, "field": e.field, "message": e.message}
                for e in self.errors
            ],
            "warnings": [
                {"stage": w.stage, "field": w.field, "message": w.message}
                for w in self.warnings
            ],
            "stages": self.stages,
            "dag_depth": self.dag_depth,
        }


def lint_workflow(path: str | Path, *, check_commands: bool = False) -> LintResult:
    """Lint a workflow YAML file.

    Runs the parser and performs additional checks. Returns a ``LintResult``
    describing every error and warning found — it never raises.

    Args:
        path: Path to the workflow YAML file.
        check_commands: When True, validate ``./bin/<cli> <subcommand>``
            patterns in stage descriptions.

    Returns:
        LintResult with ``valid=True`` iff there are no errors.
    """
    p = Path(path)
    result = LintResult(file=str(p))

    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        result.errors.append(
            LintError(stage=_GLOBAL_STAGE, field="file", message=f"file not found: {p}")
        )
        result.valid = False
        return result
    except OSError as exc:
        result.errors.append(
            LintError(stage=_GLOBAL_STAGE, field="file", message=f"cannot read {p}: {exc}")
        )
        result.valid = False
        return result

    import yaml as _yaml

    try:
        _top = _yaml.safe_load(text)
    except _yaml.YAMLError:
        _top = None
    is_fragment = isinstance(_top, dict) and bool(_top.get("fragment"))

    if is_fragment:
        return _lint_fragment(p, text, result)

    _check_include_files(text, p, result)
    if not result.valid:
        return result

    from workflow.parser import WorkflowParseError, parse_workflow_str

    try:
        defn = parse_workflow_str(text, source=str(p))
    except WorkflowParseError as exc:
        result.errors.append(
            LintError(stage=_GLOBAL_STAGE, field="<parse>", message=str(exc))
        )
        result.valid = False
        return result

    result.stages = len(defn.stages)
    result.dag_depth = _compute_dag_depth(defn.stages)

    _check_var_refs(defn, result)
    _check_fan_out_worker_queue(defn, result)
    _check_inline_executor(defn, result)
    _check_agent_access(defn, result)

    if check_commands:
        _check_cli_commands(defn, result)

    result.valid = len(result.errors) == 0
    return result


def _lint_fragment(p: Path, text: str, result: LintResult) -> LintResult:
    """Lint a fragment file using the fragment parser."""
    from workflow.include import _parse_fragment_str
    from workflow.parser import WorkflowParseError

    try:
        stages = _parse_fragment_str(text, source=str(p))
    except WorkflowParseError as exc:
        result.errors.append(
            LintError(stage=_GLOBAL_STAGE, field="<parse>", message=str(exc))
        )
        result.valid = False
        return result

    result.stages = len(stages)
    result.dag_depth = _compute_dag_depth(stages)
    _check_stage_access(stages, result)
    result.valid = True
    return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _fragment_stage_names(defn: object) -> frozenset[str]:
    """Return the names of stages that were injected from included fragments."""
    from workflow.models import WorkflowDefinition
    if not isinstance(defn, WorkflowDefinition) or not defn.includes:
        return frozenset()

    prefixes = tuple(
        inc.prefix + "-" for inc in defn.includes if inc.prefix
    )
    if not prefixes:
        return frozenset()

    return frozenset(
        stage.name
        for stage in defn.stages
        if stage.name.startswith(prefixes)
    )


def _build_known_vars(defn: WorkflowDefinition) -> tuple[frozenset[str], frozenset[str]]:
    """Return (fragment_stage_names, known_vars) for var-ref suppression logic."""
    declared_params = set(defn.trigger.params.keys())
    fragment_names = _fragment_stage_names(defn)

    fragment_vars: set[str] = set()
    caller_vars: set[str] = set()
    for stage in defn.stages:
        if stage.name in fragment_names:
            fragment_vars |= _extract_var_refs(stage.description)
        else:
            caller_vars |= _extract_var_refs(stage.description)

    exclusive_fragment_vars = fragment_vars - caller_vars
    return fragment_names, frozenset(declared_params | _RUNTIME_BUILTIN_VARS | exclusive_fragment_vars)


def _stage_undeclared_refs(stage: object, known: frozenset[str]) -> list[str]:
    """Return var refs in *stage* that are not covered by *known*."""
    from workflow.models import StageSpec
    if not isinstance(stage, StageSpec):
        return []
    fan_out_key = stage.fan_out.key if stage.fan_out is not None else None
    stage_known = known | ({fan_out_key} if fan_out_key else set())
    return [ref for ref in _extract_var_refs(stage.description) if ref not in stage_known]


def _check_var_refs(defn: object, result: LintResult) -> None:
    """Append warnings for undeclared {var} references in stage descriptions."""
    from workflow.models import WorkflowDefinition
    if not isinstance(defn, WorkflowDefinition):
        return

    fragment_names, known = _build_known_vars(defn)
    for stage in defn.stages:
        if stage.name in fragment_names:
            continue
        for ref in _stage_undeclared_refs(stage, known):
            result.warnings.append(
                LintWarning(
                    stage=stage.name,
                    field="description",
                    message=f"references undeclared variable '{{{ref}}}' (not in trigger.params)",
                )
            )


def _check_fan_out_worker_queue(defn: object, result: LintResult) -> None:
    """Emit an error for every fan_out with mode=worker_queue that has no script."""
    from workflow.models import FanOutMode, WorkflowDefinition
    if not isinstance(defn, WorkflowDefinition):
        return
    for stage in defn.stages:
        if stage.fan_out is None:
            continue
        if stage.fan_out.mode == FanOutMode.WORKER_QUEUE and not stage.fan_out.script.strip():
            result.errors.append(
                LintError(
                    stage=stage.name,
                    field="fan_out.script",
                    message=(
                        "fan_out.mode='worker_queue' requires a non-empty 'script' field — "
                        "provide a shell command template with {" + stage.fan_out.key + "} substituted per item"
                    ),
                )
            )


def _check_inline_executor(defn: object, result: LintResult) -> None:
    """Emit errors for inline executor stages that have unsupported features."""
    from workflow.models import WorkflowDefinition

    if not isinstance(defn, WorkflowDefinition):
        return
    for stage in defn.stages:
        if stage.executor != "inline":
            continue
        if stage.fan_out is not None:
            result.errors.append(
                LintError(
                    stage=stage.name,
                    field="executor",
                    message=(
                        "executor='inline' is incompatible with fan_out — "
                        "inline stages run synchronously in the orchestrator; "
                        "use executor='agent' for fan-out stages"
                    ),
                )
            )


_AGENTS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "agents"

# Tools whose presence in `disallowedTools:` means the role cannot create files.
_WRITE_TOOL = "Write"


def _roles_that_cannot_write(agents_dir: Path | None = None) -> frozenset[str]:
    """Return role names whose agent definition disallows the Write tool.

    Derived from the definitions on disk rather than hardcoded. A hardcoded list
    goes stale the moment someone edits frontmatter -- which is exactly what
    happened in PR #392, where `researcher` and `Plan` both changed and every
    reader working from memory got the wrong answer.

    Returns an empty set if the directory is missing, so linting a workflow from
    outside a checkout degrades to "no access warnings" rather than raising.
    """
    d = agents_dir if agents_dir is not None else _AGENTS_DIR
    if not d.is_dir():
        return frozenset()
    blocked: set[str] = set()
    for md in d.glob("*.md"):
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:  # nosec B112 - an unreadable agent file is not a lint failure
            continue
        for line in text.splitlines():
            if not line.startswith("disallowedTools:"):
                continue
            tools = {t.strip() for t in line.split(":", 1)[1].split(",")}
            if _WRITE_TOOL in tools:
                blocked.add(md.stem)
            break
    return frozenset(blocked)


def _role_is_defined(role: str, agents_dir: Path | None = None) -> bool:
    """True if ``role`` names an agent definition in ``.claude/agents/``.

    Workflows also use pseudo-roles that name no agent -- ``inline`` is the one in
    this tree -- and those have no frontmatter to serve as the enforcement gate.
    """
    d = agents_dir if agents_dir is not None else _AGENTS_DIR
    return (d / f"{role}.md").is_file()


def _check_agent_access(defn: object, result: LintResult) -> None:
    """Warn where a stage's ``access:`` disagrees with what its role can do.

    ``access`` is parsed and validated in ``parser_fields.py`` and stored on
    ``AgentSpec`` -- and then read by nothing. No code in ``src/`` grants or
    restricts anything based on it, and the same is true of a stage's ``tools:``
    list. Both are documentation.

    That matters because reviewers reasonably read ``access: read-only`` as a
    guarantee and file it as a security finding when a stage writes anyway. The
    only real gate is the ``disallowedTools:`` frontmatter in
    ``.claude/agents/<role>.md``.

    Two disagreements are worth surfacing, and they fail in opposite directions:

    * ``read-only`` on a stage that lists Write/Edit in ``tools:`` -- the
      declaration implies a restriction that does not exist.
    * ``read-write`` on a stage whose role CANNOT write -- the stage is
      unsatisfiable: it will gather its data and then be unable to emit any of
      it, stalling the run on a missing required output.

    Deliberately NOT warned: ``read-only`` on a stage that merely *has* a
    Write-capable role but declares no write tools. ``access`` defaults to
    ``read_only`` when the key is absent, so the parsed spec cannot distinguish
    "declared read-only" from "said nothing" -- and after #392 relaxed
    ``researcher``, almost every role can write. Warning on that shape fires on
    any stage that omits ``access`` entirely, including a minimal two-line
    gather stage that is claiming nothing. That is noise, and it broke a
    ``--strict`` lint fixture that was legitimately clean.

    Warnings rather than errors: 87 stages carried the first shape before #392
    and the tree still ran, so failing the lint would break every existing
    workflow over a field that changes no behaviour.
    """
    from workflow.models import WorkflowDefinition

    if not isinstance(defn, WorkflowDefinition):
        return
    _check_stage_access(defn.stages, result)


def _check_stage_access(stages: tuple[StageSpec, ...], result: LintResult) -> None:
    """Apply the access cross-check to a bare sequence of stages.

    Split out from ``_check_agent_access`` so fragments get the same treatment.
    ``lint_workflow`` returns through ``_lint_fragment`` for any file declaring
    ``fragment: true``, well before the full-workflow checks run -- so a fragment
    carrying either mismatch was accepted silently. 19 fragment files were
    unchecked, including the shared ones every workflow includes.
    """
    from workflow.models import AgentAccess

    cannot_write = _roles_that_cannot_write()
    for stage in stages:
        agent = getattr(stage, "agent", None)
        if agent is None:
            continue
        role = agent.role
        write_tools = sorted(t for t in agent.tools if t in {"Write", "Edit"})

        # An EMPTY tools tuple means "all tools" (models.py: "allowed tools
        # (empty = all)"), so a stage declaring access: read-only with no tools
        # list is the MOST permissive shape, not the least -- Write is available
        # unless the role's own frontmatter withholds it. Filtering for a named
        # Write/Edit reported exactly that case clean, which is backwards.
        if agent.access == AgentAccess.read_only:
            if write_tools:
                reason = f"lists {write_tools} in tools"
            elif (
                getattr(agent, "access_declared", False)
                and not agent.tools
                and _role_is_defined(role)
                and role not in cannot_write
            ):
                # Three gates, each for a case that produced a false positive:
                #
                # access_declared -- `access` defaults to read_only when the key is
                #   absent, so without this the branch fires on every minimal stage
                #   that never mentioned access at all. That is the same trap the
                #   docstring below records for the named-tools branch, and this
                #   branch walked into it: it broke a --strict lint fixture that was
                #   legitimately clean.
                # _role_is_defined -- `role: inline` and other pseudo-roles name no
                #   agent, so citing .claude/agents/inline.md would be nonsense.
                # role not in cannot_write -- a role whose frontmatter withholds
                #   Write makes `access: read-only` an accurate declaration.
                #
                # The named-tools branch above needs none of these: a stage listing
                # Write is making a claim regardless of role or defaults.
                reason = (
                    f"declares no tools, which means ALL tools, and role '{role}' "
                    f"is permitted Write"
                )
            else:
                reason = ""
            if reason:
                result.warnings.append(
                    LintWarning(
                        stage=stage.name,
                        field="agent.access",
                        message=(
                            f"declares access: read-only but {reason} — access is not "
                            f"enforced at runtime (nothing reads it), so this restricts "
                            f"nothing; the real gate is disallowedTools in "
                            f".claude/agents/{role}.md"
                        ),
                    )
                )
        elif agent.access == AgentAccess.read_write and role in cannot_write:
            result.warnings.append(
                LintWarning(
                    stage=stage.name,
                    field="agent.access",
                    message=(
                        f"declares access: read-write but role '{role}' disallows the "
                        f"Write tool (.claude/agents/{role}.md), so this stage cannot "
                        f"produce its outputs — use a Write-capable role"
                    ),
                )
            )


def _release_dependents(
    name: str,
    deps: dict[str, set[str]],
    in_degree: dict[str, int],
) -> list[str]:
    """Decrement in_degree for every remaining candidate depending on name.

    Returns the candidates that just reached in_degree 0 (newly ready).
    """
    ready: list[str] = []
    for candidate, cdeps in deps.items():
        if candidate in in_degree and name in cdeps:
            in_degree[candidate] -= 1
            if in_degree[candidate] == 0:
                del in_degree[candidate]
                ready.append(candidate)
    return ready


def _bfs_advance(
    queue: list[str],
    deps: dict[str, set[str]],
    in_degree: dict[str, int],
) -> list[str]:
    """Process one BFS wave and return the next queue."""
    next_queue: list[str] = []
    for name in queue:
        next_queue.extend(_release_dependents(name, deps, in_degree))
    for name in queue:
        if name in in_degree:
            del in_degree[name]
    return next_queue


def _compute_dag_depth(stages: tuple[object, ...]) -> int:
    """Compute the longest dependency chain depth (number of BFS levels)."""
    if not stages:
        return 0

    deps: dict[str, set[str]] = {s.name: set(s.depends_on) for s in stages}
    in_degree: dict[str, int] = {name: len(d) for name, d in deps.items()}
    queue = [name for name, deg in in_degree.items() if deg == 0]
    depth = 0

    while queue:
        depth += 1
        queue = _bfs_advance(queue, deps, in_degree)

    return depth


def _extract_var_refs(text: str) -> set[str]:
    """Return all ``{param}`` placeholder names found in *text*."""
    return set(_VAR_RE.findall(text))


def _check_cli_commands(defn: object, result: LintResult) -> None:
    """Append warnings for ./bin/<cli> <subcommand> patterns that cannot be validated."""
    from workflow.models import WorkflowDefinition
    if not isinstance(defn, WorkflowDefinition):
        return

    stage_for: dict[tuple[str, str], str] = {}
    for stage in defn.stages:
        for cli, sub in _CLI_CMD_RE.findall(stage.description):
            stage_for.setdefault((cli, sub), stage.name)

    for (cli, sub), stage_name in stage_for.items():
        warning = _validate_cli_command(cli, sub, stage_name)
        if warning is not None:
            result.warnings.append(warning)


def _cmd_warning(stage_name: str, message: str) -> LintWarning:
    """Build a LintWarning for a CLI command check."""
    return LintWarning(stage=stage_name, field="description", message=message)


def _validate_cli_command(cli: str, sub: str, stage_name: str) -> LintWarning | None:
    """Probe a single (cli, subcommand) pair and return a warning if it is invalid."""
    bin_path = Path("./bin") / cli
    not_found = f"command not found: ./bin/{cli} {sub}"

    allowlisted_subs = _CLI_NO_HELP_ALLOWLIST.get(cli)
    if allowlisted_subs is not None and sub in allowlisted_subs:
        return _cmd_warning(stage_name, not_found) if not bin_path.exists() else None

    try:
        proc = subprocess.run(  # nosec B603 - bin_path resolved from workflow YAML; sub validated against allowlist
            [str(bin_path), sub, "--help"],
            capture_output=True,
            timeout=3,
        )
    except FileNotFoundError:
        return _cmd_warning(stage_name, not_found)
    except subprocess.TimeoutExpired:
        return _cmd_warning(stage_name, f"command validation skipped (timeout): ./bin/{cli} {sub}")
    except OSError as exc:
        return _cmd_warning(stage_name, f"command validation skipped ({exc.__class__.__name__}): ./bin/{cli} {sub}")

    combined = (proc.stdout + proc.stderr).decode(errors="replace")
    if proc.returncode != 0 and _looks_like_invalid_subcommand(combined):
        return _cmd_warning(stage_name, not_found)
    return None


def _looks_like_invalid_subcommand(output: str) -> bool:
    """Return True when subprocess output indicates the subcommand does not exist."""
    lowered = output.lower()
    return "unrecognized arguments" in lowered or "invalid choice" in lowered


def _check_include_files(text: str, workflow_path: Path, result: LintResult) -> None:
    """Check that every fragment referenced in ``include:`` exists on disk."""
    for inc in extract_include_entries(text):
        if not isinstance(inc, dict) or "path" not in inc:
            continue
        path_str = str(inc["path"])
        frag = resolve_fragment_path(path_str, workflow_path)
        if not frag.exists():
            result.errors.append(
                LintError(
                    stage=_GLOBAL_STAGE,
                    field="include",
                    message=f"fragment file not found: {frag} (referenced as '{path_str}')",
                )
            )
            result.valid = False
