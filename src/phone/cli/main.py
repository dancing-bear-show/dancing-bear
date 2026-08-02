"""Phone Assistant CLI

Commands:
  export        — DEPRECATED: export layout from Finder backup to YAML
  export-device — Export layout from attached device via cfgutil to YAML
  iconmap       — Download raw icon layout from device via cfgutil
  plan          — Scaffold a plan (pins + folders) from current layout
  checklist     — Generate manual move instructions from plan

All processing is local and read-only. No device writes.
"""

from __future__ import annotations

import os
from pathlib import Path  # noqa: F401  # re-exported for test patch compatibility

from core.cli_framework import CLIApp
from core.assistant import BaseAssistant

# Import command implementations from split siblings
from .cmd_merge import cmd_merge_folders, cmd_reorg  # noqa: F401
from .cmd_layout import (  # noqa: F401
    _flatten_bundle_ids,
    _load_optional_device_apps,
    _parse_keep_list,
    _report_layout_issues,
    _update_plan_with_folders,
    cmd_analyze,
    cmd_auto_folders,
    cmd_checklist,
    cmd_export,
    cmd_export_device,
    cmd_iconmap,
    cmd_plan,
    cmd_prune,
    cmd_unused,
    cmd_validate_layout,
)
from .cmd_profile import (  # noqa: F401
    _DEFAULT_DISPLAY_NAME,
    _DEFAULT_HS_IDENTIFIER,
    _DEFAULT_PROFILE_IDENTIFIER,
    _build_all_apps_folder_config,
    _build_manifest_dict,
    _extract_manifest_profile_config,
    _sign_mobileconfig,
    _write_mobileconfig,
    cmd_identity_verify,
    cmd_manifest_build,
    cmd_manifest_create,
    cmd_manifest_from_device,
    cmd_manifest_from_export,
    cmd_manifest_install,
    cmd_profile_build,
)

# Re-export pipeline/layout/profile helpers for backwards-compatible test patches
from core.pipeline import run_pipeline  # noqa: F401
from ..layout import (  # noqa: F401
    auto_folderize,
    distribute_folders_across_pages,
)
from ..helpers import read_yaml, write_yaml  # noqa: F401
from ..helpers import load_layout  # noqa: F401
from ..profile import ProfileMetadata, build_mobileconfig  # noqa: F401


# Create the CLI app
app = CLIApp(
    "phone-assistant",
    "Phone Assistant CLI for iOS Home Screen layout planning.",
    add_common_args=True,
)

# Create assistant for agentic support
assistant = BaseAssistant(
    "phone",
    "agentic: phone\npurpose: Home Screen layout planning + manifest helpers",
)

# Create command groups
profile_group = app.group("profile", help="Home Screen Layout profile helpers")
manifest_group = app.group(
    "manifest", help="Simplified manifest helpers (embed complex plan)"
)
identity_group = app.group(
    "identity", help="Identity helpers (p12 ↔ device supervision parity)"
)


# --- Top-level commands ---


@app.command("export", help="DEPRECATED: export layout from Finder backup to YAML")
@app.argument(
    "--backup",
    help="Path to Finder backup UDID dir (defaults to latest under MobileSync/Backup)",
)
@app.argument("--out", help="Output YAML path (default out/ios.IconState.yaml)")
def _cmd_export(args) -> int:
    return cmd_export(args)


@app.command(
    "export-device", help="Export layout from attached device via cfgutil to YAML"
)
@app.argument("--udid", help="Device UDID (optional when only one device is attached)")
@app.argument("--ecid", help="Device ECID (optional; overrides --udid)")
@app.argument("--out", help="Output YAML path (default out/ios.IconState.yaml)")
def _cmd_export_device(args) -> int:
    return cmd_export_device(args)


@app.command("iconmap", help="Download raw icon layout from device via cfgutil")
@app.argument("--udid", help="Device UDID (optional when only one device is attached)")
@app.argument("--ecid", help="Device ECID (optional; overrides --udid)")
@app.argument(
    "--format",
    choices=["json", "plist"],
    default="json",
    help="Output format (default json)",
)
@app.argument("--out", help="Output path (default out/ios.iconmap.json or .plist)")
def _cmd_iconmap(args) -> int:
    return cmd_iconmap(args)


@app.command("plan", help="Scaffold a plan YAML (pins + folders) from current layout")
@app.argument("--backup", help="Path to Finder backup UDID dir (or use --layout)")
@app.argument(
    "--layout", help="Existing export YAML to derive plan from (skips backup)"
)
@app.argument("--out", help="Output plan YAML path (default out/ios.plan.yaml)")
def _cmd_plan(args) -> int:
    return cmd_plan(args)


@app.command(
    "checklist", help="Generate manual move checklist from plan + current layout"
)
@app.argument("--plan", required=True, help="Plan YAML path")
@app.argument("--layout", help="Layout export YAML (optional; otherwise reads backup)")
@app.argument(
    "--backup", help="Path to Finder backup UDID dir (used if --layout not provided)"
)
@app.argument("--out", help="Output text path (default out/ios.checklist.txt)")
def _cmd_checklist(args) -> int:
    return cmd_checklist(args)


@app.command(
    "unused", help="Suggest rarely-used app candidates from current layout (heuristic)"
)
@app.argument("--layout", help="Layout export YAML (optional; otherwise reads backup)")
@app.argument(
    "--backup", help="Path to Finder backup UDID dir (used if --layout not provided)"
)
@app.argument(
    "--recent", help="Path to file with bundle IDs used recently (one per line)"
)
@app.argument(
    "--keep", help="Path to file with bundle IDs to always keep (one per line)"
)
@app.argument("--limit", type=int, default=50, help="Max rows to display (default 50)")
@app.argument(
    "--format",
    choices=["text", "csv"],
    default="text",
    help="Output format (default text)",
)
def _cmd_unused(args) -> int:
    return cmd_unused(args)


@app.command(
    "prune",
    help="Generate OFFLOAD/DELETE checklist for unused candidates (no device writes)",
)
@app.argument("--layout", help="Layout export YAML (optional; otherwise reads backup)")
@app.argument(
    "--backup", help="Path to Finder backup UDID dir (used if --layout not provided)"
)
@app.argument(
    "--recent", help="Path to file with bundle IDs used recently (one per line)"
)
@app.argument(
    "--keep", help="Path to file with bundle IDs to always keep (one per line)"
)
@app.argument("--limit", type=int, default=50, help="Max rows to include (default 50)")
@app.argument(
    "--threshold",
    type=float,
    default=1.0,
    help="Minimum score to include (default 1.0)",
)
@app.argument(
    "--mode",
    choices=["offload", "delete"],
    default="offload",
    help="Checklist mode (default offload)",
)
@app.argument(
    "--out", default="out/ios.unused.prune_checklist.txt", help="Output text file"
)
def _cmd_prune(args) -> int:
    return cmd_prune(args)


@app.command("analyze", help="Analyze layout balance and folder structure (text/json)")
@app.argument("--layout", help="Layout export YAML (optional; otherwise reads backup)")
@app.argument(
    "--backup", help="Path to Finder backup UDID dir (used if --layout not provided)"
)
@app.argument("--plan", help="Optional plan YAML to check pins/folders alignment")
@app.argument(
    "--format",
    choices=["text", "json"],
    default="text",
    help="Output format (default text)",
)
def _cmd_analyze(args) -> int:
    return cmd_analyze(args)


@app.command(
    "validate-layout",
    help="Validate an iOS icon layout JSON file for structural errors",
)
@app.argument(
    "--layout",
    required=True,
    help="Path to layout JSON file (e.g. out/ios.iconlayout.json)",
)
@app.argument(
    "--device-layout",
    help="Optional device layout JSON with apps to check for unplaced entries",
)
def _cmd_validate_layout(args) -> int:
    return cmd_validate_layout(args)


@app.command(
    "auto-folders",
    help="Auto-assign all apps into folders in plan (keeps specified apps out)",
)
@app.argument("--layout", help="Layout export YAML (optional; otherwise reads backup)")
@app.argument(
    "--backup", help="Path to Finder backup UDID dir (used if --layout not provided)"
)
@app.argument(
    "--plan", default="out/ipad.plan.yaml", help="Plan YAML path to read/update"
)
@app.argument(
    "--keep",
    default="com.apple.mobilesafari,com.apple.Preferences",
    help="Comma-separated bundle IDs to keep out of folders",
)
@app.argument(
    "--place-folders-from-page",
    type=int,
    default=2,
    help="Start placing folders from this page (default 2)",
)
@app.argument(
    "--folders-per-page", type=int, default=12, help="Max folders per page (default 12)"
)
def _cmd_auto_folders(args) -> int:
    return cmd_auto_folders(args)


@app.command(
    "merge-folders",
    help="Redistribute dump folder apps into best-fit existing folders",
)
@app.argument(
    "--layout",
    default="out/ios.IconState.yaml",
    help="Layout export YAML (default out/ios.IconState.yaml)",
)
@app.argument(
    "--plan",
    default="out/ios.plan.merged.yaml",
    help="Output plan YAML (default out/ios.plan.merged.yaml)",
)
@app.argument(
    "--keep",
    default="",
    help="Comma-separated bundle IDs to keep as page-1 pins",
)
@app.argument(
    "--dump-folder-names",
    default="Other",
    help="Comma-separated folder names to redistribute (default Other)",
)
def _cmd_merge_folders(args) -> int:
    return cmd_merge_folders(args)


@app.command(
    "reorg",
    help="One-shot reorg: export-device → merge-folders → profile build → install",
)
@app.argument(
    "--device-label",
    default="bcsphone",
    help="Device label from credentials.ini (default bcsphone)",
)
@app.argument("--udid", help="Device UDID (overrides --device-label)")
@app.argument(
    "--keep",
    default="",
    help="Comma-separated bundle IDs to keep as page-1 pins",
)
@app.argument(
    "--out",
    default="out/ios.merged.mobileconfig",
    help="Output .mobileconfig path (default out/ios.merged.mobileconfig)",
)
@app.argument(
    "--no-install",
    action="store_true",
    default=False,
    help="Build only; skip the cfgutil copy step",
)
@app.argument(
    "--dry-run",
    action="store_true",
    default=False,
    help="Plan only; use existing layout, skip device write",
)
@app.argument(
    "--install-only",
    action="store_true",
    default=False,
    help="Skip export/merge/build; install an existing profile (see --profile)",
)
@app.argument(
    "--profile",
    default=None,
    help="Profile path for --install-only (default out/ios.merged.mobileconfig)",
)
def _cmd_reorg(args) -> int:
    return cmd_reorg(args)


# --- Profile group commands ---


@profile_group.command("build", help="Build a .mobileconfig from a plan YAML")
@profile_group.argument("--plan", required=True, help="Plan YAML path (pins + folders)")
@profile_group.argument(
    "--layout", help="Optional layout export YAML; uses 'dock' if present"
)
@profile_group.argument("--out", required=True, help="Output .mobileconfig path")
@profile_group.argument(
    "--identifier",
    default=_DEFAULT_PROFILE_IDENTIFIER,
    help="Top-level PayloadIdentifier",
)
@profile_group.argument(
    "--hs-identifier",
    default=_DEFAULT_HS_IDENTIFIER,
    help="Home Screen PayloadIdentifier",
)
@profile_group.argument(
    "--display-name", default=_DEFAULT_DISPLAY_NAME, help="Payload display name"
)
@profile_group.argument("--organization", help="Optional PayloadOrganization")
@profile_group.argument(
    "--dock-count",
    type=int,
    default=4,
    help="Dock count from pins when --layout missing (default 4)",
)
@profile_group.argument(
    "--all-apps-folder-name",
    help="Optional folder name for all remaining apps (requires --layout)",
)
@profile_group.argument(
    "--all-apps-folder-page",
    type=int,
    help="Page number to place the all-apps folder (requires --layout)",
)
@profile_group.argument(
    "--folder-page-size",
    type=int,
    default=30,
    help="Apps per folder page, must be >= 1 (9 for iPhone grids; default 30)",
)
@profile_group.argument(
    "--sign-p12", help="Path to .p12 certificate for signing the profile"
)
@profile_group.argument(
    "--sign-pass", help="Password for .p12 certificate (or set IOS_SIGN_PASS env var)"
)
def _cmd_profile_build(args) -> int:
    return cmd_profile_build(args)


# --- Manifest group commands ---


@manifest_group.command(
    "create", help="Create a manifest by embedding an existing plan"
)
@manifest_group.argument(
    "--from-plan", required=True, help="Path to existing plan YAML to embed"
)
@manifest_group.argument("--out", required=True, help="Output manifest YAML path")
@manifest_group.argument("--label", help="Optional device label to include")
@manifest_group.argument("--udid", help="Optional device UDID to include")
@manifest_group.argument(
    "--creds-profile",
    default=os.environ.get("IOS_CREDS_PROFILE", "ios_layout_manager"),
    help="Credentials profile name",
)
@manifest_group.argument(
    "--layout", help="Optional layout export YAML path to include (for Dock inference)"
)
@manifest_group.argument(
    "--identifier", default=_DEFAULT_PROFILE_IDENTIFIER, help="Profile identifier"
)
@manifest_group.argument(
    "--hs-identifier",
    default=_DEFAULT_HS_IDENTIFIER,
    help="Home Screen PayloadIdentifier",
)
@manifest_group.argument(
    "--display-name", default=_DEFAULT_DISPLAY_NAME, help="Profile display name"
)
@manifest_group.argument(
    "--organization", default="Personal", help="Profile organization"
)
def _cmd_manifest_create(args) -> int:
    return cmd_manifest_create(args)


@manifest_group.command("build-profile", help="Build a .mobileconfig from a manifest")
@manifest_group.argument("--manifest", required=True, help="Manifest YAML path")
@manifest_group.argument("--out", required=True, help="Output .mobileconfig path")
def _cmd_manifest_build(args) -> int:
    return cmd_manifest_build(args)


@manifest_group.command(
    "from-export", help="Create a device layout manifest from a layout export YAML"
)
@manifest_group.argument(
    "--export",
    required=True,
    help="Layout export YAML (from 'phone export-device' or legacy export')",
)
@manifest_group.argument("--out", required=True, help="Output manifest YAML path")
def _cmd_manifest_from_export(args) -> int:
    return cmd_manifest_from_export(args)


@manifest_group.command(
    "from-device",
    help="Create a device layout manifest from an attached device via cfgutil",
)
@manifest_group.argument("--out", required=True, help="Output manifest YAML path")
@manifest_group.argument(
    "--export-out", help="Optional export YAML to also write (dock/pages)"
)
@manifest_group.argument(
    "--udid", help="Device UDID (optional when only one device is attached)"
)
def _cmd_manifest_from_device(args) -> int:
    return cmd_manifest_from_device(args)


@manifest_group.command(
    "install",
    help="Build and install a profile from a manifest (hands-off via credentials)",
)
@manifest_group.argument("--manifest", required=True, help="Manifest YAML path")
@manifest_group.argument("--out", help="Output .mobileconfig path (default under out/)")
@manifest_group.argument(
    "--udid", help="Override device UDID (else manifest.device.udid or env)"
)
@manifest_group.argument(
    "--device-label", help="Override device label (else manifest.device.label or env)"
)
@manifest_group.argument(
    "--creds-profile",
    help="Override credentials profile (else manifest.device.creds_profile or IOS_CREDS_PROFILE)",
)
@manifest_group.argument("--config", help="credentials.ini path override (optional)")
@manifest_group.argument(
    "--dry-run",
    action="store_true",
    default=False,
    help="Plan only — build profile but skip device install",
)
def _cmd_manifest_install(args) -> int:
    return cmd_manifest_install(args)


# --- Identity group commands ---


@identity_group.command("verify", help="Verify .p12 identity vs device supervision")
@identity_group.argument(
    "--p12",
    help="Path to Supervision Identity .p12 (optional; else reads credentials.ini)",
)
@identity_group.argument(
    "--pass",
    dest="p12_pass",
    help="Password for .p12 (optional; else reads credentials.ini)",
)
@identity_group.argument(
    "--creds-profile",
    default=os.environ.get("IOS_CREDS_PROFILE", "ios_layout_manager"),
    help="Credentials profile name",
)
@identity_group.argument("--config", help="Path to credentials.ini (optional)")
@identity_group.argument(
    "--device-label",
    help="Device label to resolve UDID from credentials.ini [ios_devices]",
)
@identity_group.argument("--udid", help="Device UDID (optional)")
@identity_group.argument(
    "--expected-org",
    help="Expected organization name to match certificate subject/issuer (optional)",
)
def _cmd_identity_verify(args) -> int:
    return cmd_identity_verify(args)


def _install_output_masking() -> None:
    """Install output masking for secret shielding."""
    from core.secrets import install_output_masking_from_env

    install_output_masking_from_env()


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""
    return app.run_with_assistant(
        assistant=assistant,
        emit_func=lambda fmt, compact: _lazy_agentic()(fmt, compact),
        argv=argv,
        pre_run_hook=_install_output_masking,
    )


def _lazy_agentic():
    """Lazy loader for agentic emit function."""
    from ..agentic import emit_agentic_context

    return emit_agentic_context


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
