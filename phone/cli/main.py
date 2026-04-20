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
import subprocess
import sys
from pathlib import Path

from core.cli_framework import CLIApp
from core.assistant import BaseAssistant
from core.pipeline import run_pipeline

from ..helpers import LayoutLoadError, load_layout, read_yaml, write_yaml
from ..pipeline import (
    AnalyzeProducer,
    AnalyzeProcessor,
    AnalyzeRequest,
    ChecklistProducer,
    ChecklistProcessor,
    ChecklistRequest,
    ExportDeviceProducer,
    ExportDeviceProcessor,
    ExportDeviceRequest,
    ExportProducer,
    ExportProcessor,
    ExportRequest,
    IconmapProducer,
    IconmapProcessor,
    IconmapRequest,
    IdentityVerifyProducer,
    IdentityVerifyProcessor,
    IdentityVerifyRequest,
    ManifestFromDeviceProducer,
    ManifestFromDeviceProcessor,
    ManifestFromDeviceRequest,
    ManifestFromExportProducer,
    ManifestFromExportProcessor,
    ManifestFromExportRequest,
    ManifestInstallProducer,
    ManifestInstallProcessor,
    ManifestInstallRequest,
    PlanProducer,
    PlanProcessor,
    PlanRequest,
    PruneProducer,
    PruneProcessor,
    PruneRequest,
    UnusedProducer,
    UnusedProcessor,
    UnusedRequest,
)

from ..layout import (
    auto_folderize,
    distribute_folders_across_pages,
)
from ..profile import build_mobileconfig


# Default values for profile configuration
_DEFAULT_PROFILE_IDENTIFIER = "com.example.profile"
_DEFAULT_HS_IDENTIFIER = "com.example.hslayout"
_DEFAULT_DISPLAY_NAME = "Home Screen Layout"


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
manifest_group = app.group("manifest", help="Simplified manifest helpers (embed complex plan)")
identity_group = app.group("identity", help="Identity helpers (p12 ↔ device supervision parity)")


# --- Top-level commands ---

@app.command("export", help="DEPRECATED: export layout from Finder backup to YAML")
@app.argument("--backup", help="Path to Finder backup UDID dir (defaults to latest under MobileSync/Backup)")
@app.argument("--out", help="Output YAML path (default out/ios.IconState.yaml)")
def cmd_export(args) -> int:
    print("Deprecated: 'phone export' uses Finder backups. Use 'phone export-device' or 'phone iconmap'.", file=sys.stderr)
    out_path = Path(getattr(args, "out", None) or "out/ios.IconState.yaml")
    request = ExportRequest(backup=getattr(args, "backup", None), out_path=out_path)
    return run_pipeline(request, ExportProcessor, ExportProducer)


@app.command("export-device", help="Export layout from attached device via cfgutil to YAML")
@app.argument("--udid", help="Device UDID (optional when only one device is attached)")
@app.argument("--ecid", help="Device ECID (optional; overrides --udid)")
@app.argument("--out", help="Output YAML path (default out/ios.IconState.yaml)")
def cmd_export_device(args) -> int:
    out_path = Path(getattr(args, "out", None) or "out/ios.IconState.yaml")
    request = ExportDeviceRequest(
        udid=getattr(args, "udid", None) or os.environ.get("IOS_DEVICE_UDID"),
        ecid=getattr(args, "ecid", None),
        out_path=out_path,
    )
    return run_pipeline(request, ExportDeviceProcessor, ExportDeviceProducer)


@app.command("iconmap", help="Download raw icon layout from device via cfgutil")
@app.argument("--udid", help="Device UDID (optional when only one device is attached)")
@app.argument("--ecid", help="Device ECID (optional; overrides --udid)")
@app.argument("--format", choices=["json", "plist"], default="json", help="Output format (default json)")
@app.argument("--out", help="Output path (default out/ios.iconmap.json or .plist)")
def cmd_iconmap(args) -> int:
    fmt = getattr(args, "format", "json")
    out_default = "out/ios.iconmap.json" if fmt == "json" else "out/ios.iconmap.plist"
    out_path = Path(getattr(args, "out", None) or out_default)
    request = IconmapRequest(
        udid=getattr(args, "udid", None) or os.environ.get("IOS_DEVICE_UDID"),
        ecid=getattr(args, "ecid", None),
        format=fmt,
        out_path=out_path,
    )
    return run_pipeline(request, IconmapProcessor, IconmapProducer)


@app.command("plan", help="Scaffold a plan YAML (pins + folders) from current layout")
@app.argument("--backup", help="Path to Finder backup UDID dir (or use --layout)")
@app.argument("--layout", help="Existing export YAML to derive plan from (skips backup)")
@app.argument("--out", help="Output plan YAML path (default out/ios.plan.yaml)")
def cmd_plan(args) -> int:
    out_path = Path(getattr(args, "out", None) or "out/ios.plan.yaml")
    request = PlanRequest(
        layout=getattr(args, "layout", None),
        backup=getattr(args, "backup", None),
        out_path=out_path,
    )
    return run_pipeline(request, PlanProcessor, PlanProducer)


@app.command("checklist", help="Generate manual move checklist from plan + current layout")
@app.argument("--plan", required=True, help="Plan YAML path")
@app.argument("--layout", help="Layout export YAML (optional; otherwise reads backup)")
@app.argument("--backup", help="Path to Finder backup UDID dir (used if --layout not provided)")
@app.argument("--out", help="Output text path (default out/ios.checklist.txt)")
def cmd_checklist(args) -> int:
    plan_path = Path(args.plan)
    out_path = Path(getattr(args, "out", None) or "out/ios.checklist.txt")
    request = ChecklistRequest(
        plan_path=plan_path,
        layout=getattr(args, "layout", None),
        backup=getattr(args, "backup", None),
        out_path=out_path,
    )
    return run_pipeline(request, ChecklistProcessor, ChecklistProducer)


@app.command("unused", help="Suggest rarely-used app candidates from current layout (heuristic)")
@app.argument("--layout", help="Layout export YAML (optional; otherwise reads backup)")
@app.argument("--backup", help="Path to Finder backup UDID dir (used if --layout not provided)")
@app.argument("--recent", help="Path to file with bundle IDs used recently (one per line)")
@app.argument("--keep", help="Path to file with bundle IDs to always keep (one per line)")
@app.argument("--limit", type=int, default=50, help="Max rows to display (default 50)")
@app.argument("--format", choices=["text", "csv"], default="text", help="Output format (default text)")
def cmd_unused(args) -> int:
    request = UnusedRequest(
        layout=getattr(args, "layout", None),
        backup=getattr(args, "backup", None),
        recent_path=getattr(args, "recent", None),
        keep_path=getattr(args, "keep", None),
        limit=int(getattr(args, "limit", 50)),
        threshold=0.8,
        format=getattr(args, "format", "text"),
    )
    return run_pipeline(request, UnusedProcessor, UnusedProducer)


@app.command("prune", help="Generate OFFLOAD/DELETE checklist for unused candidates (no device writes)")
@app.argument("--layout", help="Layout export YAML (optional; otherwise reads backup)")
@app.argument("--backup", help="Path to Finder backup UDID dir (used if --layout not provided)")
@app.argument("--recent", help="Path to file with bundle IDs used recently (one per line)")
@app.argument("--keep", help="Path to file with bundle IDs to always keep (one per line)")
@app.argument("--limit", type=int, default=50, help="Max rows to include (default 50)")
@app.argument("--threshold", type=float, default=1.0, help="Minimum score to include (default 1.0)")
@app.argument("--mode", choices=["offload", "delete"], default="offload", help="Checklist mode (default offload)")
@app.argument("--out", default="out/ios.unused.prune_checklist.txt", help="Output text file")
def cmd_prune(args) -> int:
    request = PruneRequest(
        layout=getattr(args, "layout", None),
        backup=getattr(args, "backup", None),
        recent_path=getattr(args, "recent", None),
        keep_path=getattr(args, "keep", None),
        limit=int(getattr(args, "limit", 50)),
        threshold=float(getattr(args, "threshold", 1.0)),
        mode=getattr(args, "mode", "offload"),
        out_path=Path(getattr(args, "out", "out/ios.unused.prune_checklist.txt")),
    )
    return run_pipeline(request, PruneProcessor, PruneProducer)


@app.command("analyze", help="Analyze layout balance and folder structure (text/json)")
@app.argument("--layout", help="Layout export YAML (optional; otherwise reads backup)")
@app.argument("--backup", help="Path to Finder backup UDID dir (used if --layout not provided)")
@app.argument("--plan", help="Optional plan YAML to check pins/folders alignment")
@app.argument("--format", choices=["text", "json"], default="text", help="Output format (default text)")
def cmd_analyze(args) -> int:
    request = AnalyzeRequest(
        layout=getattr(args, "layout", None),
        backup=getattr(args, "backup", None),
        plan_path=getattr(args, "plan", None),
        format=getattr(args, "format", "text"),
    )
    return run_pipeline(request, AnalyzeProcessor, AnalyzeProducer)


# --- Helper functions for cmd_auto_folders ---

def _parse_keep_list(keep_csv: str) -> list[str]:
    """Parse comma-separated bundle IDs into list.

    Args:
        keep_csv: Comma-separated string of bundle IDs

    Returns:
        List of bundle IDs with whitespace stripped

    Example:
        >>> _parse_keep_list("com.app1, com.app2 ,")
        ['com.app1', 'com.app2']
    """
    return [s.strip() for s in keep_csv.split(",") if s.strip()]


def _update_plan_with_folders(
    plan: dict,
    folders: dict[str, list[str]],
    start_page: int,
    per_page: int,
) -> dict:
    """Update plan dict with folder assignments and page distribution.

    Clears pages >= start_page and repopulates with folder icons.
    Page 1 is preserved if present.

    Args:
        plan: Existing plan dict (modified in-place)
        folders: Folder assignments from auto_folderize
        start_page: First page number for folder icons
        per_page: Max folder icons per page

    Returns:
        Updated plan dict (same object as input)
    """
    plan["folders"] = folders

    folder_names = sorted(name for name, apps in folders.items() if apps)
    pages = plan.get("pages") or {}

    # Clear pages >= start_page
    for k in list(pages.keys()):
        try:
            if int(k) >= start_page:
                del pages[k]
        except (ValueError, TypeError):  # nosec B112 - skip non-integer page keys
            # Page key is not convertible to int (malformed data); skip and continue
            continue

    # Add new folder pages
    new_pages = distribute_folders_across_pages(folder_names, per_page=per_page, start_page=start_page)
    # Merge in new pages
    for k, v in new_pages.items():
        pages[k] = v
    plan["pages"] = pages

    return plan


@app.command("auto-folders", help="Auto-assign all apps into folders in plan (keeps specified apps out)")
@app.argument("--layout", help="Layout export YAML (optional; otherwise reads backup)")
@app.argument("--backup", help="Path to Finder backup UDID dir (used if --layout not provided)")
@app.argument("--plan", default="out/ipad.plan.yaml", help="Plan YAML path to read/update")
@app.argument("--keep", default="com.apple.mobilesafari,com.apple.Preferences", help="Comma-separated bundle IDs to keep out of folders")
@app.argument("--place-folders-from-page", type=int, default=2, help="Start placing folders from this page (default 2)")
@app.argument("--folders-per-page", type=int, default=12, help="Max folders per page (default 12)")
def cmd_auto_folders(args) -> int:
    try:
        layout = load_layout(getattr(args, "layout", None), getattr(args, "backup", None))
    except LayoutLoadError as err:
        print(err, file=sys.stderr)
        return err.code

    plan_path = Path(getattr(args, "plan", "out/ipad.plan.yaml"))
    keep = _parse_keep_list(getattr(args, "keep", "") or "")

    # Load existing plan or scaffold a fresh one
    if plan_path.exists():
        plan = read_yaml(plan_path)
    else:
        plan = {"pins": [], "folders": {}, "pages": {}}

    # Compute folders
    seed = plan.get("folders") or {}
    folders = auto_folderize(layout, keep=keep, seed_folders=seed)

    # Update plan with folder distribution
    plan = _update_plan_with_folders(
        plan,
        folders,
        start_page=int(getattr(args, "place_folders_from_page", 2)),
        per_page=int(getattr(args, "folders_per_page", 12)),
    )

    # Write updated plan
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(plan, plan_path)
    print(f"Updated plan with auto-folders → {plan_path}")
    print(f"Folders: {len(folders)} (non-empty: {sum(1 for a in folders.values() if a)})")
    return 0


# --- Profile group commands ---

def _build_all_apps_folder_config(args, layout_export) -> dict | None:
    """Build all-apps folder config from args.

    Args:
        args: Command arguments namespace
        layout_export: Layout export dict (required if folder requested)

    Returns:
        Folder config dict or None if not requested

    Raises:
        ValueError: If --all-apps-folder-* used without layout
    """
    if not (getattr(args, "all_apps_folder_name", None) or
            getattr(args, "all_apps_folder_page", None) is not None):
        return None

    if not layout_export:
        raise ValueError("--all-apps-folder-* requires --layout to enumerate remaining apps")

    folder = {"name": getattr(args, "all_apps_folder_name", None) or "All Apps"}
    if getattr(args, "all_apps_folder_page", None) is not None:
        folder["page"] = args.all_apps_folder_page
    return folder


def _write_mobileconfig(profile_dict: dict, out_path: Path) -> None:
    """Write profile dict as XML plist to path.

    Args:
        profile_dict: Configuration profile dictionary
        out_path: Output file path
    """
    import plistlib
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as f:
        plistlib.dump(profile_dict, f, fmt=plistlib.FMT_XML, sort_keys=False)


def _sign_mobileconfig(in_path: Path, out_path: Path, p12_path: Path, p12_pass: str) -> None:
    """Sign a mobileconfig profile using openssl smime.

    Args:
        in_path: Path to unsigned .mobileconfig
        out_path: Path for signed output
        p12_path: Path to .p12 certificate file
        p12_pass: Password for .p12 file
    """
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        cert_pem = Path(tmpdir) / "cert.pem"
        key_pem = Path(tmpdir) / "key.pem"

        # Check if openssl supports -legacy flag (OpenSSL 3.x)
        result = subprocess.run(  # nosec B603 B607 - fixed openssl command
            ["openssl", "pkcs12", "-help"],
            capture_output=True, text=True
        )
        legacy_flag = ["-legacy"] if "-legacy" in result.stderr else []

        # Extract certificate
        subprocess.run(  # nosec B603 B607 - openssl with user-provided p12 path
            ["openssl", "pkcs12", *legacy_flag, "-in", str(p12_path),
             "-clcerts", "-nokeys", "-out", str(cert_pem), "-passin", f"pass:{p12_pass}"],
            check=True, capture_output=True
        )

        # Extract private key
        subprocess.run(  # nosec B603 B607 - openssl with user-provided p12 path
            ["openssl", "pkcs12", *legacy_flag, "-in", str(p12_path),
             "-nocerts", "-nodes", "-out", str(key_pem), "-passin", f"pass:{p12_pass}"],
            check=True, capture_output=True
        )

        # Sign the profile
        subprocess.run(  # nosec B603 B607 - openssl smime with controlled paths
            ["openssl", "smime", "-sign", "-in", str(in_path), "-out", str(out_path),
             "-signer", str(cert_pem), "-inkey", str(key_pem), "-outform", "der", "-nodetach"],
            check=True, capture_output=True
        )


@profile_group.command("build", help="Build a .mobileconfig from a plan YAML")
@profile_group.argument("--plan", required=True, help="Plan YAML path (pins + folders)")
@profile_group.argument("--layout", help="Optional layout export YAML; uses 'dock' if present")
@profile_group.argument("--out", required=True, help="Output .mobileconfig path")
@profile_group.argument("--identifier", default=_DEFAULT_PROFILE_IDENTIFIER, help="Top-level PayloadIdentifier")
@profile_group.argument("--hs-identifier", default=_DEFAULT_HS_IDENTIFIER, help="Home Screen PayloadIdentifier")
@profile_group.argument("--display-name", default=_DEFAULT_DISPLAY_NAME, help="Payload display name")
@profile_group.argument("--organization", help="Optional PayloadOrganization")
@profile_group.argument("--dock-count", type=int, default=4, help="Dock count from pins when --layout missing (default 4)")
@profile_group.argument("--all-apps-folder-name", help="Optional folder name for all remaining apps (requires --layout)")
@profile_group.argument("--all-apps-folder-page", type=int, help="Page number to place the all-apps folder (requires --layout)")
@profile_group.argument("--sign-p12", help="Path to .p12 certificate for signing the profile")
@profile_group.argument("--sign-pass", help="Password for .p12 certificate (or set IOS_SIGN_PASS env var)")
def cmd_profile_build(args) -> int:
    try:
        plan = read_yaml(Path(args.plan))

        layout_export = None
        if getattr(args, "layout", None):
            layout_export = read_yaml(Path(args.layout))

        all_apps_folder = _build_all_apps_folder_config(args, layout_export)

        profile_dict = build_mobileconfig(
            plan=plan,
            layout_export=layout_export,
            top_identifier=getattr(args, "identifier", _DEFAULT_PROFILE_IDENTIFIER),
            hs_identifier=getattr(args, "hs_identifier", _DEFAULT_HS_IDENTIFIER),
            display_name=getattr(args, "display_name", _DEFAULT_DISPLAY_NAME),
            organization=getattr(args, "organization", None),
            dock_count=max(0, int(getattr(args, "dock_count", 4))),
            all_apps_folder=all_apps_folder,
        )

        out_path = Path(args.out)
        _write_mobileconfig(profile_dict, out_path)
        print(f"Wrote {_DEFAULT_DISPLAY_NAME} profile to {out_path}")

        # Sign the profile if requested
        sign_p12 = getattr(args, "sign_p12", None)
        if sign_p12:
            sign_pass = getattr(args, "sign_pass", None) or os.environ.get("IOS_SIGN_PASS", "")
            _sign_mobileconfig(out_path, out_path, Path(sign_p12), sign_pass)
            print(f"Signed profile with {sign_p12}")

        return 0
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as e:
        print(f"Error signing profile: {e}", file=sys.stderr)
        return 2


# --- Manifest group commands ---

def _build_manifest_dict(plan: dict, args) -> dict:
    """Build manifest dict from plan and args.

    Pure function - testable without I/O.

    Args:
        plan: Plan dictionary
        args: Command arguments namespace

    Returns:
        Manifest dictionary with meta, device, profile, and plan sections
    """
    manifest = {
        "meta": {"name": "ios_layout_manifest", "version": 1},
        "device": {
            "label": getattr(args, "label", None) or os.environ.get("IOS_DEVICE_LABEL"),
            "udid": getattr(args, "udid", None) or os.environ.get("IOS_DEVICE_UDID"),
            "creds_profile": getattr(args, "creds_profile", None) or os.environ.get("IOS_CREDS_PROFILE", "ios_layout_manager"),
        },
        "profile": {
            "identifier": getattr(args, "identifier", _DEFAULT_PROFILE_IDENTIFIER),
            "hs_identifier": getattr(args, "hs_identifier", _DEFAULT_HS_IDENTIFIER),
            "display_name": getattr(args, "display_name", _DEFAULT_DISPLAY_NAME),
            "organization": getattr(args, "organization", "Personal"),
        },
        "plan": plan,
    }
    if getattr(args, "layout", None):
        manifest["layout_export_path"] = str(Path(args.layout))
    return manifest


def _extract_manifest_profile_config(manifest: dict) -> tuple[dict, dict | None, dict]:
    """Extract plan, layout, and profile config from manifest.

    Args:
        manifest: Manifest dictionary

    Returns:
        Tuple of (plan, layout_export, profile_config)

    Raises:
        ValueError: If manifest is invalid or missing required sections
    """
    if not isinstance(manifest, dict) or "plan" not in manifest:
        raise ValueError("manifest missing 'plan' section")

    plan = manifest.get("plan") or {}

    layout_export = None
    lpath = manifest.get("layout_export_path")
    if lpath:
        try:
            layout_export = read_yaml(Path(lpath))
        except Exception:  # nosec B112 - optional layout, skip if missing
            layout_export = None

    profile_config = manifest.get("profile") or {}
    return plan, layout_export, profile_config


@manifest_group.command("create", help="Create a manifest by embedding an existing plan")
@manifest_group.argument("--from-plan", required=True, help="Path to existing plan YAML to embed")
@manifest_group.argument("--out", required=True, help="Output manifest YAML path")
@manifest_group.argument("--label", help="Optional device label to include")
@manifest_group.argument("--udid", help="Optional device UDID to include")
@manifest_group.argument("--creds-profile", default=os.environ.get("IOS_CREDS_PROFILE", "ios_layout_manager"), help="Credentials profile name")
@manifest_group.argument("--layout", help="Optional layout export YAML path to include (for Dock inference)")
@manifest_group.argument("--identifier", default=_DEFAULT_PROFILE_IDENTIFIER, help="Profile identifier")
@manifest_group.argument("--hs-identifier", default=_DEFAULT_HS_IDENTIFIER, help="Home Screen PayloadIdentifier")
@manifest_group.argument("--display-name", default=_DEFAULT_DISPLAY_NAME, help="Profile display name")
@manifest_group.argument("--organization", default="Personal", help="Profile organization")
def cmd_manifest_create(args) -> int:
    plan = read_yaml(Path(args.from_plan))
    manifest = _build_manifest_dict(plan, args)
    out = Path(args.out)
    write_yaml(manifest, out)
    print(f"Wrote manifest to {out}")
    return 0


@manifest_group.command("build-profile", help="Build a .mobileconfig from a manifest")
@manifest_group.argument("--manifest", required=True, help="Manifest YAML path")
@manifest_group.argument("--out", required=True, help="Output .mobileconfig path")
def cmd_manifest_build(args) -> int:
    mpath = Path(args.manifest)
    manifest = read_yaml(mpath)
    try:
        plan, layout_export, prof = _extract_manifest_profile_config(manifest)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    profile_dict = build_mobileconfig(
        plan=plan,
        layout_export=layout_export,
        top_identifier=prof.get("identifier", _DEFAULT_PROFILE_IDENTIFIER),
        hs_identifier=prof.get("hs_identifier", _DEFAULT_HS_IDENTIFIER),
        display_name=prof.get("display_name", _DEFAULT_DISPLAY_NAME),
        organization=prof.get("organization"),
        dock_count=4,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    import plistlib
    with out.open("wb") as f:
        plistlib.dump(profile_dict, f, fmt=plistlib.FMT_XML, sort_keys=False)
    print(f"Wrote {_DEFAULT_DISPLAY_NAME} profile to {out}")
    return 0


@manifest_group.command("from-export", help="Create a device layout manifest from a layout export YAML")
@manifest_group.argument("--export", required=True, help="Layout export YAML (from 'phone export-device' or legacy export')")
@manifest_group.argument("--out", required=True, help="Output manifest YAML path")
def cmd_manifest_from_export(args) -> int:
    request = ManifestFromExportRequest(
        export_path=Path(args.export),
        out_path=Path(args.out),
    )
    return run_pipeline(request, ManifestFromExportProcessor, ManifestFromExportProducer)


@manifest_group.command("from-device", help="Create a device layout manifest from an attached device via cfgutil")
@manifest_group.argument("--out", required=True, help="Output manifest YAML path")
@manifest_group.argument("--export-out", help="Optional export YAML to also write (dock/pages)")
@manifest_group.argument("--udid", help="Device UDID (optional when only one device is attached)")
def cmd_manifest_from_device(args) -> int:
    export_out = Path(args.export_out) if getattr(args, "export_out", None) else None
    request = ManifestFromDeviceRequest(
        udid=getattr(args, "udid", None),
        export_out=export_out,
        out_path=Path(args.out),
    )
    return run_pipeline(request, ManifestFromDeviceProcessor, ManifestFromDeviceProducer)


@manifest_group.command("install", help="Build and install a profile from a manifest (hands-off via credentials)")
@manifest_group.argument("--manifest", required=True, help="Manifest YAML path")
@manifest_group.argument("--out", help="Output .mobileconfig path (default under out/)")
@manifest_group.argument("--udid", help="Override device UDID (else manifest.device.udid or env)")
@manifest_group.argument("--device-label", help="Override device label (else manifest.device.label or env)")
@manifest_group.argument("--creds-profile", help="Override credentials profile (else manifest.device.creds_profile or IOS_CREDS_PROFILE)")
@manifest_group.argument("--config", help="credentials.ini path override (optional)")
def cmd_manifest_install(args) -> int:
    out_path = Path(args.out) if getattr(args, "out", None) else None
    request = ManifestInstallRequest(
        manifest_path=Path(args.manifest),
        out_path=out_path,
        dry_run=getattr(args, "dry_run", False),
        udid=getattr(args, "udid", None),
        device_label=getattr(args, "device_label", None),
        creds_profile=getattr(args, "creds_profile", None),
        config=getattr(args, "config", None),
    )
    return run_pipeline(request, ManifestInstallProcessor, ManifestInstallProducer)


# --- Identity group commands ---

@identity_group.command("verify", help="Verify .p12 identity vs device supervision")
@identity_group.argument("--p12", help="Path to Supervision Identity .p12 (optional; else reads credentials.ini)")
@identity_group.argument("--pass", dest="p12_pass", help="Password for .p12 (optional; else reads credentials.ini)")
@identity_group.argument("--creds-profile", default=os.environ.get("IOS_CREDS_PROFILE", "ios_layout_manager"), help="Credentials profile name")
@identity_group.argument("--config", help="Path to credentials.ini (optional)")
@identity_group.argument("--device-label", help="Device label to resolve UDID from credentials.ini [ios_devices]")
@identity_group.argument("--udid", help="Device UDID (optional)")
@identity_group.argument("--expected-org", help="Expected organization name to match certificate subject/issuer (optional)")
def cmd_identity_verify(args) -> int:
    request = IdentityVerifyRequest(
        p12_path=getattr(args, "p12", None),
        p12_pass=getattr(args, "p12_pass", None),
        creds_profile=getattr(args, "creds_profile", None),
        config=getattr(args, "config", None),
        device_label=getattr(args, "device_label", None),
        udid=getattr(args, "udid", None),
        expected_org=getattr(args, "expected_org", None),
    )
    return run_pipeline(request, IdentityVerifyProcessor, IdentityVerifyProducer)


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
