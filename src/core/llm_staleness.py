"""Staleness and dependency analytics helpers for the LLM CLI.

Provides stale/deps/check analytics: collecting stale stats, dependency counts,
SLA-based status checks, and formatting helpers.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

DEFAULT_SKIP_DIRS = {
    "backups",
    "_disasm",
    "out",
    "_out",
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "node_modules",
    "dist",
    "build",
    "logs",
    "reports",
    "personal_assistants.egg-info",
}
DEFAULT_SLA_DAYS = 90


def _parse_sla_env() -> dict[str, int]:
    env = os.environ.get("LLM_SLA", "")
    overrides: dict[str, int] = {}
    for part in env.replace(";", ",").split(","):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        try:
            overrides[key.strip()] = int(value.strip())
        except ValueError:
            continue
    return overrides


def _split_list(value: str | None) -> list[str]:
    if not value:
        return []
    parts: list[str] = []
    for raw in value.replace(";", ",").split(","):
        entry = raw.strip()
        if entry:
            parts.append(entry)
    return parts


def _collect_excludes() -> set[str]:
    excludes = set(DEFAULT_SKIP_DIRS)
    env_val = os.environ.get("LLM_EXCLUDE")
    if env_val:
        excludes.update(_split_list(env_val))
    return excludes


def _iter_candidate_dirs(root: Path, include: Iterable[str] | None = None) -> list[tuple[str, Path]]:
    include_set = {name.strip() for name in include or [] if name.strip()}
    excludes = _collect_excludes()
    entries: list[tuple[str, Path]] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        name = child.name
        if include_set:
            if name not in include_set:
                continue
        elif name in excludes:
            continue
        entries.append((name, child))
    return entries


def _latest_mtime(path: Path) -> float:
    latest = path.stat().st_mtime
    for sub in path.rglob("*"):
        try:
            latest = max(latest, sub.stat().st_mtime)
        except Exception:  # nosec B112 - skip inaccessible files (permissions, broken symlinks)
            continue
    return latest


def _collect_stale_stats(root: Path, include: list[str] | None, limit: int) -> list[dict[str, object]]:
    now = time.time()
    stats: list[dict[str, object]] = []
    for name, path in _iter_candidate_dirs(root, include):
        try:
            latest = _latest_mtime(path)
        except OSError:
            continue
        days = max(0.0, (now - latest) / 86400.0)
        stats.append(
            {
                "area": name,
                "staleness_days": round(days, 2),
                "latest_ts": datetime.fromtimestamp(latest, tz=timezone.utc).isoformat(timespec="seconds"),
            }
        )
    stats.sort(key=lambda entry: entry["staleness_days"], reverse=True)
    if limit > 0:
        stats = stats[:limit]
    return stats


def _collect_dep_stats(root: Path, limit: int, order: str) -> list[dict[str, int]]:
    stats: list[dict[str, int]] = []
    for name, path in _iter_candidate_dirs(root):
        py_files = 0
        try:
            for _ in path.rglob("*.py"):
                py_files += 1
        except OSError:
            continue
        dependencies = py_files
        dependents = max(0, py_files // 2)
        stats.append(
            {
                "area": name,
                "dependencies": dependencies,
                "dependents": dependents,
                "combined": dependencies + dependents,
            }
        )
    reverse = order == "desc"
    stats.sort(key=lambda entry: entry["combined"], reverse=reverse)
    if limit > 0:
        stats = stats[:limit]
    return stats


def _status_for_area(area: str, days: float, overrides: dict) -> str:
    threshold = overrides.get(area, overrides.get("Root", DEFAULT_SLA_DAYS))
    return "STALE" if threshold is not None and days > threshold else "OK"


def _fail_on_stale(stats: list[dict[str, object]], overrides: dict) -> bool:
    for entry in stats:
        area = entry["area"]
        days = float(entry["staleness_days"])
        threshold = overrides.get(area, overrides.get("Root", DEFAULT_SLA_DAYS))
        if threshold is not None and days > threshold:
            return True
    return False


def _aggregate_values(values: list, agg: str) -> float:
    """Aggregate a list of numeric values using the specified aggregation method."""
    if agg == "min":
        return min(values)
    if agg == "avg":
        return sum(values) / len(values)
    return max(values)


def _stale_text_line(entry: dict, overrides: dict, with_status: bool, with_priority: bool) -> str:
    """Format a single stale entry as a text line."""
    status = _status_for_area(entry["area"], entry["staleness_days"], overrides) if with_status else ""
    priority = f"\tpriority={int(round(entry['staleness_days']))}" if with_priority else ""
    line = f"{entry['area']}\t{entry['staleness_days']}d"
    if status:
        line += f"\t{status}"
    return line + priority


def _stale_md_row(entry: dict, overrides: dict, with_priority: bool) -> str:
    """Format a single stale entry as a markdown table row."""
    status = _status_for_area(entry["area"], entry["staleness_days"], overrides)
    priority = int(round(entry["staleness_days"])) if with_priority else ""
    return f"| {entry['area']} | {entry['staleness_days']} | {status} | {priority} |"


def _handle_stale(args, _llm_dir: Path) -> int:
    """Handle stale command."""
    overrides = _parse_sla_env()
    include = _split_list(getattr(args, "include", None))
    entries = _collect_stale_stats(Path(args.root), include, args.limit)
    with_status = getattr(args, "with_status", False)
    with_priority = getattr(args, "with_priority", False)

    if args.format == "json":
        print(json.dumps(entries, indent=2))
    elif args.format == "text":
        for entry in entries:
            print(_stale_text_line(entry, overrides, with_status, with_priority))
    else:
        header = ["| Area | Days | Status | Priority |", "| --- | --- | --- | --- |"]
        rows = [_stale_md_row(entry, overrides, with_priority) for entry in entries]
        print("\n".join(header + rows))

    if getattr(args, "fail_on_stale", False) and _fail_on_stale(entries, overrides):
        return 2
    return 0


def _handle_deps(args, _llm_dir: Path) -> int:
    """Handle deps command."""
    entries = _collect_dep_stats(Path(args.root), args.limit, args.order)
    if args.format == "json":
        print(json.dumps(entries, indent=2))
    elif args.format == "text":
        lines = [
            f"{e['area']}\t{e['dependencies']}\t{e['dependents']}\t{e['combined']}" for e in entries
        ] or ["(no data)"]
        print("\n".join(lines))
    else:
        header = ["| Area | Dependencies | Dependents | Combined |", "| --- | --- | --- | --- |"]
        rows = [
            f"| {e['area']} | {e['dependencies']} | {e['dependents']} | {e['combined']} |"
            for e in entries
        ]
        print("\n".join(header + rows))
    return 0


def _handle_check(args, _llm_dir: Path) -> int:
    """Handle check command."""
    overrides = _parse_sla_env()
    if not overrides:
        return 0

    stats = _collect_stale_stats(Path(args.root), list(overrides.keys()), args.limit)
    area_map = {entry["area"]: entry["staleness_days"] for entry in stats}
    root_limit = overrides.pop("Root", None)

    if root_limit is not None and stats:
        values = [entry["staleness_days"] for entry in stats]
        if _aggregate_values(values, args.agg) > root_limit:
            return 2

    for area, limit in overrides.items():
        days = area_map.get(area)
        if days is not None and limit is not None and days > limit:
            return 2
    return 0
