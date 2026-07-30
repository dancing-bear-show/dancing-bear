"""Fragment loading and include expansion for workflow definitions.

Handles ``include:`` directives: loads fragment YAML files, prefixes stage
names, rewrites intra-fragment dependency refs, and inlines the stages into
the parent workflow's stage list.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, cast

from .models import FanOutSpec, IncludeSpec, StageSpec

__all__ = [
    "parse_fragment",
    "_parse_include",
    "_parse_fragment_str",
    "_expand_includes",
    "resolve_fragment_path",
    "extract_include_entries",
]


def resolve_fragment_path(path_str: str, source_path: Path) -> Path:
    """Resolve a fragment include path to an absolute Path.

    Tries cwd-relative first (project-root-anchored), then falls back to the
    source file's directory for relative paths like ``../shared/x.yaml``.
    """
    frag_path = Path(path_str)
    if frag_path.is_absolute():
        return frag_path
    cwd_relative = Path.cwd() / path_str
    if cwd_relative.exists():
        return cwd_relative
    return source_path.parent / path_str


def extract_include_entries(content: str | bytes) -> list[object]:
    """Return the raw ``include:`` list from YAML *content*, or an empty list.

    Swallows all YAML errors — callers use this as a best-effort pre-parse.
    """
    import yaml  # lazy — optional dep
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    raw_includes = data.get("include") or []
    return raw_includes if isinstance(raw_includes, list) else []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_fragment(path: str | Path) -> tuple[StageSpec, ...]:
    """Load a fragment YAML file and return its stages.

    Fragment files have ``fragment: true`` at the top and only the ``stages``
    key is required. Raises ``WorkflowParseError`` on invalid input.
    """
    from workflow.parser import WorkflowParseError, _parse_stage  # noqa: PLC0415

    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise WorkflowParseError(f"fragment file not found: {p}") from None
    except OSError as exc:
        raise WorkflowParseError(f"cannot read fragment {p}: {exc}") from exc
    return _parse_fragment_str(text, source=str(p), parse_stage=_parse_stage)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_fragment_str(
    content: str,
    source: str,
    parse_stage: Callable[[dict[str, Any], str], StageSpec] | None = None,
) -> tuple[StageSpec, ...]:
    """Parse stages from a fragment YAML string."""
    from workflow.parser import WorkflowParseError, _parse_stage as _default_parse_stage  # noqa: PLC0415

    _ps = parse_stage if parse_stage is not None else _default_parse_stage

    import yaml  # lazy — optional dep
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise WorkflowParseError(f"{source}: invalid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise WorkflowParseError(f"{source}: expected a YAML mapping at top level")

    if not data.get("fragment"):
        raise WorkflowParseError(
            f"{source}: fragment YAML must declare 'fragment: true' at the top level"
        )

    if "stages" not in data:
        raise WorkflowParseError(f"{source}: fragment missing required key 'stages'")

    raw_stages = data["stages"]
    if not isinstance(raw_stages, list) or len(raw_stages) == 0:
        raise WorkflowParseError(f"{source}: fragment 'stages' must be a non-empty list")

    return tuple(_ps(s, source) for s in raw_stages)


def _require_list(value: object, field: str, context: str, source: str) -> list[Any]:
    """Return *value* as a list or raise WorkflowParseError."""
    from workflow.parser import WorkflowParseError  # noqa: PLC0415
    if not isinstance(value, (list, tuple)):
        raise WorkflowParseError(
            f"{source}: include '{context}' '{field}' must be a list, "
            f"got {type(value).__name__}"
        )
    return list(value)


def _require_dict(value: object, field: str, context: str, source: str) -> dict[str, Any]:
    """Return *value* as a dict or raise WorkflowParseError."""
    from workflow.parser import WorkflowParseError  # noqa: PLC0415
    if not isinstance(value, dict):
        raise WorkflowParseError(
            f"{source}: include '{context}' '{field}' must be a mapping, "
            f"got {type(value).__name__}"
        )
    return value


def _parse_include(data: object, source: str) -> IncludeSpec:
    """Parse one entry from the top-level ``include:`` list."""
    from workflow.parser import WorkflowParseError  # noqa: PLC0415

    if not isinstance(data, dict):
        raise WorkflowParseError(
            f"{source}: 'include' entry must be a mapping, got {type(data).__name__}"
        )
    if "path" not in data:
        raise WorkflowParseError(f"{source}: include entry missing required key 'path'")

    path_str = str(data["path"])
    raw_prefix = data.get("prefix")
    prefix = Path(path_str).stem if raw_prefix is None else str(raw_prefix)
    raw_depends = _require_list(data.get("depends_on") or [], "depends_on", path_str, source)
    raw_reads = _require_list(data.get("reads_from") or [], "reads_from", path_str, source)
    params_raw = _require_dict(data.get("params") or {}, "params", path_str, source)

    return IncludeSpec(
        path=path_str,
        prefix=prefix,
        depends_on=tuple(str(d) for d in raw_depends),
        reads_from=tuple(str(r) for r in raw_reads),
        params={str(k): str(v) for k, v in params_raw.items()},
    )


def _resolve_frag_path(inc_path: str, source_path: Path | None) -> Path:
    """Resolve a fragment include path to an absolute Path."""
    if source_path is None:
        frag = Path(inc_path)
        return frag if frag.is_absolute() else Path.cwd() / inc_path
    return resolve_fragment_path(inc_path, source_path)


def _load_frag_text(frag_path: Path, source: str) -> str:
    """Read fragment file content, raising WorkflowParseError on failure."""
    from workflow.parser import WorkflowParseError  # noqa: PLC0415

    try:
        return frag_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise WorkflowParseError(
            f"{source}: include references missing fragment file: {frag_path}"
        ) from None
    except OSError as exc:
        raise WorkflowParseError(
            f"{source}: cannot read fragment {frag_path}: {exc}"
        ) from exc


def _inline_frag_stages(
    frag_stages: tuple[StageSpec, ...],
    inc: IncludeSpec,
) -> list[StageSpec]:
    """Rename and inline fragment stages according to the IncludeSpec."""
    rename: dict[str, str] = {
        s.name: s.name if not inc.prefix else f"{inc.prefix}-{s.name}"
        for s in frag_stages
    }

    def _rewrite(refs: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(rename.get(r, r) for r in refs)

    inlined: list[StageSpec] = []
    for frag_stage in frag_stages:
        is_root = frag_stage.depends_on == ()
        new_depends = inc.depends_on if (is_root and inc.depends_on) else _rewrite(frag_stage.depends_on)
        new_reads = inc.reads_from if (is_root and inc.reads_from) else _rewrite(frag_stage.reads_from)
        inlined.append(StageSpec(
            name=rename[frag_stage.name],
            kind=frag_stage.kind,
            description=frag_stage.description,
            agent=frag_stage.agent,
            depends_on=new_depends,
            outputs=frag_stage.outputs,
            validation=frag_stage.validation,
            human_gate=frag_stage.human_gate,
            required=frag_stage.required,
            reads_from=new_reads,
            writes_to=frag_stage.writes_to,
            when=frag_stage.when,
            fan_out=_rewrite_fan_out(frag_stage.fan_out, rename),
            executor=frag_stage.executor,
            script=frag_stage.script,
            sub_workflow=frag_stage.sub_workflow,
            validates_output=frag_stage.validates_output,
        ))
    return inlined


def _rewrite_fan_out(
    fan_out: FanOutSpec | None,
    rename: dict[str, str],
) -> FanOutSpec | None:
    """Return fan_out with source rewritten through the prefix rename map."""
    if fan_out is None:
        return None
    new_source = rename.get(fan_out.source, fan_out.source)
    if new_source == fan_out.source:
        return fan_out
    return cast(FanOutSpec, replace(fan_out, source=new_source))


def _expand_includes(
    stages: tuple[StageSpec, ...],
    includes: tuple[IncludeSpec, ...],
    source_path: Path | None,
    source: str,
    *,
    _visited: frozenset[str] | None = None,
    _path: tuple[str, ...] = (),
) -> tuple[StageSpec, ...]:
    """Inline each IncludeSpec's stages into the parent stage list."""
    from workflow.parser import WorkflowParseError, _parse_stage  # noqa: PLC0415

    visited = _visited if _visited is not None else frozenset()
    expanded = list(stages)
    for inc in includes:
        frag_path = _resolve_frag_path(inc.path, source_path)
        frag_path_key = str(frag_path.resolve())
        frag_path_str = str(frag_path)

        if frag_path_key in visited:
            raise WorkflowParseError(
                f"{source}: circular include detected — '{frag_path_str}' is already "
                f"being expanded (cycle: {' -> '.join(_path + (frag_path_str,))})"
            )

        frag_text = _load_frag_text(frag_path, source)
        frag_stages = _parse_fragment_str(frag_text, source=frag_path_str, parse_stage=_parse_stage)

        frag_raw_includes = _parse_nested_includes(frag_text, frag_path_str)
        if frag_raw_includes:
            frag_stages = _expand_includes(
                frag_stages,
                frag_raw_includes,
                frag_path,
                frag_path_str,
                _visited=visited | {frag_path_key},
                _path=_path + (frag_path_str,),
            )

        expanded.extend(_inline_frag_stages(frag_stages, inc))
    return tuple(expanded)


def _parse_nested_includes(frag_text: str, source: str) -> tuple[IncludeSpec, ...]:
    """Extract and parse the ``include:`` list from a fragment's YAML text."""
    import yaml  # lazy — optional dep
    try:
        data = yaml.safe_load(frag_text)
    except yaml.YAMLError:
        return ()

    if not isinstance(data, dict):
        return ()

    raw_includes = data.get("include")
    if raw_includes is None:
        return ()
    if not isinstance(raw_includes, list):
        from workflow.parser import WorkflowParseError  # noqa: PLC0415
        raise WorkflowParseError(
            f"{source}: 'include' must be a list, got {type(raw_includes).__name__}"
        )
    if not raw_includes:
        return ()

    return tuple(_parse_include(entry, source) for entry in raw_includes)
