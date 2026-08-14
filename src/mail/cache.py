"""JSON file-based cache for Gmail metadata and full messages."""

from __future__ import annotations

import os
from typing import Any

from core.fileutil import atomic_write_json, safe_load_json


class MailCache:
    def __init__(self, root: str) -> None:
        self.root = root
        self.meta_dir = os.path.join(root, "gmail", "messages", "meta")
        self.full_dir = os.path.join(root, "gmail", "messages", "full")
        os.makedirs(self.meta_dir, exist_ok=True)
        os.makedirs(self.full_dir, exist_ok=True)

    def _path(self, kind: str, msg_id: str) -> str:
        safe = (msg_id or "").strip()
        subdir = self.meta_dir if kind == "meta" else self.full_dir
        return os.path.join(subdir, f"{safe}.json")

    def get_meta(self, msg_id: str) -> dict[str, Any] | None:
        p = self._path("meta", msg_id)
        if not os.path.exists(p):
            return None
        return safe_load_json(p, default=None)

    def put_meta(self, msg_id: str, data: dict[str, Any]) -> None:
        p = self._path("meta", msg_id)
        atomic_write_json(p, data)

    def get_full(self, msg_id: str) -> dict[str, Any] | None:
        p = self._path("full", msg_id)
        if not os.path.exists(p):
            return None
        return safe_load_json(p, default=None)

    def put_full(self, msg_id: str, data: dict[str, Any]) -> None:
        p = self._path("full", msg_id)
        atomic_write_json(p, data)

