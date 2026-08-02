"""Phone CLI merge-folders and reorg command implementations."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from ..helpers import read_yaml, write_yaml
from ..layout_merge import merge_folders, verify_conservation


def cmd_merge_folders(args) -> int:
    """Redistribute dump folder apps into best-fit existing folders."""
    layout_path = Path(getattr(args, "layout", None) or "out/ios.IconState.yaml")
    plan_out = Path(getattr(args, "plan", None) or "out/ios.plan.merged.yaml")
    keep_csv = getattr(args, "keep", "") or ""
    dump_csv = getattr(args, "dump_folder_names", "") or ""

    keep = [s.strip() for s in keep_csv.split(",") if s.strip()] if keep_csv else []
    dump_folders = (
        [s.strip() for s in dump_csv.split(",") if s.strip()]
        if dump_csv
        else ["Other"]
    )

    if not layout_path.exists():
        print(f"Error: layout not found: {layout_path}", file=sys.stderr)
        return 2

    layout = read_yaml(layout_path)

    try:
        plan = merge_folders(layout, keep=keep, dump_folders=dump_folders)
    except Exception as exc:  # nosec B112 - surface merge failures with context
        print(f"Error: merge failed: {exc}", file=sys.stderr)
        return 1

    try:
        verify_conservation(layout, plan.to_dict())
    except ValueError as exc:
        print(f"Conservation FAIL: {exc}", file=sys.stderr)
        return 1

    plan_out.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(plan.to_dict(), plan_out)

    dump_eliminated = all(name not in plan.folders for name in dump_folders)
    print("merge-folders complete:")
    print(f"  plan: {plan_out}")
    print(f"  folders: {len(plan.folders)}")
    print(f"  dump eliminated: {'yes' if dump_eliminated else 'no'}")
    print(f"  pins (page 1): {len(plan.pins)}")
    print("  conservation: PASS")
    return 0


def cmd_reorg(args) -> int:
    """Chain export-device → merge-folders → profile build → install."""
    import os

    device_label = getattr(args, "device_label", None) or "bcsphone"
    udid = getattr(args, "udid", None) or os.environ.get("IOS_DEVICE_UDID", "")
    if not udid and device_label:
        udid = _udid_for_label(device_label) or ""
    keep_csv = getattr(args, "keep", "") or ""
    out_profile = Path(getattr(args, "out", None) or "out/ios.merged.mobileconfig")
    no_install = getattr(args, "no_install", False)
    dry_run = getattr(args, "dry_run", False)

    layout_path = Path("out/ios.IconState.yaml")
    plan_path = Path("out/ios.plan.merged.yaml")
    keep = [s.strip() for s in keep_csv.split(",") if s.strip()] if keep_csv else []

    rc = _reorg_export(dry_run, udid, layout_path)
    if rc != 0:
        return rc

    plan_obj, dump_eliminated, loose_filed = _reorg_merge(layout_path, plan_path, keep)
    if plan_obj is None:
        return 1

    rc = _reorg_build_profile(dry_run, plan_path, layout_path, out_profile)
    if rc != 0:
        return rc

    rc = _reorg_install(dry_run, no_install, out_profile, udid)
    if rc != 0:
        return rc

    _reorg_summary(plan_obj, dump_eliminated, loose_filed, out_profile, no_install, dry_run)
    return 0


def _reorg_export(dry_run: bool, udid: str, layout_path: Path) -> int:
    """Step 1: export device layout."""
    print("=== reorg: step 1/4 — export-device ===")
    if dry_run:
        if not layout_path.exists():
            print(
                f"Dry-run: layout not found at {layout_path}; aborting",
                file=sys.stderr,
            )
            return 2
        print(f"Dry-run: using existing {layout_path}")
        return 0
    rc = _run_export_device(udid, layout_path)
    if rc != 0:
        print(f"Error: export-device failed (rc={rc})", file=sys.stderr)
    return rc


def _reorg_merge(layout_path: Path, plan_path: Path, keep: list[str]):
    """Step 2: run merge-folders and write plan. Returns (plan_obj, dump_eliminated, loose_filed) or (None, ...) on error."""
    print("=== reorg: step 2/4 — merge-folders ===")
    layout = read_yaml(layout_path)
    try:
        plan_obj = merge_folders(layout, keep=keep, dump_folders=["Other"])
    except Exception as exc:  # nosec B112 - surface merge failures with context
        print(f"Error: merge-folders failed: {exc}", file=sys.stderr)
        return None, False, 0
    try:
        verify_conservation(layout, plan_obj.to_dict())
    except ValueError as exc:
        print(f"Conservation FAIL: {exc}", file=sys.stderr)
        return None, False, 0
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(plan_obj.to_dict(), plan_path)

    dump_eliminated = "Other" not in plan_obj.folders
    loose_filed = sum(
        1 for bid in _collect_loose_page2plus(layout)
        if bid not in (plan_obj.pins or [])
    )
    print(
        f"  folders: {len(plan_obj.folders)}, Other eliminated: {'yes' if dump_eliminated else 'no'}"
    )
    print(f"  loose apps filed: {loose_filed}, conservation: PASS")
    return plan_obj, dump_eliminated, loose_filed


def _reorg_build_profile(
    dry_run: bool, plan_path: Path, layout_path: Path, out_profile: Path
) -> int:
    """Step 3: build mobileconfig profile."""
    print("=== reorg: step 3/4 — profile build ===")
    if dry_run:
        print(f"Dry-run: would build profile → {out_profile}")
        return 0
    out_profile.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "./bin/phone-assistant", "profile", "build",
        "--plan", str(plan_path),
        "--layout", str(layout_path),
        "--folder-page-size", "9",
        "--out", str(out_profile),
    ]
    result = subprocess.run(cmd, capture_output=False)  # nosec B603 B607 - fixed bin/phone-assistant command; list-form, no shell
    if result.returncode != 0:
        print(f"Error: profile build failed (rc={result.returncode})", file=sys.stderr)
    return result.returncode


def _reorg_install(
    dry_run: bool, no_install: bool, out_profile: Path, udid: str
) -> int:
    """Step 4: copy profile to device."""
    print("=== reorg: step 4/4 — install profile ===")
    if dry_run or no_install:
        label = "Dry-run" if dry_run else "--no-install"
        print(f"{label}: skipping install")
        print(f"Profile at: {out_profile}")
        print("To install: drag onto device in Configurator, or:")
        print(f"  cfgutil install-profile {out_profile}")
        print("  (then tap Install in Settings on the device)")
        return 0
    # Call cfgutil directly with NO -C/-K supervision flags. The supervised
    # silent-install path (SecKeyCreateFromData) is broken on macOS 26, so the
    # canonical route is copy-then-tap: cfgutil copies the profile and returns a
    # non-zero exit with "Code: 625 / User interaction on the device is
    # required", which is the EXPECTED success outcome — the user taps Install.
    cfgutil = _resolve_cfgutil()
    if not cfgutil:
        print("Error: cfgutil not found (install Apple Configurator)", file=sys.stderr)
        return 1
    cmd = [cfgutil]
    ecid = _resolve_ecid(cfgutil, udid) if udid else None
    if ecid:
        cmd += ["--ecid", ecid]
    cmd += ["install-profile", str(out_profile)]
    result = subprocess.run(  # nosec B603 - resolved cfgutil path, list-form, no shell
        cmd, capture_output=True, text=True
    )
    combined = (result.stdout or "") + (result.stderr or "")
    print(combined, end="")
    # cfgutil's "user interaction required" (Code 625) is the expected success:
    # the profile was copied and awaits an on-device tap. It surfaces in the
    # message text, not the process exit code (which is 1). Match the specific
    # phrases — a bare "625" substring could collide with unrelated numbers.
    lowered = combined.lower()
    pending_tap = (
        "user interaction on the device is required" in lowered
        or "code: 625" in lowered
    )
    if result.returncode == 0 or pending_tap:
        print("\n✓ Profile copied to device.")
        print("Open Settings -> General -> VPN & Device Management -> "
              "tap the pending profile -> Install.")
        return 0
    print(f"Error: cfgutil install-profile failed (rc={result.returncode})", file=sys.stderr)
    return result.returncode


def _udid_for_label(label: str) -> str | None:
    """Resolve a device label to its UDID via [ios_devices] in credentials.ini."""
    import configparser
    import os

    for path in (
        os.environ.get("IOS_CREDS_FILE"),
        os.path.expanduser("~/.config/credentials.ini"),
    ):
        if not path or not os.path.isfile(path):
            continue
        parser = configparser.ConfigParser()
        try:
            parser.read(path)
        except (configparser.Error, OSError):  # nosec B112 - skip unreadable/malformed creds file, try next
            continue
        if parser.has_option("ios_devices", label):
            return parser.get("ios_devices", label)
    return None


def _resolve_cfgutil() -> str | None:
    """Locate the cfgutil binary."""
    import shutil

    for candidate in (
        "/usr/local/bin/cfgutil",
        "/Applications/Apple Configurator.app/Contents/MacOS/cfgutil",
    ):
        if Path(candidate).exists():
            return candidate
    return shutil.which("cfgutil")


def _resolve_ecid(cfgutil: str, udid: str) -> str | None:
    """Map a UDID to its ECID so install targets one device."""
    try:
        out = subprocess.run(  # nosec B603 - resolved cfgutil path, list-form, no shell
            [cfgutil, "list"], capture_output=True, text=True
        ).stdout
    except OSError:
        return None
    for line in out.splitlines():
        if udid in line and "ECID:" in line:
            parts = line.split()
            for i, tok in enumerate(parts):
                if tok == "ECID:" and i + 1 < len(parts):
                    return parts[i + 1]
    return None


def _reorg_summary(plan_obj, dump_eliminated: bool, loose_filed: int, out_profile: Path, no_install: bool, dry_run: bool) -> None:
    """Print reorg summary."""
    print()
    print("=== reorg summary ===")
    print(f"  folders: {len(plan_obj.folders)}")
    print(f"  Other eliminated: {'yes' if dump_eliminated else 'no'}")
    print(f"  loose apps filed: {loose_filed}")
    print("  conservation: PASS")
    print(f"  profile: {out_profile}")
    if not no_install and not dry_run:
        print("  install: sent to device (tap Install in Settings)")


def _run_export_device(udid: str, layout_path: Path) -> int:
    """Run export-device via subprocess to avoid circular imports."""
    cmd = [
        "./bin/phone-assistant", "export-device", "--out", str(layout_path),
    ]
    if udid:
        cmd += ["--udid", udid]
    result = subprocess.run(cmd, capture_output=False)  # nosec B603 B607 - fixed bin/phone-assistant command; list-form, no shell
    return result.returncode


def _collect_loose_page2plus(layout: dict) -> list[str]:
    """Collect loose app bundle IDs from pages >= 2 (index >= 1)."""
    result = []
    for page in (layout.get("pages") or [])[1:]:
        for bid in (page.get("apps") or []):
            if bid:
                result.append(bid)
    return result
