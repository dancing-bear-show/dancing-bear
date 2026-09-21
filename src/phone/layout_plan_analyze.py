"""iOS layout analysis and scoring."""

from __future__ import annotations

from typing import Any

from .constants import COMMON_KEEP, STOCK_MAYBE_UNUSED
from .layout_normalize import (
    NormalizedLayout,
    _get_folder_apps,
    _get_folder_name,
    _is_app_item,
    _is_folder_item,
    compute_location_map,
    list_all_apps,
)
from .layout_plan_scaffold import _safe_int


def _parse_location(loc_str: str) -> tuple[int, str | None]:
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


def _score_location(page_idx: int, folder: str | None) -> float:
    """Score based on app location (page number and folder placement)."""
    score = 0.0
    if folder is None and page_idx == 1:
        score -= 1.5  # Root app on page 1 = likely used
    if page_idx > 1:
        score += (page_idx - 1) * 0.6  # Higher pages = less used
    if folder is not None:
        score += 1.0  # In folder = somewhat hidden
        if page_idx > 1:
            score += 0.4  # Folder on later page = even more hidden
    return score


def _score_membership(app: str, dock: list[str], recent: set, keep: set) -> float:
    """Score based on membership in dock, recent, and keep sets."""
    score = 0.0
    if app in keep:
        score -= 99.0  # Explicitly kept
    if app in dock:
        score -= 3.0  # Dock = frequently used
    if app in recent:
        score -= 2.0  # Recently used
    if app in COMMON_KEEP:
        score -= 2.0  # Common essential app
    if app in STOCK_MAYBE_UNUSED:
        score += 0.5  # Stock app often unused
    return score


def _compute_app_score(
    app: str, layout: NormalizedLayout, loc: dict[str, str], recent: set, keep: set
) -> float:
    """Compute unused likelihood score for an app."""
    where = loc.get(app, "")
    page_idx, folder = _parse_location(where)
    return _score_membership(app, layout.dock or [], recent, keep) + _score_location(
        page_idx, folder
    )


def rank_unused_candidates(
    layout: NormalizedLayout,
    *,
    recent_ids: list[str] | None = None,
    keep_ids: list[str] | None = None,
) -> list[tuple[str, float, str]]:
    """Heuristically rank apps by 'likely unused' score (higher = more likely unused)."""
    recent = set(recent_ids or [])
    keep = set(keep_ids or [])
    loc = compute_location_map(layout)

    results = [
        (
            app,
            _compute_app_score(app, layout, loc, recent, keep),
            loc.get(app, "(unknown)"),
        )
        for app in list_all_apps(layout)
    ]
    results.sort(key=lambda t: t[1], reverse=True)
    return results


def _analyze_pages(layout: NormalizedLayout) -> tuple[list[dict], list[dict], int]:
    """Analyze pages and return (pages_info, folder_details, total_root_apps)."""
    pages_info: list[dict[str, Any]] = []
    folder_details: list[dict[str, Any]] = []
    total_root_apps = 0

    for idx, page in enumerate(layout.pages, start=1):
        root_apps = sum(1 for it in page if _is_app_item(it))
        folders = sum(1 for it in page if _is_folder_item(it))
        total_root_apps += root_apps

        for it in page:
            if _is_folder_item(it):
                folder_details.append(
                    {
                        "name": _get_folder_name(it),
                        "page": idx,
                        "app_count": len(_get_folder_apps(it)),
                    }
                )

        pages_info.append(
            {
                "page": idx,
                "root_apps": root_apps,
                "folders": folders,
                "items_total": root_apps + folders,
            }
        )

    return pages_info, folder_details, total_root_apps


def _count_app_occurrences(layout: NormalizedLayout) -> dict[str, int]:
    """Count occurrences of each app across dock, root apps, and folder apps."""
    from .layout_normalize import _iter_all_app_ids

    counts: dict[str, int] = {}
    for app in _iter_all_app_ids(layout):
        counts[app] = counts.get(app, 0) + 1
    return counts


def _generate_observations(
    dock: list[str],
    pages_info: list[dict],
    folder_details: list[dict],
    unique_apps: list[str],
    plan: dict[str, Any] | None,
) -> list[str]:
    """Generate observations and suggestions about the layout."""
    observations: list[str] = []

    if len(dock) < 4:
        observations.append(
            f"Dock has {len(dock)} apps; consider pinning up to 4 frequently used apps."
        )

    if pages_info:
        _add_page_observations(pages_info, observations)

    _add_folder_observations(folder_details, observations)

    if plan:
        _add_plan_observations(plan, unique_apps, observations)

    return observations


def _add_page_observations(pages_info: list[dict], observations: list[str]) -> None:
    """Add page-related observations."""
    max_items = max(p["items_total"] for p in pages_info)
    min_items = min(p["items_total"] for p in pages_info)

    if max_items - min_items >= 6 and len(pages_info) > 1:
        observations.append(
            "Pages appear unbalanced; consider moving seldom-used items to later pages or folders."
        )
    if pages_info[0]["items_total"] >= 24:
        observations.append(
            "Page 1 is crowded (>=24 items); consider reducing root apps or using folders."
        )
    if pages_info[0]["root_apps"] >= 16:
        observations.append(
            "Many root apps on Page 1; move infrequent ones into folders or later pages."
        )


def _add_folder_observations(
    folder_details: list[dict], observations: list[str]
) -> None:
    """Add folder-related observations."""
    tiny = [f for f in folder_details if f["app_count"] <= 2]
    large = [f for f in folder_details if f["app_count"] >= 10]
    if tiny:
        observations.append(
            f"{len(tiny)} tiny folder(s) (<=2 apps); consider flattening or merging."
        )
    if large:
        observations.append(
            f"{len(large)} large folder(s) (>=10 apps); consider splitting for easier access."
        )


def _add_plan_observations(
    plan: dict[str, Any], unique_apps: list[str], observations: list[str]
) -> None:
    """Add plan alignment observations."""
    pins = list(plan.get("pins") or [])
    if pins:
        missing_pins = [p for p in pins if p not in unique_apps]
        if missing_pins:
            observations.append(
                f"Plan pins not found in layout: {len(missing_pins)} app(s). Install or adjust pins."
            )

    pfolders: dict[str, list[str]] = plan.get("folders") or {}
    empty_planned = [name for name, apps in pfolders.items() if not apps]
    if empty_planned:
        suffix = "…" if len(empty_planned) > 5 else ""
        observations.append(
            f"Planned folders without assigned apps: {', '.join(empty_planned[:5])}{suffix}."
        )


def analyze_layout(
    layout: NormalizedLayout, plan: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return summary metrics and observations about a Home Screen layout."""
    dock = list(layout.dock or [])
    pages_info, folder_details, total_root_apps = _analyze_pages(layout)
    unique_apps = list_all_apps(layout)
    counts = _count_app_occurrences(layout)
    duplicates = sorted([a for a, c in counts.items() if c > 1])
    observations = _generate_observations(
        dock, pages_info, folder_details, unique_apps, plan
    )

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
    layout: NormalizedLayout,
    *,
    keep: list[str] | None = None,
    seed_folders: dict[str, list[str] | None] | None = None,
) -> dict[str, list[str]]:
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
    folders: dict[str, list[str]] = {
        k: list(v or []) for k, v in (seed_folders or {}).items()
    }

    for app in list_all_apps(layout):
        if not app or app in keep_set:
            continue
        folder = classify_app(app)
        arr = folders.setdefault(folder, [])
        if app not in arr:
            arr.append(app)

    return folders


def distribute_folders_across_pages(
    folder_names: list[str], *, per_page: int = 12, start_page: int = 2
) -> dict[int, dict[str, list[str]]]:
    """Return a pages mapping that places folders across pages, starting from start_page."""
    pages: dict[int, dict[str, list[str]]] = {}
    for i in range(0, len(folder_names), per_page):
        chunk = folder_names[i : i + per_page]
        pages[start_page + i // per_page] = {"apps": [], "folders": chunk}
    return pages
