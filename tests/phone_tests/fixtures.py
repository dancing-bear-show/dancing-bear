"""Phone/iOS layout test fixtures.

Helpers for creating normalized layouts and raw IconState dicts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def make_app_item(bundle_id: str) -> Dict:
    """Create a normalized app item for NormalizedLayout.pages."""
    return {"kind": "app", "id": bundle_id}


def make_folder_item(name: str, apps: Optional[List[str]] = None) -> Dict:
    """Create a normalized folder item for NormalizedLayout.pages."""
    return {"kind": "folder", "name": name, "apps": apps or []}


def make_iconstate_app(bundle_id: str) -> Dict:
    """Create a raw IconState app entry (pre-normalization)."""
    return {"bundleIdentifier": bundle_id}


def make_iconstate_folder(name: str, apps: Optional[List[str]] = None) -> Dict:
    """Create a raw IconState folder entry (pre-normalization)."""
    return {
        "displayName": name,
        "iconLists": [[{"bundleIdentifier": bid} for bid in (apps or [])]],
    }


def make_iconstate(
    dock: Optional[List[str]] = None,
    pages: Optional[List[List[Dict]]] = None,
) -> Dict:
    """Create a raw IconState dict for testing normalize_iconstate.

    Args:
        dock: List of bundle IDs for the dock (buttonBar)
        pages: List of pages, each page is a list of items (use make_iconstate_app/folder)

    Example:
        data = make_iconstate(
            dock=["com.apple.safari"],
            pages=[[make_iconstate_app("com.app1"), make_iconstate_folder("Work", ["com.work1"])]]
        )
    """
    return {
        "buttonBar": [{"bundleIdentifier": bid} for bid in (dock or [])],
        "iconLists": pages or [],
    }


def make_layout(
    dock: Optional[List[str]] = None,
    pages: Optional[List[List[Dict]]] = None,
):
    """Create a NormalizedLayout for testing.

    Args:
        dock: List of bundle IDs for the dock
        pages: List of pages, each page is a list of items (use make_app_item/folder_item)

    Example:
        layout = make_layout(
            dock=["com.apple.safari"],
            pages=[[make_app_item("com.app1"), make_folder_item("Work", ["com.w1"])]]
        )
    """
    from phone.layout import NormalizedLayout
    return NormalizedLayout(dock=dock or [], pages=pages or [])


# -----------------------------------------------------------------------------
# Device test fixtures (for phone/device.py)
# -----------------------------------------------------------------------------


def make_plist_data(
    dock: Optional[List[str]] = None,
    apps: Optional[List[str]] = None,
    folders: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Create cfgutil plist format data for testing _parse_plist_format.

    Args:
        dock: List of bundle IDs for buttonBar
        apps: List of bundle IDs for first page apps
        folders: List of {"name": str, "apps": List[str]} for folders
    """
    page_items: List[Dict] = []
    for bid in (apps or []):
        page_items.append({"bundleIdentifier": bid})
    for folder in (folders or []):
        page_items.append({
            "displayName": folder["name"],
            "iconLists": [[{"bundleIdentifier": b} for b in folder.get("apps", [])]],
        })
    return {
        "buttonBar": [{"bundleIdentifier": b} for b in (dock or [])],
        "iconLists": [page_items] if page_items else [],
    }


def make_list_data(
    dock: Optional[List[str]] = None,
    pages: Optional[List[List[Any]]] = None,
) -> List[Any]:
    """Create cfgutil JSON list format data for testing _parse_list_format.

    Args:
        dock: List of bundle IDs for dock (first element)
        pages: List of pages, each containing strings (apps) or lists (folders)
    """
    return [dock or []] + (pages or [])


def make_ini_section(
    p12_path: Optional[str] = None,
    p12_pass: Optional[str] = None,
    key_prefix: str = "supervision_identity",
) -> Dict[str, str]:
    """Create a credentials.ini section dict for testing resolve_p12_path."""
    section: Dict[str, str] = {}
    if p12_path:
        section[f"{key_prefix}_p12"] = p12_path
    if p12_pass:
        section[f"{key_prefix}_pass"] = p12_pass
    return section


# -----------------------------------------------------------------------------
# Common test fixtures (pre-built items for reuse)
# -----------------------------------------------------------------------------

# Normalized items
SAMPLE_APP = make_app_item("com.example.app")
SAMPLE_FOLDER = make_folder_item("Work", ["com.work.app1", "com.work.app2"])
EMPTY_FOLDER = make_folder_item("Empty", [])
WIDGET_ITEM: Dict[str, Any] = {"kind": "widget", "id": "com.widget"}
UNNAMED_FOLDER: Dict[str, Any] = {"kind": "folder", "apps": []}
APP_NO_ID: Dict[str, Any] = {"kind": "app"}
