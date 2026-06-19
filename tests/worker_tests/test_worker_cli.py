"""Tests for worker CLI module."""

from __future__ import annotations

import argparse
import json
import unittest
from unittest.mock import MagicMock, mock_open, patch

from worker._helpers import log_perf_jsonl
from worker.cli import WorkerApp


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


class TestWorkerAppBuildParser(unittest.TestCase):
    """Test WorkerApp.build_parser method."""

    def test_build_parser_has_subcommands(self):
        """Test that build_parser creates expected subcommands."""
        app = WorkerApp()
        parser = app.build_parser()

        subcommands = ["enqueue", "run-once", "daemon", "list", "status", "show", "requeue-errors", "retry", "purge"]

        for cmd in subcommands:
            if cmd == "enqueue":
                args = parser.parse_args([cmd, "--type", "run_cli", "--payload-json", "{}"])
            elif cmd == "show":
                args = parser.parse_args([cmd, "job-123"])
            elif cmd == "retry":
                args = parser.parse_args([cmd, "job-123"])
            else:
                args = parser.parse_args([cmd])
            self.assertEqual(args.command, cmd)

    def test_build_parser_enqueue_options(self):
        """Test enqueue subcommand options."""
        app = WorkerApp()
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
        app = WorkerApp()
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

    def test_build_parser_requeue_errors_options(self):
        """Test requeue-errors subcommand options."""
        app = WorkerApp()
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
        app = WorkerApp()
        parser = app.build_parser()

        args = parser.parse_args([
            "purge",
            "--older-than", "7d",
            "--folders", "done"
        ])

        self.assertEqual(args.older_than, "7d")
        self.assertEqual(args.folders, "done")


class TestWorkerAppAgenticExtras(unittest.TestCase):
    """Test WorkerApp.agentic_extras method."""

    def test_agentic_extras_returns_dict(self):
        """Test that agentic_extras returns expected structure."""
        app = WorkerApp()
        extras = app.agentic_extras()

        self.assertIsInstance(extras, dict)
        self.assertEqual(extras["category"], "worker")
        self.assertIn("flows", extras)
        self.assertIn("common_commands", extras)
        self.assertIn("validation", extras)

    def test_agentic_extras_flows_have_required_fields(self):
        """Test that all flows have required fields."""
        app = WorkerApp()
        extras = app.agentic_extras()

        for flow in extras["flows"]:
            self.assertIn("id", flow)
            self.assertIn("desc", flow)
            self.assertIn("cmd", flow)


class TestWorkerAppRun(unittest.TestCase):
    """Test WorkerApp.run method."""

    def test_run_no_command_shows_usage(self):
        """Test run with no command shows usage."""
        app = WorkerApp()
        args = argparse.Namespace(command=None)

        with patch("builtins.print") as mock_print:
            result = app.run(args)

        self.assertEqual(result, 1)
        mock_print.assert_called_once()
        self.assertIn("Usage", mock_print.call_args[0][0])

    @patch("worker.cli.EnqueueCommand.run", return_value=0)
    def test_run_enqueue_command(self, mock_enqueue):
        """Test run dispatches to EnqueueCommand."""
        app = WorkerApp()
        args = argparse.Namespace(command="enqueue")

        result = app.run(args)

        mock_enqueue.assert_called_once_with(args)
        self.assertEqual(result, 0)

    @patch("worker.cli.ListCommand.run", return_value=0)
    def test_run_list_command(self, mock_list):
        """Test run dispatches to ListCommand."""
        app = WorkerApp()
        args = argparse.Namespace(command="list")

        result = app.run(args)

        mock_list.assert_called_once_with(args)
        self.assertEqual(result, 0)

    @patch("worker.cli.StatusCommand.run", return_value=0)
    def test_run_status_command(self, mock_status):
        """Test run dispatches to StatusCommand."""
        app = WorkerApp()
        args = argparse.Namespace(command="status")

        result = app.run(args)

        mock_status.assert_called_once_with(args)
        self.assertEqual(result, 0)

    @patch("worker.cli.ShowCommand.run", return_value=0)
    def test_run_show_command(self, mock_show):
        """Test run dispatches to ShowCommand."""
        app = WorkerApp()
        args = argparse.Namespace(command="show")

        result = app.run(args)

        mock_show.assert_called_once_with(args)
        self.assertEqual(result, 0)

    @patch("worker.cli.RequeueErrorsCommand.run", return_value=0)
    def test_run_requeue_errors_command(self, mock_requeue):
        """Test run dispatches to RequeueErrorsCommand."""
        app = WorkerApp()
        args = argparse.Namespace(command="requeue-errors")

        result = app.run(args)

        mock_requeue.assert_called_once_with(args)
        self.assertEqual(result, 0)

    @patch("worker.cli.RetryCommand.run", return_value=0)
    def test_run_retry_command(self, mock_retry):
        """Test run dispatches to RetryCommand."""
        app = WorkerApp()
        args = argparse.Namespace(command="retry")

        result = app.run(args)

        mock_retry.assert_called_once_with(args)
        self.assertEqual(result, 0)

    @patch("worker.cli.PurgeCommand.run", return_value=0)
    def test_run_purge_command(self, mock_purge):
        """Test run dispatches to PurgeCommand."""
        app = WorkerApp()
        args = argparse.Namespace(command="purge")

        result = app.run(args)

        mock_purge.assert_called_once_with(args)
        self.assertEqual(result, 0)

    @patch("worker.cli.DaemonRunner")
    @patch("worker.cli.JobProcessor")
    def test_run_run_once_command(self, mock_processor_cls, mock_runner_cls):
        """Test run dispatches to run-once via DaemonRunner."""
        mock_runner = MagicMock()
        mock_runner.run_once.return_value = 0
        mock_runner_cls.return_value = mock_runner

        app = WorkerApp()
        args = argparse.Namespace(
            command="run-once",
            backoff=60,
            max=5,
            max_per_tick=3,
            max_inflight=0,
            job_timeout=0,
            interval="5"
        )

        result = app.run(args)

        mock_runner.run_once.assert_called_once()
        self.assertEqual(result, 0)

    @patch("worker.cli.DaemonRunner")
    @patch("worker.cli.JobProcessor")
    def test_run_daemon_command(self, mock_processor_cls, mock_runner_cls):
        """Test run dispatches to daemon via DaemonRunner."""
        mock_runner = MagicMock()
        mock_runner.run_daemon.return_value = 0
        mock_runner_cls.return_value = mock_runner

        app = WorkerApp()
        args = argparse.Namespace(
            command="daemon",
            backoff=60,
            max_per_tick=3,
            max_inflight=0,
            job_timeout=0,
            interval="5"
        )

        result = app.run(args)

        mock_runner.run_daemon.assert_called_once()
        self.assertEqual(result, 0)


class TestWorkerAppAttributes(unittest.TestCase):
    """Test WorkerApp class attributes."""

    def test_prog_attribute(self):
        """Test prog attribute is set correctly."""
        app = WorkerApp()
        self.assertEqual(app.prog, "worker")

    def test_description_attribute(self):
        """Test description attribute is set correctly."""
        app = WorkerApp()
        self.assertEqual(app.description, "Background worker queue and daemon")


if __name__ == "__main__":
    unittest.main()
