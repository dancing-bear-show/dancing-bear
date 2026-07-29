"""Tests for telemetry/collector.py — OTEL Docker-collector lifecycle helpers."""
from __future__ import annotations

import calendar
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

import telemetry.collector as collector
from telemetry.collector import (
    _EVENTS_HEADERS,
    _decode_otlp_value,
    _docker_env,
    _emit_no_events,
    _parse_event_lines,
    _parse_otlp_event,
    _print_container_details,
    _print_data_files,
    _print_docker_containers,
    _print_port_bindings,
    _run_compose,
)


# ---------------------------------------------------------------------------
# Helper: build a CompletedProcess quickly
# ---------------------------------------------------------------------------

def _cp(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# Helper: swap module-level consoles for StringIO-backed ones, return buffers
# ---------------------------------------------------------------------------

class _ConsoleCapture:
    """Context manager that replaces the module-level consoles with StringIO-backed ones."""

    def __enter__(self):
        self._out_buf = io.StringIO()
        self._err_buf = io.StringIO()
        self._out_console = Console(file=self._out_buf, highlight=False, markup=False)
        self._err_console = Console(file=self._err_buf, highlight=False, markup=False)
        self._p1 = patch.object(collector, "console", self._out_console)
        self._p2 = patch.object(collector, "_err_console", self._err_console)
        self._p1.start()
        self._p2.start()
        return self

    def __exit__(self, *_):
        self._p1.stop()
        self._p2.stop()

    @property
    def out(self) -> str:
        return self._out_buf.getvalue()

    @property
    def err(self) -> str:
        return self._err_buf.getvalue()


# ===========================================================================
# 1. _decode_otlp_value
# ===========================================================================

class TestDecodeOtlpValue(unittest.TestCase):

    def test_string_value(self):
        self.assertEqual(_decode_otlp_value({"stringValue": "hello"}), "hello")

    def test_int_value(self):
        result = _decode_otlp_value({"intValue": "42"})
        self.assertEqual(result, 42)
        self.assertIsInstance(result, int)

    def test_double_value(self):
        result = _decode_otlp_value({"doubleValue": "3.14"})
        self.assertAlmostEqual(result, 3.14, places=5)
        self.assertIsInstance(result, float)

    def test_bool_value_true(self):
        result = _decode_otlp_value({"boolValue": True})
        self.assertIs(result, True)
        self.assertIsInstance(result, bool)

    def test_bool_value_false(self):
        result = _decode_otlp_value({"boolValue": False})
        self.assertIs(result, False)

    def test_non_dict_returned_as_is(self):
        self.assertEqual(_decode_otlp_value("plain string"), "plain string")
        self.assertEqual(_decode_otlp_value(99), 99)
        self.assertIsNone(_decode_otlp_value(None))

    def test_dict_with_no_known_keys_returned_as_is(self):
        d = {"unknownKey": "value"}
        self.assertIs(_decode_otlp_value(d), d)

    def test_int_value_non_numeric_string_falls_back(self):
        # int("not-a-number") raises ValueError — should fall back to returning raw value
        result = _decode_otlp_value({"intValue": "not-a-number"})
        self.assertEqual(result, "not-a-number")

    def test_double_value_non_numeric_string_falls_back(self):
        result = _decode_otlp_value({"doubleValue": "not-a-float"})
        self.assertEqual(result, "not-a-float")

    def test_int_value_none_falls_back(self):
        # int(None) raises TypeError
        result = _decode_otlp_value({"intValue": None})
        self.assertIsNone(result)

    def test_string_value_coercion_of_number(self):
        # str(123) succeeds → "123"
        result = _decode_otlp_value({"stringValue": 123})
        self.assertEqual(result, "123")
        self.assertIsInstance(result, str)

    def test_first_matching_key_wins(self):
        # Only one OTLP type should be decoded; stringValue is checked first
        d = {"stringValue": "first", "intValue": "999"}
        self.assertEqual(_decode_otlp_value(d), "first")


# ===========================================================================
# 2. _parse_otlp_event
# ===========================================================================

# Known: 1_000_000_000 ns = 1970-01-01 00:00:01 UTC
_ONE_SECOND_NS = 1_000_000_000
_ONE_SECOND_TS = "1970-01-01 00:00:01"

# 2024-01-15 12:30:45 UTC → nanoseconds
_DT_TUPLE = (2024, 1, 15, 12, 30, 45)
_DT_EPOCH_S = calendar.timegm(_DT_TUPLE)
_DT_NS = _DT_EPOCH_S * 1_000_000_000
_DT_TS = "2024-01-15 12:30:45"


def _make_record(
    *,
    time_unix_nano: int | str | None = _DT_NS,
    body_value: str | None = "test body",
    attributes: list | None = None,
) -> str:
    record: dict = {}
    if time_unix_nano is not None:
        record["timeUnixNano"] = time_unix_nano
    if body_value is not None:
        record["body"] = {"stringValue": body_value}
    if attributes is not None:
        record["attributes"] = attributes
    return json.dumps({
        "resourceLogs": [{"scopeLogs": [{"logRecords": [record]}]}]
    })


class TestParseOtlpEvent(unittest.TestCase):

    def test_valid_line_returns_dict(self):
        result = _parse_otlp_event(_make_record())
        self.assertIsNotNone(result)
        self.assertEqual(result["timestamp"], _DT_TS)
        self.assertEqual(result["body"], "test body")
        self.assertIsInstance(result["attributes"], dict)

    def test_timestamp_formatting_known_value(self):
        result = _parse_otlp_event(_make_record(time_unix_nano=_ONE_SECOND_NS))
        self.assertIsNotNone(result)
        self.assertEqual(result["timestamp"], _ONE_SECOND_TS)

    def test_invalid_json_returns_none(self):
        self.assertIsNone(_parse_otlp_event("not valid json {{{"))

    def test_zero_time_unix_nano_returns_none(self):
        self.assertIsNone(_parse_otlp_event(_make_record(time_unix_nano=0)))

    def test_missing_time_unix_nano_returns_none(self):
        self.assertIsNone(_parse_otlp_event(_make_record(time_unix_nano=None)))

    def test_zero_string_time_unix_nano_returns_none(self):
        # "0" casts to int 0 → treated as missing
        self.assertIsNone(_parse_otlp_event(_make_record(time_unix_nano="0")))

    def test_missing_body_string_value_returns_none(self):
        # body present but no stringValue
        record = {"timeUnixNano": _DT_NS, "body": {"intValue": 42}}
        line = json.dumps({"resourceLogs": [{"scopeLogs": [{"logRecords": [record]}]}]})
        self.assertIsNone(_parse_otlp_event(line))

    def test_null_body_returns_none(self):
        self.assertIsNone(_parse_otlp_event(_make_record(body_value=None)))

    def test_missing_resource_logs_returns_none(self):
        self.assertIsNone(_parse_otlp_event(json.dumps({})))

    def test_empty_resource_logs_list_returns_none(self):
        self.assertIsNone(_parse_otlp_event(json.dumps({"resourceLogs": []})))

    def test_empty_scope_logs_list_returns_none(self):
        line = json.dumps({"resourceLogs": [{"scopeLogs": []}]})
        self.assertIsNone(_parse_otlp_event(line))

    def test_empty_log_records_list_returns_none(self):
        line = json.dumps({"resourceLogs": [{"scopeLogs": [{"logRecords": []}]}]})
        self.assertIsNone(_parse_otlp_event(line))

    def test_attributes_decoded_correctly(self):
        attrs = [
            {"key": "service.name", "value": {"stringValue": "my-service"}},
            {"key": "http.status_code", "value": {"intValue": "200"}},
        ]
        result = _parse_otlp_event(_make_record(attributes=attrs))
        self.assertIsNotNone(result)
        self.assertEqual(result["attributes"]["service.name"], "my-service")
        self.assertEqual(result["attributes"]["http.status_code"], 200)

    def test_empty_attributes_list(self):
        result = _parse_otlp_event(_make_record(attributes=[]))
        self.assertIsNotNone(result)
        self.assertEqual(result["attributes"], {})

    def test_none_record_type_returns_none(self):
        # logRecords contains a non-dict (IndexError/TypeError swallowed)
        line = json.dumps({"resourceLogs": [{"scopeLogs": [{"logRecords": None}]}]})
        self.assertIsNone(_parse_otlp_event(line))


# ===========================================================================
# 3. _parse_event_lines
# ===========================================================================

class TestParseEventLines(unittest.TestCase):

    def test_empty_input(self):
        rows, skipped = _parse_event_lines([])
        self.assertEqual(rows, [])
        self.assertEqual(skipped, 0)

    def test_blank_and_whitespace_lines_not_counted_as_skipped(self):
        rows, skipped = _parse_event_lines(["", "   ", "\t"])
        self.assertEqual(rows, [])
        self.assertEqual(skipped, 0)

    def test_valid_line_counted_in_rows(self):
        rows, skipped = _parse_event_lines([_make_record()])
        self.assertEqual(len(rows), 1)
        self.assertEqual(skipped, 0)

    def test_invalid_line_counted_in_skipped(self):
        rows, skipped = _parse_event_lines(["not valid json"])
        self.assertEqual(rows, [])
        self.assertEqual(skipped, 1)

    def test_mix_of_valid_invalid_and_blank(self):
        lines = [
            _make_record(),         # valid
            "",                     # blank — not counted
            "bad json",             # invalid → skipped
            "   ",                  # whitespace — not counted
            _make_record(time_unix_nano=_ONE_SECOND_NS),  # valid
            "{not json",            # invalid → skipped
        ]
        rows, skipped = _parse_event_lines(lines)
        self.assertEqual(len(rows), 2)
        self.assertEqual(skipped, 2)

    def test_all_valid(self):
        lines = [_make_record(time_unix_nano=_DT_NS + i * 1_000_000_000) for i in range(5)]
        rows, skipped = _parse_event_lines(lines)
        self.assertEqual(len(rows), 5)
        self.assertEqual(skipped, 0)


# ===========================================================================
# 4. _emit_no_events
# ===========================================================================

class TestEmitNoEvents(unittest.TestCase):

    def test_json_fmt_calls_emit_rows(self):
        with patch("telemetry.collector.emit_rows") as mock_emit:
            _emit_no_events("json", "some message")
            mock_emit.assert_called_once_with([], fmt="json", headers=_EVENTS_HEADERS)

    def test_table_fmt_prints_dim_message(self):
        with _ConsoleCapture() as cap:
            _emit_no_events("table", "No events found")
        # The message should appear in output (markup stripped since markup=False)
        self.assertIn("No events found", cap.out)

    def test_non_json_fmt_prints_message(self):
        with _ConsoleCapture() as cap:
            _emit_no_events("csv", "nothing here")
        self.assertIn("nothing here", cap.out)

    def test_json_fmt_does_not_print_to_console(self):
        with _ConsoleCapture() as cap:
            with patch("telemetry.collector.emit_rows"):
                _emit_no_events("json", "should not appear")
        self.assertNotIn("should not appear", cap.out)


# ===========================================================================
# 5. _docker_env
# ===========================================================================

class TestDockerEnv(unittest.TestCase):

    def test_docker_host_already_set_is_preserved(self):
        with patch.dict(os.environ, {"DOCKER_HOST": "tcp://existing:2376"}, clear=False):
            env = _docker_env()
        self.assertEqual(env["DOCKER_HOST"], "tcp://existing:2376")

    def test_socket_exists_sets_docker_host(self):
        with tempfile.TemporaryDirectory() as td:
            fake_sock = Path(td) / "docker.sock"
            fake_sock.touch()
            with patch.dict(os.environ, {}, clear=False):
                # Remove DOCKER_HOST if it's set
                env_copy = {k: v for k, v in os.environ.items() if k != "DOCKER_HOST"}
                with patch.dict(os.environ, env_copy, clear=True):
                    with patch.object(collector, "_DOCKER_SOCKET", fake_sock):
                        env = _docker_env()
        self.assertEqual(env.get("DOCKER_HOST"), f"unix://{fake_sock}")

    def test_socket_missing_docker_host_not_set(self):
        with tempfile.TemporaryDirectory() as td:
            missing_sock = Path(td) / "no-such.sock"
            env_copy = {k: v for k, v in os.environ.items() if k != "DOCKER_HOST"}
            with patch.dict(os.environ, env_copy, clear=True):
                with patch.object(collector, "_DOCKER_SOCKET", missing_sock):
                    env = _docker_env()
        self.assertNotIn("DOCKER_HOST", env)

    def test_returns_copy_not_original(self):
        with patch.dict(os.environ, {"DOCKER_HOST": "unix:///test.sock"}, clear=False):
            env = _docker_env()
            env["DOCKER_HOST"] = "mutated"
        # os.environ should be unchanged
        self.assertNotEqual(os.environ.get("DOCKER_HOST"), "mutated")


# ===========================================================================
# 6. _run_compose
# ===========================================================================

class TestRunCompose(unittest.TestCase):

    def test_success_on_first_try(self):
        expected = _cp(returncode=0, stdout="done")
        with patch("telemetry.collector.subprocess.run", return_value=expected) as mock_run:
            result = _run_compose(["up", "-d"], env={})
        self.assertIs(result, expected)
        self.assertEqual(mock_run.call_count, 1)
        # First arg of first call should be a list starting with "docker-compose"
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "docker-compose")

    def test_fallback_to_plugin_on_file_not_found(self):
        plugin_result = _cp(returncode=0, stdout="plugin ok")
        side_effects = [FileNotFoundError(), plugin_result]
        with patch("telemetry.collector.subprocess.run", side_effect=side_effects) as mock_run:
            result = _run_compose(["up", "-d"], env={})
        self.assertIs(result, plugin_result)
        self.assertEqual(mock_run.call_count, 2)
        # Second call should use "docker" + "compose"
        plugin_cmd = mock_run.call_args[0][0]
        self.assertEqual(plugin_cmd[0], "docker")
        self.assertEqual(plugin_cmd[1], "compose")

    def test_both_forms_not_found_prints_error_and_returns_none(self):
        with _ConsoleCapture() as cap:
            with patch("telemetry.collector.subprocess.run", side_effect=FileNotFoundError()):
                result = _run_compose(["up", "-d"], env={})
        self.assertIsNone(result)
        self.assertIn("docker-compose not found", cap.err)

    def test_timeout_on_standalone_prints_error_and_returns_none(self):
        # TimeoutExpired is only caught at the outer level (standalone), not the plugin branch
        with _ConsoleCapture() as cap:
            with patch(
                "telemetry.collector.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="docker-compose", timeout=60),
            ):
                result = _run_compose(["up", "-d"], env={})
        self.assertIsNone(result)
        self.assertIn("timed out", cap.err)

    def test_tail_args_passed_through(self):
        with patch("telemetry.collector.subprocess.run", return_value=_cp()) as mock_run:
            _run_compose(["logs", "--tail", "100"], env={})
        cmd = mock_run.call_args[0][0]
        self.assertIn("logs", cmd)
        self.assertIn("--tail", cmd)
        self.assertIn("100", cmd)


# ===========================================================================
# 7. _print_port_bindings
# ===========================================================================

class TestPrintPortBindings(unittest.TestCase):

    def test_valid_port_bindings_printed(self):
        ports_json = json.dumps({
            "4317/tcp": [{"HostIp": "127.0.0.1", "HostPort": "4317"}]
        })
        with _ConsoleCapture() as cap:
            with patch("telemetry.collector.subprocess.run", return_value=_cp(stdout=ports_json)):
                _print_port_bindings("abc123def456", env={})
        self.assertIn("4317/tcp", cap.out)
        self.assertIn("127.0.0.1:4317", cap.out)

    def test_host_ip_defaults_to_0_0_0_0(self):
        ports_json = json.dumps({
            "8080/tcp": [{"HostPort": "8080"}]
        })
        with _ConsoleCapture() as cap:
            with patch("telemetry.collector.subprocess.run", return_value=_cp(stdout=ports_json)):
                _print_port_bindings("abc123def456", env={})
        self.assertIn("0.0.0.0:8080", cap.out)

    def test_host_port_defaults_to_question_mark(self):
        ports_json = json.dumps({
            "9090/tcp": [{"HostIp": "0.0.0.0"}]  # nosec B104 - fixture value, not a socket bind
        })
        with _ConsoleCapture() as cap:
            with patch("telemetry.collector.subprocess.run", return_value=_cp(stdout=ports_json)):
                _print_port_bindings("abc123def456", env={})
        self.assertIn("0.0.0.0:?", cap.out)

    def test_non_zero_returncode_no_output(self):
        with _ConsoleCapture() as cap:
            with patch("telemetry.collector.subprocess.run", return_value=_cp(returncode=1, stderr="error")):
                _print_port_bindings("abc123def456", env={})
        self.assertEqual(cap.out.strip(), "")

    def test_empty_stdout_no_output(self):
        with _ConsoleCapture() as cap:
            with patch("telemetry.collector.subprocess.run", return_value=_cp(stdout="")):
                _print_port_bindings("abc123def456", env={})
        self.assertEqual(cap.out.strip(), "")

    def test_invalid_json_stdout_no_crash(self):
        with _ConsoleCapture() as cap:
            with patch("telemetry.collector.subprocess.run", return_value=_cp(stdout="not json")):
                _print_port_bindings("abc123def456", env={})
        self.assertEqual(cap.out.strip(), "")

    def test_timeout_no_crash(self):
        with _ConsoleCapture() as cap:
            with patch(
                "telemetry.collector.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=10),
            ):
                _print_port_bindings("abc123def456", env={})
        self.assertEqual(cap.out.strip(), "")

    def test_empty_bindings_list_for_port(self):
        # None or [] for port → no print
        ports_json = json.dumps({"4317/tcp": None})
        with _ConsoleCapture() as cap:
            with patch("telemetry.collector.subprocess.run", return_value=_cp(stdout=ports_json)):
                _print_port_bindings("abc123def456", env={})
        self.assertEqual(cap.out.strip(), "")

    def test_empty_list_bindings_for_port(self):
        ports_json = json.dumps({"4317/tcp": []})
        with _ConsoleCapture() as cap:
            with patch("telemetry.collector.subprocess.run", return_value=_cp(stdout=ports_json)):
                _print_port_bindings("abc123def456", env={})
        self.assertEqual(cap.out.strip(), "")


# ===========================================================================
# 8. _print_container_details
# ===========================================================================

class TestPrintContainerDetails(unittest.TestCase):

    def test_last_five_lines_shown(self):
        log_lines = ["line1", "line2", "line3", "line4", "line5", "line6", "line7"]
        logs_stdout = "\n".join(log_lines)
        side_effects = [
            _cp(stdout="{}"),       # inspect call (port bindings — empty json)
            _cp(stdout=logs_stdout),  # logs call
        ]
        with _ConsoleCapture() as cap:
            with patch("telemetry.collector.subprocess.run", side_effect=side_effects):
                _print_container_details("abc123def456", env={})
        # lines 3-7 should appear; lines 1-2 should not
        self.assertIn("line7", cap.out)
        self.assertIn("line3", cap.out)
        self.assertNotIn("line1", cap.out)
        self.assertNotIn("line2", cap.out)

    def test_stderr_included_in_log_tail(self):
        # docker logs sends real logs to stderr; check combined
        side_effects = [
            _cp(stdout="{}"),
            _cp(stdout="stdout-line", stderr="stderr-line"),
        ]
        with _ConsoleCapture() as cap:
            with patch("telemetry.collector.subprocess.run", side_effect=side_effects):
                _print_container_details("abc123def456", env={})
        self.assertIn("stdout-line", cap.out)
        self.assertIn("stderr-line", cap.out)

    def test_non_zero_returncode_no_log_section(self):
        side_effects = [
            _cp(stdout="{}"),
            _cp(returncode=1, stderr="error"),
        ]
        with _ConsoleCapture() as cap:
            with patch("telemetry.collector.subprocess.run", side_effect=side_effects):
                _print_container_details("abc123def456", env={})
        self.assertNotIn("last 5 log lines", cap.out)

    def test_timeout_on_logs_no_crash(self):
        side_effects = [
            _cp(stdout="{}"),
            subprocess.TimeoutExpired(cmd="docker", timeout=10),
        ]
        with _ConsoleCapture() as cap:
            with patch("telemetry.collector.subprocess.run", side_effect=side_effects):
                _print_container_details("abc123def456", env={})
        # Should not raise; output may be empty or have port section
        self.assertNotIn("last 5 log lines", cap.out)

    def test_exactly_five_log_lines_all_shown(self):
        logs_stdout = "\n".join(["a", "b", "c", "d", "e"])
        side_effects = [_cp(stdout="{}"), _cp(stdout=logs_stdout)]
        with _ConsoleCapture() as cap:
            with patch("telemetry.collector.subprocess.run", side_effect=side_effects):
                _print_container_details("abc123def456", env={})
        for line in ["a", "b", "c", "d", "e"]:
            self.assertIn(line, cap.out)


# ===========================================================================
# 9. _print_docker_containers
# ===========================================================================

class TestPrintDockerContainers(unittest.TestCase):

    def test_docker_not_installed_prints_error(self):
        with _ConsoleCapture() as cap:
            with patch("telemetry.collector.subprocess.run", side_effect=FileNotFoundError()):
                _print_docker_containers(env={})
        self.assertIn("docker not found", cap.err)

    def test_timeout_prints_error(self):
        with _ConsoleCapture() as cap:
            with patch(
                "telemetry.collector.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=10),
            ):
                _print_docker_containers(env={})
        self.assertIn("timed out", cap.err)

    def test_non_zero_returncode_prints_stderr(self):
        with _ConsoleCapture() as cap:
            with patch("telemetry.collector.subprocess.run", return_value=_cp(returncode=1, stderr="permission denied")):
                _print_docker_containers(env={})
        self.assertIn("permission denied", cap.err)

    def test_non_zero_returncode_unknown_error_fallback(self):
        with _ConsoleCapture() as cap:
            with patch("telemetry.collector.subprocess.run", return_value=_cp(returncode=1, stderr="")):
                _print_docker_containers(env={})
        self.assertIn("unknown error", cap.err)

    def test_empty_stdout_prints_not_running(self):
        with _ConsoleCapture() as cap:
            with patch("telemetry.collector.subprocess.run", return_value=_cp(stdout="")):
                _print_docker_containers(env={})
        self.assertIn("Collector not running", cap.out)

    def test_whitespace_only_stdout_prints_not_running(self):
        with _ConsoleCapture() as cap:
            with patch("telemetry.collector.subprocess.run", return_value=_cp(stdout="   \n")):
                _print_docker_containers(env={})
        self.assertIn("Collector not running", cap.out)

    def test_valid_container_line_calls_print_details(self):
        valid_id = "a1b2c3d4e5f6"  # 12 hex chars
        ps_stdout = f"{valid_id}\tUp 2 hours\totel-collector\n"
        with _ConsoleCapture() as cap:
            with patch("telemetry.collector.subprocess.run", return_value=_cp(stdout=ps_stdout)):
                with patch("telemetry.collector._print_container_details") as mock_details:
                    _print_docker_containers(env={})
        mock_details.assert_called_once_with(valid_id, {})
        self.assertIn("otel-collector", cap.out)

    def test_malformed_hex_id_skipped(self):
        bad_id = "not-a-hex-id!"
        ps_stdout = f"{bad_id}\tUp 2 hours\totel-collector\n"
        with _ConsoleCapture():
            with patch("telemetry.collector.subprocess.run", return_value=_cp(stdout=ps_stdout)):
                with patch("telemetry.collector._print_container_details") as mock_details:
                    _print_docker_containers(env={})
        mock_details.assert_not_called()

    def test_uppercase_hex_not_matched_by_regex(self):
        # The regex is [0-9a-f]{12,64} — uppercase does NOT match
        upper_id = "A1B2C3D4E5F6"
        ps_stdout = f"{upper_id}\tUp 2 hours\totel-collector\n"
        with patch("telemetry.collector.subprocess.run", return_value=_cp(stdout=ps_stdout)):
            with patch("telemetry.collector._print_container_details") as mock_details:
                _print_docker_containers(env={})
        mock_details.assert_not_called()

    def test_too_short_hex_id_skipped(self):
        short_id = "a1b2c3"  # only 6 chars, less than 12
        ps_stdout = f"{short_id}\tUp\totel-collector\n"
        with patch("telemetry.collector.subprocess.run", return_value=_cp(stdout=ps_stdout)):
            with patch("telemetry.collector._print_container_details") as mock_details:
                _print_docker_containers(env={})
        mock_details.assert_not_called()

    def test_valid_64_char_id_accepted(self):
        long_id = "a" * 64
        ps_stdout = f"{long_id}\tUp 1 day\totel-collector\n"
        with _ConsoleCapture():
            with patch("telemetry.collector.subprocess.run", return_value=_cp(stdout=ps_stdout)):
                with patch("telemetry.collector._print_container_details") as mock_details:
                    _print_docker_containers(env={})
        mock_details.assert_called_once_with(long_id, {})

    def test_multiple_containers_all_processed(self):
        id1 = "a1b2c3d4e5f6"
        id2 = "b2c3d4e5f6a1"
        ps_stdout = f"{id1}\tUp\totel-collector-1\n{id2}\tExited\totel-collector-2\n"
        with _ConsoleCapture():
            with patch("telemetry.collector.subprocess.run", return_value=_cp(stdout=ps_stdout)):
                with patch("telemetry.collector._print_container_details") as mock_details:
                    _print_docker_containers(env={})
        self.assertEqual(mock_details.call_count, 2)


# ===========================================================================
# 10. _print_data_files
# ===========================================================================

class TestPrintDataFiles(unittest.TestCase):

    def test_all_files_present(self):
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            (data_dir / "events.jsonl").write_text("x" * 100, encoding="utf-8")
            (data_dir / "metrics.jsonl").write_text("y" * 200, encoding="utf-8")
            (data_dir / "spans.jsonl").write_text("z" * 300, encoding="utf-8")
            with _ConsoleCapture() as cap:
                with patch.object(collector, "_OTEL_DATA_DIR", data_dir):
                    _print_data_files()
        self.assertIn("events.jsonl", cap.out)
        self.assertIn("metrics.jsonl", cap.out)
        self.assertIn("spans.jsonl", cap.out)
        self.assertIn("100", cap.out)
        self.assertIn("200", cap.out)
        self.assertIn("300", cap.out)
        self.assertIn("bytes", cap.out)

    def test_missing_files_show_not_found(self):
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            # Only create events.jsonl
            (data_dir / "events.jsonl").write_text("hello", encoding="utf-8")
            with _ConsoleCapture() as cap:
                with patch.object(collector, "_OTEL_DATA_DIR", data_dir):
                    _print_data_files()
        self.assertIn("events.jsonl", cap.out)
        self.assertIn("not found", cap.out)
        # metrics and spans not created → should say not found
        out = cap.out
        lines = [line for line in out.splitlines() if "metrics.jsonl" in line]
        self.assertTrue(any("not found" in line for line in lines))

    def test_all_files_missing_shows_not_found_for_each(self):
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            with _ConsoleCapture() as cap:
                with patch.object(collector, "_OTEL_DATA_DIR", data_dir):
                    _print_data_files()
        out = cap.out
        for fname in ("events.jsonl", "metrics.jsonl", "spans.jsonl"):
            lines = [line for line in out.splitlines() if fname in line]
            self.assertTrue(
                any("not found" in line for line in lines),
                f"Expected 'not found' for {fname}",
            )

    def test_large_file_thousands_separator(self):
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            # 1,234 bytes → should render as "1,234"
            (data_dir / "events.jsonl").write_bytes(b"x" * 1234)
            with _ConsoleCapture() as cap:
                with patch.object(collector, "_OTEL_DATA_DIR", data_dir):
                    _print_data_files()
        self.assertIn("1,234", cap.out)

    def test_data_files_header_printed(self):
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            with _ConsoleCapture() as cap:
                with patch.object(collector, "_OTEL_DATA_DIR", data_dir):
                    _print_data_files()
        self.assertIn("Data files", cap.out)


if __name__ == "__main__":
    unittest.main()
