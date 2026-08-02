"""Tests for worker CLI module."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, mock_open, patch

from worker._helpers import log_perf_jsonl
from worker.cli import app, main


class TestPerfLog(unittest.TestCase):
    """Test log_perf_jsonl function."""

    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_perf_log_writes_record(self, mock_mkdir, mock_file):
        """Test that log_perf_jsonl writes a performance record."""
        log_perf_jsonl("worker", 1500, args=["daemon"], exit_code=0)

        mock_mkdir.assert_called_once()
        mock_file().write.assert_called_once()

        written = mock_file().write.call_args[0][0]
        data = json.loads(written.strip())
        self.assertEqual(data["prog"], "worker")
        self.assertEqual(data["args"], ["daemon"])
        self.assertEqual(data["exit_code"], 0)
        self.assertEqual(data["duration_ms"], 1500)
        self.assertIn("ts", data)
        self.assertIn("cwd", data)
        self.assertIn("pid", data)

    @patch("pathlib.Path.open", side_effect=OSError("Write failed"))
    @patch("pathlib.Path.mkdir")
    def test_perf_log_handles_write_error(self, mock_mkdir, mock_file):
        """Test that log_perf_jsonl handles write errors gracefully."""
        # Should not raise exception
        log_perf_jsonl("worker", 1000, args=["daemon"], exit_code=0)

    @patch("worker._helpers._get_log_dir", side_effect=Exception())
    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_perf_log_fallback_log_dir(self, mock_mkdir, mock_file, mock_get_log_dir):
        """Test log_perf_jsonl falls back to default log dir on error."""
        log_perf_jsonl("worker", 100, args=["list"], exit_code=0)


class TestWorkerBuildParser(unittest.TestCase):
    """Test the shipping CLIApp parser (app.build_parser())."""

    def test_build_parser_has_subcommands(self):
        """Test that build_parser creates expected subcommands."""
        parser = app.build_parser()

        subcommands = ["enqueue", "run-once", "daemon", "list", "status", "show", "requeue-errors", "retry", "purge"]

        for cmd in subcommands:
            if cmd == "enqueue":
                args = parser.parse_args([cmd, "--type", "run_cli", "--payload-json", "{}"])
            elif cmd in ("show", "retry"):
                args = parser.parse_args([cmd, "job-123"])
            else:
                args = parser.parse_args([cmd])
            self.assertEqual(args.command, cmd)

    def test_build_parser_enqueue_options(self):
        """Test enqueue subcommand options."""
        parser = app.build_parser()

        args = parser.parse_args([
            "enqueue",
            "--type", "run_cli",
            "--payload-json", '{"cmd": ["echo"]}',
            "--priority", "3",
            "--max-attempts", "5"
        ])

        self.assertEqual(args.type, "run_cli")
        self.assertEqual(args.payload_json, '{"cmd": ["echo"]}')
        self.assertEqual(args.priority, 3)
        self.assertEqual(args.max_attempts, 5)

    def test_build_parser_daemon_options(self):
        """Test daemon subcommand options."""
        parser = app.build_parser()

        args = parser.parse_args([
            "daemon",
            "--interval", "10",
            "--max-per-tick", "5",
            "--backoff", "120",
            "--max-inflight", "10",
            "--job-timeout", "60"
        ])

        self.assertEqual(args.interval, "10")
        self.assertEqual(args.max_per_tick, 5)
        self.assertEqual(args.backoff, 120)
        self.assertEqual(args.max_inflight, 10)
        self.assertEqual(args.job_timeout, 60)

    def test_build_parser_run_once_options(self):
        """Test run-once subcommand options (disjoint from daemon's flags)."""
        parser = app.build_parser()

        args = parser.parse_args(["run-once", "--max", "10", "--backoff", "30"])

        self.assertEqual(args.max, 10)
        self.assertEqual(args.backoff, 30)
        self.assertFalse(hasattr(args, "max_per_tick"))

    def test_build_parser_requeue_errors_options(self):
        """Test requeue-errors subcommand options."""
        parser = app.build_parser()

        args = parser.parse_args([
            "requeue-errors",
            "--limit", "10",
            "--delay", "30",
            "--reset-attempts",
            "--new-max-attempts", "5",
            "--since", "2d",
            "--match", "timeout"
        ])

        self.assertEqual(args.limit, 10)
        self.assertEqual(args.delay, 30)
        self.assertTrue(args.reset_attempts)
        self.assertEqual(args.new_max_attempts, 5)
        self.assertEqual(args.since, "2d")
        self.assertEqual(args.match, ["timeout"])

    def test_build_parser_purge_options(self):
        """Test purge subcommand options."""
        parser = app.build_parser()

        args = parser.parse_args([
            "purge",
            "--older-than", "7d",
            "--folders", "done"
        ])

        self.assertEqual(args.older_than, "7d")
        self.assertEqual(args.folders, "done")


class TestWorkerMain(unittest.TestCase):
    """Test the module-level main() entry point (what bin/worker actually runs)."""

    def test_main_no_command_shows_usage(self):
        """Test main with no command shows usage and exits 1."""
        with patch("builtins.print") as mock_print:
            result = main([])

        self.assertEqual(result, 1)
        mock_print.assert_called_once()
        self.assertIn("Usage", mock_print.call_args[0][0])

    @patch("worker.cli.EnqueueCommand.run", return_value=0)
    def test_main_enqueue_command(self, mock_enqueue):
        """Test main dispatches to EnqueueCommand."""
        result = main(["enqueue", "--type", "run_cli", "--payload-json", "{}"])

        mock_enqueue.assert_called_once()
        self.assertEqual(result, 0)

    @patch("worker.cli.ListCommand.run", return_value=0)
    def test_main_list_command(self, mock_list):
        """Test main dispatches to ListCommand."""
        result = main(["list"])

        mock_list.assert_called_once()
        self.assertEqual(result, 0)

    @patch("worker.cli.StatusCommand.run", return_value=0)
    def test_main_status_command(self, mock_status):
        """Test main dispatches to StatusCommand."""
        result = main(["status"])

        mock_status.assert_called_once()
        self.assertEqual(result, 0)

    @patch("worker.cli.ShowCommand.run", return_value=0)
    def test_main_show_command(self, mock_show):
        """Test main dispatches to ShowCommand."""
        result = main(["show", "job-123"])

        mock_show.assert_called_once()
        self.assertEqual(result, 0)

    @patch("worker.cli.RequeueErrorsCommand.run", return_value=0)
    def test_main_requeue_errors_command(self, mock_requeue):
        """Test main dispatches to RequeueErrorsCommand."""
        result = main(["requeue-errors"])

        mock_requeue.assert_called_once()
        self.assertEqual(result, 0)

    @patch("worker.cli.RetryCommand.run", return_value=0)
    def test_main_retry_command(self, mock_retry):
        """Test main dispatches to RetryCommand."""
        result = main(["retry", "job-123"])

        mock_retry.assert_called_once()
        self.assertEqual(result, 0)

    @patch("worker.cli.PurgeCommand.run", return_value=0)
    def test_main_purge_command(self, mock_purge):
        """Test main dispatches to PurgeCommand."""
        result = main(["purge"])

        mock_purge.assert_called_once()
        self.assertEqual(result, 0)

    @patch("worker.cli.DaemonRunner")
    @patch("worker.cli.JobProcessor")
    def test_main_run_once_command(self, mock_processor_cls, mock_runner_cls):
        """Test main dispatches run-once via DaemonRunner."""
        mock_runner = MagicMock()
        mock_runner.run_once.return_value = 0
        mock_runner_cls.return_value = mock_runner

        result = main(["run-once", "--max", "5", "--backoff", "60"])

        mock_runner.run_once.assert_called_once()
        self.assertEqual(result, 0)

    @patch("worker.cli.DaemonRunner")
    @patch("worker.cli.JobProcessor")
    def test_main_daemon_command(self, mock_processor_cls, mock_runner_cls):
        """Test main dispatches daemon via DaemonRunner."""
        mock_runner = MagicMock()
        mock_runner.run_daemon.return_value = 0
        mock_runner_cls.return_value = mock_runner

        result = main(["daemon"])

        mock_runner.run_daemon.assert_called_once()
        self.assertEqual(result, 0)

    def test_main_separator_normalization_is_idempotent(self):
        """A leading '--' separator and its absence must parse identically,
        and a later '--' guarding a flag-like positional must survive
        app.run()'s internal normalization (no double-stripping)."""
        with patch("worker.cli.ShowCommand.run", return_value=0) as mock_show:
            main(["--", "show", "job-123"])
            first_call_args = mock_show.call_args[0][0]

        with patch("worker.cli.ShowCommand.run", return_value=0) as mock_show:
            main(["show", "job-123"])
            second_call_args = mock_show.call_args[0][0]

        self.assertEqual(first_call_args.id, second_call_args.id)

    def test_main_preserves_second_separator_as_end_of_options(self):
        """'worker -- show -- -my-job-id' has two '--' tokens: the first is
        the optional CLIApp separator (stripped), the second is a genuine
        POSIX end-of-options marker protecting '-my-job-id' as the literal
        positional value. Double-normalizing (main()'s pre-check plus
        app.run()'s internal call) would incorrectly strip both, causing
        argparse to treat '-my-job-id' as an unrecognized flag instead."""
        with patch("worker.cli.ShowCommand.run", return_value=0) as mock_show:
            result = main(["--", "show", "--", "-my-job-id"])

        self.assertEqual(result, 0)
        mock_show.assert_called_once()
        self.assertEqual(mock_show.call_args[0][0].id, "-my-job-id")


if __name__ == "__main__":
    unittest.main()
