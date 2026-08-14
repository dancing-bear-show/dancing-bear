"""Phone CLI layout command implementations.

Contains the command functions for top-level layout commands: export, export-device,
iconmap, plan, checklist, unused, prune, analyze, validate-layout, and auto-folders.
Command functions are registered on the app in phone/cli/main.py.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from core.cli_output import emit_one
from core.pipeline import run_pipeline

from ..helpers import LayoutLoadError, load_layout, read_yaml, write_yaml
from ..pipeline_export import (
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
from ..layout_plan_analyze import (
    auto_folderize,
    distribute_folders_across_pages,
)


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
    new_pages = distribute_folders_across_pages(
        folder_names, per_page=per_page, start_page=start_page
    )
    # Merge in new pages
    for k, v in new_pages.items():
        pages[k] = v
    plan["pages"] = pages

    return plan


def _flatten_bundle_ids(layout: object) -> list[str]:
    """Recursively collect all string leaf values from a nested layout structure."""
    result: list[str] = []
    if isinstance(layout, str):
        result.append(layout)
    elif isinstance(layout, list):
        for item in layout:
            result.extend(_flatten_bundle_ids(item))
    return result


def _load_optional_device_apps(
    device_layout_arg: str | None,
) -> tuple[list[str] | None, int | None]:
    """Load device layout apps from path. Returns (apps, error_code).

    On success, error_code is None. On failure, apps is None and error_code is set.
    """
    import json

    if not device_layout_arg:
        return None, None

    device_layout_path = Path(device_layout_arg)
    if not device_layout_path.exists():
        print(
            f"Error: device-layout file not found: {device_layout_path}",
            file=sys.stderr,
        )
        return None, 2
    try:
        device_layout = json.loads(device_layout_path.read_text())
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON in {device_layout_path}: {exc}", file=sys.stderr)
        return None, 2
    return _flatten_bundle_ids(device_layout), None


def _report_layout_issues(issues: list) -> int:
    """Print layout validation issues and return exit code."""
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]
    for issue in issues:
        prefix = "ERROR" if issue.level == "error" else "WARNING"
        print(f"{prefix}: {issue.message}")
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


def cmd_export(args) -> int:
    """DEPRECATED: export layout from Finder backup to YAML."""
    print(
        "Deprecated: 'phone export' uses Finder backups. Use 'phone export-device' or 'phone iconmap'.",
        file=sys.stderr,
    )
    out_path = Path(getattr(args, "out", None) or "out/ios.IconState.yaml")
    request = ExportRequest(backup=getattr(args, "backup", None), out_path=out_path)
    return run_pipeline(request, ExportProcessor, ExportProducer)


def cmd_export_device(args) -> int:
    """Export layout from attached device via cfgutil to YAML."""
    out_path = Path(getattr(args, "out", None) or "out/ios.IconState.yaml")
    request = ExportDeviceRequest(
        udid=getattr(args, "udid", None) or os.environ.get("IOS_DEVICE_UDID"),
        ecid=getattr(args, "ecid", None),
        out_path=out_path,
    )
    return run_pipeline(request, ExportDeviceProcessor, ExportDeviceProducer)


def cmd_iconmap(args) -> int:
    """Download raw icon layout from device via cfgutil."""
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


def cmd_plan(args) -> int:
    """Scaffold a plan YAML (pins + folders) from current layout."""
    out_path = Path(getattr(args, "out", None) or "out/ios.plan.yaml")
    request = PlanRequest(
        layout=getattr(args, "layout", None),
        backup=getattr(args, "backup", None),
        out_path=out_path,
    )
    return run_pipeline(request, PlanProcessor, PlanProducer)


def cmd_checklist(args) -> int:
    """Generate manual move checklist from plan + current layout."""
    plan_path = Path(args.plan)
    out_path = Path(getattr(args, "out", None) or "out/ios.checklist.txt")
    request = ChecklistRequest(
        plan_path=plan_path,
        layout=getattr(args, "layout", None),
        backup=getattr(args, "backup", None),
        out_path=out_path,
    )
    return run_pipeline(request, ChecklistProcessor, ChecklistProducer)


def cmd_unused(args) -> int:
    """Suggest rarely-used app candidates from current layout (heuristic)."""
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


def cmd_prune(args) -> int:
    """Generate OFFLOAD/DELETE checklist for unused candidates (no device writes)."""
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


def cmd_analyze(args) -> int:
    """Analyze layout balance and folder structure (text/json)."""
    request = AnalyzeRequest(
        layout=getattr(args, "layout", None),
        backup=getattr(args, "backup", None),
        plan_path=getattr(args, "plan", None),
        format=getattr(args, "format", "text"),
    )
    return run_pipeline(request, AnalyzeProcessor, AnalyzeProducer)


def cmd_validate_layout(args) -> int:
    """Validate an iOS icon layout JSON file for structural errors."""
    import json

    from ..validate import validate_layout_json

    layout_path = Path(args.layout)
    if not layout_path.exists():
        print(f"Error: layout file not found: {layout_path}", file=sys.stderr)
        return 2

    try:
        layout = json.loads(layout_path.read_text())
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON in {layout_path}: {exc}", file=sys.stderr)
        return 2

    device_apps, err_code = _load_optional_device_apps(getattr(args, "device_layout", None))
    if err_code is not None:
        return err_code

    issues = validate_layout_json(layout, device_apps=device_apps)

    if not issues:
        print(f"OK: {layout_path} — no issues found")
        return 0

    return _report_layout_issues(issues)


def cmd_auto_folders(args) -> int:
    """Auto-assign all apps into folders in plan (keeps specified apps out)."""
    try:
        layout = load_layout(
            getattr(args, "layout", None), getattr(args, "backup", None)
        )
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
    emit_one({
        "status": "ok",
        "plan": str(plan_path),
        "folders_total": len(folders),
        "folders_nonempty": sum(1 for a in folders.values() if a),
    })
    return 0
