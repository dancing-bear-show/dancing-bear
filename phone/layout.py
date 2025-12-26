from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


Item = Dict[str, Any]


@dataclass
class NormalizedLayout:
    dock: List[str]
    pages: List[List[Item]]  # items: {kind: app|folder, id|name, apps?}


def _flatten_folder_iconlists(folder_dict: Dict[str, Any]) -> List[str]:
    apps: List[str] = []
    icon_lists = folder_dict.get("iconLists") or []
    for page in icon_lists:
        if not isinstance(page, list):
            continue
        for it in page:
            bid = _extract_bundle_id(it)
            if bid:
                apps.append(bid)
    return apps


def _extract_bundle_id(item: Any) -> Optional[str]:
    # Handle dict-style entries first
    if isinstance(item, dict):
        for k in ("bundleIdentifier", "displayIdentifier"):
            v = item.get(k)
            if isinstance(v, str) and v:
                return v
        return None
    # Some IconState variants may encode items as strings (bundle IDs)
    if isinstance(item, str):
        s = item.strip()
        # Heuristic: looks like a bundle id (contains dot, no slashes)
        if "." in s and "/" not in s:
            return s
    return None


def _is_folder(item: Dict[str, Any]) -> bool:
    return isinstance(item, dict) and ("iconLists" in item) and ("displayName" in item)


def normalize_iconstate(data: Dict[str, Any]) -> NormalizedLayout:
    pages_raw = data.get("iconLists") or []
    dock_raw = data.get("buttonBar") or []

    dock: List[str] = []
    for it in dock_raw:
        bid = _extract_bundle_id(it)
        if bid:
            dock.append(bid)

    pages: List[List[Item]] = []
    for page in pages_raw:
        if not isinstance(page, list):
            continue
        n_items: List[Item] = []
        for it in page:
            if _is_folder(it):
                name = it.get("displayName") or "Folder"
                apps = _flatten_folder_iconlists(it)
                n_items.append({"kind": "folder", "name": name, "apps": apps})
            else:
                bid = _extract_bundle_id(it)
                if bid:
                    n_items.append({"kind": "app", "id": bid})
                else:
                    continue
        pages.append(n_items)

    return NormalizedLayout(dock=dock, pages=pages)


def to_yaml_export(layout: NormalizedLayout) -> Dict[str, Any]:
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
                page_out["apps"].append(it["id"])  # type: ignore[index]
            elif it.get("kind") == "folder":
                page_out["folders"].append({"name": it.get("name"), "apps": it.get("apps", [])})
        export["pages"].append(page_out)
    return export


def scaffold_plan(layout: NormalizedLayout) -> Dict[str, Any]:
    pinned = list(dict.fromkeys(layout.dock))
    if layout.pages:
        for it in layout.pages[0]:
            if it.get("kind") == "app":
                bid = it.get("id")
                if bid and bid not in pinned:
                    pinned.append(bid)
                    if len(pinned) >= 12:
                        break
    all_app_ids: List[str] = []
    for page in layout.pages:
        for it in page:
            if it.get("kind") == "app":
                all_app_ids.append(it.get("id"))  # type: ignore[arg-type]
            elif it.get("kind") == "folder":
                all_app_ids.extend(it.get("apps", []))

    unassigned = [a for a in all_app_ids if a not in pinned]

    plan = {
        "#": [
            "Home Screen plan. Fill folders.apps with bundle IDs.",
            "pins: always on page 1 (top), plus dock.",
            "unassigned: all remaining apps from current layout.",
        ],
        "pins": pinned,
        "folders": {
            "Work": [],
            "Finance": [],
            "Travel": [],
            "Health": [],
            "Media": [],
            "Shopping": [],
            "Social": [],
            "Utilities": [],
        },
        "unassigned": unassigned,
    }
    return plan


def checklist_from_plan(layout: NormalizedLayout, plan: Dict[str, Any]) -> List[str]:
    instructions: List[str] = []
    loc = compute_location_map(layout)

    pins = set(plan.get("pins") or [])
    folders: Dict[str, List[str]] = plan.get("folders") or {}

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
            elif at.endswith(f"> {fname}"):
                continue
            else:
                instructions.append(f"  • Move {a} from {at} into folder {fname}")

    # Optional: page organization if plan provides a 'pages' mapping
    pages_spec = plan.get("pages") if isinstance(plan.get("pages"), dict) else None
    if pages_spec:
        # Build helper maps
        folder_page = compute_folder_page_map(layout)
        root_app_page = compute_root_app_page_map(layout)
        instructions.append("")
        instructions.append("Page organization:")
        # Normalize keys to ints, keep order by page number
        def _to_int(k: Any) -> int:
            try:
                return int(k)
            except Exception:
                return 0
        for page_key in sorted(pages_spec.keys(), key=_to_int):
            try:
                target_page = int(page_key)
            except Exception:  # noqa: S112 - skip on error
                continue
            spec = pages_spec.get(page_key) or {}
            # folders
            for fname in (spec.get("folders") or []):
                curp = folder_page.get(fname)
                if curp is None:
                    instructions.append(f"  • Locate folder '{fname}' and move to Page {target_page}")
                elif curp != target_page:
                    instructions.append(f"  • Move folder '{fname}' from Page {curp} to Page {target_page}")
            # apps (only root apps; if in folder, instruct moving out)
            for app in (spec.get("apps") or []):
                cur_root = root_app_page.get(app)
                if cur_root is None:
                    where = loc.get(app)
                    if where:
                        instructions.append(f"  • Move app {app} from {where} to Page {target_page}")
                    else:
                        instructions.append(f"  • Install or locate app: {app} (then move to Page {target_page})")
                elif cur_root != target_page:
                    instructions.append(f"  • Move app {app} from Page {cur_root} to Page {target_page}")
    return instructions


def compute_location_map(layout: NormalizedLayout) -> Dict[str, str]:
    """Map bundle id -> location string (e.g., 'Page 2' or 'Page 3 > Work').

    The first seen location wins when duplicates exist.
    """
    loc: Dict[str, str] = {}
    for pi, page in enumerate(layout.pages, start=1):
        for it in page:
            if it.get("kind") == "app":
                bid = it.get("id")
                if bid and bid not in loc:
                    loc[bid] = f"Page {pi}"
            elif it.get("kind") == "folder":
                fname = it.get("name", "Folder")
                for a in it.get("apps", []):
                    if a and a not in loc:
                        loc[a] = f"Page {pi} > {fname}"
    return loc


def list_all_apps(layout: NormalizedLayout) -> List[str]:
    """Return a de-duplicated list of all bundle IDs in layout (dock + pages)."""
    apps: List[str] = []
    seen: set[str] = set()
    for a in layout.dock:
        if a and a not in seen:
            apps.append(a)
            seen.add(a)
    for page in layout.pages:
        for it in page:
            if it.get("kind") == "app":
                bid = it.get("id")
                if bid and bid not in seen:
                    apps.append(bid)
                    seen.add(bid)
            elif it.get("kind") == "folder":
                for a in it.get("apps", []):
                    if a and a not in seen:
                        apps.append(a)
                        seen.add(a)
    return apps


def rank_unused_candidates(
    layout: NormalizedLayout,
    *,
    recent_ids: Optional[List[str]] = None,
    keep_ids: Optional[List[str]] = None,
) -> List[Tuple[str, float, str]]:
    """Heuristically rank apps by 'likely unused' score.

    Higher score = more likely unused.

    Factors (additive):
    - In dock: -3.0
    - On page 1 (outside folder): -1.5
    - Page index penalty: (page_index - 1) * 0.6
    - Inside folder: +1.0 (plus +0.4 if folder is on page > 1)
    - Marked recent: -2.0 (via --recent list)
    - Mild defaults for Apple bundles (subjective): +0.5 for some stock apps
    - Strong keep list: -99.0 to remove from consideration
    """
    recent = set(recent_ids or [])
    keep = set(keep_ids or [])
    loc = compute_location_map(layout)

    # helper to parse page index and folder presence
    def _parse_loc(s: str) -> Tuple[int, Optional[str]]:
        # Formats: 'Page K' or 'Page K > FolderName'
        if not s.startswith("Page "):
            # Unknown or Dock; do not apply page penalties
            return (0, None)
        try:
            parts = s.split(" ")
            page = int(parts[1])
        except Exception:
            page = 999
        folder = None
        if ">" in s:
            try:
                folder = s.split(" > ", 1)[1]
            except Exception:
                folder = None
        return (page, folder)

    results: List[Tuple[str, float, str]] = []
    for app in list_all_apps(layout):
        score = 0.0
        if app in keep:
            score -= 99.0
        # dock
        if app in (layout.dock or []):
            score -= 3.0
        # location penalties
        where = loc.get(app, "")
        page_idx, folder = _parse_loc(where)
        if folder is None and page_idx == 1:
            score -= 1.5
        if page_idx and page_idx > 1:
            score += (page_idx - 1) * 0.6
        if folder is not None:
            score += 1.0
            if page_idx and page_idx > 1:
                score += 0.4
        # recency
        if app in recent:
            score -= 2.0
        # mild priors for some stock apps
        if app.startswith("com.apple."):
            stock_maybe_unused = {
                "com.apple.tips",
                "com.apple.stocks",
                "com.apple.measure",
                "com.apple.compass",
                "com.apple.podcasts",
                "com.apple.books",
            }
            if app in stock_maybe_unused:
                score += 0.5
        # strong priors for common utilities (reduce false positives)
        common_keep = {
            "com.apple.camera",
            "com.apple.Preferences",
            "com.apple.facetime",
            "com.apple.mobilephone",
            "com.apple.mobilesafari",
            "com.apple.MobileSMS",
            "com.apple.mobilemail",
            "com.apple.Maps",
        }
        if app in common_keep:
            score -= 2.0
        results.append((app, score, where or "(unknown)"))
    # sort: highest score first (more likely unused)
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


def analyze_layout(layout: NormalizedLayout, plan: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return summary metrics and observations about a Home Screen layout.

    Keys:
      dock, dock_count, pages_count, pages (per-page counts),
      folders (name, page, app_count), duplicates, totals, observations
    """
    # Dock
    dock = list(layout.dock or [])
    # Pages breakdown
    pages_info: List[Dict[str, Any]] = []
    folder_details: List[Dict[str, Any]] = []
    total_root_apps = 0
    for idx, page in enumerate(layout.pages, start=1):
        root_apps = 0
        folders = 0
        for it in page:
            if it.get("kind") == "app":
                root_apps += 1
            elif it.get("kind") == "folder":
                folders += 1
                folder_details.append({
                    "name": it.get("name") or "Folder",
                    "page": idx,
                    "app_count": len(it.get("apps", []) or []),
                })
        total_root_apps += root_apps
        pages_info.append({
            "page": idx,
            "root_apps": root_apps,
            "folders": folders,
            "items_total": root_apps + folders,
        })

    # Totals
    unique_apps = list_all_apps(layout)
    total_apps = len(unique_apps)
    total_folders = len(folder_details)

    # Duplicates: count occurrences across dock, root apps, and folder apps
    counts: Dict[str, int] = {}
    for a in (layout.dock or []):
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
    duplicates = sorted([a for a, c in counts.items() if c > 1])

    # Observations / suggestions
    observations: List[str] = []
    # Dock guidance
    if len(dock) < 4:
        observations.append(f"Dock has {len(dock)} apps; consider pinning up to 4 frequently used apps.")
    # Page balance
    if pages_info:
        max_items = max(p["items_total"] for p in pages_info)
        min_items = min(p["items_total"] for p in pages_info)
        if max_items - min_items >= 6 and len(pages_info) > 1:
            observations.append("Pages appear unbalanced; consider moving seldom-used items to later pages or folders.")
        if pages_info[0]["items_total"] >= 24:
            observations.append("Page 1 is crowded (>=24 items); consider reducing root apps or using folders.")
        if pages_info[0]["root_apps"] >= 16:
            observations.append("Many root apps on Page 1; move infrequent ones into folders or later pages.")
    # Folder guidance
    tiny = [f for f in folder_details if f["app_count"] <= 2]
    large = [f for f in folder_details if f["app_count"] >= 10]
    if tiny:
        observations.append(f"{len(tiny)} tiny folder(s) (<=2 apps); consider flattening or merging.")
    if large:
        observations.append(f"{len(large)} large folder(s) (>=10 apps); consider splitting for easier access.")
    # Plan alignment
    if plan:
        pins = list(plan.get("pins") or [])
        if pins:
            missing_pins = [p for p in pins if p not in unique_apps]
            if missing_pins:
                observations.append(f"Plan pins not found in layout: {len(missing_pins)} app(s). Install or adjust pins.")
        pfolders: Dict[str, List[str]] = plan.get("folders") or {}
        empty_planned = [name for name, apps in pfolders.items() if not apps]
        if empty_planned:
            observations.append(f"Planned folders without assigned apps: {', '.join(empty_planned[:5])}{'…' if len(empty_planned)>5 else ''}.")

    # Build result
    result: Dict[str, Any] = {
        "dock": dock,
        "dock_count": len(dock),
        "pages_count": len(layout.pages or []),
        "pages": pages_info,
        "folders": folder_details,
        "totals": {
            "unique_apps": total_apps,
            "root_apps": total_root_apps,
            "folders": total_folders,
        },
        "duplicates": duplicates,
        "observations": observations,
    }
    return result


# ---- Auto-folderization helpers ----


def auto_folderize(layout: NormalizedLayout, *,
                   keep: Optional[List[str]] = None,
                   seed_folders: Optional[Dict[str, List[str]]] = None) -> Dict[str, List[str]]:
    """Return a folder -> apps mapping assigning all apps (except keep) to folders.

    - keep: bundle IDs to exclude from assignment (e.g., Safari/Settings)
    - seed_folders: existing mapping to start from (apps are added idempotently)
    """
    from .classify import classify_app

    keep_set = set(keep or [])
    folders: Dict[str, List[str]] = {k: list(v) for k, v in (seed_folders or {}).items()}

    def add(folder: str, app: str):
        arr = folders.setdefault(folder, [])
        if app not in arr:
            arr.append(app)

    for app in list_all_apps(layout):
        if not app or app in keep_set:
            continue
        folder = classify_app(app)
        add(folder, app)
    return folders


def distribute_folders_across_pages(folder_names: List[str], *, per_page: int = 12,
                                    start_page: int = 2) -> Dict[int, Dict[str, List[str]]]:
    """Return a pages mapping that places folders across pages (no apps), starting from start_page."""
    pages: Dict[int, Dict[str, List[str]]] = {}
    i = 0
    page = start_page
    while i < len(folder_names):
        chunk = folder_names[i:i+per_page]
        pages[page] = { 'apps': [], 'folders': chunk }
        i += per_page
        page += 1
    return pages
