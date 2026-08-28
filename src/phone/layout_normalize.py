"""iOS layout normalization helpers.

Responsible for converting raw IconState dicts into NormalizedLayout,
and exporting normalized layouts back to YAML-friendly dicts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.collections import dedupe

Item = dict[str, Any]


@dataclass
class NormalizedLayout:
    dock: list[str]
    pages: list[list[Item]]  # items: {kind: app|folder, id|name, apps?}


def _extract_bundle_id(item: Any) -> str | None:
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


def _is_folder(item: Any) -> bool:
    """Check whether a raw IconState entry is a folder.

    Takes `Any` rather than `dict`: entries come from an external plist, where a
    page slot may be a bare string, None, or a non-mapping. The isinstance guard
    is load-bearing — annotating this as `dict` makes it read as dead code.
    """
    return isinstance(item, dict) and ("iconLists" in item) and ("displayName" in item)


def _is_app_item(item: Item) -> bool:
    """Check if a normalized item is an app."""
    return item.get("kind") == "app"


def _is_folder_item(item: Item) -> bool:
    """Check if a normalized item is a folder."""
    return item.get("kind") == "folder"


def _get_app_id(item: Item) -> str | None:
    """Get app ID from an app item, or None."""
    return item.get("id") if _is_app_item(item) else None


def _get_folder_apps(item: Item) -> list[str]:
    """Get apps list from a folder item, or empty list."""
    return item.get("apps", []) if _is_folder_item(item) else []


def _get_folder_name(item: Item) -> str:
    """Get folder name from a folder item."""
    return item.get("name", "Folder") if _is_folder_item(item) else ""


def _extract_bundle_ids(items: list[Any]) -> list[str]:
    """Extract bundle IDs from a list of items, filtering out invalid entries."""
    return [bid for it in items if (bid := _extract_bundle_id(it))]


def _flatten_folder_iconlists(folder_dict: dict[str, Any]) -> list[str]:
    """Extract all bundle IDs from a folder's iconLists."""
    apps: list[str] = []
    for page in folder_dict.get("iconLists") or []:
        if isinstance(page, list):
            apps.extend(_extract_bundle_ids(page))
    return apps


def _normalize_page_item(item: Any) -> Item | None:
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


def normalize_iconstate(data: dict[str, Any]) -> NormalizedLayout:
    """Normalize raw IconState data into a NormalizedLayout."""
    dock = _extract_bundle_ids(data.get("buttonBar") or [])
    pages: list[list[Item]] = []
    for page in data.get("iconLists") or []:
        if not isinstance(page, list):
            continue
        items = [it for raw in page if (it := _normalize_page_item(raw))]
        pages.append(items)
    return NormalizedLayout(dock=dock, pages=pages)


def to_yaml_export(layout: NormalizedLayout) -> dict[str, Any]:
    """Export layout to a YAML-friendly dict."""
    export: dict[str, Any] = {
        "#": [
            "Exported iOS Home Screen layout (apps + folders only).",
            "Widgets are omitted. Edit-friendly; not used to reapply directly.",
        ],
        "dock": layout.dock,
        "pages": [],
    }
    for page in layout.pages:
        page_out: dict[str, Any] = {"apps": [], "folders": []}
        for it in page:
            if _is_app_item(it):
                page_out["apps"].append(it["id"])
            elif _is_folder_item(it):
                page_out["folders"].append(
                    {"name": _get_folder_name(it), "apps": _get_folder_apps(it)}
                )
        export["pages"].append(page_out)
    return export


def _add_app_location(loc: dict[str, str], bid: str, location: str) -> None:
    """Add app to location map if not already present."""
    if bid and bid not in loc:
        loc[bid] = location


def compute_location_map(layout: NormalizedLayout) -> dict[str, str]:
    """Map bundle id -> location string (e.g., 'Page 2' or 'Page 3 > Work')."""
    loc: dict[str, str] = {}
    for pi, page in enumerate(layout.pages, start=1):
        page_loc = f"Page {pi}"
        for it in page:
            if _is_app_item(it):
                _add_app_location(loc, _get_app_id(it), page_loc)
            elif _is_folder_item(it):
                folder_loc = f"{page_loc} > {_get_folder_name(it)}"
                for a in _get_folder_apps(it):
                    _add_app_location(loc, a, folder_loc)
    return loc


def _iter_page_app_ids(page: list[Item]):
    """Yield app IDs from a single page (including its folder contents)."""
    for it in page:
        if _is_app_item(it):
            bid = _get_app_id(it)
            if bid:
                yield bid
        elif _is_folder_item(it):
            yield from (a for a in _get_folder_apps(it) if a)


def _iter_all_app_ids(layout: NormalizedLayout):
    """Yield all app IDs from dock and pages (including folder contents)."""
    yield from (a for a in layout.dock if a)
    for page in layout.pages:
        yield from _iter_page_app_ids(page)


def list_all_apps(layout: NormalizedLayout) -> list[str]:
    """Return a de-duplicated list of all bundle IDs in layout (dock + pages)."""
    return dedupe(list(_iter_all_app_ids(layout)))


def _compute_first_page_map(
    layout: NormalizedLayout, key_of: Callable[[Item], str | None]
) -> dict[str, int]:
    """Map a key (derived per-item via key_of) to the first page index it appears on."""
    m: dict[str, int] = {}
    for pi, page in enumerate(layout.pages, start=1):
        for it in page:
            key = key_of(it)
            if key and key not in m:
                m[key] = pi
    return m


def _folder_name_key(item: Item) -> str | None:
    """Return the folder name key for page-map computation, or None for non-folders."""
    return _get_folder_name(item) if _is_folder_item(item) else None


def compute_folder_page_map(layout: NormalizedLayout) -> dict[str, int]:
    """Map folder name to the first page index where it appears."""
    return _compute_first_page_map(layout, _folder_name_key)


def compute_root_app_page_map(layout: NormalizedLayout) -> dict[str, int]:
    """Map root-level app bundle id to page index (apps inside folders are excluded)."""
    return _compute_first_page_map(layout, _get_app_id)
