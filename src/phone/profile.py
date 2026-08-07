from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .classify import classify_app


@dataclass(frozen=True)
class MobileConfigOptions:
    """Tuning knobs for build_mobileconfig that don't belong in the plan."""

    dock_count: int = 4
    folder_page_size: int = 30
    auto_categories: list[str] | None = None
    auto_categories_page: int = 2


def _app_item(bundle_id: str) -> dict[str, Any]:
    return AppItem(bundle_id).as_spec()


def _int_or_default(value: Any, default: int) -> int:
    """Convert value to int, falling back to default on any conversion failure."""
    try:
        return int(value)
    except Exception:  # nosec B110 - fallback to caller-supplied default
        return default


@dataclass
class ProfileMetadata:
    """Identification fields for a mobileconfig profile."""

    top_identifier: str = "com.example.profile"
    hs_identifier: str = "com.example.hslayout"
    display_name: str = "Home Screen Layout"
    organization: str | None = None


@dataclass
class AppItem:
    """Represents a single application on the Home Screen."""

    bundle_id: str

    def as_spec(self) -> dict[str, Any]:
        return {"Type": "Application", "BundleID": self.bundle_id}


@dataclass
class FolderItem:
    """Represents a folder with one or more pages of apps."""

    name: str
    apps: list[AppItem] = field(default_factory=list)
    page_size: int = 30

    def as_spec(self) -> dict[str, Any]:
        pages: list[list[dict[str, Any]]] = []
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



def _collect_apps(items: list[Any], seen: set[str], apps: list[str]) -> None:
    """Collect apps from items list, updating seen set and apps list."""
    for a in items:
        if isinstance(a, str) and a and a not in seen:
            apps.append(a)
            seen.add(a)


def _collect_page_apps(page: dict[str, Any], seen: set[str], apps: list[str]) -> None:
    """Collect apps from a single page, including folders."""
    _collect_apps(page.get("apps") or [], seen, apps)
    for folder in page.get("folders") or []:
        _collect_apps(folder.get("apps") or [], seen, apps)


def _list_apps_from_export(layout_export: dict[str, Any]) -> list[str]:
    """Return a de-duped list of bundle IDs from a layout export dict."""
    seen: set[str] = set()
    apps: list[str] = []

    # Collect dock apps
    _collect_apps(layout_export.get("dock") or [], seen, apps)

    # Collect apps from all pages
    for page in layout_export.get("pages") or []:
        _collect_page_apps(page, seen, apps)

    return apps


@dataclass
class Page:
    """Page representation that can emit spec items."""

    apps: list[AppItem] = field(default_factory=list)
    folders: list[FolderItem] = field(default_factory=list)

    def as_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        items.extend([a.as_spec() for a in self.apps])
        items.extend([f.as_spec() for f in self.folders])
        return items


class HomeScreenConfigBuilder:
    """Object-oriented builder for Home Screen layout payloads."""

    def __init__(
        self,
        layout_export: dict[str, Any] | None = None,
        *,
        folder_page_size: int = 30,
    ) -> None:
        self.layout_export = layout_export or {"dock": [], "pages": []}
        self.dock: list[str] = []
        self.pages: dict[int, Page] = {}
        self.folder_page_size = folder_page_size

    def set_dock(self, dock_ids: list[str]) -> None:
        self.dock = [d for d in dock_ids if isinstance(d, str) and d]

    def _ensure_page(self, page: int) -> None:
        if page not in self.pages:
            self.pages[page] = Page()

    def add_app(self, page: int, bundle_id: str) -> None:
        if not bundle_id:
            return
        self._ensure_page(page)
        self.pages[page].apps.append(AppItem(bundle_id))

    def add_folder(self, page: int, name: str, apps: list[str]) -> None:
        self._ensure_page(page)
        self.pages[page].folders.append(
            FolderItem(
                name or "Folder",
                [AppItem(a) for a in apps or []],
                page_size=self.folder_page_size,
            )
        )

    def add_all_apps_folder(
        self, *, page: int, name: str = "All Apps", exclude: set[str] | None = None
    ) -> None:
        if not self.layout_export:
            return
        exclude = exclude or set()
        remaining = [
            a
            for a in _list_apps_from_export(self.layout_export)
            if a and a not in exclude
        ]
        self.add_folder(page, name, remaining)

    def _build_pages_items(self) -> list[list[dict[str, Any]]]:
        if not self.pages:
            return []
        pages_items: list[list[dict[str, Any]]] = []
        for idx in range(1, max(self.pages.keys()) + 1):
            spec = self.pages.get(idx, Page())
            pages_items.append(spec.as_items())
        return pages_items

    def build_payload(
        self, *, payload_identifier: str, display_name: str
    ) -> dict[str, Any]:
        pages_items = self._build_pages_items()
        return _build_hsl_payload(
            HslPayloadConfig(
                dock_ids=self.dock,
                pinned_ids=[],
                folders={},
                payload_identifier=payload_identifier,
                display_name=display_name,
                pages_items=pages_items,
            )
        )

    def build_profile(
        self,
        *,
        payload_identifier: str,
        display_name: str,
        top_identifier: str,
        organization: str | None = None,
    ) -> dict[str, Any]:
        payload = self.build_payload(
            payload_identifier=payload_identifier, display_name=display_name
        )
        profile: dict[str, Any] = {
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


@dataclass
class HslPayloadConfig:
    """Configuration for building a Home Screen layout payload."""

    dock_ids: list[str]
    pinned_ids: list[str]
    folders: dict[str, list[str]]
    payload_identifier: str
    display_name: str
    pages_items: list[list[dict[str, Any]]] | None = None


def _build_hsl_payload(config: HslPayloadConfig) -> dict[str, Any]:
    dock_items = [_app_item(b) for b in config.dock_ids]

    # Pages: use provided pages_items when present; else default to Page 1 with pins+folders
    if config.pages_items is not None:
        pages = config.pages_items
    else:
        pins_page: list[dict[str, Any]] = []
        dock_set = set(config.dock_ids)
        for b in config.pinned_ids:
            if b and b not in dock_set:
                pins_page.append(_app_item(b))

        folder_items: list[dict[str, Any]] = []
        for fname, apps in (config.folders or {}).items():
            if not apps:
                continue
            folder_items.append(FolderItem(fname, [AppItem(a) for a in apps if a]).as_spec())

        page1 = pins_page + folder_items
        pages = [page1]

    payload = {
        "PayloadType": "com.apple.homescreenlayout",
        "PayloadVersion": 1,
        "PayloadIdentifier": config.payload_identifier,
        "PayloadUUID": str(uuid4()),
        "PayloadDisplayName": config.display_name,
        "Dock": dock_items,
        "Pages": pages,
    }
    return payload


def _normalize_pages_spec(pages_spec: dict[Any, Any]) -> list[dict[str, Any]]:
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

    ordered: list[dict[str, Any]] = []
    for k in sorted(pages_spec.keys(), key=lambda k: _int_or_default(k, 0)):
        v = pages_spec.get(k) or {}
        ordered.append(
            {
                "apps": list(v.get("apps") or []),
                "folders": list(v.get("folders") or []),
            }
        )
    return ordered


def _validate_folder_page_size(folder_page_size: int) -> None:
    """Reject non-positive page sizes so the <=0 'unlimited' sentinel in
    FolderItem.as_spec() cannot be reached through the public build path."""
    if folder_page_size < 1:
        raise ValueError(f"folder_page_size must be >= 1, got {folder_page_size}")


def _resolve_dock(
    plan: dict[str, Any],
    layout_export: dict[str, Any] | None,
    pins: list[str],
    dock_count: int,
) -> list[str]:
    """Resolve dock apps from plan, layout export, or pins."""
    plan_dock = plan.get("dock") if isinstance(plan.get("dock"), list) else None
    if plan_dock is not None:
        return [d for d in plan_dock if isinstance(d, str) and d]
    if layout_export and isinstance(layout_export.get("dock"), list):
        return list(layout_export.get("dock") or [])
    return pins[: max(dock_count, 0)]


def _build_pages_from_spec(
    builder: HomeScreenConfigBuilder,
    pages_spec: dict[Any, Any],
    folders: dict[str, list[str]],
    dock: list[str],
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
    pins: list[str],
    folders: dict[str, list[str]],
    dock: list[str],
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
    dock: list[str],
    pins: list[str],
    folders: dict[str, list[str]],
) -> set[str]:
    """Collect all apps already assigned to dock, pins, folders, or pages."""
    assigned: set[str] = set(dock) | set(pins)
    for apps in folders.values():
        assigned.update(apps or [])
    for spec in builder.pages.values():
        assigned.update(a.bundle_id for a in spec.apps)
        for f in spec.folders:
            assigned.update(a.bundle_id for a in f.apps)
    return assigned


def _add_all_apps_folder(
    builder: HomeScreenConfigBuilder,
    merged_all_apps_cfg: dict[str, Any],
    dock: list[str],
    pins: list[str],
    folders: dict[str, list[str]],
) -> None:
    """Add a catch-all folder for remaining apps."""
    page_num = merged_all_apps_cfg.get("page") or (len(builder.pages) + 1)
    page_num = _int_or_default(page_num, len(builder.pages) + 1)

    assigned = _collect_assigned_apps(builder, dock, pins, folders)
    builder.add_all_apps_folder(
        page=page_num,
        name=merged_all_apps_cfg.get("name") or "All Apps",
        exclude=assigned,
    )


@dataclass
class AutoCategorizeConfig:
    """Configuration for auto-categorizing remaining apps into folders."""

    auto_categories: list[str]
    auto_categories_page: int
    layout_export: dict[str, Any]
    dock: list[str]
    pins: list[str]
    folders: dict[str, list[str]]


def _add_auto_categorized_folders(
    builder: HomeScreenConfigBuilder,
    config: AutoCategorizeConfig,
) -> None:
    """Auto-categorize remaining apps into folders on a target page."""
    target_page = _int_or_default(config.auto_categories_page, 2)

    assigned = _collect_assigned_apps(builder, config.dock, config.pins, config.folders)
    remaining = [
        a
        for a in _list_apps_from_export(config.layout_export)
        if a and a not in assigned
    ]

    buckets: dict[str, list[str]] = {cat: [] for cat in config.auto_categories}
    for app_id in remaining:
        cat = classify_app(app_id)
        if cat not in buckets:
            buckets.setdefault("Utilities", [])
            cat = "Utilities"
        buckets[cat].append(app_id)

    for cat in config.auto_categories:
        apps = buckets.get(cat) or []
        if apps:
            builder.add_folder(target_page, cat, apps)


def _merge_all_apps_cfg(
    plan: dict[str, Any], all_apps_folder: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Merge plan['all_apps_folder'] with an explicit all_apps_folder override."""
    merged: dict[str, Any] | None = None
    if isinstance(plan.get("all_apps_folder"), dict):
        merged = dict(plan.get("all_apps_folder") or {})
    if isinstance(all_apps_folder, dict):
        merged = {**(merged or {}), **all_apps_folder}
    return merged


def build_mobileconfig(
    *,
    plan: dict[str, Any],
    layout_export: dict[str, Any] | None = None,
    profile_meta: ProfileMetadata | None = None,
    all_apps_folder: dict[str, Any] | None = None,
    options: MobileConfigOptions | None = None,
) -> dict[str, Any]:
    """Return a Configuration profile dict suitable for plistlib.dump().

    Profile identification fields are passed via a ProfileMetadata instance
    (profile_meta).  Defaults to ProfileMetadata() when omitted.

    Dock comes from `layout_export['dock']` when provided; otherwise, take
    the first N from plan['pins'] (N=options.dock_count, default 4).
    Page 1 contains remaining pins, then folders. Folder contents are chunked
    into sub-pages of options.folder_page_size apps each (default 30; use 9
    for iPhone 3x3 folder grids; must be >= 1).
    Optionally place all remaining apps into a single folder (all_apps_folder)
    on a target page.  Pass a MobileConfigOptions instance to override defaults.
    """
    opts = options or MobileConfigOptions()
    _validate_folder_page_size(opts.folder_page_size)
    meta = profile_meta or ProfileMetadata()
    pins: list[str] = list(plan.get("pins") or [])
    folders: dict[str, list[str]] = dict(plan.get("folders") or {})

    # Resolve dock configuration
    dock = _resolve_dock(plan, layout_export, pins, opts.dock_count)

    # Initialize builder and configure dock
    builder = HomeScreenConfigBuilder(
        layout_export or {"dock": [], "pages": []},
        folder_page_size=opts.folder_page_size,
    )
    builder.set_dock(dock)

    # Build pages from specification or use defaults
    pages_spec = plan.get("pages") if isinstance(plan.get("pages"), dict) else None
    if pages_spec:
        _build_pages_from_spec(builder, pages_spec, folders, dock)
    else:
        _build_default_pages(builder, pins, folders, dock)

    # Add catch-all folder if configured (unless auto-categorization is on)
    if layout_export and not opts.auto_categories:
        merged_all_apps_cfg = _merge_all_apps_cfg(plan, all_apps_folder)
        if merged_all_apps_cfg:
            _add_all_apps_folder(builder, merged_all_apps_cfg, dock, pins, folders)

    # Auto-categorize remaining apps if enabled
    if opts.auto_categories and layout_export:
        _add_auto_categorized_folders(
            builder,
            AutoCategorizeConfig(
                auto_categories=opts.auto_categories,
                auto_categories_page=opts.auto_categories_page,
                layout_export=layout_export,
                dock=dock,
                pins=pins,
                folders=folders,
            ),
        )

    return builder.build_profile(
        payload_identifier=meta.hs_identifier,
        display_name=meta.display_name,
        top_identifier=meta.top_identifier,
        organization=meta.organization,
    )
