"""YAML loading and validation for workflow definitions.

Loads a YAML file (or string), validates structural constraints, and
constructs a fully typed ``WorkflowDefinition``.
"""

from __future__ import annotations

from pathlib import Path

from .models import WorkflowDefinition
from .include import (
    parse_fragment,  # re-exported for backward compat — keep in __all__
    _parse_include,
    _expand_includes,
)
from .parser_errors import WorkflowParseError
from .parser_fields import _parse_stage, _parse_trigger
from .parser_validate import (
    _validate_dag,
    _validate_reads_from_ordering,
    _validate_refs,
    _validate_unique_names,
)

__all__ = [
    "WorkflowParseError",
    "parse_workflow",
    "parse_workflow_str",
    "parse_fragment",
]

_REQUIRED_TOP_KEYS = ("name", "version", "description", "trigger", "stages")


def parse_workflow(path: str | Path) -> WorkflowDefinition:
    """Load and validate a workflow definition from a YAML file.

    Raises ``WorkflowParseError`` on invalid input.
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise WorkflowParseError(f"file not found: {p}") from None
    except OSError as exc:
        raise WorkflowParseError(f"cannot read {p}: {exc}") from exc
    return parse_workflow_str(text, source=str(p))


def parse_workflow_str(content: str, source: str = "<string>") -> WorkflowDefinition:
    """Parse a workflow definition from a YAML string.

    Useful for testing. *source* is used in error messages.
    """
    import yaml  # lazy — optional dep
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise WorkflowParseError(f"{source}: invalid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise WorkflowParseError(f"{source}: expected a YAML mapping at top level")

    for key in _REQUIRED_TOP_KEYS:
        if key not in data:
            raise WorkflowParseError(f"{source}: missing required key '{key}'")

    trigger = _parse_trigger(data["trigger"], source)
    raw_stages = data["stages"]
    if not isinstance(raw_stages, list) or len(raw_stages) == 0:
        raise WorkflowParseError(f"{source}: 'stages' must be a non-empty list")

    stages = tuple(_parse_stage(s, source) for s in raw_stages)

    raw_includes = data.get("include") or []
    if not isinstance(raw_includes, list):
        raise WorkflowParseError(f"{source}: 'include' must be a list, got {type(raw_includes).__name__}")
    includes = tuple(_parse_include(inc, source) for inc in raw_includes)
    if includes:
        source_path = Path(source) if source != "<string>" else None
        stages = _expand_includes(stages, includes, source_path, source)

    _validate_unique_names(stages, source)
    _validate_refs(stages, source)
    _validate_dag(stages, source)
    _validate_reads_from_ordering(stages, source)

    return WorkflowDefinition(
        name=data["name"],
        version=str(data["version"]),
        description=data["description"],
        trigger=trigger,
        stages=stages,
        workspace_dir=data.get("workspace_dir"),
        metadata=data.get("metadata") or {},
        includes=includes,
    )
