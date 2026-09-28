"""Canonical concern-guide selector for dancing-bear.

Loads ``concerns/selection.yaml`` (the single source of truth) and returns an
ordered, deduplicated list of guide filenames for a set of changed paths and an
optional task_type.

Usage::

    from workflow.concern_select import select_guides

    guides = select_guides(
        paths=["src/workflow/cli.py", "workflows/my.yaml"],
        task_type="feature",
    )
    # → ["patterns.md", "correctness.md", "security.md", ...]

The function is pure (no I/O after the YAML is cached) and deterministic: same
inputs always produce the same output.
"""

from __future__ import annotations

import fnmatch
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

# Path to the canonical selection rules file, resolved relative to this
# module so it works regardless of the caller's working directory.
_CONCERNS_DIR = Path(__file__).parent.parent.parent / "concerns"
_SELECTION_YAML = _CONCERNS_DIR / "selection.yaml"


# ---------------------------------------------------------------------------
# YAML loading (lazy import, cached)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_rules() -> dict[str, Any]:
    """Load and cache concerns/selection.yaml. Raises on parse error."""
    import yaml  # lazy — optional dep

    text = _SELECTION_YAML.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"selection.yaml must be a mapping, got {type(data).__name__}")
    return data


# ---------------------------------------------------------------------------
# Core selector (internal)
# ---------------------------------------------------------------------------


def _collect_guides(
    paths: list[str],
    task_type: str | None,
) -> dict[str, list[str]]:
    """Return an ordered ``{guide: [reasons]}`` dict.

    Applies always-rules, glob rules (with override-group suppression),
    task_type rules, and the default fallback when no input is given.

    Reasons are deduplicated per guide: the same reason string is recorded at
    most once, so two ``.py`` files matching ``glob:*.py`` produce a single
    ``"glob:*.py"`` entry rather than one per path. Use path-prefixed reasons
    (``"src/x.py: glob:*.py"``) when per-path detail is needed.
    """
    rules = _load_rules()

    # order: dict preserves insertion order (Python 3.7+); reason_sets tracks
    # seen reasons per guide to avoid duplicates.
    seen: dict[str, list[str]] = {}
    reason_sets: dict[str, set[str]] = {}

    def _add(guide: str, reason: str) -> None:
        if guide not in seen:
            seen[guide] = []
            reason_sets[guide] = set()
        if reason not in reason_sets[guide]:
            seen[guide].append(reason)
            reason_sets[guide].add(reason)

    # 1. Always-include guides
    for guide in rules.get("always", []):
        _add(guide, "always")

    # 2. Path-based glob rules
    _apply_path_rules(paths, rules, _add)

    # 3. task_type rules
    if task_type:
        task_rules: dict[str, list[str]] = rules.get("task_type_rules", {})
        for guide in task_rules.get(task_type, []):
            _add(guide, f"task_type:{task_type}")

    # 4. Default when nothing matched (no paths, no task_type)
    if not paths and not task_type:
        defaults: list[str] = rules.get("default_guides", ["correctness.md", "patterns.md"])
        for guide in defaults:
            _add(guide, "default")

    return seen


def _apply_path_rules(
    paths: list[str],
    rules: dict[str, Any],
    add: Any,
) -> None:
    """Apply glob_rules and override_groups to each path, calling ``add(guide, reason)``."""
    override_groups: dict[str, Any] = rules.get("override_groups", {})
    glob_rules: list[dict[str, Any]] = rules.get("glob_rules", [])

    for path in paths:
        norm = path.replace(os.sep, "/")
        basename = os.path.basename(norm)
        _, dot_ext = os.path.splitext(basename)

        # Track which override groups fired for this path.
        suppressed = _fire_override_groups(norm, basename, dot_ext, override_groups, add)

        # Evaluate generic glob rules, skipping suppressed override groups.
        for rule in glob_rules:
            override_group = rule.get("override_group")
            if override_group and override_group in suppressed:
                continue
            if _path_matches(norm, basename, dot_ext, rule):
                pattern = _rule_pattern(rule)
                for guide in rule.get("guides", []):
                    add(guide, f"glob:{pattern}")


def _fire_override_groups(
    norm: str,
    basename: str,
    dot_ext: str,
    override_groups: dict[str, Any],
    add: Any,
) -> set[str]:
    """Fire override-group rules for a path; return the set of group names that fired."""
    suppressed: set[str] = set()
    for group_name, group_def in override_groups.items():
        for override_rule in group_def.get("rules", []):
            if _path_matches(norm, basename, dot_ext, override_rule):
                for guide in override_rule.get("guides", []):
                    add(guide, f"override:{group_name}:{_rule_pattern(override_rule)}")
                suppressed.add(group_name)
    return suppressed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def select_guides(
    paths: list[str] | None = None,
    task_type: str | None = None,
) -> list[str]:
    """Return an ordered, deduplicated list of guide filenames.

    Args:
        paths:      Repo-relative file paths (or absolute paths) to consider.
        task_type:  Optional task context: ``feature``, ``test``, ``security``,
                    ``docs``, ``refactor``, ``workflow``.

    Returns:
        A list of guide filenames (e.g. ``["patterns.md", "correctness.md"]``).
        ``patterns.md`` is always first (it is in the ``always`` list).
    """
    return list(_collect_guides(list(paths or []), task_type or None).keys())


def select_guides_with_reasons(
    paths: list[str] | None = None,
    task_type: str | None = None,
) -> dict[str, list[str]]:
    """Like :func:`select_guides` but returns ``{guide: [reasons]}`` mapping.

    Used by the CLI ``--format json`` output to produce the ``matched`` field.
    """
    return _collect_guides(list(paths or []), task_type or None)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _path_matches(
    norm_path: str,
    basename: str,
    dot_ext: str,
    rule: dict[str, Any],
) -> bool:
    """Return True if the path matches the rule's glob/ext/name pattern."""
    if "glob" in rule:
        return fnmatch.fnmatch(norm_path, rule["glob"])
    if "ext" in rule:
        return dot_ext == rule["ext"]
    if "name" in rule:
        return basename == rule["name"]
    return False


def _rule_pattern(rule: dict[str, Any]) -> str:
    """Return a human-readable pattern string for a rule."""
    if "glob" in rule:
        return rule["glob"]
    if "ext" in rule:
        return f"*{rule['ext']}"
    if "name" in rule:
        return rule["name"]
    return "(unknown)"


# ---------------------------------------------------------------------------
# Catalogue helpers (used by tests)
# ---------------------------------------------------------------------------


def all_concern_guides() -> list[str]:
    """Return all *.md filenames in concerns/ except README.md."""
    return sorted(
        p.name
        for p in _CONCERNS_DIR.iterdir()
        if p.suffix == ".md" and p.name != "README.md"
    )


def reachable_guides() -> set[str]:
    """Return the set of guides reachable by *some* rule in selection.yaml."""
    rules = _load_rules()
    reachable: set[str] = set()

    for guide in rules.get("always", []):
        reachable.add(guide)

    for rule in rules.get("glob_rules", []):
        reachable.update(rule.get("guides", []))

    for group_def in rules.get("override_groups", {}).values():
        for orule in group_def.get("rules", []):
            reachable.update(orule.get("guides", []))

    for guides in rules.get("task_type_rules", {}).values():
        reachable.update(guides)

    for guide in rules.get("default_guides", []):
        reachable.add(guide)

    return reachable


