"""
Lightweight OTLP HTTP receiver — replaces the Docker-based OTel collector.

Listens on localhost:4318, accepts OTLP JSON payloads for metrics, logs
(events), and traces (spans), and appends each request body as a JSONL record
to the appropriate file under ~/.config/otel/.

Run as a daemon:
    python -m telemetry.otel.collector --daemon
    python -m telemetry.otel.collector --stop
    python -m telemetry.otel.collector --status
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Lock

DEFAULT_DATA_DIR = Path.home() / ".config" / "otel"
DEFAULT_PORT = 4318
PID_FILE = Path.home() / ".config" / "otel-collector.pid"

_file_locks: dict[Path, Lock] = {}


def _lock_for(path: Path) -> Lock:
    if path not in _file_locks:
        _file_locks[path] = Lock()
    return _file_locks[path]


def _append_jsonl(path: Path, body: bytes) -> bool:
    try:
        json.loads(body)  # validate only
    except json.JSONDecodeError:
        return False
    line = body.decode(errors="replace").strip() + "\n"
    with _lock_for(path):
        with path.open("a") as fh:
            fh.write(line)
    return True


class _OTLPHandler(BaseHTTPRequestHandler):
    data_dir: Path = DEFAULT_DATA_DIR

    _path_map = {
        "/v1/metrics": "metrics.jsonl",
        "/v1/logs": "events.jsonl",
        "/v1/traces": "spans.jsonl",
    }

    def do_POST(self) -> None:  # noqa: N802
        filename = self._path_map.get(self.path)
        if filename is None:
            self.send_response(404)
            self.end_headers()
            return

        content_length = self.headers.get("Content-Length")
        if content_length is None:
            self.send_response(411)
            self.end_headers()
            return
        try:
            length = int(content_length)
        except ValueError:
            self.send_response(400)
            self.end_headers()
            return
        body = self.rfile.read(length)
        if not _append_jsonl(self.data_dir / filename, body):
            self.send_response(400)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"partialSuccess":{}}')

    def log_message(self, *_args: object) -> None:  # suppress request logs
        pass


def run_server(data_dir: Path = DEFAULT_DATA_DIR, port: int = DEFAULT_PORT) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)

    class _Handler(_OTLPHandler):
        pass
    _Handler.data_dir = data_dir

    server = HTTPServer(("127.0.0.1", port), _Handler)
    server.serve_forever()


def _write_pid() -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))


def _read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text().strip())
    except ValueError:
        return None


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _daemonize(data_dir: Path, port: int) -> None:
    """Run as daemon after double-fork. Called only in the grandchild process."""
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull_fd, 1)
    os.dup2(devnull_fd, 2)
    os.close(devnull_fd)
    _write_pid()

    def _cleanup(sig: int, _frame: object) -> None:
        PID_FILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)
    try:
        run_server(data_dir, port)
    finally:
        PID_FILE.unlink(missing_ok=True)


def cmd_start(data_dir: Path, port: int) -> None:
    if not hasattr(os, "fork"):
        print("Daemon mode requires a Unix-like OS. Use --no-daemon to run in foreground.")
        raise SystemExit(1)

    pid = _read_pid()
    if pid and _pid_running(pid):
        print(f"Collector already running (pid {pid})")
        return

    # Double-fork to daemonize: parent returns; first child exits; grandchild continues
    if os.fork() > 0:
        return
    os.setsid()
    if os.fork() > 0:
        sys.exit(0)

    _daemonize(data_dir, port)


def cmd_stop() -> None:
    pid = _read_pid()
    if pid is None or not _pid_running(pid):
        print("Collector is not running")
        PID_FILE.unlink(missing_ok=True)
        return
    os.kill(pid, signal.SIGTERM)
    stopped = False
    for _ in range(20):
        time.sleep(0.1)
        if not _pid_running(pid):
            stopped = True
            break
    if stopped:
        PID_FILE.unlink(missing_ok=True)
        print(f"Collector stopped (pid {pid})")
    else:
        print(f"Collector did not stop within 2s (pid {pid}) — PID file retained for retry")
        raise SystemExit(1)


def cmd_status(data_dir: Path) -> None:
    pid = _read_pid()
    if pid and _pid_running(pid):
        print(f"running (pid {pid})")
    else:
        print("not running")

    for name in ("metrics.jsonl", "events.jsonl", "spans.jsonl"):
        fp = data_dir / name
        if fp.exists():
            size = fp.stat().st_size
            if size < 10 * 1024 * 1024:  # only count lines for files < 10MB
                lines = 0
                with fp.open("rb") as fh:
                    for chunk in iter(lambda: fh.read(65536), b""):
                        lines += chunk.count(b"\n")
                print(f"  {name}: {size:,} bytes, {lines:,} lines")
            else:
                print(f"  {name}: {size:,} bytes")
        else:
            print(f"  {name}: not found")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Lightweight OTLP HTTP receiver")
    parser.add_argument("--daemon", action="store_true", help="Start as background daemon")
    parser.add_argument("--stop", action="store_true", help="Stop running daemon")
    parser.add_argument("--status", action="store_true", help="Show status")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()

    if args.stop:
        cmd_stop()
    elif args.status:
        cmd_status(args.data_dir)
    elif args.daemon:
        cmd_start(args.data_dir, args.port)
        print(f"Collector starting on port {args.port}, data → {args.data_dir}")
    else:
        print(f"Serving on port {args.port}, data → {args.data_dir}  (Ctrl-C to stop)")
        run_server(args.data_dir, args.port)
