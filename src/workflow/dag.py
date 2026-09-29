"""Level-by-level topological walk of a stage dependency graph.

Shared by the compiler (parallel groups; a cycle is fatal) and the linter
(DAG depth; a cycle is reported elsewhere, so the walk must not raise).
"""
from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass

__all__ = ["DagLevels", "bfs_levels"]


@dataclass(frozen=True)
class DagLevels:
    """BFS levels of a DAG plus the stages the walk could never reach."""

    levels: tuple[tuple[str, ...], ...]
    unresolved: frozenset[str]


def bfs_levels(deps: Mapping[str, Collection[str]]) -> DagLevels:
    """Group stages into BFS levels, each sorted by name.

    A stage joins a level once every one of its dependencies sits in an earlier
    level. Stages on a cycle, downstream of one, or depending on a name not in
    *deps* never qualify; they are returned in ``unresolved`` rather than raised,
    so each caller chooses whether that is an error.
    """
    placed: set[str] = set()
    levels: list[tuple[str, ...]] = []
    ready = sorted(name for name, d in deps.items() if not d)
    while ready:
        levels.append(tuple(ready))
        placed.update(ready)
        ready = sorted(
            name
            for name, d in deps.items()
            if name not in placed and all(dep in placed for dep in d)
        )
    return DagLevels(levels=tuple(levels), unresolved=frozenset(deps.keys() - placed))
