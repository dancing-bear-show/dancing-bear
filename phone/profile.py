from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from .classify import classify_app


def _app_item(bundle_id: str) -> Dict[str, Any]:
    return AppItem(bundle_id).as_spec()


@dataclass
class AppItem:
    """Represents a single application on the Home Screen."""

    bundle_id: str

    def as_spec(self) -> Dict[str, Any]:
        return {"Type": "Application", "BundleID": self.bundle_id}


@dataclass
class FolderItem:
    """Represents a folder with one or more pages of apps."""

    name: str
    apps: List[AppItem] = field(default_factory=list)
    page_size: int = 30

    def as_spec(self) -> Dict[str, Any]:
        pages: List[List[Dict[str, Any]]] = []
        if self.page_size <= 0:
            pages = [[a.as_spec() for a in self.apps]]
        else:
            for i in range(0, len(self.apps), self.page_size):
                pages.append([a.as_spec() for a in self.apps[i : i + self.page_size]])
        if not pages:
            pages = [[]]
        return {
            "Type": "Folder",
            "DisplayName": self.name or "Folder",
            "Pages": pages,
        }


def _folder_item(name: str, apps: List[str], *, page_size: int = 30) -> Dict[str, Any]:
    """Build a folder item with one or more pages.

    - iOS supports multi-page folders; chunk apps accordingly.
    - Default page_size 30 fits common iPad grids (adjust if needed).
    """
    items = [_app_item(a) for a in apps if a]
    pages: List[List[Dict[str, Any]]] = []
    if page_size <= 0:
        pages = [items]
    else:
        for i in range(0, len(items), page_size):
            pages.append(items[i : i + page_size])
    if not pages:
        pages = [[]]
    return {
        "Type": "Folder",
        "DisplayName": name or "Folder",
        "Pages": pages,
    }


def _collect_apps(items: List[Any], seen: Set[str], apps: List[str]) -> None:
    """Collect apps from items list, updating seen set and apps list."""
    for a in items:
        if isinstance(a, str) and a and a not in seen:
            apps.append(a)
            seen.add(a)


def _collect_page_apps(page: Dict[str, Any], seen: Set[str], apps: List[str]) -> None:
    """Collect apps from a single page, including folders."""
    _collect_apps(page.get("apps") or [], seen, apps)
    for folder in page.get("folders") or []:
        _collect_apps(folder.get("apps") or [], seen, apps)


def _list_apps_from_export(layout_export: Dict[str, Any]) -> List[str]:
    """Return a de-duped list of bundle IDs from a layout export dict."""
    seen: Set[str] = set()
    apps: List[str] = []

    # Collect dock apps
    _collect_apps(layout_export.get("dock") or [], seen, apps)

    # Collect apps from all pages
    for page in layout_export.get("pages") or []:
        _collect_page_apps(page, seen, apps)

    return apps


@dataclass
class Page:
    """Page representation that can emit spec items."""

    apps: List[AppItem] = field(default_factory=list)
    folders: List[FolderItem] = field(default_factory=list)

    def as_items(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        items.extend([a.as_spec() for a in self.apps])
        items.extend([f.as_spec() for f in self.folders])
        return items


class HomeScreenConfigBuilder:
    """Object-oriented builder for Home Screen layout payloads."""

    def __init__(self, layout_export: Optional[Dict[str, Any]] = None) -> None:
        self.layout_export = layout_export or {"dock": [], "pages": []}
        self.dock: List[str] = []
        self.pages: Dict[int, Page] = {}

    def set_dock(self, dock_ids: List[str]) -> None:
        self.dock = [d for d in dock_ids if isinstance(d, str) and d]

    def _ensure_page(self, page: int) -> None:
        if page not in self.pages:
            self.pages[page] = Page()

    def add_app(self, page: int, bundle_id: str) -> None:
        if not bundle_id:
            return
        self._ensure_page(page)
        self.pages[page].apps.append(AppItem(bundle_id))

    def add_folder(self, page: int, name: str, apps: List[str]) -> None:
        self._ensure_page(page)
        self.pages[page].folders.append(FolderItem(name or "Folder", [AppItem(a) for a in apps or []]))

    def add_all_apps_folder(self, *, page: int, name: str = "All Apps", exclude: Optional[Set[str]] = None) -> None:
        if not self.layout_export:
            return
        exclude = exclude or set()
        remaining = [a for a in _list_apps_from_export(self.layout_export) if a and a not in exclude]
        self.add_folder(page, name, remaining)

    def _build_pages_items(self) -> List[List[Dict[str, Any]]]:
        if not self.pages:
            return []
        pages_items: List[List[Dict[str, Any]]] = []
        for idx in range(1, max(self.pages.keys()) + 1):
            spec = self.pages.get(idx, Page())
            pages_items.append(spec.as_items())
        return pages_items

    def build_payload(self, *, payload_identifier: str, display_name: str) -> Dict[str, Any]:
        pages_items = self._build_pages_items()
        return _build_hsl_payload(
            dock_ids=self.dock,
            pinned_ids=[],
            folders={},
            payload_identifier=payload_identifier,
            display_name=display_name,
            pages_items=pages_items,
        )

    def build_profile(
        self,
        *,
        payload_identifier: str,
        display_name: str,
        top_identifier: str,
        organization: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = self.build_payload(payload_identifier=payload_identifier, display_name=display_name)
        profile: Dict[str, Any] = {
            "PayloadContent": [payload],
            "PayloadType": "Configuration",
            "PayloadVersion": 1,
            "PayloadIdentifier": top_identifier,
            "PayloadUUID": str(uuid4()),
            "PayloadDisplayName": display_name,
        }
        if organization:
            profile["PayloadOrganization"] = organization
        return profile


def _build_hsl_payload(
    *,
    dock_ids: List[str],
    pinned_ids: List[str],
    folders: Dict[str, List[str]],
    payload_identifier: str,
    display_name: str,
    pages_items: Optional[List[List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    dock_items = [_app_item(b) for b in dock_ids]

    # Pages: use provided pages_items when present; else default to Page 1 with pins+folders
    if pages_items is not None:
        pages = pages_items
    else:
        pins_page: List[Dict[str, Any]] = []
        dock_set = set(dock_ids)
        for b in pinned_ids:
            if b and b not in dock_set:
                pins_page.append(_app_item(b))

        folder_items: List[Dict[str, Any]] = []
        for fname, apps in (folders or {}).items():
            if not apps:
                continue
            folder_items.append(_folder_item(fname, apps))

        page1 = pins_page + folder_items
        pages = [page1]

    payload = {
        "PayloadType": "com.apple.homescreenlayout",
        "PayloadVersion": 1,
        "PayloadIdentifier": payload_identifier,
        "PayloadUUID": str(uuid4()),
        "PayloadDisplayName": display_name,
        "Dock": dock_items,
        "Pages": pages,
    }
    return payload


def _normalize_pages_spec(pages_spec: Dict[Any, Any]) -> List[Dict[str, Any]]:
    """Return a list ordered by page number with apps/folders entries.

    Input shape (plan):
      pages:
        1:
          apps: [bundle.id,...]
          folders: [NameA, NameB]
        2:
          apps: [...]
          folders: [...]
    """
    def _to_int(k: Any) -> int:
        try:
            return int(k)
        except Exception:
            return 0

    ordered: List[Dict[str, Any]] = []
    for k in sorted(pages_spec.keys(), key=_to_int):
        v = pages_spec.get(k) or {}
        ordered.append({
            "apps": list(v.get("apps") or []),
            "folders": list(v.get("folders") or []),
        })
    return ordered


def _resolve_dock(
    plan: Dict[str, Any],
    layout_export: Optional[Dict[str, Any]],
    pins: List[str],
    dock_count: int,
) -> List[str]:
    """Resolve dock apps from plan, layout export, or pins."""
    plan_dock = plan.get("dock") if isinstance(plan.get("dock"), list) else None
    if plan_dock is not None:
        return [d for d in plan_dock if isinstance(d, str) and d]
    if layout_export and isinstance(layout_export.get("dock"), list):
        return list(layout_export.get("dock") or [])
    return pins[: max(dock_count, 0)]


def _build_pages_from_spec(
    builder: HomeScreenConfigBuilder,
    pages_spec: Dict[Any, Any],
    folders: Dict[str, List[str]],
    dock: List[str],
) -> None:
    """Build pages from explicit pages specification."""
    ordered = _normalize_pages_spec(pages_spec)
    dock_set = set(dock)
    for idx, page in enumerate(ordered, start=1):
        for a in page.get("apps", []) or []:
            if a and a not in dock_set:
                builder.add_app(idx, a)
        for name in page.get("folders", []) or []:
            builder.add_folder(idx, name, folders.get(name, []))


def _build_default_pages(
    builder: HomeScreenConfigBuilder,
    pins: List[str],
    folders: Dict[str, List[str]],
    dock: List[str],
) -> None:
    """Build default page 1 layout from pins and folders."""
    dock_set = set(dock)
    for b in pins:
        if b and b not in dock_set:
            builder.add_app(1, b)
    for fname, apps in (folders or {}).items():
        builder.add_folder(1, fname, apps)


def _collect_assigned_apps(
    builder: HomeScreenConfigBuilder,
    dock: List[str],
    pins: List[str],
    folders: Dict[str, List[str]],
) -> Set[str]:
    """Collect all apps already assigned to dock, pins, folders, or pages."""
    assigned: Set[str] = set(dock) | set(pins)
    for apps in folders.values():
        assigned.update(apps or [])
    for spec in builder.pages.values():
        assigned.update(a.bundle_id for a in spec.apps)
        for f in spec.folders:
            assigned.update(a.bundle_id for a in f.apps)
    return assigned


def _add_all_apps_folder(
    builder: HomeScreenConfigBuilder,
    merged_all_apps_cfg: Dict[str, Any],
    layout_export: Dict[str, Any],
    dock: List[str],
    pins: List[str],
    folders: Dict[str, List[str]],
) -> None:
    """Add a catch-all folder for remaining apps."""
    page_num = merged_all_apps_cfg.get("page") or (len(builder.pages) + 1)
    try:
        page_num = int(page_num)
    except Exception:  # nosec B110 - fallback to next page
        page_num = len(builder.pages) + 1

    assigned = _collect_assigned_apps(builder, dock, pins, folders)
    builder.add_all_apps_folder(
        page=page_num,
        name=merged_all_apps_cfg.get("name") or "All Apps",
        exclude=assigned,
    )


def _add_auto_categorized_folders(
    builder: HomeScreenConfigBuilder,
    auto_categories: List[str],
    auto_categories_page: int,
    layout_export: Dict[str, Any],
    dock: List[str],
    pins: List[str],
    folders: Dict[str, List[str]],
) -> None:
    """Auto-categorize remaining apps into folders on a target page."""
    try:
        target_page = int(auto_categories_page)
    except Exception:  # nosec B110 - fallback to page 2
        target_page = 2

    assigned = _collect_assigned_apps(builder, dock, pins, folders)
    remaining = [a for a in _list_apps_from_export(layout_export) if a and a not in assigned]

    buckets: Dict[str, List[str]] = {cat: [] for cat in auto_categories}
    for app_id in remaining:
        cat = classify_app(app_id)
        if cat not in buckets:
            buckets.setdefault("Utilities", [])
            cat = "Utilities"
        buckets[cat].append(app_id)

    for cat in auto_categories:
        apps = buckets.get(cat) or []
        if apps:
            builder.add_folder(target_page, cat, apps)


def build_mobileconfig(
    *,
    plan: Dict[str, Any],
    layout_export: Optional[Dict[str, Any]] = None,
    top_identifier: str = "com.example.profile",
    hs_identifier: str = "com.example.hslayout",
    display_name: str = "Home Screen Layout",
    organization: Optional[str] = None,
    dock_count: int = 4,
    all_apps_folder: Optional[Dict[str, Any]] = None,
    auto_categories: Optional[List[str]] = None,
    auto_categories_page: int = 2,
) -> Dict[str, Any]:
    """Return a Configuration profile dict suitable for plistlib.dump().

    Dock comes from `layout_export['dock']` when provided; otherwise, take
    the first N from plan['pins'] (N=dock_count, default 4).
    Page 1 contains remaining pins, then folders (single page each).
    Optionally place all remaining apps into a single folder (all_apps_folder) on a target page.
    """
    pins: List[str] = list(plan.get("pins") or [])
    folders: Dict[str, List[str]] = dict(plan.get("folders") or {})

    # Resolve dock configuration
    dock = _resolve_dock(plan, layout_export, pins, dock_count)

    # Initialize builder and configure dock
    builder = HomeScreenConfigBuilder(layout_export or {"dock": [], "pages": []})
    builder.set_dock(dock)

    # Build pages from specification or use defaults
    pages_spec = plan.get("pages") if isinstance(plan.get("pages"), dict) else None
    if pages_spec:
        _build_pages_from_spec(builder, pages_spec, folders, dock)
    else:
        _build_default_pages(builder, pins, folders, dock)

    # Merge all_apps_folder configuration
    merged_all_apps_cfg: Optional[Dict[str, Any]] = None
    if isinstance(plan.get("all_apps_folder"), dict):
        merged_all_apps_cfg = dict(plan.get("all_apps_folder") or {})
    if isinstance(all_apps_folder, dict):
        merged_all_apps_cfg = {**(merged_all_apps_cfg or {}), **all_apps_folder}

    # Add catch-all folder if configured
    if merged_all_apps_cfg and layout_export and not auto_categories:
        _add_all_apps_folder(builder, merged_all_apps_cfg, layout_export, dock, pins, folders)

    # Auto-categorize remaining apps if enabled
    if auto_categories and layout_export:
        _add_auto_categorized_folders(
            builder, auto_categories, auto_categories_page, layout_export, dock, pins, folders
        )

    return builder.build_profile(
        payload_identifier=hs_identifier,
        display_name=display_name,
        top_identifier=top_identifier,
        organization=organization,
    )
