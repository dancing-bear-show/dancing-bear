"""Poll state files: lifecycle, tolerant loading, and signalling safety."""

from __future__ import annotations

import json
import os
import signal
import time
import unittest
from pathlib import Path
from unittest import mock

from monitor_poll import state
from tests.fixtures import TempDirMixin


class TrackedPollTests(TempDirMixin, unittest.TestCase):
    def _only_file(self) -> dict:
        files = list(Path(self.tmpdir).glob("*.json"))
        self.assertEqual(len(files), 1)
        return json.loads(files[0].read_text())

    def test_records_running_then_caller_set_status(self):
        root = Path(self.tmpdir)
        with state.tracked_poll("file", {"path": "/x"}, root) as st:
            self.assertEqual(self._only_file()["status"], state.STATUS_RUNNING)
            st.status = state.STATUS_DONE
        data = self._only_file()
        self.assertEqual((data["status"], data["condition"], data["pid"]), ("done", "file", os.getpid()))
        self.assertEqual(data["args"], {"path": "/x"})

    def test_unset_status_is_recorded_as_error(self):
        with state.tracked_poll("file", {}, Path(self.tmpdir)) as st:
            self.assertEqual(st.status, state.STATUS_RUNNING)
        self.assertEqual(self._only_file()["status"], state.STATUS_ERROR)

    def test_exception_is_recorded_as_error_and_reraised(self):
        with self.assertRaises(RuntimeError):
            with state.tracked_poll("file", {}, Path(self.tmpdir)):
                raise RuntimeError("boom")
        self.assertEqual(self._only_file()["status"], state.STATUS_ERROR)

    def test_interrupt_is_recorded_as_error(self):
        with self.assertRaises(KeyboardInterrupt):
            with state.tracked_poll("file", {}, Path(self.tmpdir)):
                raise KeyboardInterrupt
        self.assertEqual(self._only_file()["status"], state.STATUS_ERROR)

    def test_unwritable_directory_warns_instead_of_raising(self):
        blocker = Path(self.tmpdir) / "file-not-dir"
        blocker.write_text("x")
        with mock.patch("sys.stderr") as err:
            with state.tracked_poll("file", {}, blocker / "sub") as st:
                st.status = state.STATUS_DONE
        written = "".join(str(a) for call in err.write.call_args_list for a in call.args)
        self.assertIn("warning", written.lower())


class LoadStatesTests(TempDirMixin, unittest.TestCase):
    def test_skips_unparseable_and_non_object_files(self):
        root = Path(self.tmpdir)
        (root / "bad.json").write_text("{not json")
        (root / "list.json").write_text("[1, 2]")
        (root / "ok.json").write_text(json.dumps({"poll_id": "a", "pid": "12", "status": "done"}))
        loaded = state.load_states(root)
        self.assertEqual([(s.poll_id, s.pid) for s in loaded], [("a", 12)])

    def test_malformed_fields_degrade_to_safe_defaults(self):
        st = state.PollState.from_dict({"poll_id": "a", "pid": None, "args": "oops"})
        self.assertEqual(st and (st.pid, st.args, st.status), (0, {}, "unknown"))

    def test_missing_directory_loads_nothing(self):
        self.assertEqual(state.load_states(Path(self.tmpdir) / "absent"), [])

    def test_sorted_by_start_time(self):
        root = Path(self.tmpdir)
        for pid_, started in (("b", "2026-01-02"), ("a", "2026-01-03"), ("c", "2026-01-01")):
            (root / f"{pid_}.json").write_text(json.dumps({"poll_id": pid_, "started_at": started}))
        self.assertEqual([s.poll_id for s in state.load_states(root)], ["c", "b", "a"])


class PruneTests(TempDirMixin, unittest.TestCase):
    def test_deletes_only_files_older_than_cutoff(self):
        root = Path(self.tmpdir)
        old, new = root / "old.json", root / "new.json"
        old.write_text("{}")
        new.write_text("{}")
        week_ago = time.time() - 7 * 24 * 3600
        os.utime(old, (week_ago, week_ago))
        state.prune_stale(root)
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())

    def test_running_poll_with_alive_pid_survives_pruning(self):
        root = Path(self.tmpdir)
        path = root / "p1.json"
        path.write_text(json.dumps({"poll_id": "p1", "pid": 4242, "status": state.STATUS_RUNNING}))
        week_ago = time.time() - 7 * 24 * 3600
        os.utime(path, (week_ago, week_ago))
        with mock.patch.object(state, "is_pid_alive", return_value=True):
            state.prune_stale(root)
        self.assertTrue(path.exists())

    def test_running_poll_with_dead_pid_is_pruned(self):
        root = Path(self.tmpdir)
        path = root / "p2.json"
        path.write_text(json.dumps({"poll_id": "p2", "pid": 4242, "status": state.STATUS_RUNNING}))
        week_ago = time.time() - 7 * 24 * 3600
        os.utime(path, (week_ago, week_ago))
        with mock.patch.object(state, "is_pid_alive", return_value=False):
            state.prune_stale(root)
        self.assertFalse(path.exists())


class FindAndSignalTests(unittest.TestCase):
    def _st(self, **kw) -> state.PollState:
        base = {"poll_id": "p1", "pid": 4242, "condition": "file", "status": state.STATUS_RUNNING}
        return state.PollState(**{**base, **kw})

    def test_find_by_poll_id_or_pid(self):
        states = [self._st(), self._st(poll_id="p2", pid=7)]
        by_id = state.find_state(states, "p2", None)
        by_pid = state.find_state(states, None, 4242)
        self.assertEqual(by_id.pid if by_id else None, 7)
        self.assertEqual(by_pid.poll_id if by_pid else None, "p1")
        self.assertIsNone(state.find_state(states, "nope", None))

    def test_pid_zero_never_matches_a_corrupt_entry(self):
        self.assertIsNone(state.find_state([self._st(pid=0)], None, 0))

    def test_skip_reasons(self):
        self.assertIn("no pid", state.skip_signal_reason(self._st(pid=0)) or "")
        self.assertIn("finished", state.skip_signal_reason(self._st(status="done")) or "")
        with mock.patch.object(state, "is_pid_alive", return_value=False):
            self.assertIn("not found", state.skip_signal_reason(self._st()) or "")
        with mock.patch.object(state, "is_pid_alive", return_value=True):
            self.assertIsNone(state.skip_signal_reason(self._st()))

    def test_is_pid_alive_handles_eperm_esrch_and_nonpositive(self):
        with mock.patch.object(state.os, "kill", side_effect=PermissionError):
            self.assertTrue(state.is_pid_alive(5))
        with mock.patch.object(state.os, "kill", side_effect=ProcessLookupError):
            self.assertFalse(state.is_pid_alive(5))
        self.assertFalse(state.is_pid_alive(0))
        self.assertTrue(state.is_pid_alive(os.getpid()))

    def test_send_sigterm_reports_failure_message(self):
        with mock.patch.object(state.os, "kill") as kill:
            self.assertIsNone(state.send_sigterm(99))
            kill.assert_called_once_with(99, signal.SIGTERM)
        with mock.patch.object(state.os, "kill", side_effect=PermissionError("denied")):
            self.assertIn("denied", state.send_sigterm(99) or "")


if __name__ == "__main__":
    unittest.main()
