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
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from workflow.models import WorkflowDefinition

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


def _bfs_advance(
    queue: list[str],
    deps: dict[str, set[str]],
    in_degree: dict[str, int],
) -> list[str]:
    """Process one BFS wave and return the next queue."""
    next_queue: list[str] = []
    for name in queue:
        for candidate, cdeps in deps.items():
            if candidate in in_degree and name in cdeps:
                in_degree[candidate] -= 1
                if in_degree[candidate] == 0:
                    del in_degree[candidate]
                    next_queue.append(candidate)
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
