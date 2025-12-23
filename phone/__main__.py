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

import argparse
import sys
from pathlib import Path
from typing import Optional
import os
import subprocess

from core.assistant import BaseAssistant

from .helpers import LayoutLoadError, load_layout, read_lines_file, read_yaml, write_yaml
from .pipeline import (
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

from .layout import (
    normalize_iconstate,
    to_yaml_export,
    scaffold_plan,
    checklist_from_plan,
    auto_folderize,
    distribute_folders_across_pages,
)
from .profile import build_mobileconfig


def cmd_export(args: argparse.Namespace) -> int:
    print("Deprecated: 'phone export' uses Finder backups. Use 'phone export-device' or 'phone iconmap'.", file=sys.stderr)
    out_path = Path(args.out or "out/ios.IconState.yaml")
    request = ExportRequest(backup=args.backup, out_path=out_path)
    envelope = ExportProcessor().process(ExportRequestConsumer(request).consume())
    ExportProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 4))


def cmd_plan(args: argparse.Namespace) -> int:
    out_path = Path(args.out or "out/ios.plan.yaml")
    request = PlanRequest(layout=args.layout, backup=args.backup, out_path=out_path)
    envelope = PlanProcessor().process(PlanRequestConsumer(request).consume())
    PlanProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


def cmd_checklist(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan)
    out_path = Path(args.out or "out/ios.checklist.txt")
    request = ChecklistRequest(
        plan_path=plan_path,
        layout=args.layout,
        backup=args.backup,
        out_path=out_path,
    )
    envelope = ChecklistProcessor().process(ChecklistRequestConsumer(request).consume())
    ChecklistProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


def cmd_unused(args: argparse.Namespace) -> int:
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


def cmd_prune(args: argparse.Namespace) -> int:
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

def cmd_profile_build(args: argparse.Namespace) -> int:
    plan = read_yaml(Path(args.plan))

    layout_export = None
    if args.layout:
        layout_export = read_yaml(Path(args.layout))

    all_apps_folder = None
    if args.all_apps_folder_name or args.all_apps_folder_page is not None:
        if not layout_export:
            print("Error: --all-apps-folder-* requires --layout to enumerate remaining apps", file=sys.stderr)
            return 2
        all_apps_folder = {
            "name": args.all_apps_folder_name or "All Apps",
        }
        if args.all_apps_folder_page is not None:
            all_apps_folder["page"] = args.all_apps_folder_page

    profile_dict = build_mobileconfig(
        plan=plan,
        layout_export=layout_export,
        top_identifier=args.identifier,
        hs_identifier=args.hs_identifier,
        display_name=args.display_name,
        organization=args.organization,
        dock_count=max(0, int(args.dock_count)),
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


def cmd_analyze(args: argparse.Namespace) -> int:
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


def cmd_auto_folders(args: argparse.Namespace) -> int:
    try:
        layout = load_layout(getattr(args, "layout", None), getattr(args, "backup", None))
    except LayoutLoadError as err:
        print(err, file=sys.stderr)
        return err.code
    plan_path = Path(getattr(args, 'plan', 'out/ipad.plan.yaml'))
    keep_csv = getattr(args, 'keep', '') or ''
    keep = [s.strip() for s in keep_csv.split(',') if s.strip()]
    # Load existing plan or scaffold a fresh one
    if plan_path.exists():
        plan = read_yaml(plan_path)
    else:
        plan = {'pins': [], 'folders': {}, 'pages': {}}
    # Compute folders
    seed = plan.get('folders') or {}
    folders = auto_folderize(layout, keep=keep, seed_folders=seed)
    plan['folders'] = folders
    # Ensure Page 1 stays as-is if defined; place folder icons starting from specified page
    start_page = int(getattr(args, 'place_folders_from_page', 2))
    per_page = int(getattr(args, 'folders_per_page', 12))
    folder_names = [name for name, apps in folders.items() if apps]
    folder_names.sort()
    pages = plan.get('pages') or {}
    # Clear pages >= start_page, then repopulate with folders only
    for k in list(pages.keys()):
        try:
            if int(k) >= start_page:
                del pages[k]
        except Exception:
            continue
    new_pages = distribute_folders_across_pages(folder_names, per_page=per_page, start_page=start_page)
    # Merge in new pages
    for k, v in new_pages.items():
        pages[k] = v
    plan['pages'] = pages
    # Write updated plan
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(plan, plan_path)
    print(f"Updated plan with auto-folders → {plan_path}")
    print(f"Folders: {len(folders)} (non-empty: {sum(1 for a in folders.values() if a)})")
    return 0


assistant = BaseAssistant(
    "phone",
    "agentic: phone\npurpose: Home Screen layout planning + manifest helpers",
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Phone Assistant CLI")
    assistant.add_agentic_flags(p)
    sub = p.add_subparsers(dest="command")

    p_exp = sub.add_parser("export", help="DEPRECATED: export layout from Finder backup to YAML")
    p_exp.add_argument("--backup", help="Path to Finder backup UDID dir (defaults to latest under MobileSync/Backup)")
    p_exp.add_argument("--out", help="Output YAML path (default out/ios.IconState.yaml)")
    p_exp.set_defaults(func=cmd_export)

    p_exp_dev = sub.add_parser("export-device", help="Export layout from attached device via cfgutil to YAML")
    p_exp_dev.add_argument("--udid", help="Device UDID (optional when only one device is attached)")
    p_exp_dev.add_argument("--ecid", help="Device ECID (optional; overrides --udid)")
    p_exp_dev.add_argument("--out", help="Output YAML path (default out/ios.IconState.yaml)")
    p_exp_dev.set_defaults(func=cmd_export_device)

    p_icon = sub.add_parser("iconmap", help="Download raw icon layout from device via cfgutil")
    p_icon.add_argument("--udid", help="Device UDID (optional when only one device is attached)")
    p_icon.add_argument("--ecid", help="Device ECID (optional; overrides --udid)")
    p_icon.add_argument("--format", choices=["json", "plist"], default="json", help="Output format (default json)")
    p_icon.add_argument("--out", help="Output path (default out/ios.iconmap.json or .plist)")
    p_icon.set_defaults(func=cmd_iconmap)

    p_plan = sub.add_parser("plan", help="Scaffold a plan YAML (pins + folders) from current layout")
    p_plan.add_argument("--backup", help="Path to Finder backup UDID dir (or use --layout)")
    p_plan.add_argument("--layout", help="Existing export YAML to derive plan from (skips backup)")
    p_plan.add_argument("--out", help="Output plan YAML path (default out/ios.plan.yaml)")
    p_plan.set_defaults(func=cmd_plan)

    p_list = sub.add_parser("checklist", help="Generate manual move checklist from plan + current layout")
    p_list.add_argument("--plan", required=True, help="Plan YAML path")
    p_list.add_argument("--layout", help="Layout export YAML (optional; otherwise reads backup)")
    p_list.add_argument("--backup", help="Path to Finder backup UDID dir (used if --layout not provided)")
    p_list.add_argument("--out", help="Output text path (default out/ios.checklist.txt)")
    p_list.set_defaults(func=cmd_checklist)

    # unused analysis
    p_unused = sub.add_parser("unused", help="Suggest rarely-used app candidates from current layout (heuristic)")
    p_unused.add_argument("--layout", help="Layout export YAML (optional; otherwise reads backup)")
    p_unused.add_argument("--backup", help="Path to Finder backup UDID dir (used if --layout not provided)")
    p_unused.add_argument("--recent", help="Path to file with bundle IDs used recently (one per line)")
    p_unused.add_argument("--keep", help="Path to file with bundle IDs to always keep (one per line)")
    p_unused.add_argument("--limit", type=int, default=50, help="Max rows to display (default 50)")
    p_unused.add_argument("--format", choices=["text", "csv"], default="text", help="Output format (default text)")
    p_unused.set_defaults(func=cmd_unused)

    # prune checklist (offload/delete)
    p_prune = sub.add_parser("prune", help="Generate OFFLOAD/DELETE checklist for unused candidates (no device writes)")
    p_prune.add_argument("--layout", help="Layout export YAML (optional; otherwise reads backup)")
    p_prune.add_argument("--backup", help="Path to Finder backup UDID dir (used if --layout not provided)")
    p_prune.add_argument("--recent", help="Path to file with bundle IDs used recently (one per line)")
    p_prune.add_argument("--keep", help="Path to file with bundle IDs to always keep (one per line)")
    p_prune.add_argument("--limit", type=int, default=50, help="Max rows to include (default 50)")
    p_prune.add_argument("--threshold", type=float, default=1.0, help="Minimum score to include (default 1.0)")
    p_prune.add_argument("--mode", choices=["offload", "delete"], default="offload", help="Checklist mode (default offload)")
    p_prune.add_argument("--out", default="out/ios.unused.prune_checklist.txt", help="Output text file (default out/ios.unused.prune_checklist.txt)")
    p_prune.set_defaults(func=cmd_prune)

    # profile build: generate Home Screen Layout .mobileconfig from plan (and optional layout for dock)
    p_prof = sub.add_parser("profile", help="Home Screen Layout profile helpers")
    sub_prof = p_prof.add_subparsers(dest="profile_cmd")

    p_prof_b = sub_prof.add_parser("build", help="Build a .mobileconfig from a plan YAML")
    p_prof_b.add_argument("--plan", required=True, help="Plan YAML path (pins + folders)")
    p_prof_b.add_argument("--layout", help="Optional layout export YAML; uses 'dock' if present")
    p_prof_b.add_argument("--out", required=True, help="Output .mobileconfig path")
    p_prof_b.add_argument("--identifier", default="com.example.profile", help="Top-level PayloadIdentifier (default: com.example.profile)")
    p_prof_b.add_argument("--hs-identifier", default="com.example.hslayout", help="Home Screen PayloadIdentifier (default: com.example.hslayout)")
    p_prof_b.add_argument("--display-name", default="Home Screen Layout", help="Payload display name")
    p_prof_b.add_argument("--organization", help="Optional PayloadOrganization")
    p_prof_b.add_argument("--dock-count", type=int, default=4, help="Dock count from pins when --layout missing (default 4)")
    p_prof_b.add_argument("--all-apps-folder-name", help="Optional folder name for all remaining apps (requires --layout)")
    p_prof_b.add_argument("--all-apps-folder-page", type=int, help="Page number to place the all-apps folder (requires --layout)")
    p_prof_b.set_defaults(func=cmd_profile_build)

    # analyze layout
    p_an = sub.add_parser("analyze", help="Analyze layout balance and folder structure (text/json)")
    p_an.add_argument("--layout", help="Layout export YAML (optional; otherwise reads backup)")
    p_an.add_argument("--backup", help="Path to Finder backup UDID dir (used if --layout not provided)")
    p_an.add_argument("--plan", help="Optional plan YAML to check pins/folders alignment")
    p_an.add_argument("--format", choices=["text", "json"], default="text", help="Output format (default text)")
    p_an.set_defaults(func=cmd_analyze)

    # auto-folders: assign all apps to folders and update/write plan
    p_auto = sub.add_parser("auto-folders", help="Auto-assign all apps into folders in plan (keeps specified apps out)")
    p_auto.add_argument("--layout", help="Layout export YAML (optional; otherwise reads backup)")
    p_auto.add_argument("--backup", help="Path to Finder backup UDID dir (used if --layout not provided)")
    p_auto.add_argument("--plan", default="out/ipad.plan.yaml", help="Plan YAML path to read/update (default out/ipad.plan.yaml)")
    p_auto.add_argument("--keep", default="com.apple.mobilesafari,com.apple.Preferences", help="Comma-separated bundle IDs to keep out of folders")
    p_auto.add_argument("--place-folders-from-page", type=int, default=2, help="Start placing folders from this page (default 2)")
    p_auto.add_argument("--folders-per-page", type=int, default=12, help="Max folders per page (default 12)")
    p_auto.set_defaults(func=cmd_auto_folders)

    # manifest helpers
    p_m = sub.add_parser("manifest", help="Simplified manifest helpers (embed complex plan)")
    sub_m = p_m.add_subparsers(dest="manifest_cmd")

    p_mk = sub_m.add_parser("create", help="Create a manifest by embedding an existing plan")
    p_mk.add_argument("--from-plan", required=True, help="Path to existing plan YAML to embed")
    p_mk.add_argument("--out", required=True, help="Output manifest YAML path")
    p_mk.add_argument("--label", help="Optional device label to include")
    p_mk.add_argument("--udid", help="Optional device UDID to include")
    p_mk.add_argument("--creds-profile", default=os.environ.get("IOS_CREDS_PROFILE", "ios_layout_manager"), help="Credentials profile name (default from IOS_CREDS_PROFILE or ios_layout_manager)")
    p_mk.add_argument("--layout", help="Optional layout export YAML path to include (for Dock inference)")
    p_mk.add_argument("--identifier", default="com.example.profile", help="Profile identifier (default com.example.profile)")
    p_mk.add_argument("--hs-identifier", default="com.example.hslayout", help="Home Screen PayloadIdentifier (default com.example.hslayout)")
    p_mk.add_argument("--display-name", default="Home Screen Layout", help="Profile display name")
    p_mk.add_argument("--organization", default="Personal", help="Profile organization")
    p_mk.set_defaults(func=cmd_manifest_create)

    p_mb = sub_m.add_parser("build-profile", help="Build a .mobileconfig from a manifest")
    p_mb.add_argument("--manifest", required=True, help="Manifest YAML path")
    p_mb.add_argument("--out", required=True, help="Output .mobileconfig path")
    p_mb.set_defaults(func=cmd_manifest_build)

    p_mr = sub_m.add_parser("from-export", help="Create a device layout manifest from a layout export YAML")
    p_mr.add_argument("--export", required=True, help="Layout export YAML (from 'phone export-device' or legacy export')")
    p_mr.add_argument("--out", required=True, help="Output manifest YAML path")
    p_mr.set_defaults(func=cmd_manifest_from_export)

    p_md = sub_m.add_parser("from-device", help="Create a device layout manifest from an attached device via cfgutil")
    p_md.add_argument("--out", required=True, help="Output manifest YAML path")
    p_md.add_argument("--export-out", help="Optional export YAML to also write (dock/pages)")
    p_md.add_argument("--udid", help="Device UDID (optional when only one device is attached)")
    p_md.set_defaults(func=cmd_manifest_from_device)

    p_mi = sub_m.add_parser("install", help="Build and install a profile from a manifest (hands-off via credentials)")
    p_mi.add_argument("--manifest", required=True, help="Manifest YAML path")
    p_mi.add_argument("--out", help="Output .mobileconfig path (default under out/)")
    p_mi.add_argument("--udid", help="Override device UDID (else manifest.device.udid or env)")
    p_mi.add_argument("--device-label", help="Override device label (else manifest.device.label or env)")
    p_mi.add_argument("--creds-profile", help="Override credentials profile (else manifest.device.creds_profile or IOS_CREDS_PROFILE)"
                     )
    p_mi.add_argument("--config", help="credentials.ini path override (optional)")
    p_mi.add_argument("--dry-run", action="store_true", help="Print actions only; do not install")
    p_mi.set_defaults(func=cmd_manifest_install)

    # identity helpers
    p_id = sub.add_parser("identity", help="Identity helpers (p12 ↔ device supervision parity)")
    sub_id = p_id.add_subparsers(dest="identity_cmd")

    p_idv = sub_id.add_parser("verify", help="Verify .p12 identity vs device supervision")
    p_idv.add_argument("--p12", help="Path to Supervision Identity .p12 (optional; else reads credentials.ini)")
    p_idv.add_argument("--pass", dest="p12_pass", help="Password for .p12 (optional; else reads credentials.ini)")
    p_idv.add_argument("--creds-profile", default=os.environ.get("IOS_CREDS_PROFILE", "ios_layout_manager"), help="Credentials profile name (default from IOS_CREDS_PROFILE or ios_layout_manager)")
    p_idv.add_argument("--config", help="Path to credentials.ini (optional)")
    p_idv.add_argument("--device-label", help="Device label to resolve UDID from credentials.ini [ios_devices]")
    p_idv.add_argument("--udid", help="Device UDID (optional)")
    p_idv.add_argument("--expected-org", help="Expected organization name to match certificate subject/issuer (optional)")
    p_idv.set_defaults(func=cmd_identity_verify)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    # Install conservative secret shielding for stdout/stderr (env-toggled)
    try:
        from mail_assistant.utils.secrets import install_output_masking_from_env as _install_mask  # reuse module
        _install_mask()
    except Exception:
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    agentic_result = assistant.maybe_emit_agentic(
        args, emit_func=lambda fmt, compact: _lazy_agentic()(fmt, compact)
    )
    if agentic_result is not None:
        return agentic_result
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return int(args.func(args))


def cmd_manifest_create(args: argparse.Namespace) -> int:
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


def cmd_manifest_build(args: argparse.Namespace) -> int:
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


def cmd_manifest_from_export(args: argparse.Namespace) -> int:
    request = ManifestFromExportRequest(
        export_path=Path(args.export),
        out_path=Path(args.out),
    )
    envelope = ManifestFromExportProcessor().process(ManifestFromExportRequestConsumer(request).consume())
    ManifestFromExportProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


def cmd_export_device(args: argparse.Namespace) -> int:
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


def cmd_iconmap(args: argparse.Namespace) -> int:
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


def cmd_manifest_from_device(args: argparse.Namespace) -> int:
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


def cmd_manifest_install(args: argparse.Namespace) -> int:
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


def cmd_identity_verify(args: argparse.Namespace) -> int:
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


if __name__ == "__main__":
    raise SystemExit(main())
