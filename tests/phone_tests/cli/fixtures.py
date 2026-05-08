"""Test fixtures for phone CLI commands.

Provides arg builders for all phone CLI commands to simplify testing.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock

# Default paths used across fixtures
_DEFAULT_ICON_STATE_PATH = "out/ios.IconState.yaml"
_DEFAULT_PLAN_PATH = "out/ios.plan.yaml"
_DEFAULT_MANIFEST_PATH = "out/ios.manifest.yaml"

# Default profile identifiers (match phone/cli/main.py constants)
_DEFAULT_PROFILE_IDENTIFIER = "com.example.profile"
_DEFAULT_HS_IDENTIFIER = "com.example.hslayout"
_DEFAULT_DISPLAY_NAME = "Home Screen Layout"


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
    out: str = _DEFAULT_ICON_STATE_PATH,
) -> MagicMock:
    """Create args for cmd_export."""
    return make_args(backup=backup, out=out)


def make_export_device_args(
    out: str = _DEFAULT_ICON_STATE_PATH,
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
    out: str = _DEFAULT_PLAN_PATH,
) -> MagicMock:
    """Create args for cmd_plan."""
    return make_args(layout=layout, backup=backup, out=out)


def make_checklist_args(
    plan: str = _DEFAULT_PLAN_PATH,
    layout: Optional[str] = None,
    backup: Optional[str] = None,
    out: str = "out/ios.checklist.txt",
) -> MagicMock:
    """Create args for cmd_checklist."""
    return make_args(plan=plan, layout=layout, backup=backup, out=out)


_UNUSED_DEFAULTS: Dict[str, Any] = {
    "layout": None,
    "backup": None,
    "keep": None,
    "limit": 20,
    "format": "text",  # Note: CLI uses 'format' not 'output'
    "out": None,
}


def make_unused_args(**overrides: Any) -> MagicMock:
    """Create args for cmd_unused.  Override any field via kwargs."""
    return make_args(**{**_UNUSED_DEFAULTS, **overrides})


_PRUNE_DEFAULTS: Dict[str, Any] = {
    "layout": None,
    "backup": None,
    "keep": None,
    "limit": 20,
    "mode": "offload",  # Note: CLI uses 'mode' not 'delete'
    "out": "out/ios.prune_plan.txt",
}


def make_prune_args(**overrides: Any) -> MagicMock:
    """Create args for cmd_prune.  Override any field via kwargs."""
    return make_args(**{**_PRUNE_DEFAULTS, **overrides})


def make_analyze_args(
    layout: Optional[str] = None,
    backup: Optional[str] = None,
    plan: Optional[str] = None,
    format: str = "text",  # Note: CLI uses 'format' not 'output'
) -> MagicMock:
    """Create args for cmd_analyze."""
    return make_args(layout=layout, backup=backup, plan=plan, format=format)


_MANIFEST_FROM_EXPORT_DEFAULTS: Dict[str, Any] = {
    "export": _DEFAULT_ICON_STATE_PATH,
    "out": "out/ios.manifest.from_export.yaml",
    "label": None,
    "udid": None,
    "creds_profile": "ios_layout_manager",
    "identifier": _DEFAULT_PROFILE_IDENTIFIER,
    "hs_identifier": _DEFAULT_HS_IDENTIFIER,
    "display_name": _DEFAULT_DISPLAY_NAME,
    "organization": "Personal",
}


def make_manifest_from_export_args(**overrides: Any) -> MagicMock:
    """Create args for cmd_manifest_from_export.  Override any field via kwargs."""
    return make_args(**{**_MANIFEST_FROM_EXPORT_DEFAULTS, **overrides})


_MANIFEST_FROM_DEVICE_DEFAULTS: Dict[str, Any] = {
    "out": "out/ios.manifest.from_device.yaml",
    "udid": None,
    "timeout": 30,
    "label": None,
    "creds_profile": "ios_layout_manager",
    "identifier": _DEFAULT_PROFILE_IDENTIFIER,
    "hs_identifier": _DEFAULT_HS_IDENTIFIER,
    "display_name": _DEFAULT_DISPLAY_NAME,
    "organization": "Personal",
}


def make_manifest_from_device_args(**overrides: Any) -> MagicMock:
    """Create args for cmd_manifest_from_device.  Override any field via kwargs."""
    return make_args(**{**_MANIFEST_FROM_DEVICE_DEFAULTS, **overrides})


def make_manifest_install_args(
    manifest: str = _DEFAULT_MANIFEST_PATH,
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


_AUTO_FOLDERS_DEFAULTS: Dict[str, Any] = {
    "plan": _DEFAULT_PLAN_PATH,
    "out": "out/ios.plan.folderized.yaml",
    "start_page": 2,
    "per_page": 12,
    "keep": None,
    "layout": None,
}


def make_auto_folders_args(**overrides: Any) -> MagicMock:
    """Create args for cmd_auto_folders.  Override any field via kwargs."""
    return make_args(**{**_AUTO_FOLDERS_DEFAULTS, **overrides})


_PROFILE_BUILD_DEFAULTS: Dict[str, Any] = {
    "plan": _DEFAULT_PLAN_PATH,
    "out": "out/ios.mobileconfig",
    "layout": None,
    "identifier": _DEFAULT_PROFILE_IDENTIFIER,
    "hs_identifier": _DEFAULT_HS_IDENTIFIER,
    "display_name": _DEFAULT_DISPLAY_NAME,
    "organization": None,
    "all_apps_folder_name": None,
    "all_apps_folder_page": None,
    "dock_count": 4,
    "sign_p12": None,
    "sign_pass": None,
}


def make_profile_build_args(**overrides: Any) -> MagicMock:
    """Create args for cmd_profile_build.  Override any field via kwargs."""
    return make_args(**{**_PROFILE_BUILD_DEFAULTS, **overrides})


_MANIFEST_CREATE_DEFAULTS: Dict[str, Any] = {
    "from_plan": _DEFAULT_PLAN_PATH,
    "out": _DEFAULT_MANIFEST_PATH,
    "label": None,
    "udid": None,
    "creds_profile": "ios_layout_manager",
    "layout": None,
    "identifier": _DEFAULT_PROFILE_IDENTIFIER,
    "hs_identifier": _DEFAULT_HS_IDENTIFIER,
    "display_name": _DEFAULT_DISPLAY_NAME,
    "organization": "Personal",
}


def make_manifest_create_args(**overrides: Any) -> MagicMock:
    """Create args for cmd_manifest_create.  Override any field via kwargs."""
    return make_args(**{**_MANIFEST_CREATE_DEFAULTS, **overrides})


def make_manifest_build_args(
    manifest: str = _DEFAULT_MANIFEST_PATH,
    out: str = "out/ios.mobileconfig",
) -> MagicMock:
    """Create args for cmd_manifest_build."""
    return make_args(manifest=manifest, out=out)
