"""CLI wiring: argv shape, exit codes, output records, status/cancel."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from monitor_poll import cli, state
from monitor_poll.engine import Outcome, Probe
from tests.fixtures import TempDirMixin, capture_stderr, capture_stdout


class CliTestCase(TempDirMixin, unittest.TestCase):
    """Points the state dir at a private temp dir for every test."""

    def setUp(self) -> None:
        super().setUp()
        self.data_home = Path(self.tmpdir) / "data"
        env = mock.patch.dict(os.environ, {"DANCING_BEAR_DATA_HOME": str(self.data_home)})
        env.start()
        self.addCleanup(env.stop)

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        with capture_stdout() as out, capture_stderr() as err:
            rc = cli.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def last_record(self, out: str) -> dict[str, Any]:
        return json.loads(out.strip().splitlines()[-1])

    def state_files(self) -> list[Path]:
        return sorted((self.data_home / "monitor-poll").glob("*.json"))


class FilePollTests(CliTestCase):
    def test_existing_file_passes_with_one_json_record(self):
        target = Path(self.tmpdir) / "ready"
        target.write_text("x")
        rc, out, _ = self.run_cli("file", str(target), "--timeout", "0")
        rec = self.last_record(out)
        self.assertEqual(rc, 0)
        self.assertEqual((rec["condition"], rec["verdict"], rec["polls"]), ("file", "passed", 1))
        self.assertEqual(len(out.strip().splitlines()), 1)

    def test_missing_file_times_out_with_exit_one(self):
        rc, out, _ = self.run_cli("file", str(Path(self.tmpdir) / "never"), "--timeout", "0.05", "--interval", "0.02")
        self.assertEqual(rc, 1)
        self.assertEqual(self.last_record(out)["verdict"], "timed_out")

    def test_absent_flag_waits_for_removal(self):
        rc, out, _ = self.run_cli("file", str(Path(self.tmpdir) / "never"), "--absent", "--timeout", "0")
        self.assertEqual(rc, 0)
        self.assertEqual(self.last_record(out)["verdict"], "passed")

    def test_ticks_stream_ndjson_before_the_final_record(self):
        rc, out, _ = self.run_cli("file", str(Path(self.tmpdir) / "never"), "--timeout", "0.05",
                                  "--interval", "0.02", "--ticks")
        lines = [json.loads(line) for line in out.strip().splitlines()]
        self.assertEqual(rc, 1)
        self.assertGreaterEqual(len(lines), 2)
        self.assertEqual(lines[0]["outcome"], "pending")
        self.assertIn("verdict", lines[-1])
        self.assertNotIn("verdict", lines[0])

    def test_text_format_is_key_value_line(self):
        target = Path(self.tmpdir) / "ready"
        target.write_text("x")
        _, out, _ = self.run_cli("file", str(target), "--timeout", "0", "--format", "text")
        self.assertIn("condition=file verdict=passed polls=1", out)

    def test_state_file_records_terminal_status(self):
        self.run_cli("file", str(Path(self.tmpdir) / "never"), "--timeout", "0")
        data = json.loads(self.state_files()[0].read_text())
        self.assertEqual((data["status"], data["condition"]), ("timeout", "file"))


class CmdPollTests(CliTestCase):
    def test_command_exit_zero_passes(self):
        rc, out, _ = self.run_cli("cmd", "--timeout", "0", sys.executable, "-c", "raise SystemExit(0)")
        self.assertEqual(rc, 0)
        self.assertEqual(self.last_record(out)["verdict"], "passed")

    def test_command_flags_after_command_belong_to_the_command(self):
        rc, _, _ = self.run_cli("cmd", "--timeout", "0", sys.executable, "-c", "import sys; sys.exit(int(sys.argv[1]))", "0")
        self.assertEqual(rc, 0)

    def test_optional_separator_is_accepted(self):
        rc, _, _ = self.run_cli("cmd", "--timeout", "0", "--", sys.executable, "-c", "pass")
        self.assertEqual(rc, 0)

    def test_expect_rc_matches_nonzero_code(self):
        rc, _, _ = self.run_cli("cmd", "--timeout", "0", "--expect-rc", "3", sys.executable, "-c", "raise SystemExit(3)")
        self.assertEqual(rc, 0)

    def test_wrong_rc_times_out(self):
        rc, out, _ = self.run_cli("cmd", "--timeout", "0", sys.executable, "-c", "raise SystemExit(1)")
        self.assertEqual(rc, 1)
        self.assertEqual(self.last_record(out)["detail"], "exit 1")

    def test_missing_binary_is_error_exit_two_with_stderr_message(self):
        rc, out, err = self.run_cli("cmd", "--timeout", "0", "definitely-not-a-binary-xyz")
        self.assertEqual(rc, 2)
        self.assertEqual(self.last_record(out)["verdict"], "error")
        self.assertIn("cannot execute", err)

    def test_no_command_is_error_exit_two(self):
        rc, _, err = self.run_cli("cmd", "--timeout", "0")
        self.assertEqual(rc, 2)
        self.assertIn("no command", err)

    def test_state_args_hold_only_the_program_name(self):
        self.run_cli("cmd", "--timeout", "0", sys.executable, "-c", "pass", "secret-token")
        text = self.state_files()[0].read_text()
        self.assertNotIn("secret-token", text)


class OutputPollTests(CliTestCase):
    def test_match_passes(self):
        rc, out, _ = self.run_cli("output", "--match", "RE+ADY", "--timeout", "0",
                                  sys.executable, "-c", "print('REEADY')")
        self.assertEqual(rc, 0)
        self.assertIn("REEADY", self.last_record(out)["detail"])

    def test_fail_match_fails_before_timeout(self):
        rc, out, _ = self.run_cli("output", "--match", "ok", "--fail-match", "BAD", "--timeout", "30",
                                  sys.executable, "-c", "print('ok BAD')")
        self.assertEqual(rc, 1)
        self.assertEqual(self.last_record(out)["verdict"], "failed")

    def test_invalid_regex_exits_two(self):
        rc, _, err = self.run_cli("output", "--match", "(", "--timeout", "0", "true")
        self.assertEqual(rc, 2)
        self.assertIn("invalid --match regex", err)


class HttpPollTests(CliTestCase):
    def test_bad_scheme_exits_two(self):
        rc, _, err = self.run_cli("http", "file:///etc/passwd", "--timeout", "0")
        self.assertEqual(rc, 2)
        self.assertIn("unsupported URL scheme", err)

    def test_state_masks_credentials_in_url(self):
        with mock.patch("monitor_poll.conditions.http_condition",
                        return_value=lambda: Probe(Outcome.SUCCESS, "HTTP 200")):
            rc, _, _ = self.run_cli("http", "https://h/x?access_token=SEKRET123", "--timeout", "0")
        self.assertEqual(rc, 0)
        self.assertNotIn("SEKRET123", self.state_files()[0].read_text())


class GhPollTests(CliTestCase):
    def test_gh_pr_passes_through_to_condition(self):
        with mock.patch("monitor_poll.conditions.gh_pr_condition",
                        return_value=lambda: Probe(Outcome.SUCCESS, "3 checks passed")) as factory:
            rc, out, _ = self.run_cli("gh-pr", "--pr", "7", "--repo", "o/r", "--timeout", "0")
        factory.assert_called_once_with(7, repo="o/r")
        self.assertEqual(rc, 0)
        self.assertEqual(self.last_record(out)["condition"], "gh-pr")

    def test_gh_run_failure_exits_one(self):
        with mock.patch("monitor_poll.conditions.gh_run_condition",
                        return_value=lambda: Probe(Outcome.FAILURE, "run failure")) as factory:
            rc, out, _ = self.run_cli("gh-run", "--run", "55", "--timeout", "0")
        factory.assert_called_once_with("55", repo=None)
        self.assertEqual(rc, 1)
        self.assertEqual(self.last_record(out)["verdict"], "failed")

    def test_gh_run_requires_run_id(self):
        with self.assertRaises(SystemExit) as ctx, capture_stderr():
            cli.main(["gh-run"])
        self.assertEqual(ctx.exception.code, 2)


class ArgumentValidationTests(CliTestCase):
    def test_interval_must_be_positive(self):
        for bad in ("0", "-1", "abc"):
            with self.subTest(interval=bad), self.assertRaises(SystemExit) as ctx, capture_stderr():
                cli.main(["file", "x", "--interval", bad])
            self.assertEqual(ctx.exception.code, 2)

    def test_timeout_must_not_be_negative(self):
        with self.assertRaises(SystemExit) as ctx, capture_stderr():
            cli.main(["file", "x", "--timeout", "-5"])
        self.assertEqual(ctx.exception.code, 2)


def write_state_file(root: Path, **fields: Any) -> state.PollState:
    st = state.PollState(**{"poll_id": "p1", "pid": os.getpid(), "condition": "file",
                            "started_at": "2026-01-01T00:00:00Z", **fields})
    state.write_state(st, root)
    return st


class StatusTests(CliTestCase):
    def test_empty_json_is_a_valid_empty_array(self):
        rc, out, _ = self.run_cli("status")
        self.assertEqual((rc, json.loads(out)), (0, []))

    def test_lists_polls_and_marks_dead_running_ones_stale(self):
        root = self.data_home / "monitor-poll"
        write_state_file(root, poll_id="live", pid=os.getpid())
        write_state_file(root, poll_id="dead", pid=2**22 + 12345, started_at="2026-01-02T00:00:00Z")
        write_state_file(root, poll_id="fin", status="done", started_at="2026-01-03T00:00:00Z")
        with mock.patch.object(state, "is_pid_alive", side_effect=lambda pid: pid == os.getpid()):
            rc, out, _ = self.run_cli("status")
        rows = {r["poll_id"]: r["status"] for r in json.loads(out)}
        self.assertEqual(rc, 0)
        self.assertEqual(rows, {"live": "running", "dead": "stale", "fin": "done"})

    def test_csv_format(self):
        write_state_file(self.data_home / "monitor-poll", status="done")
        _, out, _ = self.run_cli("status", "--format", "csv")
        self.assertTrue(out.startswith("poll_id,condition,pid,status"))


class CancelTests(CliTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.root = self.data_home / "monitor-poll"

    def _cancel(self, *argv: str) -> tuple[int, dict[str, Any]]:
        rc, out, _ = self.run_cli("cancel", *argv)
        return rc, json.loads(out)

    def test_running_poll_gets_sigterm_and_is_marked_cancelled(self):
        write_state_file(self.root, pid=4242)
        with mock.patch.object(state, "is_pid_alive", return_value=True), \
                mock.patch.object(state.os, "kill") as kill:
            rc, rec = self._cancel("--poll-id", "p1")
        kill.assert_called_once_with(4242, mock.ANY)
        self.assertEqual((rc, rec["cancelled"]), (0, True))
        self.assertEqual(json.loads(self.state_files()[0].read_text())["status"], "cancelled")

    def test_cancel_by_pid(self):
        write_state_file(self.root, pid=4242)
        with mock.patch.object(state, "is_pid_alive", return_value=True), mock.patch.object(state.os, "kill"):
            rc, rec = self._cancel("--pid", "4242")
        self.assertEqual((rc, rec["poll_id"]), (0, "p1"))

    def test_finished_poll_is_never_signalled(self):
        write_state_file(self.root, status="done")
        with mock.patch.object(state.os, "kill") as kill:
            rc, rec = self._cancel("--poll-id", "p1")
        kill.assert_not_called()
        self.assertEqual((rc, rec["cancelled"]), (0, False))
        self.assertIn("already finished", rec["detail"])

    def test_signal_failure_exits_one_and_leaves_status(self):
        write_state_file(self.root, pid=4242)
        with mock.patch.object(state, "is_pid_alive", return_value=True), \
                mock.patch.object(state.os, "kill", side_effect=PermissionError("denied")):
            rc, rec = self._cancel("--poll-id", "p1")
        self.assertEqual((rc, rec["cancelled"]), (1, False))
        self.assertEqual(json.loads(self.state_files()[0].read_text())["status"], "running")

    def test_unknown_poll_exits_not_found(self):
        rc, _, err = self.run_cli("cancel", "--poll-id", "missing")
        self.assertEqual(rc, 6)
        self.assertIn("no poll found", err)

    def test_requires_exactly_one_selector(self):
        for argv in ((), ("--poll-id", "a", "--pid", "5")):
            with self.subTest(argv=argv):
                rc, _, err = self.run_cli("cancel", *argv)
                self.assertEqual(rc, 2)
                self.assertIn("exactly one", err)


class SharedFlagsTests(unittest.TestCase):
    def test_poll_args_are_shared_by_every_poll_command(self):
        parser = cli.app.build_parser()
        for name in ("cmd", "output", "file", "http", "gh-pr", "gh-run"):
            with self.subTest(command=name):
                sub = next(a for a in parser._actions if getattr(a, "choices", None) and name in a.choices)
                flags = {o for act in sub.choices[name]._actions for o in act.option_strings}
                self.assertLessEqual({"--timeout", "--interval", "--ticks", "--format"}, flags)


if __name__ == "__main__":
    unittest.main()
