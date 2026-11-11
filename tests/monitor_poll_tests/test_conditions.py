"""Condition factories, with subprocess, HTTP and gh calls faked at their seams."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from core.gh_cli import GhCLI
from core.process import CompletedRun
from monitor_poll import conditions
from monitor_poll.engine import ConditionError, Outcome


class FakeRunner:
    """Replays scripted ``CompletedRun`` results and records each call."""

    def __init__(self, *results: CompletedRun) -> None:
        self.results = list(results)
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> CompletedRun:
        self.calls.append((argv, kwargs))
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


def done(stdout: str = "", rc: int = 0) -> CompletedRun:
    return CompletedRun(stdout=stdout, stderr="", returncode=rc)


class FileConditionTests(unittest.TestCase):
    def test_missing_then_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "flag"
            check = conditions.file_condition(target)
            self.assertEqual(check().outcome, Outcome.PENDING)
            target.write_text("x")
            self.assertEqual(check().outcome, Outcome.SUCCESS)

    def test_absent_mode_inverts(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "flag"
            target.write_text("x")
            check = conditions.file_condition(target, absent=True)
            self.assertEqual(check().outcome, Outcome.PENDING)
            target.unlink()
            self.assertEqual(check().outcome, Outcome.SUCCESS)


class CommandConditionTests(unittest.TestCase):
    def test_expected_rc_succeeds_and_passes_timeout_to_runner(self):
        runner = FakeRunner(done(rc=0))
        probe = conditions.command_condition(["true"], attempt_timeout=7, runner=runner)()
        self.assertEqual(probe.outcome, Outcome.SUCCESS)
        argv, kwargs = runner.calls[0]
        self.assertEqual(argv, ["true"])
        self.assertEqual(kwargs["timeout"], 7)

    def test_other_rc_is_pending_with_code_in_detail(self):
        probe = conditions.command_condition(["x"], runner=FakeRunner(done(rc=3)))()
        self.assertEqual((probe.outcome, probe.detail), (Outcome.PENDING, "exit 3"))

    def test_custom_expect_rc(self):
        check = conditions.command_condition(["x"], expect_rc=3, runner=FakeRunner(done(rc=3)))
        self.assertEqual(check().outcome, Outcome.SUCCESS)

    def test_attempt_timeout_is_pending_not_error(self):
        timed_out = CompletedRun("", "timeout", 124, timed_out=True)
        probe = conditions.command_condition(["x"], attempt_timeout=2, runner=FakeRunner(timed_out))()
        self.assertEqual(probe.outcome, Outcome.PENDING)
        self.assertIn("timed out", probe.detail)

    def test_missing_binary_is_condition_error(self):
        missing = CompletedRun("", "nope", 127, exec_error=FileNotFoundError("nope"))
        with self.assertRaises(ConditionError):
            conditions.command_condition(["nope"], runner=FakeRunner(missing))()

    def test_empty_argv_is_condition_error(self):
        with self.assertRaises(ConditionError):
            conditions.command_condition([], runner=FakeRunner(done()))()

    def test_real_subprocess_runs_without_a_shell(self):
        # A metacharacter must reach the program as data, not be interpreted.
        check = conditions.command_condition(["echo", "a;b"], expect_rc=0)
        self.assertEqual(check().outcome, Outcome.SUCCESS)


class OutputConditionTests(unittest.TestCase):
    def test_match_succeeds_and_reports_matched_text(self):
        check = conditions.output_condition(["x"], r"ready \d+", runner=FakeRunner(done("state: ready 42\n")))
        probe = check()
        self.assertEqual(probe.outcome, Outcome.SUCCESS)
        self.assertIn("ready 42", probe.detail)

    def test_no_match_is_pending(self):
        check = conditions.output_condition(["x"], "ready", runner=FakeRunner(done("starting")))
        self.assertEqual(check().outcome, Outcome.PENDING)

    def test_fail_pattern_wins_over_match(self):
        check = conditions.output_condition(
            ["x"], "done", fail_pattern="FAILED", runner=FakeRunner(done("done FAILED")))
        self.assertEqual(check().outcome, Outcome.FAILURE)

    def test_nonzero_rc_still_matches_output(self):
        check = conditions.output_condition(["x"], "ok", runner=FakeRunner(done("ok", rc=1)))
        self.assertEqual(check().outcome, Outcome.SUCCESS)

    def test_invalid_regex_fails_at_construction(self):
        with self.assertRaises(ConditionError):
            conditions.output_condition(["x"], "(")
        with self.assertRaises(ConditionError):
            conditions.output_condition(["x"], "ok", fail_pattern="[")


class FakeResponse:
    def __init__(self, status: int, body: bytes = b"") -> None:
        self.status = status
        self._body = io.BytesIO(body)

    def read(self, n: int = -1) -> bytes:
        return self._body.read(n)

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class ScriptedOpener:
    """An ``urlopen`` stand-in yielding each item in turn: a response, or an exception to raise."""

    def __init__(self, *items: Any) -> None:
        self.items = list(items)
        self.seen: list[dict[str, Any]] = []

    def __call__(self, request: Any, timeout: float) -> FakeResponse:
        self.seen.append({"url": request.full_url, "timeout": timeout})
        item = self.items.pop(0) if len(self.items) > 1 else self.items[0]
        if isinstance(item, BaseException):
            raise item
        return item


opener_returning = ScriptedOpener


class HttpConditionTests(unittest.TestCase):
    def test_expected_status_succeeds(self):
        opener = opener_returning(FakeResponse(200, b"ok"))
        probe = conditions.http_condition("http://h/x", attempt_timeout=3, opener=opener)()
        self.assertEqual(probe.outcome, Outcome.SUCCESS)
        self.assertEqual(opener.seen[0], {"url": "http://h/x", "timeout": 3})

    def test_http_error_status_is_a_result_not_an_exception(self):
        err = urllib.error.HTTPError("http://h/x", 503, "down", Message(), io.BytesIO(b"nope"))
        check = conditions.http_condition("http://h/x", opener=opener_returning(err))
        probe = check()
        self.assertEqual((probe.outcome, probe.detail), (Outcome.PENDING, "HTTP 503"))

    def test_expected_error_status_can_be_awaited(self):
        err = urllib.error.HTTPError("http://h/x", 404, "gone", Message(), io.BytesIO(b""))
        check = conditions.http_condition("http://h/x", status=404, opener=opener_returning(err))
        self.assertEqual(check().outcome, Outcome.SUCCESS)

    def test_connection_refused_is_pending(self):
        refused = urllib.error.URLError(ConnectionRefusedError("refused"))
        probe = conditions.http_condition("http://h/x", opener=opener_returning(refused))()
        self.assertEqual(probe.outcome, Outcome.PENDING)
        self.assertIn("unreachable", probe.detail)

    def test_socket_timeout_is_pending(self):
        probe = conditions.http_condition("http://h/x", opener=opener_returning(TimeoutError("slow")))()
        self.assertEqual(probe.outcome, Outcome.PENDING)

    def test_body_match_required_when_given(self):
        opener = opener_returning(FakeResponse(200, b"starting"), FakeResponse(200, b"status: UP"))
        check = conditions.http_condition("http://h/x", match="UP", opener=opener)
        self.assertEqual(check().outcome, Outcome.PENDING)
        self.assertEqual(check().outcome, Outcome.SUCCESS)

    def test_non_http_schemes_are_rejected(self):
        for url in ("file:///etc/passwd", "ftp://h/x", "javascript:1", "/just/a/path"):
            with self.subTest(url=url), self.assertRaises(ConditionError):
                conditions.http_condition(url)

    def test_invalid_match_regex_is_rejected(self):
        with self.assertRaises(ConditionError):
            conditions.http_condition("http://h/x", match="(")

    def test_malformed_url_is_condition_error(self):
        check = conditions.http_condition("http://bad host/x")
        with self.assertRaises(ConditionError):
            check()


def gh_client_with(stdout: str = "", stderr: str = "", returncode: int = 0) -> tuple[GhCLI, list[list[str]]]:
    calls: list[list[str]] = []

    def fake(cmd: list[str], **_kwargs: Any) -> SimpleNamespace:
        calls.append(list(cmd))
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    return GhCLI(run_func=fake), calls


def checks_json(*buckets: str) -> str:
    return json.dumps([{"name": f"job{i}", "bucket": b} for i, b in enumerate(buckets)])


class GhPrConditionTests(unittest.TestCase):
    def _probe(self, stdout: str, **kwargs: Any):
        gh, calls = gh_client_with(stdout=stdout, **kwargs)
        return conditions.gh_pr_condition(12, repo="o/r", gh=gh)(), calls

    def test_all_pass_or_skipping_succeeds(self):
        probe, calls = self._probe(checks_json("pass", "skipping", "pass"))
        self.assertEqual(probe.outcome, Outcome.SUCCESS)
        self.assertEqual(calls[0][:4], ["gh", "pr", "checks", "12"])
        self.assertIn("o/r", calls[0])

    def test_any_pending_is_pending(self):
        probe, _ = self._probe(checks_json("pass", "pending"))
        self.assertEqual((probe.outcome, probe.detail), (Outcome.PENDING, "1/2 checks pending"))

    def test_failure_beats_pending_and_names_the_job(self):
        probe, _ = self._probe(checks_json("pending", "fail"))
        self.assertEqual(probe.outcome, Outcome.FAILURE)
        self.assertIn("job1", probe.detail)

    def test_cancelled_check_is_failure(self):
        probe, _ = self._probe(checks_json("cancel"))
        self.assertEqual(probe.outcome, Outcome.FAILURE)

    def test_no_checks_yet_is_pending(self):
        probe, _ = self._probe("", stderr="no checks reported on the 'x' branch", returncode=1)
        self.assertEqual((probe.outcome, probe.detail), (Outcome.PENDING, "no checks reported yet"))

    def test_gh_failure_is_condition_error(self):
        gh, _ = gh_client_with(stdout="", stderr="gh: not logged in", returncode=4)
        with self.assertRaises(ConditionError):
            conditions.gh_pr_condition(1, gh=gh)()


class GhRunConditionTests(unittest.TestCase):
    def _probe(self, payload: object, **kwargs: Any):
        gh, calls = gh_client_with(stdout=json.dumps(payload), **kwargs)
        return conditions.gh_run_condition(99, repo="o/r", gh=gh)(), calls

    def test_in_progress_is_pending(self):
        probe, calls = self._probe({"status": "in_progress", "conclusion": ""})
        self.assertEqual(probe.outcome, Outcome.PENDING)
        self.assertEqual(calls[0][:4], ["gh", "run", "view", "99"])
        self.assertEqual(calls[0][-2:], ["--repo", "o/r"])

    def test_completed_success(self):
        probe, _ = self._probe({"status": "completed", "conclusion": "success"})
        self.assertEqual(probe.outcome, Outcome.SUCCESS)

    def test_completed_other_conclusions_fail(self):
        for conclusion in ("failure", "cancelled", "timed_out"):
            with self.subTest(conclusion=conclusion):
                probe, _ = self._probe({"status": "completed", "conclusion": conclusion})
                self.assertEqual(probe.outcome, Outcome.FAILURE)

    def test_gh_error_exit_is_condition_error(self):
        gh, _ = gh_client_with(stderr="HTTP 404: Not Found", returncode=1)
        with self.assertRaises(ConditionError):
            conditions.gh_run_condition(1, gh=gh)()

    def test_non_json_output_is_condition_error(self):
        gh, _ = gh_client_with(stdout="<html>")
        with self.assertRaises(ConditionError):
            conditions.gh_run_condition(1, gh=gh)()

    def test_non_object_payload_is_condition_error(self):
        gh, _ = gh_client_with(stdout="[]")
        with self.assertRaises(ConditionError):
            conditions.gh_run_condition(1, gh=gh)()


if __name__ == "__main__":
    unittest.main()
