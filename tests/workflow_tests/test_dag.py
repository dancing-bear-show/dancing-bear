"""Tests for workflow.dag.bfs_levels and its two callers.

The compiler must raise on a cycle; the linter's depth count must not.
"""

from __future__ import annotations

import unittest

from tests.workflow_tests.helpers.factories import make_stage_spec
from workflow.compiler import WorkflowCompileError, _compute_parallel_groups
from workflow.dag import bfs_levels
from workflow.linter import _compute_dag_depth

_DIAMOND = {"root": (), "left": ("root",), "right": ("root",), "merge": ("left", "right")}
_CYCLE_BEHIND_ROOT = {"root": (), "a": ("root", "b"), "b": ("a",)}


def _stages(deps: dict[str, tuple[str, ...]], gated: frozenset[str] = frozenset()):
    return tuple(
        make_stage_spec(name=name, depends_on=d, human_gate=name in gated)
        for name, d in deps.items()
    )


class TestBfsLevels(unittest.TestCase):
    def test_empty(self) -> None:
        walk = bfs_levels({})
        self.assertEqual(walk.levels, ())
        self.assertEqual(walk.unresolved, frozenset())

    def test_diamond_levels_are_sorted(self) -> None:
        walk = bfs_levels(_DIAMOND)
        self.assertEqual(walk.levels, (("root",), ("left", "right"), ("merge",)))
        self.assertEqual(walk.unresolved, frozenset())

    def test_cycle_is_returned_not_raised(self) -> None:
        walk = bfs_levels(_CYCLE_BEHIND_ROOT)
        self.assertEqual(walk.levels, (("root",),))
        self.assertEqual(walk.unresolved, frozenset({"a", "b"}))

    def test_self_and_unknown_dependencies_never_resolve(self) -> None:
        walk = bfs_levels({"a": ("a",), "b": ("missing",), "c": ()})
        self.assertEqual(walk.levels, (("c",),))
        self.assertEqual(walk.unresolved, frozenset({"a", "b"}))


class TestCompilerParallelGroups(unittest.TestCase):
    def test_diamond_groups(self) -> None:
        self.assertEqual(
            _compute_parallel_groups(_stages(_DIAMOND)),
            (("root",), ("left", "right"), ("merge",)),
        )

    def test_human_gate_isolated_within_level(self) -> None:
        groups = _compute_parallel_groups(_stages(_DIAMOND, gated=frozenset({"left"})))
        self.assertEqual(groups, (("root",), ("right",), ("left",), ("merge",)))

    def test_cycle_raises(self) -> None:
        with self.assertRaises(WorkflowCompileError) as ctx:
            _compute_parallel_groups(_stages(_CYCLE_BEHIND_ROOT))
        self.assertIn("Cyclic dependency detected involving stages: a, b", str(ctx.exception))

    def test_unknown_dependency_raises(self) -> None:
        with self.assertRaises(WorkflowCompileError) as ctx:
            _compute_parallel_groups(_stages({"a": ("ghost",)}))
        self.assertIn("unknown stage 'ghost'", str(ctx.exception))


class TestLinterDagDepth(unittest.TestCase):
    def test_diamond_depth(self) -> None:
        self.assertEqual(_compute_dag_depth(_stages(_DIAMOND)), 3)

    def test_cycle_behind_root_counts_reachable_levels_only(self) -> None:
        self.assertEqual(_compute_dag_depth(_stages(_CYCLE_BEHIND_ROOT)), 1)

    def test_pure_cycle_is_zero_without_raising(self) -> None:
        self.assertEqual(_compute_dag_depth(_stages({"a": ("b",), "b": ("a",)})), 0)


if __name__ == "__main__":
    unittest.main()
