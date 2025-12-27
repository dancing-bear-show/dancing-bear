"""Phone/iOS layout test fixtures.

Helpers for creating normalized layouts and raw IconState dicts.
"""

from __future__ import annotations

from typing import Dict, List, Optional


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
