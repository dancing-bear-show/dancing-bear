"""Tests for workflow.dispatchers — LocalDispatcher unique behaviors not in test_dispatchers.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow.dispatchers import LocalDispatcher
from workflow.models import StageResult

from tests.workflow_tests.helpers.factories import (
    make_resolved_stage,
    make_stage_spec,
)


class TestLocalDispatcherDispatchGroup(unittest.TestCase):
    """dispatch_group sequential: result types verified."""

    def test_results_are_stage_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            spec_a = make_stage_spec(name="stage-alpha")
            spec_b = make_stage_spec(name="stage-beta")
            stage_a = make_resolved_stage(spec=spec_a, index=0)
            stage_b = make_resolved_stage(spec=spec_b, index=1)
            dispatcher = LocalDispatcher()

            results = dispatcher.dispatch_group([stage_a, stage_b], tmp_path)

            self.assertIsInstance(results["stage-alpha"], StageResult)
            self.assertIsInstance(results["stage-beta"], StageResult)


if __name__ == "__main__":
    unittest.main()
