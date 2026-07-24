"""OTEL collector lifecycle subcommands for bin/telemetry."""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from core.cli_output import emit_rows

console = Console()
_err_console = Console(stderr=True)

def _get_repo_root() -> Path:
    """Return the repo root (two levels above telemetry/collector.py)."""
    return Path(__file__).resolve().parents[1]


_COMPOSE_PATH = _get_repo_root() / "docker-compose.otel.yaml"
_OTEL_DATA_DIR = Path.home() / ".config" / "otel"
_DOCKER_SOCKET = Path.home() / ".colima" / "default" / "docker.sock"

# File name constants for data files written by the collector
_EVENTS_FILE = "events.jsonl"
_METRICS_FILE = "metrics.jsonl"
_SPANS_FILE = "spans.jsonl"

# Docker Compose invocation constants
_COMPOSE_STANDALONE = "docker-compose"
_COMPOSE_PLUGIN = ["docker", "compose"]
_COMPOSE_NOT_FOUND_MSG = "docker-compose not found. Install Docker Compose (standalone: docker-compose, or plugin: docker compose)."
_COMPOSE_TIMEOUT_S = 60
_DOCKER_CMD_TIMEOUT_S = 10
_COMPOSE_PROJECT = "dancing-bear"


def _docker_env() -> dict[str, str]:
    """Return a copy of os.environ, optionally with DOCKER_HOST set to the Colima socket."""
    env = dict(os.environ)
    if "DOCKER_HOST" not in env and _DOCKER_SOCKET.exists():
        env["DOCKER_HOST"] = f"unix://{_DOCKER_SOCKET}"
    return env


def _run_compose(tail: list[str], env: dict[str, str]) -> subprocess.CompletedProcess | None:
    """Run docker-compose or fall back to the docker compose plugin form."""
    cmd = [_COMPOSE_STANDALONE, "-f", str(_COMPOSE_PATH), "-p", _COMPOSE_PROJECT] + tail
    try:
        return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=_COMPOSE_TIMEOUT_S)
    except FileNotFoundError:
        cmd[0:1] = _COMPOSE_PLUGIN
        try:
            return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=_COMPOSE_TIMEOUT_S)
        except FileNotFoundError:
            _err_console.print(f"[red]{_COMPOSE_NOT_FOUND_MSG}[/]")
            return None
    except subprocess.TimeoutExpired:
        _err_console.print(f"[red]docker-compose timed out after {_COMPOSE_TIMEOUT_S}s.[/]")
        return None


def _print_port_bindings(cid: str, env: dict[str, str]) -> None:
    """Print port bindings for a container from docker inspect."""
    try:
        inspect = subprocess.run(
            ["docker", "inspect", "--format", "{{json .NetworkSettings.Ports}}", cid],
            env=env, capture_output=True, text=True, timeout=_DOCKER_CMD_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return
    if not (inspect.returncode == 0 and inspect.stdout.strip()):
        return
    try:
        ports = json.loads(inspect.stdout.strip())
    except json.JSONDecodeError:
        return
    for port, bindings in (ports or {}).items():
        for b in (bindings or []):
            console.print(f"  [dim]{port}[/] → {b.get('HostIp', '0.0.0.0')}:{b.get('HostPort', '?')}")


def _print_container_details(cid: str, env: dict[str, str]) -> None:
    """Print port bindings and last log lines for a container."""
    _print_port_bindings(cid, env)

    try:
        logs = subprocess.run(
            ["docker", "logs", "--tail", "5", cid],
            env=env, capture_output=True, text=True, timeout=_DOCKER_CMD_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return
    if logs.returncode == 0 and (logs.stdout or logs.stderr):
        console.print("[dim]--- last 5 log lines ---[/]")
        for log_line in (logs.stdout + logs.stderr).splitlines()[-5:]:
            console.print(f"  [dim]{log_line}[/]")


def _decode_otlp_value(value: object) -> object:
    """Decode an OTLP AnyValue dict to a Python scalar, preserving types."""
    if not isinstance(value, dict):
        return value
    for key, typ in (
        ("stringValue", str),
        ("intValue", int),
        ("doubleValue", float),
        ("boolValue", bool),
    ):
        if key in value:
            try:
                return typ(value[key])  # type: ignore[operator]
            except (TypeError, ValueError):
                return value[key]
    return value


def _parse_otlp_event(line: str) -> dict[str, object] | None:
    """Parse one OTLP JSONL line into {timestamp, body, attributes}. Returns None on error."""
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    try:
        record = data["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        ts_ns = int(record.get("timeUnixNano") or 0)
        if ts_ns == 0:
            return None
        timestamp = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        body = record.get("body", {}).get("stringValue")
        if body is None:
            return None
        raw_attrs = record.get("attributes", [])
        attributes = {a["key"]: _decode_otlp_value(a.get("value")) for a in raw_attrs}
        return {"timestamp": timestamp, "body": body, "attributes": attributes}
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return None


def positive_int(value: str) -> int:
    """Parse an argparse int argument, requiring it to be >= 1."""
    ivalue = int(value)
    if ivalue < 1:
        raise argparse.ArgumentTypeError(f"{value!r} is not >= 1")
    return ivalue


def _print_docker_containers(env: dict[str, str]) -> None:
    """Print otel-collector container state via docker ps."""
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=otel-collector", "--format", "{{.ID}}\t{{.Status}}\t{{.Names}}"],
            env=env, capture_output=True, text=True, timeout=_DOCKER_CMD_TIMEOUT_S,
        )
    except FileNotFoundError:
        _err_console.print("[red]docker not found. Install Docker to use the collector.[/]")
        return
    except subprocess.TimeoutExpired:
        _err_console.print(f"[red]docker ps timed out after {_DOCKER_CMD_TIMEOUT_S}s (is Docker running?)[/]")
        return
    if result.returncode != 0:
        _err_console.print(f"[red]docker ps failed: {result.stderr.strip() or 'unknown error'}[/]")
        return
    if not result.stdout.strip():
        console.print("[yellow]Collector not running (no container found).[/]")
        return
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        cid, cstatus, cname = (parts + ["", "", ""])[:3]
        if not re.fullmatch(r"[0-9a-f]{12,64}", cid):
            continue
        console.print(f"[bold]Container:[/] {cname} ({cid[:12]})  status=[green]{cstatus}[/]")
        _print_container_details(cid, env)


def _print_data_files() -> None:
    """Print sizes of OTEL data files."""
    console.print()
    console.print("[bold]Data files:[/]")
    for fname in (_EVENTS_FILE, _METRICS_FILE, _SPANS_FILE):
        fpath = _OTEL_DATA_DIR / fname
        if fpath.exists():
            size = fpath.stat().st_size
            console.print(f"  {fname}: {size:,} bytes")
        else:
            console.print(f"  {fname}: [dim]not found[/]")


def collector_status() -> int:
    """Show collector container state and data file sizes."""
    _print_docker_containers(_docker_env())
    _print_data_files()
    return 0


def collector_start() -> int:
    """Start the OTEL collector via docker-compose."""
    if not _COMPOSE_PATH.exists():
        _err_console.print(f"[red]docker-compose.otel.yaml not found at {_COMPOSE_PATH}[/]")
        return 1

    env = _docker_env()
    result = _run_compose(["up", "-d"], env)
    if result is None:
        return 1

    if result.returncode != 0:
        _err_console.print(f"[red]Failed to start collector:[/]\n{result.stderr}")
        return 1

    console.print("[green]Collector started.[/]")
    if result.stdout:
        console.print(result.stdout.strip())
    return 0


def collector_stop() -> int:
    """Stop the OTEL collector via docker-compose."""
    if not _COMPOSE_PATH.exists():
        console.print(f"[yellow]docker-compose.otel.yaml not found at {_COMPOSE_PATH} — nothing to stop.[/]")
    else:
        env = _docker_env()
        result = _run_compose(["down"], env)
        if result is None:
            return 1

        if result.returncode != 0:
            _err_console.print(
                f"[red]docker-compose down failed (exit {result.returncode}):[/] {result.stderr.strip() or 'no output'}"
            )
            return 1

        console.print("[green]Stopped.[/]")
    return 0


_EVENTS_HEADERS = ["timestamp", "body", "attributes"]


def _emit_no_events(fmt: str, message: str) -> None:
    """Emit an empty result for events — [] for JSON, dim message for table."""
    if fmt == "json":
        emit_rows([], fmt="json", headers=_EVENTS_HEADERS)
    else:
        console.print(f"[dim]{message}[/]")


def _parse_event_lines(tail_lines: list[str]) -> tuple[list[dict[str, object]], int]:
    """Parse OTLP JSONL lines into row dicts. Returns (rows, skipped_count)."""
    rows: list[dict[str, object]] = []
    skipped = 0
    for line in tail_lines:
        line = line.strip()
        if not line:
            continue
        parsed = _parse_otlp_event(line)
        if parsed is None:
            skipped += 1
        else:
            rows.append(parsed)
    return rows, skipped


def collector_events(limit: int, fmt: str) -> int:
    """Tail recent events from the OTEL events.jsonl file."""
    events_file = _OTEL_DATA_DIR / _EVENTS_FILE

    if not events_file.exists():
        _emit_no_events(fmt, "No events file found. Start the collector and run a session first.")
        return 0

    try:
        with events_file.open(encoding="utf-8") as fp:
            tail_lines = list(collections.deque(
                (ln.rstrip("\n") for ln in fp),
                maxlen=limit,
            ))
    except OSError as exc:
        _err_console.print(f"[red]Cannot read events file: {exc}[/]")
        return 1

    if not tail_lines:
        _emit_no_events(fmt, "Events file is empty.")
        return 0

    rows, skipped = _parse_event_lines(tail_lines)

    if skipped:
        _err_console.print(f"[dim]Skipped {skipped} malformed line(s).[/]")

    if not rows:
        _emit_no_events(fmt, "No parseable events found.")
        return 0

    return emit_rows(rows, fmt=fmt, headers=_EVENTS_HEADERS)
