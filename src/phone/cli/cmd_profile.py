"""Phone CLI profile, manifest, and identity command implementations.

Contains the command functions for profile, manifest, and identity group commands.
Command functions are registered on the app groups in phone/cli/main.py.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from core.cli_errors import CLIError, ExitCode
from core.cli_output import emit_one
from core.pipeline import run_pipeline

from ..helpers import read_yaml, write_yaml
from ..pipeline import (
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
)
from ..profile import MobileConfigOptions, ProfileMetadata, build_mobileconfig

# Default values for profile configuration
_DEFAULT_PROFILE_IDENTIFIER = "com.example.profile"
_DEFAULT_HS_IDENTIFIER = "com.example.hslayout"
_DEFAULT_DISPLAY_NAME = "Home Screen Layout"


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
    if not (
        getattr(args, "all_apps_folder_name", None)
        or getattr(args, "all_apps_folder_page", None) is not None
    ):
        return None

    if not layout_export:
        raise ValueError(
            "--all-apps-folder-* requires --layout to enumerate remaining apps"
        )

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


def _sign_mobileconfig(
    in_path: Path, out_path: Path, p12_path: Path, p12_pass: str
) -> None:
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
            ["openssl", "pkcs12", "-help"], capture_output=True, text=True
        )
        legacy_flag = ["-legacy"] if "-legacy" in (result.stdout + result.stderr) else []

        import os

        env = {**os.environ, "_IOS_P12_PASS": p12_pass}

        # Extract certificate
        subprocess.run(  # nosec B603 B607 - openssl with user-provided p12 path; mitigations: list-form args (no shell), check=True raises on failure, password passed via env var not argv
            [
                "openssl",
                "pkcs12",
                *legacy_flag,
                "-in",
                str(p12_path),
                "-clcerts",
                "-nokeys",
                "-out",
                str(cert_pem),
                "-passin",
                "env:_IOS_P12_PASS",
            ],
            check=True,
            capture_output=True,
            env=env,
        )

        # Extract private key
        subprocess.run(  # nosec B603 B607 - openssl with user-provided p12 path; mitigations: list-form args (no shell), check=True raises on failure, password passed via env var not argv
            [
                "openssl",
                "pkcs12",
                *legacy_flag,
                "-in",
                str(p12_path),
                "-nocerts",
                "-nodes",
                "-out",
                str(key_pem),
                "-passin",
                "env:_IOS_P12_PASS",
            ],
            check=True,
            capture_output=True,
            env=env,
        )

        # Sign the profile
        subprocess.run(  # nosec B603 B607 - openssl smime with controlled paths
            [
                "openssl",
                "smime",
                "-sign",
                "-in",
                str(in_path),
                "-out",
                str(out_path),
                "-signer",
                str(cert_pem),
                "-inkey",
                str(key_pem),
                "-outform",
                "der",
                "-nodetach",
            ],
            check=True,
            capture_output=True,
        )


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
            "creds_profile": getattr(args, "creds_profile", None)
            or os.environ.get("IOS_CREDS_PROFILE", "ios_layout_manager"),
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


def cmd_profile_build(args) -> int:
    """Build a .mobileconfig from a plan YAML."""
    try:
        plan = read_yaml(Path(args.plan))
    except FileNotFoundError as e:
        raise CLIError(str(e), ExitCode.USAGE) from e

    layout_export = None
    if getattr(args, "layout", None):
        try:
            layout_export = read_yaml(Path(args.layout))
        except FileNotFoundError as e:
            raise CLIError(str(e), ExitCode.USAGE) from e

    try:
        all_apps_folder = _build_all_apps_folder_config(args, layout_export)
    except ValueError as e:
        raise CLIError(str(e), ExitCode.USAGE) from e

    profile_dict = build_mobileconfig(
        plan=plan,
        layout_export=layout_export,
        profile_meta=ProfileMetadata(
            top_identifier=getattr(args, "identifier", _DEFAULT_PROFILE_IDENTIFIER),
            hs_identifier=getattr(args, "hs_identifier", _DEFAULT_HS_IDENTIFIER),
            display_name=getattr(args, "display_name", _DEFAULT_DISPLAY_NAME),
            organization=getattr(args, "organization", None),
        ),
        all_apps_folder=all_apps_folder,
        options=MobileConfigOptions(
            dock_count=max(0, int(getattr(args, "dock_count", 4))),
            folder_page_size=int(getattr(args, "folder_page_size", 30)),
        ),
    )

    out_path = Path(args.out)
    _write_mobileconfig(profile_dict, out_path)
    print(f"Wrote {_DEFAULT_DISPLAY_NAME} profile to {out_path}")

    # Sign the profile if requested
    sign_p12 = getattr(args, "sign_p12", None)
    if sign_p12:
        sign_pass = getattr(args, "sign_pass", None) or os.environ.get(
            "IOS_SIGN_PASS", ""
        )
        try:
            _sign_mobileconfig(out_path, out_path, Path(sign_p12), sign_pass)
        except subprocess.CalledProcessError as e:
            raise CLIError(f"Error signing profile: {e}", ExitCode.ERROR) from e
        print(f"Signed profile with {sign_p12}")

    return 0


def cmd_manifest_create(args) -> int:
    """Create a manifest by embedding an existing plan."""
    plan = read_yaml(Path(args.from_plan))
    manifest = _build_manifest_dict(plan, args)
    out = Path(args.out)
    write_yaml(manifest, out)
    emit_one({"status": "ok", "manifest": str(out)})
    return 0


def cmd_manifest_build(args) -> int:
    """Build a .mobileconfig from a manifest."""
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
        profile_meta=ProfileMetadata(
            top_identifier=prof.get("identifier", _DEFAULT_PROFILE_IDENTIFIER),
            hs_identifier=prof.get("hs_identifier", _DEFAULT_HS_IDENTIFIER),
            display_name=prof.get("display_name", _DEFAULT_DISPLAY_NAME),
            organization=prof.get("organization"),
        ),
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    import plistlib

    with out.open("wb") as f:
        plistlib.dump(profile_dict, f, fmt=plistlib.FMT_XML, sort_keys=False)
    print(f"Wrote {_DEFAULT_DISPLAY_NAME} profile to {out}")
    return 0


def cmd_manifest_from_export(args) -> int:
    """Create a device layout manifest from a layout export YAML."""
    request = ManifestFromExportRequest(
        export_path=Path(args.export),
        out_path=Path(args.out),
    )
    return run_pipeline(
        request, ManifestFromExportProcessor, ManifestFromExportProducer
    )


def cmd_manifest_from_device(args) -> int:
    """Create a device layout manifest from an attached device via cfgutil."""
    export_out = Path(args.export_out) if getattr(args, "export_out", None) else None
    request = ManifestFromDeviceRequest(
        udid=getattr(args, "udid", None),
        export_out=export_out,
        out_path=Path(args.out),
    )
    return run_pipeline(
        request, ManifestFromDeviceProcessor, ManifestFromDeviceProducer
    )


def cmd_manifest_install(args) -> int:
    """Build and install a profile from a manifest (hands-off via credentials)."""
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


def cmd_identity_verify(args) -> int:
    """Verify .p12 identity vs device supervision."""
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
