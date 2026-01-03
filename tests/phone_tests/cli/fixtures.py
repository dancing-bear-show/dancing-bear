"""Test fixtures for phone CLI commands.

Provides arg builders for all phone CLI commands to simplify testing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock


def make_args(**kwargs: Any) -> MagicMock:
    """Create a MagicMock args object with given attributes.

    Example:
        args = make_args(layout="export.yaml", out="plan.yaml", backup=None)
    """
    args = MagicMock()
    for key, value in kwargs.items():
        setattr(args, key, value)
    return args


# Pipeline command arg builders


def make_export_args(
    backup: Optional[str] = None,
    out: str = "out/ios.IconState.yaml",
) -> MagicMock:
    """Create args for cmd_export."""
    return make_args(backup=backup, out=out)


def make_export_device_args(
    out: str = "out/ios.IconState.yaml",
    udid: Optional[str] = None,
    timeout: int = 30,
) -> MagicMock:
    """Create args for cmd_export_device."""
    return make_args(out=out, udid=udid, timeout=timeout)


def make_iconmap_args(
    out: str = "out/ios.iconmap.json",
    udid: Optional[str] = None,
    timeout: int = 30,
) -> MagicMock:
    """Create args for cmd_iconmap."""
    return make_args(out=out, udid=udid, timeout=timeout)


def make_plan_args(
    layout: Optional[str] = None,
    backup: Optional[str] = None,
    out: str = "out/ios.plan.yaml",
) -> MagicMock:
    """Create args for cmd_plan."""
    return make_args(layout=layout, backup=backup, out=out)


def make_checklist_args(
    plan: str = "out/ios.plan.yaml",
    layout: Optional[str] = None,
    backup: Optional[str] = None,
    out: str = "out/ios.checklist.txt",
) -> MagicMock:
    """Create args for cmd_checklist."""
    return make_args(plan=plan, layout=layout, backup=backup, out=out)


def make_unused_args(
    layout: Optional[str] = None,
    backup: Optional[str] = None,
    keep: Optional[str] = None,
    limit: int = 20,
    output: str = "text",
    out: Optional[str] = None,
) -> MagicMock:
    """Create args for cmd_unused."""
    return make_args(
        layout=layout,
        backup=backup,
        keep=keep,
        limit=limit,
        output=output,
        out=out,
    )


def make_prune_args(
    layout: Optional[str] = None,
    backup: Optional[str] = None,
    keep: Optional[str] = None,
    limit: int = 20,
    delete: bool = False,
    out: str = "out/ios.prune_plan.txt",
) -> MagicMock:
    """Create args for cmd_prune."""
    return make_args(
        layout=layout,
        backup=backup,
        keep=keep,
        limit=limit,
        delete=delete,
        out=out,
    )


def make_analyze_args(
    layout: Optional[str] = None,
    backup: Optional[str] = None,
    plan: Optional[str] = None,
    output: str = "text",
) -> MagicMock:
    """Create args for cmd_analyze."""
    return make_args(layout=layout, backup=backup, plan=plan, output=output)


def make_manifest_from_export_args(
    export: str = "out/ios.IconState.yaml",
    out: str = "out/ios.manifest.from_export.yaml",
    label: Optional[str] = None,
    udid: Optional[str] = None,
    creds_profile: str = "ios_layout_manager",
    identifier: str = "com.example.profile",
    hs_identifier: str = "com.example.hslayout",
    display_name: str = "Home Screen Layout",
    organization: str = "Personal",
) -> MagicMock:
    """Create args for cmd_manifest_from_export."""
    return make_args(
        export=export,
        out=out,
        label=label,
        udid=udid,
        creds_profile=creds_profile,
        identifier=identifier,
        hs_identifier=hs_identifier,
        display_name=display_name,
        organization=organization,
    )


def make_manifest_from_device_args(
    out: str = "out/ios.manifest.from_device.yaml",
    udid: Optional[str] = None,
    timeout: int = 30,
    label: Optional[str] = None,
    creds_profile: str = "ios_layout_manager",
    identifier: str = "com.example.profile",
    hs_identifier: str = "com.example.hslayout",
    display_name: str = "Home Screen Layout",
    organization: str = "Personal",
) -> MagicMock:
    """Create args for cmd_manifest_from_device."""
    return make_args(
        out=out,
        udid=udid,
        timeout=timeout,
        label=label,
        creds_profile=creds_profile,
        identifier=identifier,
        hs_identifier=hs_identifier,
        display_name=display_name,
        organization=organization,
    )


def make_manifest_install_args(
    manifest: str = "out/ios.manifest.yaml",
) -> MagicMock:
    """Create args for cmd_manifest_install."""
    return make_args(manifest=manifest)


def make_identity_verify_args(
    p12: Optional[str] = None,
    p12_pass: Optional[str] = None,
    creds_profile: str = "ios_layout_manager",
    udid: Optional[str] = None,
) -> MagicMock:
    """Create args for cmd_identity_verify."""
    return make_args(
        p12=p12,
        p12_pass=p12_pass,
        creds_profile=creds_profile,
        udid=udid,
    )


# Inline command arg builders


def make_auto_folders_args(
    plan: str = "out/ios.plan.yaml",
    out: str = "out/ios.plan.folderized.yaml",
    start_page: int = 2,
    per_page: int = 12,
    keep: Optional[str] = None,
    layout: Optional[str] = None,
) -> MagicMock:
    """Create args for cmd_auto_folders."""
    return make_args(
        plan=plan,
        out=out,
        start_page=start_page,
        per_page=per_page,
        keep=keep,
        layout=layout,
    )


def make_profile_build_args(
    plan: str = "out/ios.plan.yaml",
    out: str = "out/ios.mobileconfig",
    layout: Optional[str] = None,
    identifier: str = "com.example.profile",
    hs_identifier: str = "com.example.hslayout",
    display_name: str = "Home Screen Layout",
    organization: Optional[str] = None,
    all_apps_folder_name: Optional[str] = None,
    all_apps_folder_page: Optional[int] = None,
    dock_count: int = 4,
) -> MagicMock:
    """Create args for cmd_profile_build."""
    return make_args(
        plan=plan,
        out=out,
        layout=layout,
        identifier=identifier,
        hs_identifier=hs_identifier,
        display_name=display_name,
        organization=organization,
        all_apps_folder_name=all_apps_folder_name,
        all_apps_folder_page=all_apps_folder_page,
        dock_count=dock_count,
    )


def make_manifest_create_args(
    from_plan: str = "out/ios.plan.yaml",
    out: str = "out/ios.manifest.yaml",
    label: Optional[str] = None,
    udid: Optional[str] = None,
    creds_profile: str = "ios_layout_manager",
    layout: Optional[str] = None,
    identifier: str = "com.example.profile",
    hs_identifier: str = "com.example.hslayout",
    display_name: str = "Home Screen Layout",
    organization: str = "Personal",
) -> MagicMock:
    """Create args for cmd_manifest_create."""
    return make_args(
        from_plan=from_plan,
        out=out,
        label=label,
        udid=udid,
        creds_profile=creds_profile,
        layout=layout,
        identifier=identifier,
        hs_identifier=hs_identifier,
        display_name=display_name,
        organization=organization,
    )


def make_manifest_build_args(
    manifest: str = "out/ios.manifest.yaml",
    out: str = "out/ios.mobileconfig",
) -> MagicMock:
    """Create args for cmd_manifest_build."""
    return make_args(manifest=manifest, out=out)
