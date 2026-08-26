"""Phone CLI merge-folders and reorg command implementations."""

from __future__ import annotations

import os
import subprocess  # nosec B404 - subprocess imported deliberately; individual call sites carry their own B602/B603 review
import sys
from dataclasses import dataclass
from pathlib import Path

from ..device import find_cfgutil_path, map_udid_to_ecid
from ..helpers import read_yaml, write_yaml
from ..layout_merge import merge_folders, verify_conservation


def _merge_and_verify(
    layout: dict, keep: list[str], dump_folders: list[str], merge_fail_prefix: str
):
    """Run merge_folders + verify_conservation. Returns (plan, None) or (None, error_message)."""
    try:
        plan = merge_folders(layout, keep=keep, dump_folders=dump_folders)
    except ValueError as exc:
        return None, f"{merge_fail_prefix}: {exc}"

    try:
        verify_conservation(layout, plan.to_dict())
    except ValueError as exc:
        return None, f"Conservation FAIL: {exc}"

    return plan, None


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

    plan, err = _merge_and_verify(layout, keep, dump_folders, "Error: merge failed")
    if err:
        print(err, file=sys.stderr)
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


def _resolve_reorg_udid(args, dry_run: bool) -> tuple[str, int]:
    """Resolve the target device UDID for a reorg run.

    Precedence: --udid / $IOS_DEVICE_UDID > an explicit --device-label > the
    configured [ios_devices] default label. If a label is named at either level
    but can't be resolved, this fails fast (outside --dry-run) rather than
    silently auto-detecting — reorg replaces the whole Home Screen, so a named
    device that isn't found must not target some other attached device. Only
    when NO label is named at all is "" returned, so cfgutil auto-detects a
    single attached device. Callers gate on the int.
    """
    udid = getattr(args, "udid", None) or os.environ.get("IOS_DEVICE_UDID", "")
    if udid:
        return udid, 0

    # A named target (explicit flag, else the configured default) must resolve.
    label = getattr(args, "device_label", None) or _default_device_label()
    if not label:
        return "", 0  # nothing named → cfgutil auto-detects the single device

    udid = _udid_for_label(label) or ""
    if not udid and not dry_run:
        print(
            f"Error: could not resolve device label '{label}' to a UDID "
            f"(check [ios_devices] in credentials.ini); pass --udid or --dry-run",
            file=sys.stderr,
        )
        return "", 1
    return udid, 0


def cmd_reorg(args) -> int:
    """Chain export-device → merge-folders → profile build → install."""
    install_only = getattr(args, "install_only", False)
    no_install = getattr(args, "no_install", False)

    if install_only and no_install:
        print("Error: --install-only and --no-install are mutually exclusive", file=sys.stderr)
        return 1

    if install_only:
        return _cmd_reorg_install_only(args)

    dry_run = getattr(args, "dry_run", False)
    udid, rc = _resolve_reorg_udid(args, dry_run)
    if rc != 0:
        return rc

    keep_csv = getattr(args, "keep", "") or ""
    out_profile = Path(getattr(args, "out", None) or "out/ios.merged.mobileconfig")

    layout_path = Path("out/ios.IconState.yaml")
    plan_path = Path("out/ios.plan.merged.yaml")
    keep = [s.strip() for s in keep_csv.split(",") if s.strip()] if keep_csv else []

    rc = _reorg_export(dry_run, udid, layout_path)
    if rc != 0:
        return rc

    plan_obj, dump_eliminated, loose_filed = _reorg_merge(layout_path, plan_path, keep)
    if plan_obj is None:
        return 1

    # Remaining steps share the same "nonzero rc aborts the chain" contract.
    for step in (
        lambda: _reorg_build_profile(dry_run, plan_path, layout_path, out_profile),
        lambda: _reorg_install(dry_run, no_install, out_profile, udid),
    ):
        rc = step()
        if rc != 0:
            return rc

    _reorg_summary(
        ReorgSummary(
            plan_obj=plan_obj,
            dump_eliminated=dump_eliminated,
            loose_filed=loose_filed,
            out_profile=out_profile,
            no_install=no_install,
            dry_run=dry_run,
        )
    )
    return 0


def _cmd_reorg_install_only(args) -> int:
    """Install-only mode: skip export/merge/build; install an existing profile."""
    dry_run = getattr(args, "dry_run", False)
    udid, rc = _resolve_reorg_udid(args, dry_run)
    if rc != 0:
        return rc

    # --profile-path takes precedence; fall back to --out default
    profile_arg = getattr(args, "profile_path", None)
    out_arg = getattr(args, "out", None)
    profile_path = Path(profile_arg or out_arg or "out/ios.merged.mobileconfig")

    if not profile_path.exists():
        print(f"Error: profile not found: {profile_path}", file=sys.stderr)
        return 1

    return _reorg_install(dry_run, False, profile_path, udid)


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
    if not layout_path.exists():
        print(f"Error: layout not found: {layout_path}", file=sys.stderr)
        return None, False, 0
    layout = read_yaml(layout_path)
    plan_obj, err = _merge_and_verify(layout, keep, ["Other"], "Error: merge-folders failed")
    if err:
        print(err, file=sys.stderr)
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
    try:
        cfgutil = find_cfgutil_path()
    except FileNotFoundError:
        print("Error: cfgutil not found (install Apple Configurator)", file=sys.stderr)
        return 1
    cmd = [cfgutil]
    ecid: str | None = None
    if udid:
        try:
            ecid = map_udid_to_ecid(cfgutil, udid) or None
        except RuntimeError:
            ecid = None
    if ecid:
        cmd += ["--ecid", ecid]
    cmd += ["install-profile", str(out_profile)]
    result = subprocess.run(  # nosec B603 - resolved cfgutil path, list-form, no shell
        cmd, capture_output=True, text=True
    )
    combined = (result.stdout or "") + (result.stderr or "")
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
        # Success: suppress cfgutil's raw "error:" line (misleading here) and
        # print a clear instruction instead.
        print("✓ Profile copied to device.")
        print("Open Settings -> General -> VPN & Device Management -> "
              "tap the pending profile -> Install.")
        return 0
    # Genuine failure: surface cfgutil's actual output for diagnosis.
    print(combined, end="", file=sys.stderr)
    print(f"Error: cfgutil install-profile failed (rc={result.returncode})", file=sys.stderr)
    return result.returncode


def _ios_devices_option(option: str) -> str | None:
    """Return an [ios_devices] option value from the first creds file that has it."""
    from core.constants import credential_ini_paths, read_credential_ini_first

    env_creds = os.environ.get("IOS_CREDS_FILE")
    search_paths = ([env_creds] if env_creds else []) + credential_ini_paths()

    # require_option skips files whose [ios_devices] lacks this key, so a
    # partial creds file does not shadow a later one that defines the device.
    _path, sections = read_credential_ini_first(
        search_paths=search_paths,
        require_section="ios_devices",
        require_option=option,
    )
    return sections.get("ios_devices", {}).get(option)


def _udid_for_label(label: str) -> str | None:
    """Resolve a device label to its UDID via [ios_devices] in credentials.ini."""
    return _ios_devices_option(label)


def _default_device_label() -> str | None:
    """Return the configured default device label ([ios_devices] default = <label>)."""
    return _ios_devices_option("default")


@dataclass(frozen=True)
class ReorgSummary:
    """Bundle of reorg-result fields for the summary printout."""

    plan_obj: object
    dump_eliminated: bool
    loose_filed: int
    out_profile: Path
    no_install: bool
    dry_run: bool


def _reorg_summary(summary: ReorgSummary) -> None:
    """Print reorg summary."""
    print()
    print("=== reorg summary ===")
    print(f"  folders: {len(summary.plan_obj.folders)}")
    print(f"  Other eliminated: {'yes' if summary.dump_eliminated else 'no'}")
    print(f"  loose apps filed: {summary.loose_filed}")
    print("  conservation: PASS")
    print(f"  profile: {summary.out_profile}")
    if not summary.no_install and not summary.dry_run:
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
