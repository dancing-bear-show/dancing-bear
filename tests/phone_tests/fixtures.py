"""Phone/iOS layout test fixtures.

Helpers for creating normalized layouts and raw IconState dicts.
"""

from __future__ import annotations

from typing import Any


def make_app_item(bundle_id: str) -> dict:
    """Create a normalized app item for NormalizedLayout.pages."""
    return {"kind": "app", "id": bundle_id}


def make_folder_item(name: str, apps: list[str] | None = None) -> dict:
    """Create a normalized folder item for NormalizedLayout.pages."""
    return {"kind": "folder", "name": name, "apps": apps or []}


def make_iconstate_app(bundle_id: str) -> dict:
    """Create a raw IconState app entry (pre-normalization)."""
    return {"bundleIdentifier": bundle_id}


def make_iconstate_folder(name: str, apps: list[str] | None = None) -> dict:
    """Create a raw IconState folder entry (pre-normalization)."""
    return {
        "displayName": name,
        "iconLists": [[{"bundleIdentifier": bid} for bid in (apps or [])]],
    }


def make_iconstate(
    dock: list[str] | None = None,
    pages: list[list[dict]] | None = None,
) -> dict:
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
    dock: list[str] | None = None,
    pages: list[list[dict]] | None = None,
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
    from phone.layout_normalize import NormalizedLayout

    return NormalizedLayout(dock=dock or [], pages=pages or [])


# -----------------------------------------------------------------------------
# Device test fixtures (for phone/device.py)
# -----------------------------------------------------------------------------


def make_plist_data(
    dock: list[str] | None = None,
    apps: list[str] | None = None,
    folders: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create cfgutil plist format data for testing _parse_plist_format.

    Args:
        dock: List of bundle IDs for buttonBar
        apps: List of bundle IDs for first page apps
        folders: List of {"name": str, "apps": List[str]} for folders
    """
    page_items: list[dict] = []
    for bid in apps or []:
        page_items.append({"bundleIdentifier": bid})
    for folder in folders or []:
        page_items.append(
            {
                "displayName": folder["name"],
                "iconLists": [[{"bundleIdentifier": b} for b in folder.get("apps", [])]],
            }
        )
    return {
        "buttonBar": [{"bundleIdentifier": b} for b in (dock or [])],
        "iconLists": [page_items] if page_items else [],
    }


def make_list_data(
    dock: list[str] | None = None,
    pages: list[list[Any]] | None = None,
) -> list[Any]:
    """Create cfgutil JSON list format data for testing _parse_list_format.

    Args:
        dock: List of bundle IDs for dock (first element)
        pages: List of pages, each containing strings (apps) or lists (folders)
    """
    return [dock or []] + (pages or [])


def make_ini_section(
    p12_path: str | None = None,
    p12_pass: str | None = None,
    key_prefix: str = "supervision_identity",
) -> dict[str, str]:
    """Create a credentials.ini section dict for testing resolve_p12_path."""
    section: dict[str, str] = {}
    if p12_path:
        section[f"{key_prefix}_p12"] = p12_path
    if p12_pass:
        section[f"{key_prefix}_pass"] = p12_pass
    return section


# -----------------------------------------------------------------------------
# YAML structure fixtures (for CLI testing)
# -----------------------------------------------------------------------------


def make_mock_layout_export(
    dock: list[str] | None = None,
    pages: dict[int, list[str]] | None = None,
    folders: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Create a mock layout export YAML structure.

    Args:
        dock: List of bundle IDs for dock
        pages: Dict of page_num -> list of bundle IDs
        folders: Dict of folder_name -> list of bundle IDs

    Returns:
        Dict matching the structure of phone export YAML files
    """
    return {
        "dock": dock or ["com.apple.mobilesafari"],
        "pages": pages or {1: ["com.apple.Music", "com.apple.podcasts"]},
        "folders": folders or {"Utilities": ["com.apple.calculator", "com.apple.compass"]},
    }


def make_mock_plan(
    pins: list[str] | None = None,
    folders: dict[str, list[str]] | None = None,
    pages: dict[int, list[str]] | None = None,
    unassigned: list[str] | None = None,
) -> dict[str, Any]:
    """Create a mock plan YAML structure.

    Args:
        pins: List of bundle IDs to pin to page 1
        folders: Dict of folder_name -> list of bundle IDs
        pages: Dict of page_num -> list of folder names
        unassigned: List of bundle IDs not yet assigned

    Returns:
        Dict matching the structure of phone plan YAML files
    """
    return {
        "pins": pins or ["com.apple.mobilesafari", "com.apple.Music"],
        "folders": folders
        or {
            "Work": ["com.slack.Slack", "com.microsoft.Office.Outlook"],
            "Utilities": ["com.apple.calculator", "com.apple.compass"],
        },
        "pages": pages or {2: ["Work"], 3: ["Utilities"]},
        "unassigned": unassigned or [],
    }


def make_mock_manifest(
    plan: dict[str, Any] | None = None,
    layout_export_path: str | None = None,
    device_label: str | None = None,
    device_udid: str | None = None,
) -> dict[str, Any]:
    """Create a mock manifest YAML structure.

    Args:
        plan: Embedded plan dict (defaults to make_mock_plan())
        layout_export_path: Optional path to layout export YAML
        device_label: Optional device label
        device_udid: Optional device UDID

    Returns:
        Dict matching the structure of phone manifest YAML files
    """
    manifest = {
        "meta": {"name": "ios_layout_manifest", "version": 1},
        "device": {
            "label": device_label or "Test Device",
            "udid": device_udid,
            "creds_profile": "ios_layout_manager",
        },
        "profile": {
            "identifier": "com.example.profile",
            "hs_identifier": "com.example.hslayout",
            "display_name": "Home Screen Layout",
            "organization": "Personal",
        },
        "plan": plan or make_mock_plan(),
    }
    if layout_export_path:
        manifest["layout_export_path"] = layout_export_path
    return manifest


# -----------------------------------------------------------------------------
# Common test fixtures (pre-built items for reuse)
# -----------------------------------------------------------------------------

# Normalized items
SAMPLE_APP = make_app_item("com.example.app")
SAMPLE_FOLDER = make_folder_item("Work", ["com.work.app1", "com.work.app2"])
WIDGET_ITEM: dict[str, Any] = {"kind": "widget", "id": "com.widget"}
UNNAMED_FOLDER: dict[str, Any] = {"kind": "folder", "apps": []}
APP_NO_ID: dict[str, Any] = {"kind": "app"}
