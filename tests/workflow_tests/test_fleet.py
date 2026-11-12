"""Tests for workflow fleet: ledger-backed fan-out of one workflow over many items."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import threading
import unittest.mock
from collections.abc import Iterator
from pathlib import Path

from workflow import fleet
from workflow.cli import main
from workflow.fleet import (
    FleetError,
    ItemRecord,
    ItemStatus,
    Ledger,
    enumerate_items,
    ledger_path,
    load_ledger,
    mark_fields,
    save_ledger,
    select_batch,
    update_item,
    workflow_slug,
)

_WORKFLOW = """\
name: fleet-demo
version: "1.0"
description: Fleet test workflow.
trigger:
  source: manual
  params:
    target: ""
stages:
  - name: gather
    kind: gather
    description: Gather facts about {target}.
    agent:
      role: researcher
    outputs:
      - name: facts
        mode: generate
        writes_to: facts.json
  - name: report
    kind: execute
    depends_on: [gather]
    description: Report on {target}.
    agent:
      role: doc-writer
    outputs:
      - name: report
        mode: generate
        writes_to: report.md
"""


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


class _DataHomeCase(unittest.TestCase):
    """Points the ledger root (and workspaces) at a private temp dir."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        patcher = unittest.mock.patch.dict(os.environ, {"DANCING_BEAR_DATA_HOME": str(self.root / "data")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.wf = self.root / "fleet-demo.yaml"
        self.wf.write_text(_WORKFLOW)
        self.ws_base = self.root / "ws"

    def _new_ledger(self, **items: ItemStatus) -> Ledger:
        ledger = Ledger("fleet-demo", str(self.wf), "items:x", "t0", "t0")
        ledger.items = {name: ItemRecord(status=status) for name, status in items.items()}
        save_ledger(ledger)
        return ledger

    def _fleet_run(self, *extra: str) -> tuple[int, str, str]:
        return _run(
            "fleet", "run", str(self.wf), "--fan-over", "items:alpha,beta,gamma",
            "--fan-param", "target={item}", "--base-dir", str(self.ws_base), *extra,
        )

    def _ledger(self) -> Ledger:
        ledger = load_ledger("fleet-demo")
        if ledger is None:
            self.fail("ledger missing")
        return ledger


class EnumerateItemsTests(unittest.TestCase):
    def test_literal_items_dedupe_and_strip(self) -> None:
        self.assertEqual(enumerate_items("items: a, b,,a ,c"), ["a", "b", "c"])

    def test_file_items_skip_blanks_and_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "items.txt"
            path.write_text("# header\nalpha\n\n  beta  \n#gamma\nalpha\n")
            self.assertEqual(enumerate_items(f"file:{path}"), ["alpha", "beta"])

    def test_missing_file(self) -> None:
        with _raises(self, FleetError, "cannot read item file"):
            enumerate_items("file:/nonexistent/items.txt")

    def test_unknown_source(self) -> None:
        with _raises(self, FleetError, "unknown --fan-over source"):
            enumerate_items("teams")

    def test_empty_source(self) -> None:
        with _raises(self, FleetError, "no items"):
            enumerate_items("items: , ,")


class LedgerModelTests(unittest.TestCase):
    def test_slug_normalizes(self) -> None:
        self.assertEqual(workflow_slug("My Flow_v2"), "my-flow-v2")
        self.assertEqual(workflow_slug("../../etc"), "etc")

    def test_slug_rejects_empty(self) -> None:
        with self.assertRaises(FleetError):
            workflow_slug("///")

    def test_round_trip_and_unknown_status(self) -> None:
        ledger = Ledger("wf", "p.yaml", "items:a", "t0", "t1", {"a": ItemRecord(ItemStatus.done, "/w")})
        again = Ledger.from_dict(json.loads(json.dumps(ledger.as_dict())))
        self.assertEqual(again, ledger)
        self.assertEqual(ItemRecord.from_dict({"status": "exploded"}).status, ItemStatus.pending)
        self.assertEqual(Ledger.from_dict({"items": ["junk"]}).items, {})

    def test_select_batch_sorted_and_retries_failed(self) -> None:
        ledger = Ledger("wf", "p", "s", "t", "t", {
            "d": ItemRecord(ItemStatus.pending), "a": ItemRecord(ItemStatus.done),
            "c": ItemRecord(ItemStatus.failed), "b": ItemRecord(ItemStatus.running),
            "e": ItemRecord(ItemStatus.pending),
        })
        self.assertEqual(select_batch(ledger, 2), ["c", "d"])
        self.assertEqual(select_batch(ledger, 0), ["c", "d", "e"])

    def test_mark_fields(self) -> None:
        running = mark_fields(ItemStatus.running, None, None)
        self.assertIsNone(running["completed_at"])
        self.assertNotIn("workspace", running)
        done = mark_fields(ItemStatus.done, "/w", None)
        self.assertEqual((done["status"], done["workspace"]), ("done", "/w"))
        self.assertIsNotNone(done["completed_at"])
        with _raises(self, FleetError, "fleet reset"):
            mark_fields(ItemStatus.pending, None, None)


class LedgerIoTests(_DataHomeCase):
    def test_ledger_lives_under_data_home(self) -> None:
        self.assertEqual(
            ledger_path("fleet-demo"),
            self.root / "data" / "workflow-fleet" / "fleet-demo" / "ledger.json",
        )

    def test_missing_ledger_read_creates_nothing(self) -> None:
        self.assertIsNone(load_ledger("fleet-demo"))
        self.assertFalse((self.root / "data").exists())

    def test_update_item_requires_ledger_and_item(self) -> None:
        with _raises(self, FleetError, "no fleet ledger"):
            update_item("fleet-demo", "a", status="done")
        self._new_ledger(a=ItemStatus.pending)
        with _raises(self, FleetError, "not in the"):
            update_item("fleet-demo", "zz", status="done")

    def test_corrupt_ledger_is_an_error(self) -> None:
        path = ledger_path("fleet-demo")
        path.parent.mkdir(parents=True)
        path.write_text("[not a ledger")
        with _raises(self, FleetError, "cannot read fleet ledger"):
            load_ledger("fleet-demo")

    def test_concurrent_marks_are_not_lost(self) -> None:
        names = [f"item{i:02d}" for i in range(24)]
        self._new_ledger(**dict.fromkeys(names, ItemStatus.running))
        threads = [
            threading.Thread(target=update_item, args=("fleet-demo", n), kwargs={"status": "done"})
            for n in names
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(self._ledger().counts()[ItemStatus.done], len(names))


class FleetRunCliTests(_DataHomeCase):
    def test_dry_run_writes_nothing(self) -> None:
        code, out, err = self._fleet_run("--batch-size", "2", "--dry-run", "-f", "json")
        self.assertEqual(code, 0, err)
        self.assertEqual([r["item"] for r in json.loads(out)], ["alpha", "beta"])
        self.assertIn("2 would start", err)
        self.assertFalse((self.root / "data").exists())
        self.assertFalse(self.ws_base.exists())

    def test_run_inits_workspace_per_batch_item(self) -> None:
        code, out, err = self._fleet_run("--batch-size", "2", "-f", "json")
        self.assertEqual(code, 0, err)
        rows = json.loads(out)
        self.assertEqual([(r["item"], r["status"]) for r in rows], [("alpha", "running"), ("beta", "running")])
        ledger = self._ledger()
        self.assertEqual(ledger.items["gamma"].status, ItemStatus.pending)
        for item in ("alpha", "beta"):
            ws = Path(ledger.items[item].workspace or "")
            manifest = json.loads((ws / "manifest.json").read_text())
            self.assertEqual(manifest["trigger_params"]["target"], item)
            self.assertTrue((ws / "plan.json").is_file())

    def test_failed_item_retry_reuses_workspace(self) -> None:
        self._fleet_run("--batch-size", "1")
        first = self._ledger().items["alpha"].workspace
        self.assertEqual(_run("fleet", "mark", str(self.wf), "alpha", "failed", "--error", "boom")[0], 0)
        code, _, err = self._fleet_run("--batch-size", "1")
        self.assertEqual(code, 0, err)
        rec = self._ledger().items["alpha"]
        self.assertEqual((rec.status, rec.workspace, rec.error), (ItemStatus.running, first, None))

    def test_force_items_restarts_fresh(self) -> None:
        self._fleet_run("--batch-size", "1")
        first = self._ledger().items["alpha"].workspace
        code, _, _ = self._fleet_run("--batch-size", "1", "--force-items", "alpha")
        self.assertEqual(code, 0)
        self.assertNotEqual(self._ledger().items["alpha"].workspace, first)

    def test_bad_source_and_param_write_nothing(self) -> None:
        for extra in (("--fan-over", "teams"), ("--fan-param", "no-equals")):
            with self.subTest(extra=extra):
                code, _, err = _run("fleet", "run", str(self.wf), "--fan-over", "items:a", *extra)
                self.assertEqual(code, 1)
                self.assertIn("Error", err)
        self.assertFalse((self.root / "data").exists())

    def test_negative_batch_size_is_usage_error(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            self._fleet_run("--batch-size", "-1")
        self.assertEqual(ctx.exception.code, 2)

    def test_unknown_workflow(self) -> None:
        code, _, err = _run("fleet", "run", str(self.root / "nope.yaml"), "--fan-over", "items:a")
        self.assertEqual(code, 1)
        self.assertIn("not found", err)

    def test_workspace_init_failure_marks_item_failed(self) -> None:
        code, out, _ = self._fleet_run("--batch-size", "1", "--base-dir", str(self.root / "bad dir"), "-f", "json")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)[0]["status"], "failed")
        rec = self._ledger().items["alpha"]
        self.assertEqual(rec.status, ItemStatus.failed)
        self.assertTrue(rec.error)


class FleetStatusAndReportCliTests(_DataHomeCase):
    def test_status_without_ledger(self) -> None:
        code, _, err = _run("fleet", "status", str(self.wf))
        self.assertEqual(code, 1)
        self.assertIn("no fleet ledger", err)

    def test_status_filter(self) -> None:
        self._new_ledger(a=ItemStatus.done, b=ItemStatus.failed, c=ItemStatus.pending)
        code, out, _ = _run("fleet", "status", str(self.wf), "--filter", "failed", "-f", "json")
        self.assertEqual(code, 0)
        self.assertEqual([r["item"] for r in json.loads(out)], ["b"])

    def test_reset_by_filter_and_items(self) -> None:
        self._new_ledger(a=ItemStatus.done, b=ItemStatus.failed, c=ItemStatus.failed)
        code, out, _ = _run("fleet", "reset", str(self.wf), "--filter", "failed", "--items", "a")
        self.assertEqual(code, 0)
        self.assertIn("Reset 3", out)
        self.assertEqual(set(self._ledger().counts()), {ItemStatus.pending})

    def test_reset_requires_selector_and_known_items(self) -> None:
        self._new_ledger(a=ItemStatus.done)
        self.assertEqual(_run("fleet", "reset", str(self.wf))[0], 2)
        code, _, err = _run("fleet", "reset", str(self.wf), "--items", "a,zz")
        self.assertEqual(code, 1)
        self.assertIn("zz", err)
        self.assertEqual(self._ledger().items["a"].status, ItemStatus.done)

    def test_report_reads_stage_progress(self) -> None:
        self._fleet_run("--batch-size", "1")
        ws = self._ledger().items["alpha"].workspace or ""
        self.assertEqual(_run("set-state", ws, "gather")[0], 0)
        code, out, _ = _run("fleet", "report", str(self.wf), "-f", "json")
        self.assertEqual(code, 0)
        rows = {r["item"]: r for r in json.loads(out)}
        self.assertEqual((rows["alpha"]["stages_done"], rows["alpha"]["stages_total"]), (1, 2))
        self.assertEqual(rows["beta"]["stages_done"], "-")

    def test_report_table_totals(self) -> None:
        self._new_ledger(a=ItemStatus.done, b=ItemStatus.failed)
        code, out, _ = _run("fleet", "report", str(self.wf))
        self.assertEqual(code, 0)
        self.assertIn("TOTAL  pending=0 running=0 done=1 failed=1 skipped=0", out)


class FleetMarkCliTests(_DataHomeCase):
    def setUp(self) -> None:
        super().setUp()
        self._fleet_run("--batch-size", "1")
        self.ws = self._ledger().items["alpha"].workspace or ""

    def _mark(self, *argv: str) -> tuple[int, str, str]:
        return _run("fleet", "mark", str(self.wf), *argv)

    def test_done_refused_while_stages_remain(self) -> None:
        code, _, err = self._mark("alpha", "done")
        self.assertEqual(code, 1)
        self.assertIn("2 stage(s) still to run", err)
        self.assertEqual(self._ledger().items["alpha"].status, ItemStatus.running)

    def test_done_accepted_once_stages_complete(self) -> None:
        for stage in ("gather", "report"):
            self.assertEqual(_run("set-state", self.ws, stage)[0], 0)
        code, out, _ = self._mark("alpha", "done")
        self.assertEqual(code, 0)
        self.assertIn("Marked alpha done", out)
        rec = self._ledger().items["alpha"]
        self.assertEqual(rec.status, ItemStatus.done)
        self.assertIsNotNone(rec.completed_at)

    def test_force_overrides_progress_check(self) -> None:
        self.assertEqual(self._mark("alpha", "done", "--force")[0], 0)
        self.assertEqual(self._ledger().items["alpha"].status, ItemStatus.done)

    def test_failed_records_error_and_workspace(self) -> None:
        code, _, _ = self._mark("alpha", "failed", "--error", "boom", "--workspace", "/elsewhere")
        self.assertEqual(code, 0)
        rec = self._ledger().items["alpha"]
        self.assertEqual((rec.status, rec.error, rec.workspace), (ItemStatus.failed, "boom", "/elsewhere"))

    def test_unknown_item(self) -> None:
        code, _, err = self._mark("nobody", "done")
        self.assertEqual(code, 1)
        self.assertIn("not in the", err)

    def test_pending_is_not_a_mark_status(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            self._mark("alpha", "pending")
        self.assertEqual(ctx.exception.code, 2)


class FleetModuleBoundaryTests(unittest.TestCase):
    def test_no_subprocess_execution(self) -> None:
        """The ledger must not shell out to `workflow run --execute` (false greens)."""
        source = Path(fleet.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", source)


if __name__ == "__main__":
    unittest.main()
