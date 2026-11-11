"""Tests for workflow set-state / seed-pr-lifecycle: hand-seeded stage markers."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path

from workflow.cli import main
from workflow.models import StageStatus
from workflow.persistence import list_stage_results, read_stage_result, write_stage_result
from workflow.set_state import (
    PrSeed,
    SeedError,
    SetStateRequest,
    next_stage_index,
    seed_pr_lifecycle,
    set_state,
)

from tests.workflow_tests.helpers.factories import make_stage_result

_PLAN = ["build", "pr-open-pr", "pr-wait-for-ci", "pr-qlty-check", "pr-post-fix-review"]
_PR_SUFFIXES = ("open-pr", "wait-for-ci", "qlty-check", "post-fix-review")


def _make_workspace(root: Path, stages: list[str] | None = None) -> Path:
    """A run workspace with manifest.json and a plan.json listing *stages*."""
    ws = root / "wf-run"
    (ws / "stages").mkdir(parents=True)
    (ws / "manifest.json").write_text(json.dumps({"workflow": "wf", "parallel_groups": []}))
    plan = {"parallel_groups": [{"stages": [s]} for s in (stages if stages is not None else _PLAN)]}
    (ws / "plan.json").write_text(json.dumps(plan))
    return ws


def _run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


@contextlib.contextmanager
def _raises(case: unittest.TestCase, exc_type: type[Exception], needle: str) -> Iterator[None]:
    """assertRaises plus a substring check on the message."""
    with case.assertRaises(exc_type) as ctx:
        yield
    case.assertIn(needle, str(ctx.exception))


class _WorkspaceCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ws = _make_workspace(Path(tmp.name))

    def _resume_rows(self) -> dict[str, dict[str, str]]:
        code, out, _ = _run("resume", str(self.ws), "--format", "json")
        self.assertIn(code, (0, 2))
        return {row["stage"]: row for row in json.loads(out)}


class SetStateFunctionTests(_WorkspaceCase):
    def test_next_index_is_zero_for_empty_workspace(self) -> None:
        self.assertEqual(next_stage_index(self.ws), 0)

    def test_next_index_follows_highest_existing(self) -> None:
        write_stage_result(self.ws, make_stage_result(stage_name="build", stage_index=7))
        self.assertEqual(next_stage_index(self.ws), 8)

    def test_marker_outranks_earlier_failure(self) -> None:
        """The recovery case: a failed marker is superseded, not edited."""
        write_stage_result(
            self.ws,
            make_stage_result(stage_name="build", stage_index=0, status=StageStatus.failed),
        )
        seeded = set_state(self.ws, "build", SetStateRequest(note="fixed by hand"), _PLAN)
        self.assertEqual(seeded.stage_index, 1)
        latest = read_stage_result(self.ws, "build")
        if latest is None:
            self.fail("no marker for build")
        self.assertEqual(latest.status, StageStatus.success)
        self.assertEqual(latest.metadata["seeded_by"], "workflow-set-state")
        self.assertEqual(latest.metadata["note"], "fixed by hand")
        # The older marker is kept as history.
        self.assertEqual(len(list_stage_results(self.ws)), 2)

    def test_explicit_index_and_data(self) -> None:
        req = SetStateRequest(status=StageStatus.skipped, data={"pr": 5}, stage_index=42)
        seeded = set_state(self.ws, "build", req, _PLAN)
        self.assertEqual(seeded.path.name, "042-build.json")
        body = json.loads(seeded.path.read_text())
        self.assertEqual(body["status"], "skipped")
        self.assertEqual(body["data"], {"pr": 5})
        self.assertNotIn("note", body["metadata"])

    def test_rejects_unsafe_names_without_writing(self) -> None:
        for name in ("../escape", "a/b", "", "-lead", "x.json", "a b"):
            with self.subTest(name=name), self.assertRaises(SeedError):
                set_state(self.ws, name, SetStateRequest())
        self.assertEqual(sorted(p.name for p in self.ws.rglob("*.json")), ["manifest.json", "plan.json"])
        self.assertEqual(list((self.ws / "stages").iterdir()), [])

    def test_rejects_stage_outside_plan(self) -> None:
        with _raises(self, SeedError, "not in this run's plan"):
            set_state(self.ws, "typo", SetStateRequest(), _PLAN)
        self.assertEqual(list((self.ws / "stages").iterdir()), [])

    def test_no_plan_allows_any_safe_name(self) -> None:
        seeded = set_state(self.ws, "anything", SetStateRequest(), known_stages=())
        self.assertTrue(seeded.path.is_file())

    def test_rejects_negative_index(self) -> None:
        with _raises(self, SeedError, ">= 0"):
            set_state(self.ws, "build", SetStateRequest(stage_index=-1), _PLAN)


class SeedPrLifecycleFunctionTests(_WorkspaceCase):
    def test_seeds_every_stage_consecutively(self) -> None:
        write_stage_result(self.ws, make_stage_result(stage_name="build", stage_index=0))
        seeded = seed_pr_lifecycle(
            self.ws, "pr", _PR_SUFFIXES, PrSeed(9, url="https://example.invalid/9"), _PLAN,
        )
        self.assertEqual([s.stage_name for s in seeded], _PLAN[1:])
        self.assertEqual([s.stage_index for s in seeded], [1, 2, 3, 4])
        open_pr = json.loads(seeded[0].path.read_text())
        self.assertEqual(open_pr["data"], {"pr": 9, "pr_number": 9, "url": "https://example.invalid/9"})
        wait = json.loads(seeded[1].path.read_text())
        self.assertEqual(wait["data"], {"pr": 9})

    def test_wrong_prefix_writes_nothing(self) -> None:
        with _raises(self, SeedError, "not in this run's plan"):
            seed_pr_lifecycle(self.ws, "nope", _PR_SUFFIXES, PrSeed(9), _PLAN)
        self.assertEqual(list((self.ws / "stages").iterdir()), [])

    def test_partial_plan_match_writes_nothing(self) -> None:
        """All names are checked before the first write."""
        plan = _PLAN[:-1]
        with self.assertRaises(SeedError):
            seed_pr_lifecycle(self.ws, "pr", _PR_SUFFIXES, PrSeed(9), plan)
        self.assertEqual(list((self.ws / "stages").iterdir()), [])

    def test_unsafe_prefix_rejected(self) -> None:
        with _raises(self, SeedError, "invalid stage name"):
            seed_pr_lifecycle(self.ws, "../x", _PR_SUFFIXES, PrSeed(9))

    def test_non_positive_pr_rejected(self) -> None:
        for pr in (0, -3):
            with self.subTest(pr=pr), _raises(self, SeedError, "positive"):
                seed_pr_lifecycle(self.ws, "pr", _PR_SUFFIXES, PrSeed(pr))

    def test_empty_fragment_rejected(self) -> None:
        with _raises(self, SeedError, "no stages"):
            seed_pr_lifecycle(self.ws, "pr", (), PrSeed(9))


class SetStateCliTests(_WorkspaceCase):
    def test_happy_path_flips_resume_row(self) -> None:
        self.assertEqual(self._resume_rows()["build"]["needs_run"], "yes")
        code, out, err = _run(
            "set-state", str(self.ws), "build", "--data", '{"pr": 711}',
            "--note", "merged manually", "--format", "json",
        )
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["stage_name"], "build")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(self._resume_rows()["build"]["needs_run"], "no")

    def test_unknown_workspace(self) -> None:
        code, out, err = _run("set-state", str(self.ws / "missing"), "build")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("not found", err)

    def test_stage_not_in_plan(self) -> None:
        code, _, err = _run("set-state", str(self.ws), "typo")
        self.assertEqual(code, 1)
        self.assertIn("not in this run's plan", err)
        self.assertEqual(list((self.ws / "stages").iterdir()), [])

    def test_invalid_status_is_usage_error(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            _run("set-state", str(self.ws), "build", "--status", "done")
        self.assertEqual(ctx.exception.code, 2)

    def test_bad_data_json(self) -> None:
        for data, needle in (("{oops", "invalid --data JSON"), ("[1, 2]", "expected an object")):
            with self.subTest(data=data):
                code, _, err = _run("set-state", str(self.ws), "build", "--data", data)
                self.assertEqual(code, 1)
                self.assertIn(needle, err)
        self.assertEqual(list((self.ws / "stages").iterdir()), [])

    def test_failed_status_keeps_stage_pending_in_resume(self) -> None:
        code, _, _ = _run("set-state", str(self.ws), "build", "--status", "failed")
        self.assertEqual(code, 0)
        row = self._resume_rows()["build"]
        self.assertEqual((row["status"], row["needs_run"]), ("failed", "yes"))


class SeedPrLifecycleCliTests(_WorkspaceCase):
    def test_default_fragment_seeds_shipped_stage_names(self) -> None:
        code, out, err = _run(
            "seed-pr-lifecycle", str(self.ws), "pr", "--pr", "12", "--format", "json",
        )
        self.assertEqual(code, 0, err)
        self.assertEqual([r["stage"] for r in json.loads(out)], _PLAN[1:])
        rows = self._resume_rows()
        self.assertEqual([rows[s]["needs_run"] for s in _PLAN[1:]], ["no"] * 4)
        self.assertEqual(rows["build"]["needs_run"], "yes")

    def test_explicit_fragment(self) -> None:
        frag = self.ws.parent / "frag.yaml"
        frag.write_text(
            "fragment: true\nname: f\nstages:\n"
            "  - name: build\n    kind: execute\n    description: d\n"
            "    agent: {role: code-writer}\n"
        )
        ws = _make_workspace(self.ws.parent / "other", ["x-build"])
        code, _, err = _run("seed-pr-lifecycle", str(ws), "x", "--pr", "3", "--fragment", str(frag))
        self.assertEqual(code, 0, err)
        self.assertIsNotNone(read_stage_result(ws, "x-build"))

    def test_missing_fragment(self) -> None:
        code, _, err = _run(
            "seed-pr-lifecycle", str(self.ws), "pr", "--pr", "12",
            "--fragment", str(self.ws / "nope.yaml"),
        )
        self.assertEqual(code, 1)
        self.assertIn("fragment file not found", err)

    def test_wrong_prefix(self) -> None:
        code, _, err = _run("seed-pr-lifecycle", str(self.ws), "zz", "--pr", "12")
        self.assertEqual(code, 1)
        self.assertIn("zz-open-pr", err)
        self.assertEqual(list((self.ws / "stages").iterdir()), [])

    def test_unknown_workspace(self) -> None:
        code, _, err = _run("seed-pr-lifecycle", str(self.ws / "missing"), "pr", "--pr", "1")
        self.assertEqual(code, 1)
        self.assertIn("not found", err)

    def test_pr_required(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            _run("seed-pr-lifecycle", str(self.ws), "pr")
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
