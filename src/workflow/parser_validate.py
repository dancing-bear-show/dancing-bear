"""Cross-stage validators for parsed workflow definitions (uniqueness, refs, DAG ordering)."""

from __future__ import annotations

from .models import StageSpec
from .parser_errors import WorkflowParseError


def _validate_unique_names(stages: tuple[StageSpec, ...], source: str) -> None:
    """Reject duplicate stage names."""
    seen: set[str] = set()
    for stage in stages:
        if stage.name in seen:
            raise WorkflowParseError(f"{source}: duplicate stage name '{stage.name}'")
        seen.add(stage.name)


def _validate_refs(stages: tuple[StageSpec, ...], source: str) -> None:
    """Ensure depends_on and reads_from reference existing stage names."""
    names = {s.name for s in stages}
    for stage in stages:
        for dep in stage.depends_on:
            if dep not in names:
                raise WorkflowParseError(
                    f"{source}: stage '{stage.name}' depends_on unknown stage '{dep}'"
                )
        for ref in stage.reads_from:
            if ref not in names:
                raise WorkflowParseError(
                    f"{source}: stage '{stage.name}' reads_from unknown stage '{ref}'"
                )


def _validate_dag(stages: tuple[StageSpec, ...], source: str) -> None:
    """Detect cycles in the dependency graph via iterative DFS."""
    adjacency: dict[str, list[str]] = {s.name: list(s.depends_on) for s in stages}
    state: dict[str, int] = dict.fromkeys(adjacency, 0)

    for start in adjacency:
        if state[start] == 2:
            continue
        _dfs_visit(start, adjacency, state, source)


def _dfs_visit(
    start: str,
    adjacency: dict[str, list[str]],
    state: dict[str, int],
    source: str,
) -> None:
    """Run iterative DFS from *start*, updating *state* in place."""
    stack: list[tuple[str, int]] = [(start, 0)]
    while stack:
        node, idx = stack.pop()
        if idx == 0:
            if state[node] == 1:
                raise WorkflowParseError(
                    f"{source}: dependency cycle detected involving stage '{node}'"
                )
            if state[node] == 2:
                continue
            state[node] = 1
        neighbors = adjacency.get(node, [])
        if idx < len(neighbors):
            stack.append((node, idx + 1))
            stack.append((neighbors[idx], 0))
        else:
            state[node] = 2


def _validate_reads_from_ordering(
    stages: tuple[StageSpec, ...], source: str
) -> None:
    """Validate that reads_from entries are transitively reachable via depends_on."""
    deps: dict[str, set[str]] = {s.name: set(s.depends_on) for s in stages}
    _cache: dict[str, set[str]] = {}

    def _transitive_deps(name: str) -> set[str]:
        if name in _cache:
            return _cache[name]
        visited: set[str] = set()
        stack = list(deps.get(name, set()))
        while stack:
            dep = stack.pop()
            if dep not in visited:
                visited.add(dep)
                stack.extend(deps.get(dep, set()) - visited)
        _cache[name] = visited
        return visited

    for spec in stages:
        if not spec.reads_from:
            continue
        reachable = _transitive_deps(spec.name)
        for rf in spec.reads_from:
            if rf not in reachable:
                raise WorkflowParseError(
                    f"{source}: stage '{spec.name}' reads_from '{rf}' but "
                    f"'{rf}' is not a transitive dependency (via depends_on). "
                    f"Add '{rf}' to the depends_on chain to ensure ordering."
                )
