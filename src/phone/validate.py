"""Validation helpers for iOS icon layout JSON.

The canonical layout format is a list::

    [
        ["dock_app_1", ...],          # index 0: Dock (list of bundle IDs, max 4)
        ["page1_app", ...],           # index 1+: page — list of strings or folders
        [                             # a page can also be a list of folders
            ["FolderName", [apps...], [apps...], ...],
            ...
        ],
    ]

A folder element is ``["Name", [page1_apps], [page2_apps], ...]``.
The *wrong* flat format (strings after the name) raises an error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_BUNDLE_ID_RE = re.compile(r"^[A-Za-z0-9][\w.\-]*\.[A-Za-z0-9][\w.\-]*$")
_MAX_DOCK_ITEMS = 4
_MAX_FOLDER_PAGE_APPS = 9


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation finding from ``validate_layout_json``."""

    level: str  # 'error' or 'warning'
    message: str


@dataclass
class _FolderValidationCtx:
    """Shared context threaded through folder validation helpers."""

    dock_set: set[str]
    all_bundle_ids: list[str]
    issues: list[ValidationIssue]


def _is_bundle_id(value: str) -> bool:
    return bool(_BUNDLE_ID_RE.match(value))


def _validate_dock(dock: object, issues: list[ValidationIssue]) -> set[str]:
    """Validate dock structure; return set of dock bundle IDs."""
    if not isinstance(dock, list):
        issues.append(ValidationIssue("error", "dock (item 0) must be a list"))
        return set()

    for item in dock:
        if not isinstance(item, str):
            issues.append(
                ValidationIssue(
                    "error", f"dock item must be a string, got: {type(item).__name__}"
                )
            )

    if len(dock) > _MAX_DOCK_ITEMS:
        issues.append(
            ValidationIssue(
                "error", f"dock has {len(dock)} items; max is {_MAX_DOCK_ITEMS}"
            )
        )

    return set(item for item in dock if isinstance(item, str))


def _validate_bundle_id(
    app: str,
    context: str,
    ctx: _FolderValidationCtx,
) -> None:
    """Check a single bundle ID and record it in ctx.all_bundle_ids."""
    ctx.all_bundle_ids.append(app)
    if not _is_bundle_id(app):
        ctx.issues.append(
            ValidationIssue(
                "warning", f"'{app}' does not look like a bundle ID (no dot)"
            )
        )
    if app in ctx.dock_set:
        ctx.issues.append(
            ValidationIssue("error", f"'{app}' appears in both dock and {context}")
        )


def _validate_folder_page(
    folder_name: str,
    page_index: int,
    page: list,
    ctx: _FolderValidationCtx,
) -> None:
    """Validate a single folder page (list of bundle IDs)."""
    if len(page) > _MAX_FOLDER_PAGE_APPS:
        ctx.issues.append(
            ValidationIssue(
                "warning",
                f"folder '{folder_name}' page {page_index} has {len(page)} apps; "
                f"recommended max is {_MAX_FOLDER_PAGE_APPS}",
            )
        )
    if len(page) == 0:
        ctx.issues.append(
            ValidationIssue(
                "warning", f"folder '{folder_name}' page {page_index} is empty"
            )
        )

    for app in page:
        if isinstance(app, str):
            _validate_bundle_id(app, f"folder '{folder_name}'", ctx)


def _validate_folder(
    folder: object,
    ctx: _FolderValidationCtx,
) -> None:
    """Validate a folder element: [\"Name\", [page_apps], ...]."""
    if not isinstance(folder, list) or len(folder) < 1:
        ctx.issues.append(ValidationIssue("error", "folder must be a non-empty list"))
        return

    if not isinstance(folder[0], str):
        ctx.issues.append(
            ValidationIssue(
                "error",
                f"folder first element must be a string name, got: {type(folder[0]).__name__}",
            )
        )
        return

    folder_name: str = folder[0]

    for i, item in enumerate(folder[1:], start=1):
        if isinstance(item, str):
            ctx.issues.append(
                ValidationIssue(
                    "error",
                    f"folder '{folder_name}' item {i} is a string ('{item}'); "
                    "folder pages must be lists of bundle IDs, not flat strings",
                )
            )
        elif isinstance(item, list):
            _validate_folder_page(folder_name, i, item, ctx)
        else:
            ctx.issues.append(
                ValidationIssue(
                    "warning",
                    f"folder '{folder_name}' item {i} is unexpected type: {type(item).__name__}",
                )
            )


def _validate_page_item(
    item: object,
    page_idx: int,
    ctx: _FolderValidationCtx,
) -> None:
    """Validate a single item within a page (string app or folder list)."""
    if isinstance(item, str):
        _validate_bundle_id(item, f"page {page_idx}", ctx)
    elif isinstance(item, list):
        _validate_folder(item, ctx)
    else:
        ctx.issues.append(
            ValidationIssue(
                "warning",
                f"page {page_idx} contains unexpected item type: {type(item).__name__}",
            )
        )


def _validate_page(
    page: object,
    page_idx: int,
    ctx: _FolderValidationCtx,
) -> None:
    """Validate a single page entry (string or list)."""
    if isinstance(page, str):
        _validate_bundle_id(page, f"page {page_idx}", ctx)
    elif isinstance(page, list):
        for item in page:
            _validate_page_item(item, page_idx, ctx)
    else:
        ctx.issues.append(
            ValidationIssue(
                "error",
                f"page {page_idx} must be a string or list, got: {type(page).__name__}",
            )
        )


def _check_duplicates(all_bundle_ids: list[str], issues: list[ValidationIssue]) -> None:
    seen: set[str] = set()
    for bid in all_bundle_ids:
        if bid in seen:
            issues.append(ValidationIssue("warning", f"duplicate bundle ID: '{bid}'"))
        seen.add(bid)


def _check_unplaced(
    all_bundle_ids: list[str],
    device_apps: list[str],
    issues: list[ValidationIssue],
) -> None:
    placed = set(all_bundle_ids)
    for app in device_apps:
        if app not in placed:
            issues.append(
                ValidationIssue("warning", f"device app not placed in layout: '{app}'")
            )


def validate_layout_json(
    layout: object,
    device_apps: list[str] | None = None,
) -> list[ValidationIssue]:
    """Validate an iOS icon layout JSON structure.

    Args:
        layout: Parsed JSON value (should be a list).
        device_apps: Optional list of bundle IDs present on the device.
            Apps not placed anywhere in layout produce a warning.

    Returns:
        List of :class:`ValidationIssue` instances (empty means valid).
    """
    issues: list[ValidationIssue] = []

    if not isinstance(layout, list) or len(layout) < 2:
        issues.append(
            ValidationIssue(
                "error",
                "layout must be a list with at least 2 items (dock + ≥1 page)",
            )
        )
        return issues

    dock = layout[0]
    pages = layout[1:]

    dock_set = _validate_dock(dock, issues)
    all_bundle_ids: list[str] = list(dock_set)
    ctx = _FolderValidationCtx(dock_set=dock_set, all_bundle_ids=all_bundle_ids, issues=issues)

    for page_idx, page in enumerate(pages, start=1):
        _validate_page(page, page_idx, ctx)

    _check_duplicates(all_bundle_ids, issues)

    if device_apps is not None:
        _check_unplaced(all_bundle_ids, device_apps, issues)

    return issues
