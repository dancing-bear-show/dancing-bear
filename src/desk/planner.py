from __future__ import annotations

import os
import time
from dataclasses import dataclass

from core.cli_errors import NotFoundError
from core.yamlio import load_config as _load_yaml

from .utils import expand_paths, parse_duration, parse_size


@dataclass
class MatchCriteria:
    """Criteria for matching files against a rule."""
    extensions: list[str]
    size_threshold: int | None
    age_threshold: int | None


def _file_matches_criteria(
    filename: str,
    stat: os.stat_result,
    criteria: MatchCriteria,
) -> bool:
    """Check if a file matches the given criteria."""
    # Extension check
    if criteria.extensions:
        if not any(filename.lower().endswith(ext) for ext in criteria.extensions):
            return False

    # Size check
    if criteria.size_threshold is not None:
        if stat.st_size < criteria.size_threshold:
            return False

    # Age check
    if criteria.age_threshold is not None:
        if (time.time() - stat.st_mtime) < criteria.age_threshold:
            return False

    return True


def _build_operation(
    src: str,
    filename: str,
    action: dict,
    rule_name: str,
) -> dict | None:
    """Build an operation dict from action config, or None if no action."""
    move_to = action.get("move_to")
    trash = bool(action.get("trash", False))

    if move_to:
        dest_dir = os.path.expanduser(move_to)
        return {
            "action": "move",
            "src": src,
            "dest": os.path.join(dest_dir, filename),
            "rule": rule_name,
        }
    elif trash:
        return {
            "action": "trash",
            "src": src,
            "rule": rule_name,
        }
    return None


def _parse_rule(rule: dict) -> tuple:
    """Parse a rule into match criteria, action, paths, and rule name."""
    match = rule.get("match", {})
    action = rule.get("action", {})

    paths = expand_paths(match.get("paths", ["~"]))
    extensions = [e.lower() for e in match.get("extensions", [])]

    size_gte = match.get("size_gte")
    older_than = match.get("older_than")

    criteria = MatchCriteria(
        extensions=extensions,
        size_threshold=parse_size(size_gte) if size_gte else None,
        age_threshold=parse_duration(older_than) if older_than else None,
    )

    return criteria, action, paths, rule.get("name", "")


def _plan_operation_for_file(
    dirpath: str,
    name: str,
    criteria: MatchCriteria,
    action: dict,
    rule_name: str,
) -> dict | None:
    """Build the operation for one file, or None if it doesn't match or has no action."""
    src = os.path.join(dirpath, name)
    try:
        st = os.stat(src)
    except (PermissionError, FileNotFoundError):
        return None

    if not _file_matches_criteria(name, st, criteria):
        return None

    return _build_operation(src, name, action, rule_name)


def _scan_directory(
    root: str,
    criteria: MatchCriteria,
    action: dict,
    rule_name: str,
) -> list[dict]:
    """Scan a directory tree and return matching operations."""
    operations: list[dict] = []

    if not os.path.exists(root):
        return operations

    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            op = _plan_operation_for_file(dirpath, name, criteria, action, rule_name)
            if op:
                operations.append(op)

    return operations


def plan_from_config(config_path: str) -> dict:
    """Generate a plan of file operations from a config file."""
    config_path = os.path.expanduser(config_path)
    if not os.path.exists(config_path):
        raise NotFoundError(f"Config file not found: {config_path}")

    cfg = _load_yaml(config_path) or {}
    version = int(cfg.get("version", 1))
    rules: list[dict] = cfg.get("rules", [])
    operations: list[dict] = []

    for rule in rules:
        criteria, action, paths, rule_name = _parse_rule(rule)
        for root in paths:
            operations.extend(_scan_directory(root, criteria, action, rule_name))

    return {
        "version": version,
        "generated_from": os.path.abspath(config_path),
        "operations": operations,
    }
