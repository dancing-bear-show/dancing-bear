"""iOS layout plan scaffolding and instruction generation."""

from __future__ import annotations

from typing import Any

from .constants import FOLDERS
from .layout_normalize import (
    NormalizedLayout,
    _get_app_id,
    _get_folder_apps,
    _is_app_item,
    _is_folder_item,
    compute_folder_page_map,
    compute_location_map,
    compute_root_app_page_map,
)


def _safe_int(value: Any, default: int = 0) -> int:
    """Safely convert a value to int, returning default if conversion fails."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _collect_pinned_apps(layout: NormalizedLayout, max_pins: int = 12) -> list[str]:
    """Collect pinned apps from dock and page 1."""
    pinned = list(dict.fromkeys(layout.dock))
    if not layout.pages:
        return pinned
    for it in layout.pages[0]:
        bid = _get_app_id(it)
        if bid and bid not in pinned:
            pinned.append(bid)
            if len(pinned) >= max_pins:
                break
    return pinned


def _collect_all_app_ids(layout: NormalizedLayout) -> list[str]:
    """Collect all app IDs from pages (not deduplicated)."""
    all_ids: list[str] = []
    for page in layout.pages:
        for it in page:
            if _is_app_item(it):
                all_ids.append(_get_app_id(it))
            elif _is_folder_item(it):
                all_ids.extend(_get_folder_apps(it))
    return all_ids


def scaffold_plan(layout: NormalizedLayout) -> dict[str, Any]:
    """Generate a scaffold plan from a layout."""
    pinned = _collect_pinned_apps(layout)
    all_app_ids = _collect_all_app_ids(layout)
    unassigned = [a for a in all_app_ids if a not in pinned]
    return {
        "#": [
            "Home Screen plan. Fill folders.apps with bundle IDs.",
            "pins: always on page 1 (top), plus dock.",
            "unassigned: all remaining apps from current layout.",
        ],
        "pins": pinned,
        "folders": {name: [] for name in FOLDERS},
        "unassigned": unassigned,
    }


def _generate_folder_instructions(
    folders: dict[str, list[str]], pins: set, loc: dict[str, str]
) -> list[str]:
    """Generate instructions for moving apps into folders."""
    instructions: list[str] = []
    for fname, apps in folders.items():
        if not apps:
            continue
        instructions.append(f"Create/Rename folder: {fname}")
        for a in apps:
            if a in pins:
                continue
            at = loc.get(a)
            if at is None:
                instructions.append(f"  • Install or locate app: {a}")
            elif not at.endswith(f"> {fname}"):
                instructions.append(f"  • Move {a} from {at} into folder {fname}")
    return instructions


def _generate_page_instructions(
    pages_spec: dict[str, Any],
    folder_page: dict[str, int],
    root_app_page: dict[str, int],
    loc: dict[str, str],
) -> list[str]:
    """Generate instructions for page organization."""
    instructions: list[str] = ["", "Page organization:"]
    for page_key in sorted(pages_spec.keys(), key=_safe_int):
        target_page = _safe_int(page_key)
        if target_page == 0:
            continue
        spec = pages_spec.get(page_key) or {}
        instructions.extend(_folder_page_instructions(spec, folder_page, target_page))
        instructions.extend(
            _app_page_instructions(spec, root_app_page, loc, target_page)
        )
    return instructions


def _missing_folder_line(fname: str, target: int) -> str:
    return f"  • Locate folder '{fname}' and move to Page {target}"


def _missing_app_line(app: str, where: str | None, target: int) -> str:
    if where:
        return f"  • Move app {app} from {where} to Page {target}"
    return f"  • Install or locate app: {app} (then move to Page {target})"


def _folder_page_instructions(
    spec: dict, folder_page: dict[str, int], target: int
) -> list[str]:
    """Generate folder move instructions for a target page."""
    result: list[str] = []
    for fname in spec.get("folders") or []:
        curp = folder_page.get(fname)
        if curp is None:
            result.append(_missing_folder_line(fname, target))
        elif curp != target:
            result.append(
                f"  • Move folder '{fname}' from Page {curp} to Page {target}"
            )
    return result


def _app_page_instructions(
    spec: dict, root_app_page: dict[str, int], loc: dict[str, str], target: int
) -> list[str]:
    """Generate app move instructions for a target page."""
    result: list[str] = []
    for app in spec.get("apps") or []:
        cur_root = root_app_page.get(app)
        if cur_root is None:
            result.append(_missing_app_line(app, loc.get(app), target))
        elif cur_root != target:
            result.append(f"  • Move app {app} from Page {cur_root} to Page {target}")
    return result


def checklist_from_plan(layout: NormalizedLayout, plan: dict[str, Any]) -> list[str]:
    """Generate a checklist of manual move instructions from a plan."""
    loc = compute_location_map(layout)
    pins = set(plan.get("pins") or [])
    folders: dict[str, list[str]] = plan.get("folders") or {}

    instructions = _generate_folder_instructions(folders, pins, loc)

    pages_spec = plan.get("pages") if isinstance(plan.get("pages"), dict) else None
    if pages_spec:
        folder_page = compute_folder_page_map(layout)
        root_app_page = compute_root_app_page_map(layout)
        instructions.extend(
            _generate_page_instructions(pages_spec, folder_page, root_app_page, loc)
        )

    return instructions
