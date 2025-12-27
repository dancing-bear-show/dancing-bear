from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

Item = Dict[str, Any]

# Constants for rank_unused_candidates
_STOCK_MAYBE_UNUSED = frozenset({
    "com.apple.tips",
    "com.apple.stocks",
    "com.apple.measure",
    "com.apple.compass",
    "com.apple.podcasts",
    "com.apple.books",
})

_COMMON_KEEP = frozenset({
    "com.apple.camera",
    "com.apple.Preferences",
    "com.apple.facetime",
    "com.apple.mobilephone",
    "com.apple.mobilesafari",
    "com.apple.MobileSMS",
    "com.apple.mobilemail",
    "com.apple.Maps",
})


@dataclass
class NormalizedLayout:
    dock: List[str]
    pages: List[List[Item]]  # items: {kind: app|folder, id|name, apps?}


def _extract_bundle_id(item: Any) -> Optional[str]:
    """Extract bundle ID from an IconState item.

    Handles dict entries with ``bundleIdentifier`` or ``displayIdentifier`` fields,
    or string bundle IDs (must contain a dot and no slashes).
    """
    if isinstance(item, dict):
        for k in ("bundleIdentifier", "displayIdentifier"):
            v = item.get(k)
            if isinstance(v, str) and v:
                return v
        return None
    if isinstance(item, str):
        s = item.strip()
        if "." in s and "/" not in s:
            return s
    return None


def _is_folder(item: Dict[str, Any]) -> bool:
    return isinstance(item, dict) and ("iconLists" in item) and ("displayName" in item)


def _flatten_folder_iconlists(folder_dict: Dict[str, Any]) -> List[str]:
    """Extract all bundle IDs from a folder's iconLists."""
    apps: List[str] = []
    for page in folder_dict.get("iconLists") or []:
        if not isinstance(page, list):
            continue
        for it in page:
            bid = _extract_bundle_id(it)
            if bid:
                apps.append(bid)
    return apps


def _extract_bundle_ids(items: List[Any]) -> List[str]:
    """Extract bundle IDs from a list of items, filtering out invalid entries."""
    return [bid for it in items if (bid := _extract_bundle_id(it))]


def _normalize_page_item(item: Any) -> Optional[Item]:
    """Convert a raw IconState item to a normalized item dict."""
    if _is_folder(item):
        return {
            "kind": "folder",
            "name": item.get("displayName") or "Folder",
            "apps": _flatten_folder_iconlists(item),
        }
    bid = _extract_bundle_id(item)
    if bid:
        return {"kind": "app", "id": bid}
    return None


def normalize_iconstate(data: Dict[str, Any]) -> NormalizedLayout:
    """Normalize raw IconState data into a NormalizedLayout."""
    dock = _extract_bundle_ids(data.get("buttonBar") or [])
    pages: List[List[Item]] = []
    for page in data.get("iconLists") or []:
        if not isinstance(page, list):
            continue
        items = [it for raw in page if (it := _normalize_page_item(raw))]
        pages.append(items)
    return NormalizedLayout(dock=dock, pages=pages)


def to_yaml_export(layout: NormalizedLayout) -> Dict[str, Any]:
    """Export layout to a YAML-friendly dict."""
    export: Dict[str, Any] = {
        "#": [
            "Exported iOS Home Screen layout (apps + folders only).",
            "Widgets are omitted. Edit-friendly; not used to reapply directly.",
        ],
        "dock": layout.dock,
        "pages": [],
    }
    for page in layout.pages:
        page_out: Dict[str, Any] = {"apps": [], "folders": []}
        for it in page:
            if it.get("kind") == "app":
                page_out["apps"].append(it["id"])
            elif it.get("kind") == "folder":
                page_out["folders"].append({"name": it.get("name"), "apps": it.get("apps", [])})
        export["pages"].append(page_out)
    return export


def _collect_pinned_apps(layout: NormalizedLayout, max_pins: int = 12) -> List[str]:
    """Collect pinned apps from dock and page 1."""
    pinned = list(dict.fromkeys(layout.dock))
    if not layout.pages:
        return pinned
    for it in layout.pages[0]:
        if it.get("kind") == "app":
            bid = it.get("id")
            if bid and bid not in pinned:
                pinned.append(bid)
                if len(pinned) >= max_pins:
                    break
    return pinned


def _collect_all_app_ids(layout: NormalizedLayout) -> List[str]:
    """Collect all app IDs from pages (not deduplicated)."""
    all_ids: List[str] = []
    for page in layout.pages:
        for it in page:
            if it.get("kind") == "app":
                all_ids.append(it.get("id"))
            elif it.get("kind") == "folder":
                all_ids.extend(it.get("apps", []))
    return all_ids


def scaffold_plan(layout: NormalizedLayout) -> Dict[str, Any]:
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
        "folders": {
            "Work": [], "Finance": [], "Travel": [], "Health": [],
            "Media": [], "Shopping": [], "Social": [], "Utilities": [],
        },
        "unassigned": unassigned,
    }


def _generate_folder_instructions(
    folders: Dict[str, List[str]], pins: set, loc: Dict[str, str]
) -> List[str]:
    """Generate instructions for moving apps into folders."""
    instructions: List[str] = []
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


def _safe_int(value: Any, default: int = 0) -> int:
    """Safely convert a value to int, returning default if conversion fails."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _generate_page_instructions(
    pages_spec: Dict[str, Any],
    folder_page: Dict[str, int],
    root_app_page: Dict[str, int],
    loc: Dict[str, str],
) -> List[str]:
    """Generate instructions for page organization."""
    instructions: List[str] = ["", "Page organization:"]
    for page_key in sorted(pages_spec.keys(), key=_safe_int):
        target_page = _safe_int(page_key)
        if target_page == 0:
            continue
        spec = pages_spec.get(page_key) or {}
        instructions.extend(_folder_page_instructions(spec, folder_page, target_page))
        instructions.extend(_app_page_instructions(spec, root_app_page, loc, target_page))
    return instructions


def _folder_page_instructions(spec: Dict, folder_page: Dict[str, int], target: int) -> List[str]:
    """Generate folder move instructions for a target page."""
    result: List[str] = []
    for fname in spec.get("folders") or []:
        curp = folder_page.get(fname)
        if curp is None:
            result.append(f"  • Locate folder '{fname}' and move to Page {target}")
        elif curp != target:
            result.append(f"  • Move folder '{fname}' from Page {curp} to Page {target}")
    return result


def _app_page_instructions(
    spec: Dict, root_app_page: Dict[str, int], loc: Dict[str, str], target: int
) -> List[str]:
    """Generate app move instructions for a target page."""
    result: List[str] = []
    for app in spec.get("apps") or []:
        cur_root = root_app_page.get(app)
        if cur_root is None:
            where = loc.get(app)
            if where:
                result.append(f"  • Move app {app} from {where} to Page {target}")
            else:
                result.append(f"  • Install or locate app: {app} (then move to Page {target})")
        elif cur_root != target:
            result.append(f"  • Move app {app} from Page {cur_root} to Page {target}")
    return result


def checklist_from_plan(layout: NormalizedLayout, plan: Dict[str, Any]) -> List[str]:
    """Generate a checklist of manual move instructions from a plan."""
    loc = compute_location_map(layout)
    pins = set(plan.get("pins") or [])
    folders: Dict[str, List[str]] = plan.get("folders") or {}

    instructions = _generate_folder_instructions(folders, pins, loc)

    pages_spec = plan.get("pages") if isinstance(plan.get("pages"), dict) else None
    if pages_spec:
        folder_page = compute_folder_page_map(layout)
        root_app_page = compute_root_app_page_map(layout)
        instructions.extend(_generate_page_instructions(pages_spec, folder_page, root_app_page, loc))

    return instructions


def _add_app_location(loc: Dict[str, str], bid: str, location: str) -> None:
    """Add app to location map if not already present."""
    if bid and bid not in loc:
        loc[bid] = location


def compute_location_map(layout: NormalizedLayout) -> Dict[str, str]:
    """Map bundle id -> location string (e.g., 'Page 2' or 'Page 3 > Work')."""
    loc: Dict[str, str] = {}
    for pi, page in enumerate(layout.pages, start=1):
        page_loc = f"Page {pi}"
        for it in page:
            if it.get("kind") == "app":
                _add_app_location(loc, it.get("id"), page_loc)
            elif it.get("kind") == "folder":
                fname = it.get("name", "Folder")
                folder_loc = f"{page_loc} > {fname}"
                for a in it.get("apps", []):
                    _add_app_location(loc, a, folder_loc)
    return loc


def _add_unique(apps: List[str], seen: set, bid: str) -> None:
    """Add bundle ID to list if not already seen."""
    if bid and bid not in seen:
        apps.append(bid)
        seen.add(bid)


def list_all_apps(layout: NormalizedLayout) -> List[str]:
    """Return a de-duplicated list of all bundle IDs in layout (dock + pages)."""
    apps: List[str] = []
    seen: set = set()
    for a in layout.dock:
        _add_unique(apps, seen, a)
    for page in layout.pages:
        for it in page:
            if it.get("kind") == "app":
                _add_unique(apps, seen, it.get("id"))
            elif it.get("kind") == "folder":
                for a in it.get("apps", []):
                    _add_unique(apps, seen, a)
    return apps


def _parse_location(loc_str: str) -> Tuple[int, Optional[str]]:
    """Parse a location string into (page_index, folder_name).

    Expected formats:
      - "Page N"
      - "Page N > Folder Name"

    Returns:
      - (page_index, folder_name) where folder_name may be None.
      - (0, None) if the string does not start with "Page ".
      - (999, folder_name) if the page number cannot be parsed.
    """
    if not loc_str.startswith("Page "):
        return (0, None)
    parts = loc_str.split(" ")
    page = _safe_int(parts[1], 999) if len(parts) > 1 else 999
    folder = loc_str.split(" > ", 1)[1] if " > " in loc_str else None
    return (page, folder)


def _compute_app_score(
    app: str, layout: NormalizedLayout, loc: Dict[str, str],
    recent: set, keep: set
) -> float:
    """Compute unused likelihood score for an app."""
    score = 0.0
    if app in keep:
        score -= 99.0
    if app in (layout.dock or []):
        score -= 3.0

    where = loc.get(app, "")
    page_idx, folder = _parse_location(where)

    if folder is None and page_idx == 1:
        score -= 1.5
    if page_idx > 1:
        score += (page_idx - 1) * 0.6
    if folder is not None:
        score += 1.0
        if page_idx > 1:
            score += 0.4

    if app in recent:
        score -= 2.0
    if app in _STOCK_MAYBE_UNUSED:
        score += 0.5
    if app in _COMMON_KEEP:
        score -= 2.0

    return score


def rank_unused_candidates(
    layout: NormalizedLayout,
    *,
    recent_ids: Optional[List[str]] = None,
    keep_ids: Optional[List[str]] = None,
) -> List[Tuple[str, float, str]]:
    """Heuristically rank apps by 'likely unused' score (higher = more likely unused)."""
    recent = set(recent_ids or [])
    keep = set(keep_ids or [])
    loc = compute_location_map(layout)

    results = [
        (app, _compute_app_score(app, layout, loc, recent, keep), loc.get(app, "(unknown)"))
        for app in list_all_apps(layout)
    ]
    results.sort(key=lambda t: t[1], reverse=True)
    return results


def compute_folder_page_map(layout: NormalizedLayout) -> Dict[str, int]:
    """Map folder name to the first page index where it appears."""
    m: Dict[str, int] = {}
    for pi, page in enumerate(layout.pages, start=1):
        for it in page:
            if it.get("kind") == "folder":
                name = it.get("name") or "Folder"
                if name not in m:
                    m[name] = pi
    return m


def compute_root_app_page_map(layout: NormalizedLayout) -> Dict[str, int]:
    """Map root-level app bundle id to page index (apps inside folders are excluded)."""
    m: Dict[str, int] = {}
    for pi, page in enumerate(layout.pages, start=1):
        for it in page:
            if it.get("kind") == "app":
                bid = it.get("id")
                if bid and bid not in m:
                    m[bid] = pi
    return m


def _analyze_pages(layout: NormalizedLayout) -> Tuple[List[Dict], List[Dict], int]:
    """Analyze pages and return (pages_info, folder_details, total_root_apps)."""
    pages_info: List[Dict[str, Any]] = []
    folder_details: List[Dict[str, Any]] = []
    total_root_apps = 0

    for idx, page in enumerate(layout.pages, start=1):
        root_apps = sum(1 for it in page if it.get("kind") == "app")
        folders = sum(1 for it in page if it.get("kind") == "folder")
        total_root_apps += root_apps

        for it in page:
            if it.get("kind") == "folder":
                folder_details.append({
                    "name": it.get("name") or "Folder",
                    "page": idx,
                    "app_count": len(it.get("apps", []) or []),
                })

        pages_info.append({
            "page": idx, "root_apps": root_apps,
            "folders": folders, "items_total": root_apps + folders,
        })

    return pages_info, folder_details, total_root_apps


def _count_app_occurrences(layout: NormalizedLayout) -> Dict[str, int]:
    """Count occurrences of each app across dock, root apps, and folder apps."""
    counts: Dict[str, int] = {}
    for a in layout.dock or []:
        counts[a] = counts.get(a, 0) + 1
    for page in layout.pages:
        for it in page:
            if it.get("kind") == "app":
                a = it.get("id")
                if a:
                    counts[a] = counts.get(a, 0) + 1
            elif it.get("kind") == "folder":
                for a in it.get("apps", []) or []:
                    counts[a] = counts.get(a, 0) + 1
    return counts


def _generate_observations(
    dock: List[str], pages_info: List[Dict], folder_details: List[Dict],
    unique_apps: List[str], plan: Optional[Dict[str, Any]]
) -> List[str]:
    """Generate observations and suggestions about the layout."""
    observations: List[str] = []

    if len(dock) < 4:
        observations.append(f"Dock has {len(dock)} apps; consider pinning up to 4 frequently used apps.")

    if pages_info:
        _add_page_observations(pages_info, observations)

    _add_folder_observations(folder_details, observations)

    if plan:
        _add_plan_observations(plan, unique_apps, observations)

    return observations


def _add_page_observations(pages_info: List[Dict], observations: List[str]) -> None:
    """Add page-related observations."""
    max_items = max(p["items_total"] for p in pages_info)
    min_items = min(p["items_total"] for p in pages_info)

    if max_items - min_items >= 6 and len(pages_info) > 1:
        observations.append("Pages appear unbalanced; consider moving seldom-used items to later pages or folders.")
    if pages_info[0]["items_total"] >= 24:
        observations.append("Page 1 is crowded (>=24 items); consider reducing root apps or using folders.")
    if pages_info[0]["root_apps"] >= 16:
        observations.append("Many root apps on Page 1; move infrequent ones into folders or later pages.")


def _add_folder_observations(folder_details: List[Dict], observations: List[str]) -> None:
    """Add folder-related observations."""
    tiny = [f for f in folder_details if f["app_count"] <= 2]
    large = [f for f in folder_details if f["app_count"] >= 10]
    if tiny:
        observations.append(f"{len(tiny)} tiny folder(s) (<=2 apps); consider flattening or merging.")
    if large:
        observations.append(f"{len(large)} large folder(s) (>=10 apps); consider splitting for easier access.")


def _add_plan_observations(plan: Dict[str, Any], unique_apps: List[str], observations: List[str]) -> None:
    """Add plan alignment observations."""
    pins = list(plan.get("pins") or [])
    if pins:
        missing_pins = [p for p in pins if p not in unique_apps]
        if missing_pins:
            observations.append(f"Plan pins not found in layout: {len(missing_pins)} app(s). Install or adjust pins.")

    pfolders: Dict[str, List[str]] = plan.get("folders") or {}
    empty_planned = [name for name, apps in pfolders.items() if not apps]
    if empty_planned:
        suffix = "…" if len(empty_planned) > 5 else ""
        observations.append(f"Planned folders without assigned apps: {', '.join(empty_planned[:5])}{suffix}.")


def analyze_layout(layout: NormalizedLayout, plan: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return summary metrics and observations about a Home Screen layout."""
    dock = list(layout.dock or [])
    pages_info, folder_details, total_root_apps = _analyze_pages(layout)
    unique_apps = list_all_apps(layout)
    counts = _count_app_occurrences(layout)
    duplicates = sorted([a for a, c in counts.items() if c > 1])
    observations = _generate_observations(dock, pages_info, folder_details, unique_apps, plan)

    return {
        "dock": dock,
        "dock_count": len(dock),
        "pages_count": len(layout.pages or []),
        "pages": pages_info,
        "folders": folder_details,
        "totals": {
            "unique_apps": len(unique_apps),
            "root_apps": total_root_apps,
            "folders": len(folder_details),
        },
        "duplicates": duplicates,
        "observations": observations,
    }


# ---- Auto-folderization helpers ----


def auto_folderize(
    layout: NormalizedLayout, *,
    keep: Optional[List[str]] = None,
    seed_folders: Optional[Dict[str, List[str]]] = None
) -> Dict[str, List[str]]:
    """Return a folder -> apps mapping assigning all apps (except keep) to folders.

    Args:
        layout: Normalized layout to analyze.
        keep: Bundle IDs to exclude from assignment.
        seed_folders: Existing mapping to start from.

    Returns:
        A mapping from folder name to the list of bundle IDs assigned to that folder.
    """
    from .classify import classify_app

    keep_set = set(keep or [])
    folders: Dict[str, List[str]] = {k: list(v) for k, v in (seed_folders or {}).items()}

    for app in list_all_apps(layout):
        if not app or app in keep_set:
            continue
        folder = classify_app(app)
        arr = folders.setdefault(folder, [])
        if app not in arr:
            arr.append(app)

    return folders


def distribute_folders_across_pages(
    folder_names: List[str], *, per_page: int = 12, start_page: int = 2
) -> Dict[int, Dict[str, List[str]]]:
    """Return a pages mapping that places folders across pages, starting from start_page."""
    pages: Dict[int, Dict[str, List[str]]] = {}
    for i in range(0, len(folder_names), per_page):
        chunk = folder_names[i:i + per_page]
        pages[start_page + i // per_page] = {"apps": [], "folders": chunk}
    return pages
