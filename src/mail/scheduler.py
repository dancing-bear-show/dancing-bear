from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from core.fileutil import atomic_write_json


def _queue_path() -> Path:
    env = os.environ.get("MAIL_ASSISTANT_SCHEDULE_PATH")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    base = Path(os.path.join(os.path.expanduser(xdg), "mail"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "scheduled_sends.json"


@dataclass
class ScheduledItem:
    provider: str  # e.g., 'gmail'
    profile: str   # e.g., 'gmail_personal'
    due_at: int    # epoch seconds (local time interpreted when parsed)
    raw_b64: str   # base64-encoded EmailMessage bytes
    thread_id: str | None = None
    to: str | None = None
    subject: str | None = None
    created_at: int = 0


def _load_queue() -> list[dict]:
    p = _queue_path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8")) or []
    except Exception:
        return []


def _save_queue(items: list[dict]) -> None:
    p = _queue_path()
    atomic_write_json(p, items)


def enqueue(item: ScheduledItem) -> None:
    items = _load_queue()
    if not item.created_at:
        item.created_at = int(time.time())
    items.append(asdict(item))
    _save_queue(items)


def pop_due(now_ts: int | None = None, *, profile: str | None = None, limit: int | None = None) -> list[dict]:
    now = int(now_ts or time.time())
    items = _load_queue()
    due: list[dict] = []
    rest: list[dict] = []
    for it in items:
        if it.get("due_at", 0) <= now and (profile is None or it.get("profile") == profile):
            due.append(it)
        else:
            rest.append(it)
    if limit is not None and len(due) > limit:
        send_now = due[:limit]
        keep_for_later = due[limit:]
        rest.extend(keep_for_later)
        due = send_now
    _save_queue(rest)
    return due


def parse_send_at(s: str) -> int | None:
    """Parse absolute time like 'YYYY-MM-DD HH:MM' or ISO8601 'YYYY-MM-DDTHH:MM'.

    Returns epoch seconds in local time.
    """
    if not s:
        return None
    s = s.strip()
    from datetime import datetime
    fmts = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(s, fmt)
            return int(dt.timestamp())
        except Exception:  # nosec B112 - skip on error
            continue
    return None


def parse_send_in(s: str) -> int | None:
    """Parse relative duration like '90m', '2h', '1h30m', '2d4h'. Returns seconds."""
    if not s:
        return None
    s = s.strip().lower()
    import re

    total = 0
    for amount, unit in re.findall(r"(\d+)([smhd])", s):
        n = int(amount)
        if unit == "s":
            total += n
        elif unit == "m":
            total += n * 60
        elif unit == "h":
            total += n * 3600
        elif unit == "d":
            total += n * 86400
    return total or None
