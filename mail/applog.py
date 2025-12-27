"""Minimal structured logger used by the CLI.

Hand-restored to provide stable behavior without external deps.
Writes JSON lines to a file, creating parent directories as needed.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional


class AppLogger:
    def __init__(self, path: str) -> None:
        self.path = path
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)

    def _write(self, record: Dict[str, Any]) -> None:
        try:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:  # noqa: S110 - logging must never crash the app
            pass

    def start(self, cmd: str, argv: Optional[List[str]] = None) -> str:
        sid = str(uuid.uuid4())
        rec = {
            "ts": time.time(),
            "event": "start",
            "cmd": cmd,
            "argv": argv,
            "pid": os.getpid(),
            "session_id": sid,
        }
        self._write(rec)
        return sid

    def end(
        self,
        session_id: str,
        status: str = "ok",
        duration_ms: Optional[int] = None,
        error: Optional[str] = None,
    ) -> None:
        rec = {
            "ts": time.time(),
            "event": "end",
            "session_id": session_id,
            "status": status,
        }
        if duration_ms is not None:
            rec["duration_ms"] = int(duration_ms)
        if error:
            rec["error"] = error
        self._write(rec)

    def info(self, session_id: str, data: Dict[str, Any]) -> None:
        rec = {"ts": time.time(), "event": "info", "session_id": session_id, "data": data}
        self._write(rec)

    def error(self, session_id: str, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        rec = {
            "ts": time.time(),
            "event": "error",
            "session_id": session_id,
            "message": message,
            "extra": extra,
        }
        self._write(rec)
