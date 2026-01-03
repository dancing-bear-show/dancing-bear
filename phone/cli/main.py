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
import sys
from pathlib import Path

from core.cli_framework import CLIApp
from core.assistant import BaseAssistant

from ..helpers import LayoutLoadError, load_layout, read_yaml, write_yaml
from ..pipeline import (
    AnalyzeProducer,
    AnalyzeProcessor,
    AnalyzeRequest,
    AnalyzeRequestConsumer,
    ChecklistProducer,
    ChecklistProcessor,
    ChecklistRequest,
    ChecklistRequestConsumer,
    ExportDeviceProducer,
    ExportDeviceProcessor,
    ExportDeviceRequest,
    ExportDeviceRequestConsumer,
    ExportProducer,
    ExportProcessor,
    ExportRequest,
    ExportRequestConsumer,
    IconmapProducer,
    IconmapProcessor,
    IconmapRequest,
    IconmapRequestConsumer,
    IdentityVerifyProducer,
    IdentityVerifyProcessor,
    IdentityVerifyRequest,
    IdentityVerifyRequestConsumer,
    ManifestFromDeviceProducer,
    ManifestFromDeviceProcessor,
    ManifestFromDeviceRequest,
    ManifestFromDeviceRequestConsumer,
    ManifestFromExportProducer,
    ManifestFromExportProcessor,
    ManifestFromExportRequest,
    ManifestFromExportRequestConsumer,
    ManifestInstallProducer,
    ManifestInstallProcessor,
    ManifestInstallRequest,
    ManifestInstallRequestConsumer,
    PlanProducer,
    PlanProcessor,
    PlanRequest,
    PlanRequestConsumer,
    PruneProducer,
    PruneProcessor,
    PruneRequest,
    PruneRequestConsumer,
    UnusedProducer,
    UnusedProcessor,
    UnusedRequest,
    UnusedRequestConsumer,
)

from ..layout import (
    auto_folderize,
    distribute_folders_across_pages,
)
from ..profile import build_mobileconfig


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
    envelope = ExportProcessor().process(ExportRequestConsumer(request).consume())
    ExportProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 4))


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
    envelope = ExportDeviceProcessor().process(ExportDeviceRequestConsumer(request).consume())
    ExportDeviceProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 3))


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
    envelope = IconmapProcessor().process(IconmapRequestConsumer(request).consume())
    IconmapProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 3))


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
    envelope = PlanProcessor().process(PlanRequestConsumer(request).consume())
    PlanProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


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
    envelope = ChecklistProcessor().process(ChecklistRequestConsumer(request).consume())
    ChecklistProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


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
    envelope = UnusedProcessor().process(UnusedRequestConsumer(request).consume())
    UnusedProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


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
    envelope = PruneProcessor().process(PruneRequestConsumer(request).consume())
    PruneProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


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
    envelope = AnalyzeProcessor().process(AnalyzeRequestConsumer(request).consume())
    AnalyzeProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


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
    keep_csv = getattr(args, "keep", "") or ""
    keep = [s.strip() for s in keep_csv.split(",") if s.strip()]
    # Load existing plan or scaffold a fresh one
    if plan_path.exists():
        plan = read_yaml(plan_path)
    else:
        plan = {"pins": [], "folders": {}, "pages": {}}
    # Compute folders
    seed = plan.get("folders") or {}
    folders = auto_folderize(layout, keep=keep, seed_folders=seed)
    plan["folders"] = folders
    # Ensure Page 1 stays as-is if defined; place folder icons starting from specified page
    start_page = int(getattr(args, "place_folders_from_page", 2))
    per_page = int(getattr(args, "folders_per_page", 12))
    folder_names = [name for name, apps in folders.items() if apps]
    folder_names.sort()
    pages = plan.get("pages") or {}
    # Clear pages >= start_page, then repopulate with folders only
    for k in list(pages.keys()):
        try:
            if int(k) >= start_page:
                del pages[k]
        except (ValueError, TypeError):  # nosec B112 - skip non-integer page keys
            # Page key is not convertible to int (malformed data); skip and continue
            continue
    new_pages = distribute_folders_across_pages(folder_names, per_page=per_page, start_page=start_page)
    # Merge in new pages
    for k, v in new_pages.items():
        pages[k] = v
    plan["pages"] = pages
    # Write updated plan
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(plan, plan_path)
    print(f"Updated plan with auto-folders → {plan_path}")
    print(f"Folders: {len(folders)} (non-empty: {sum(1 for a in folders.values() if a)})")
    return 0


# --- Profile group commands ---

@profile_group.command("build", help="Build a .mobileconfig from a plan YAML")
@profile_group.argument("--plan", required=True, help="Plan YAML path (pins + folders)")
@profile_group.argument("--layout", help="Optional layout export YAML; uses 'dock' if present")
@profile_group.argument("--out", required=True, help="Output .mobileconfig path")
@profile_group.argument("--identifier", default="com.example.profile", help="Top-level PayloadIdentifier")
@profile_group.argument("--hs-identifier", default="com.example.hslayout", help="Home Screen PayloadIdentifier")
@profile_group.argument("--display-name", default="Home Screen Layout", help="Payload display name")
@profile_group.argument("--organization", help="Optional PayloadOrganization")
@profile_group.argument("--dock-count", type=int, default=4, help="Dock count from pins when --layout missing (default 4)")
@profile_group.argument("--all-apps-folder-name", help="Optional folder name for all remaining apps (requires --layout)")
@profile_group.argument("--all-apps-folder-page", type=int, help="Page number to place the all-apps folder (requires --layout)")
def cmd_profile_build(args) -> int:
    plan = read_yaml(Path(args.plan))

    layout_export = None
    if getattr(args, "layout", None):
        layout_export = read_yaml(Path(args.layout))

    all_apps_folder = None
    if getattr(args, "all_apps_folder_name", None) or getattr(args, "all_apps_folder_page", None) is not None:
        if not layout_export:
            print("Error: --all-apps-folder-* requires --layout to enumerate remaining apps", file=sys.stderr)
            return 2
        all_apps_folder = {
            "name": getattr(args, "all_apps_folder_name", None) or "All Apps",
        }
        if getattr(args, "all_apps_folder_page", None) is not None:
            all_apps_folder["page"] = args.all_apps_folder_page

    profile_dict = build_mobileconfig(
        plan=plan,
        layout_export=layout_export,
        top_identifier=getattr(args, "identifier", "com.example.profile"),
        hs_identifier=getattr(args, "hs_identifier", "com.example.hslayout"),
        display_name=getattr(args, "display_name", "Home Screen Layout"),
        organization=getattr(args, "organization", None),
        dock_count=max(0, int(getattr(args, "dock_count", 4))),
        all_apps_folder=all_apps_folder,
    )

    # Write plist as XML mobileconfig
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    import plistlib

    with out.open("wb") as f:
        plistlib.dump(profile_dict, f, fmt=plistlib.FMT_XML, sort_keys=False)
    print(f"Wrote Home Screen Layout profile to {out}")
    return 0


# --- Manifest group commands ---

@manifest_group.command("create", help="Create a manifest by embedding an existing plan")
@manifest_group.argument("--from-plan", required=True, help="Path to existing plan YAML to embed")
@manifest_group.argument("--out", required=True, help="Output manifest YAML path")
@manifest_group.argument("--label", help="Optional device label to include")
@manifest_group.argument("--udid", help="Optional device UDID to include")
@manifest_group.argument("--creds-profile", default=os.environ.get("IOS_CREDS_PROFILE", "ios_layout_manager"), help="Credentials profile name")
@manifest_group.argument("--layout", help="Optional layout export YAML path to include (for Dock inference)")
@manifest_group.argument("--identifier", default="com.example.profile", help="Profile identifier")
@manifest_group.argument("--hs-identifier", default="com.example.hslayout", help="Home Screen PayloadIdentifier")
@manifest_group.argument("--display-name", default="Home Screen Layout", help="Profile display name")
@manifest_group.argument("--organization", default="Personal", help="Profile organization")
def cmd_manifest_create(args) -> int:
    plan = read_yaml(Path(args.from_plan))
    manifest = {
        "meta": {"name": "ios_layout_manifest", "version": 1},
        "device": {
            "label": getattr(args, "label", None) or os.environ.get("IOS_DEVICE_LABEL"),
            "udid": getattr(args, "udid", None) or os.environ.get("IOS_DEVICE_UDID"),
            "creds_profile": getattr(args, "creds_profile", None) or os.environ.get("IOS_CREDS_PROFILE", "ios_layout_manager"),
        },
        "profile": {
            "identifier": getattr(args, "identifier", "com.example.profile"),
            "hs_identifier": getattr(args, "hs_identifier", "com.example.hslayout"),
            "display_name": getattr(args, "display_name", "Home Screen Layout"),
            "organization": getattr(args, "organization", "Personal"),
        },
        "plan": plan,
    }
    if getattr(args, "layout", None):
        manifest["layout_export_path"] = str(Path(args.layout))
    out = Path(args.out)
    write_yaml(manifest, out)
    print(f"Wrote manifest to {out}")
    return 0


@manifest_group.command("build-profile", help="Build a .mobileconfig from a manifest")
@manifest_group.argument("--manifest", required=True, help="Manifest YAML path")
@manifest_group.argument("--out", required=True, help="Output .mobileconfig path")
def cmd_manifest_build(args) -> int:
    mpath = Path(args.manifest)
    man = read_yaml(mpath)
    if not isinstance(man, dict) or "plan" not in man:
        print("Error: manifest missing 'plan' section", file=sys.stderr)
        return 2
    plan = man.get("plan") or {}
    layout_export = None
    lpath = man.get("layout_export_path")
    if lpath:
        try:
            layout_export = read_yaml(Path(lpath))
        except Exception:
            layout_export = None
    prof = man.get("profile") or {}
    profile_dict = build_mobileconfig(
        plan=plan,
        layout_export=layout_export,
        top_identifier=prof.get("identifier", "com.example.profile"),
        hs_identifier=prof.get("hs_identifier", "com.example.hslayout"),
        display_name=prof.get("display_name", "Home Screen Layout"),
        organization=prof.get("organization"),
        dock_count=4,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    import plistlib
    with out.open("wb") as f:
        plistlib.dump(profile_dict, f, fmt=plistlib.FMT_XML, sort_keys=False)
    print(f"Wrote Home Screen Layout profile to {out}")
    return 0


@manifest_group.command("from-export", help="Create a device layout manifest from a layout export YAML")
@manifest_group.argument("--export", required=True, help="Layout export YAML (from 'phone export-device' or legacy export')")
@manifest_group.argument("--out", required=True, help="Output manifest YAML path")
def cmd_manifest_from_export(args) -> int:
    request = ManifestFromExportRequest(
        export_path=Path(args.export),
        out_path=Path(args.out),
    )
    envelope = ManifestFromExportProcessor().process(ManifestFromExportRequestConsumer(request).consume())
    ManifestFromExportProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


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
    envelope = ManifestFromDeviceProcessor().process(ManifestFromDeviceRequestConsumer(request).consume())
    ManifestFromDeviceProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 3))


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
    envelope = ManifestInstallProcessor().process(ManifestInstallRequestConsumer(request).consume())
    ManifestInstallProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


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
    envelope = IdentityVerifyProcessor().process(IdentityVerifyRequestConsumer(request).consume())
    IdentityVerifyProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


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
