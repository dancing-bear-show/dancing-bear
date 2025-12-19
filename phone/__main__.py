"""Phone Assistant CLI

Commands:
  export   — Read latest Finder backup and export layout to YAML
  plan     — Scaffold a plan (pins + folders) from current layout
  checklist— Generate manual move instructions from plan

All processing is local and read-only. No device writes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional
import os
import subprocess

from personal_core.assistant import BaseAssistant

from .helpers import LayoutLoadError, load_layout, read_lines_file, read_yaml, write_yaml
from .pipeline import (
    ChecklistProducer,
    ChecklistProcessor,
    ChecklistRequest,
    ChecklistRequestConsumer,
    ExportProducer,
    ExportProcessor,
    ExportRequest,
    ExportRequestConsumer,
    PlanProducer,
    PlanProcessor,
    PlanRequest,
    PlanRequestConsumer,
)

from .layout import (
    normalize_iconstate,
    to_yaml_export,
    scaffold_plan,
    checklist_from_plan,
    rank_unused_candidates,
    analyze_layout,
    auto_folderize,
    distribute_folders_across_pages,
)
from .profile import build_mobileconfig


def cmd_export(args: argparse.Namespace) -> int:
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
    try:
        layout = load_layout(getattr(args, "layout", None), getattr(args, "backup", None))
    except LayoutLoadError as err:
        print(err, file=sys.stderr)
        return err.code
    recent = read_lines_file(getattr(args, "recent", None))
    keep = read_lines_file(getattr(args, "keep", None))
    rows = rank_unused_candidates(layout, recent_ids=recent, keep_ids=keep)
    rows = [r for r in rows if r[1] >= 0.8][: int(getattr(args, "limit", 50))]
    if getattr(args, "format", "text") == "csv":
        out_lines = ["app,score,location"]
        out_lines.extend([f"{a},{score:.2f},{loc}" for a, score, loc in rows])
        print("\n".join(out_lines))
        return 0
    # text table-ish
    print("Likely unused app candidates (heuristic):")
    print("score  app                                   location")
    for a, score, loc in rows:
        print(f"{score:4.1f}  {a:36}  {loc}")
    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    try:
        layout = load_layout(getattr(args, "layout", None), getattr(args, "backup", None))
    except LayoutLoadError as err:
        print(err, file=sys.stderr)
        return err.code
    recent = read_lines_file(getattr(args, "recent", None))
    keep = read_lines_file(getattr(args, "keep", None))
    rows = rank_unused_candidates(layout, recent_ids=recent, keep_ids=keep)
    thr = float(getattr(args, "threshold", 1.0))
    rows = [r for r in rows if r[1] >= thr][: int(getattr(args, "limit", 50))]
    mode = getattr(args, "mode", "offload")
    out = Path(getattr(args, "out", "out/ios.unused.prune_checklist.txt"))
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append(f"Unused apps checklist — mode: {mode.upper()}")
    lines.append("")
    lines.append("Instructions:")
    if mode == "offload":
        lines.append("1) Settings → General → iPhone Storage → search for app → Offload App")
        lines.append("   or long‑press app icon → Remove App → Offload App")
    else:
        lines.append("1) Long‑press app icon → Remove App → Delete App")
        lines.append("   or Settings → General → iPhone Storage → Delete App")
    lines.append("")
    lines.append("Candidates:")
    for a, score, loc in rows:
        lines.append(f"- {a}  (score {score:.1f}; location: {loc})")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {mode} checklist to {out}")
    return 0

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
    try:
        layout = load_layout(getattr(args, "layout", None), getattr(args, "backup", None))
    except LayoutLoadError as err:
        print(err, file=sys.stderr)
        return err.code
    plan = None
    if getattr(args, "plan", None):
        plan = read_yaml(Path(args.plan))
    metrics = analyze_layout(layout, plan)
    fmt = getattr(args, "format", "text")
    if fmt == "json":
        import json as _json
        print(_json.dumps(metrics, indent=2))
        return 0
    # text output
    print("Layout Summary")
    print(f"Dock: {metrics['dock_count']} apps")
    if metrics.get("dock"):
        print("  - " + ", ".join(metrics["dock"]))
    print(f"Pages: {metrics['pages_count']}")
    for p in metrics.get("pages", []):
        print(f"  Page {p['page']}: {p['root_apps']} apps, {p['folders']} folders (items {p['items_total']})")
    print(f"Folders: {metrics['totals']['folders']}")
    if metrics.get("folders"):
        # show top 5 by app_count
        top = sorted(metrics["folders"], key=lambda x: x.get("app_count", 0), reverse=True)[:5]
        for f in top:
            print(f"  - {f['name']} (page {f['page']}, {f['app_count']} apps)")
    if metrics.get("duplicates"):
        print("Duplicates:")
        for a in metrics["duplicates"]:
            print(f"  - {a}")
    if metrics.get("observations"):
        print("Observations:")
        for o in metrics["observations"]:
            print(f"- {o}")
    return 0


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

    p_exp = sub.add_parser("export", help="Export current Home Screen layout from Finder backup to YAML")
    p_exp.add_argument("--backup", help="Path to Finder backup UDID dir (defaults to latest under MobileSync/Backup)")
    p_exp.add_argument("--out", help="Output YAML path (default out/ios.IconState.yaml)")
    p_exp.set_defaults(func=cmd_export)

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
    p_mr.add_argument("--export", required=True, help="Layout export YAML (from 'phone export')")
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
    exp = read_yaml(Path(args.export))
    if not isinstance(exp, dict) or 'dock' not in exp or 'pages' not in exp:
        print("Error: export file must contain 'dock' and 'pages' keys", file=sys.stderr)
        return 2
    dock = list(exp.get('dock') or [])
    pages_in = exp.get('pages') or []
    pages_out = []
    all_apps = []
    seen = set()
    folders_total = 0
    for p in pages_in:
        apps = list(p.get('apps') or [])
        folders = []
        for f in p.get('folders') or []:
            name = f.get('name') or 'Folder'
            fapps = list(f.get('apps') or [])
            folders.append({'name': name, 'apps': fapps})
            folders_total += 1
        pages_out.append({'apps': apps, 'folders': folders})
        for a in apps:
            if a and a not in seen:
                seen.add(a); all_apps.append(a)
        for f in folders:
            for a in f['apps']:
                if a and a not in seen:
                    seen.add(a); all_apps.append(a)
    for a in dock:
        if a and a not in seen:
            seen.add(a); all_apps.append(a)
    manifest = {
        'meta': {'name': 'device_layout_manifest', 'version': 1},
        'device': {'udid': os.environ.get('IOS_DEVICE_UDID'), 'label': os.environ.get('IOS_DEVICE_LABEL')},
        'layout': {'dock': dock, 'pages': pages_out},
        'apps': {'all': all_apps},
        'counts': {'apps_total': len(all_apps), 'pages_count': len(pages_out), 'folders_count': folders_total},
        'source': {'export_path': str(Path(args.export))},
    }
    out = Path(args.out)
    write_yaml(manifest, out)
    print(f"Wrote device layout manifest to {out}")
    return 0


def _find_cfgutil_path() -> str:
    # Prefer PATH
    from shutil import which
    p = which("cfgutil")
    if p:
        return p
    # Fallback to app bundle path
    alt = "/Applications/Apple Configurator.app/Contents/MacOS/cfgutil"
    if Path(alt).exists():
        return alt
    raise FileNotFoundError("cfgutil not found; install Apple Configurator or add cfgutil to PATH")


def _map_udid_to_ecid(cfgutil: str, udid: str) -> str:
    import subprocess as _sp
    try:
        out = _sp.check_output([cfgutil, "list"], stderr=_sp.STDOUT, text=True)
    except Exception as e:
        raise RuntimeError(f"cfgutil list failed: {e}")
    for line in out.splitlines():
        if "UDID:" in line and udid in line:
            # Extract ECID token (after 'ECID:')
            parts = line.split()
            for i, tok in enumerate(parts):
                if tok.startswith("ECID:"):
                    # token may be 'ECID:' then value next, or 'ECID:0x...'
                    if tok == "ECID:":
                        if i + 1 < len(parts):
                            return parts[i + 1]
                    else:
                        return tok.split(":", 1)[1]
    return ""


def _export_from_device(cfgutil: str, ecid: str | None = None) -> dict:
    import subprocess as _sp
    import plistlib as _plist
    cmd = [cfgutil]
    if ecid:
        cmd.extend(["--ecid", ecid])
    cmd.extend(["--format", "plist", "get-icon-layout"])
    try:
        out = _sp.check_output(cmd, stderr=_sp.DEVNULL)
    except Exception as e:
        raise RuntimeError(f"cfgutil get-icon-layout failed: {e}")
    try:
        data = _plist.loads(out)
    except Exception as e:
        raise RuntimeError(f"Failed to parse plist from cfgutil: {e}")
    # Try to convert into our export shape via normalize_iconstate if compatible
    export: dict[str, object] = {}
    try:
        layout = normalize_iconstate(data)  # type: ignore[arg-type]
        export = to_yaml_export(layout)
    except Exception:
        # Best-effort fallback: attempt to map common keys
        dock = []
        pages = []
        try:
            # Some cfgutil plists carry similar keys as backups
            for it in (data.get("buttonBar") or []):  # type: ignore[attr-defined]
                bid = it.get("bundleIdentifier") or it.get("displayIdentifier")
                if bid:
                    dock.append(bid)
            for page in (data.get("iconLists") or []):  # type: ignore[attr-defined]
                page_out = {"apps": [], "folders": []}
                for it in (page or []):
                    if isinstance(it, dict) and ("iconLists" in it) and ("displayName" in it):
                        name = it.get("displayName") or "Folder"
                        flist = []
                        for sub in (it.get("iconLists") or [[]])[0]:
                            bid = sub.get("bundleIdentifier") or sub.get("displayIdentifier")
                            if bid:
                                flist.append(bid)
                        page_out["folders"].append({"name": name, "apps": flist})  # type: ignore[index]
                    else:
                        bid = it.get("bundleIdentifier") or it.get("displayIdentifier") if isinstance(it, dict) else None
                        if bid:
                            page_out["apps"].append(bid)  # type: ignore[index]
                pages.append(page_out)
            export = {"dock": dock, "pages": pages}
        except Exception:
            export = {}
    return export


def cmd_manifest_from_device(args: argparse.Namespace) -> int:
    cfg = _find_cfgutil_path()
    udid = getattr(args, "udid", None) or os.environ.get("IOS_DEVICE_UDID")
    ecid = _map_udid_to_ecid(cfg, udid) if udid else None
    exp = _export_from_device(cfg, ecid)
    if not exp:
        print("Error: could not derive export from device layout", file=sys.stderr)
        return 3
    # Optionally write export YAML
    if getattr(args, "export_out", None):
        write_yaml(exp, Path(args.export_out))
    # Build the same manifest as from-export
    class _Args:
        export: str
        out: str
    tmp = _Args()
    tmp.export = str(Path(args.export_out) if getattr(args, "export_out", None) else Path("out/device.IconState.yaml"))
    # Ensure we have a path for export if not written
    if not getattr(args, "export_out", None):
        # Write to out/device.IconState.yaml
        out_path = Path("out/device.IconState.yaml")
        write_yaml(exp, out_path)
        tmp.export = str(out_path)
    tmp.out = getattr(args, "out")
    return cmd_manifest_from_export(tmp)  # type: ignore[arg-type]


def _plan_from_layout(layout_obj: dict) -> dict:
    plan: dict = {"dock": list(layout_obj.get("dock") or []), "pages": {}, "folders": {}}
    pages = layout_obj.get("pages") or []
    page_map: dict[int, dict] = {}
    for idx, p in enumerate(pages, start=1):
        apps = list(p.get("apps") or [])
        folders = []
        for f in p.get("folders") or []:
            name = f.get("name") or "Folder"
            fapps = list(f.get("apps") or [])
            plan["folders"][name] = fapps
            folders.append(name)
        page_map[idx] = {"apps": apps, "folders": folders}
    plan["pages"] = page_map
    return plan


def cmd_manifest_install(args: argparse.Namespace) -> int:
    mpath = Path(args.manifest)
    man = read_yaml(mpath)
    if not isinstance(man, dict):
        print("Error: invalid manifest", file=sys.stderr)
        return 2
    # Build plan from manifest
    plan = man.get("plan") or {}
    if not plan and man.get("layout"):
        plan = _plan_from_layout(man.get("layout") or {})
    if not plan:
        print("Error: manifest missing 'plan' or 'layout' section", file=sys.stderr)
        return 2
    prof = man.get("profile") or {}
    layout_export = None  # plan contains dock/pages; no need for export
    profile_dict = build_mobileconfig(
        plan=plan,
        layout_export=layout_export,
        top_identifier=prof.get("identifier", "com.example.profile"),
        hs_identifier=prof.get("hs_identifier", "com.example.hslayout"),
        display_name=prof.get("display_name", "Home Screen Layout"),
        organization=prof.get("organization"),
        dock_count=4,
    )
    # Determine output profile path
    _out_s = getattr(args, "out", None) or ""
    if _out_s:
        out_path = Path(_out_s)
    else:
        dev = man.get("device") or {}
        suffix = dev.get("label") or dev.get("udid") or "device"
        out_path = Path("out") / f"{suffix}.hslayout.from_manifest.mobileconfig"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import plistlib
    with out_path.open("wb") as f:
        plistlib.dump(profile_dict, f, fmt=plistlib.FMT_XML, sort_keys=False)
    print(f"Built profile: {out_path}")

    if getattr(args, "dry_run", False):
        print("Dry-run: skipping install")
        return 0

    # Resolve install parameters
    dev = man.get("device") or {}
    udid = getattr(args, "udid", None) or dev.get("udid") or os.environ.get("IOS_DEVICE_UDID")
    label = getattr(args, "device_label", None) or dev.get("label") or os.environ.get("IOS_DEVICE_LABEL")
    creds_profile = getattr(args, "creds_profile", None) or dev.get("creds_profile") or os.environ.get("IOS_CREDS_PROFILE")
    # Build install command
    repo_root = Path(__file__).resolve().parents[1]
    installer = str(repo_root / "bin" / "ios-install-profile")
    cmd = [installer, "--profile", str(out_path)]
    if creds_profile:
        cmd.extend(["--creds-profile", creds_profile])
    if getattr(args, "config", None):
        cmd.extend(["--config", str(getattr(args, "config"))])
    if udid:
        cmd.extend(["--udid", udid])
    elif label:
        cmd.extend(["--device-label", label])
    print("Installing via:", " ".join(cmd))
    try:
        rc = subprocess.call(cmd)
    except FileNotFoundError:
        print("Error: ios-install-profile not found", file=sys.stderr)
        return 127
    return int(rc)


def _read_credentials_ini(explicit: str | None = None) -> tuple[str | None, dict]:
    """Return (path, mapping) for credentials.ini if found."""
    cand: list[str] = []
    if explicit:
        cand.append(explicit)
    envp = os.environ.get("CREDENTIALS")
    if envp:
        cand.append(envp)
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config"))
    cand.extend([
        os.path.join(xdg, "credentials.ini"),
        os.path.join(os.path.expanduser("~"), ".config", "credentials.ini"),
        os.path.join(xdg, "sre-utils", "credentials.ini"),
        os.path.join(os.path.expanduser("~"), ".config", "sre-utils", "credentials.ini"),
        os.path.join(os.path.expanduser("~"), ".config", "sreutils", "credentials.ini"),
        os.path.join(os.path.expanduser("~"), ".sre-utils", "credentials.ini"),
    ])
    for p in cand:
        if p and os.path.exists(p):
            # Minimal INI reader
            import configparser
            cp = configparser.ConfigParser()
            cp.read(p)
            data = {s: dict(cp.items(s)) for s in cp.sections()}
            return p, data
    return None, {}


def cmd_identity_verify(args: argparse.Namespace) -> int:
    # Resolve p12
    p12_path = getattr(args, "p12", None)
    p12_pass = getattr(args, "p12_pass", None)
    cfg_path, ini = _read_credentials_ini(getattr(args, "config", None))
    prof = getattr(args, "creds_profile", os.environ.get("IOS_CREDS_PROFILE", "ios_layout_manager"))
    if not p12_path and prof in ini:
        sec = ini[prof]
        p12_path = sec.get("supervision_identity_p12") or sec.get("ios_home_layout_identity_p12") or sec.get("supervision_p12")
        p12_pass = p12_pass or sec.get("supervision_identity_pass") or sec.get("ios_home_layout_identity_pass") or sec.get("supervision_p12_pass")
    # Expand ~
    if p12_path and p12_path.startswith("~/"):
        p12_path = os.path.join(os.path.expanduser("~"), p12_path[2:])
    # Extract cert subject/issuer
    cert_subject = ""
    cert_issuer = ""
    if not p12_path or not os.path.exists(p12_path):
        print("Error: .p12 path not provided or not found (use --p12 or credentials.ini)", file=sys.stderr)
        return 2
    import subprocess as _sp
    # Extract cert PEM with -legacy for OpenSSL 3
    cert_pem = None
    try:
        cmd = ["openssl", "pkcs12", "-legacy", "-in", p12_path, "-clcerts", "-nokeys"]
        if p12_pass:
            cmd.extend(["-passin", f"pass:{p12_pass}"])
        cert_pem = _sp.check_output(cmd, stderr=_sp.DEVNULL)
    except Exception:
        try:
            cmd = ["openssl", "pkcs12", "-in", p12_path, "-clcerts", "-nokeys"]
            if p12_pass:
                cmd.extend(["-passin", f"pass:{p12_pass}"])
            cert_pem = _sp.check_output(cmd, stderr=_sp.DEVNULL)
        except Exception as e:
            print(f"Error: failed to extract certificate from {p12_path}: {e}", file=sys.stderr)
            return 3
    try:
        subj = _sp.check_output(["openssl", "x509", "-noout", "-subject"], input=cert_pem, stderr=_sp.DEVNULL)
        iss = _sp.check_output(["openssl", "x509", "-noout", "-issuer"], input=cert_pem, stderr=_sp.DEVNULL)
        cert_subject = subj.decode().strip().replace("subject=", "")
        cert_issuer = iss.decode().strip().replace("issuer=", "")
    except Exception:
        pass

    # Device supervision status
    cfg = _find_cfgutil_path()
    udid = getattr(args, "udid", None)
    if not udid:
        lbl = getattr(args, "device_label", None) or os.environ.get("IOS_DEVICE_LABEL")
        if lbl and cfg_path and os.path.exists(cfg_path):
            # map label to UDID
            import configparser
            cp = configparser.ConfigParser()
            cp.read(cfg_path)
            if cp.has_section("ios_devices") and cp.has_option("ios_devices", lbl):
                udid = cp.get("ios_devices", lbl)
    supervised = None
    try:
        out = _sp.check_output([cfg, "get", "Supervised"], stderr=_sp.DEVNULL, text=True)
        if "Supervised:" in out:
            supervised = out.split(":", 1)[1].strip()
    except Exception:
        pass

    print("Identity Verification Summary")
    print(f"- p12: {p12_path}")
    print(f"- cert.subject: {cert_subject or '(unknown)'}")
    print(f"- cert.issuer:  {cert_issuer or '(unknown)'}")
    if getattr(args, "expected_org", None):
        exp = getattr(args, "expected_org")
        ok = (exp in cert_subject) or (exp in cert_issuer)
        print(f"- expected org '{exp}': {'MATCH' if ok else 'NO MATCH'}")
    print(f"- device.udid: {udid or '(not provided)'}")
    print(f"- device.supervised: {supervised if supervised is not None else '(unknown)'}")
    print("")
    print("Next steps:")
    print("- Ensure the device shows 'Supervised by <Org>' matching the certificate subject/issuer above.")
    print("- If they match, no-touch installs should succeed using this identity.")
    print("- If they do not match, Prepare again under the correct Organization, or export the matching Supervision Identity.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
