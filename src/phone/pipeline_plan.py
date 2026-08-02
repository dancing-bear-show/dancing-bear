"""Phone pipeline components for manifest and identity workflows."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.pipeline import (
    RequestConsumer,
    SafeProcessor,
)

from .helpers import read_yaml, write_yaml
from .pipeline_export import BaseProducer, _build_manifest_from_export
from .profile import ProfileMetadata


# -----------------------------------------------------------------------------
# Manifest pipelines
# -----------------------------------------------------------------------------


@dataclass
class ManifestFromExportRequest:
    export_path: Path
    out_path: Path


ManifestFromExportRequestConsumer = RequestConsumer[ManifestFromExportRequest]


@dataclass
class ManifestFromExportResult:
    manifest: dict[str, Any]
    out_path: Path


class ManifestFromExportProcessor(
    SafeProcessor[ManifestFromExportRequest, ManifestFromExportResult]
):
    def _process_safe(
        self, payload: ManifestFromExportRequest
    ) -> ManifestFromExportResult:
        try:
            exp = read_yaml(payload.export_path)
        except FileNotFoundError:
            raise ValueError(f"Export not found: {payload.export_path}")

        if not isinstance(exp, dict) or "dock" not in exp or "pages" not in exp:
            raise ValueError("Export file must contain 'dock' and 'pages' keys")

        manifest = _build_manifest_from_export(exp, str(payload.export_path))
        return ManifestFromExportResult(manifest=manifest, out_path=payload.out_path)


class ManifestFromExportProducer(BaseProducer):
    def _produce_success(
        self, payload: ManifestFromExportResult, diagnostics: dict[str, Any] | None
    ) -> None:
        write_yaml(payload.manifest, payload.out_path)
        print(f"Wrote device layout manifest to {payload.out_path}")


@dataclass
class ManifestFromDeviceRequest:
    udid: str | None
    export_out: Path | None
    out_path: Path


ManifestFromDeviceRequestConsumer = RequestConsumer[ManifestFromDeviceRequest]


@dataclass
class ManifestFromDeviceResult:
    manifest: dict[str, Any]
    out_path: Path
    export_out: Path | None
    export_document: dict[str, Any] | None


class ManifestFromDeviceProcessor(
    SafeProcessor[ManifestFromDeviceRequest, ManifestFromDeviceResult]
):
    def _process_safe(
        self, payload: ManifestFromDeviceRequest
    ) -> ManifestFromDeviceResult:
        import os
        from .device import find_cfgutil_path, map_udid_to_ecid, export_from_device

        cfgutil = find_cfgutil_path()

        udid = payload.udid or os.environ.get("IOS_DEVICE_UDID")
        ecid = map_udid_to_ecid(cfgutil, udid) if udid else None

        exp = export_from_device(cfgutil, ecid)

        if not exp:
            raise ValueError("Could not derive export from device layout")

        export_path = payload.export_out or Path("out/device.IconState.yaml")
        manifest = _build_manifest_from_export(exp, str(export_path))

        return ManifestFromDeviceResult(
            manifest=manifest,
            out_path=payload.out_path,
            export_out=payload.export_out,
            export_document=exp,
        )


class ManifestFromDeviceProducer(BaseProducer):
    def _produce_success(
        self, payload: ManifestFromDeviceResult, diagnostics: dict[str, Any] | None
    ) -> None:
        # Write export if path specified or default
        if payload.export_document:
            export_path = payload.export_out or Path("out/device.IconState.yaml")
            export_path.parent.mkdir(parents=True, exist_ok=True)
            write_yaml(payload.export_document, export_path)
        # Write manifest
        write_yaml(payload.manifest, payload.out_path)
        print(f"Wrote device layout manifest to {payload.out_path}")


# -----------------------------------------------------------------------------
# Manifest install pipeline
# -----------------------------------------------------------------------------


@dataclass
class ManifestInstallRequest:
    manifest_path: Path
    out_path: Path | None
    dry_run: bool
    udid: str | None
    device_label: str | None
    creds_profile: str | None
    config: str | None


ManifestInstallRequestConsumer = RequestConsumer[ManifestInstallRequest]


@dataclass
class ManifestInstallResult:
    profile_path: Path
    profile_bytes: bytes
    dry_run: bool
    install_cmd: list[str] | None


def _load_and_validate_manifest(manifest_path: Path) -> dict[str, Any]:
    """Load manifest from path and validate it's a dict."""
    try:
        man = read_yaml(manifest_path)
    except FileNotFoundError:
        raise ValueError(f"Manifest not found: {manifest_path}")

    if not isinstance(man, dict):
        raise ValueError("Invalid manifest")
    return man


def _extract_plan_from_manifest(man: dict[str, Any]) -> dict[str, Any]:
    """Extract or derive plan from manifest dict."""
    plan = man.get("plan") or {}
    if not plan and man.get("layout"):
        plan = _plan_from_layout(man.get("layout") or {})
    if not plan:
        raise ValueError("Manifest missing 'plan' or 'layout' section")
    return plan


def _determine_profile_path(
    payload_path: Path | None, manifest: dict[str, Any]
) -> Path:
    """Determine output path for profile."""
    if payload_path:
        return payload_path
    dev = manifest.get("device") or {}
    suffix = dev.get("label") or dev.get("udid") or "device"
    return Path("out") / f"{suffix}.hslayout.from_manifest.mobileconfig"


def _build_install_command(
    payload: ManifestInstallRequest,
    manifest: dict[str, Any],
    profile_path: Path,
) -> list[str] | None:
    """Build install command if not dry-run."""
    if payload.dry_run:
        return None

    import os

    dev = manifest.get("device") or {}
    udid = payload.udid or dev.get("udid") or os.environ.get("IOS_DEVICE_UDID")
    label = (
        payload.device_label or dev.get("label") or os.environ.get("IOS_DEVICE_LABEL")
    )
    creds_profile = (
        payload.creds_profile
        or dev.get("creds_profile")
        or os.environ.get("IOS_CREDS_PROFILE")
    )

    repo_root = Path(__file__).resolve().parents[1]
    installer = str(repo_root / "bin" / "ios-install-profile")
    cmd = [installer, "--profile", str(profile_path)]
    if creds_profile:
        cmd.extend(["--creds-profile", creds_profile])
    if payload.config:
        cmd.extend(["--config", payload.config])
    if udid:
        cmd.extend(["--udid", udid])
    elif label:
        cmd.extend(["--device-label", label])
    return cmd


class ManifestInstallProcessor(
    SafeProcessor[ManifestInstallRequest, ManifestInstallResult]
):
    def _process_safe(self, payload: ManifestInstallRequest) -> ManifestInstallResult:
        import plistlib
        from .profile import build_mobileconfig

        man = _load_and_validate_manifest(payload.manifest_path)
        plan = _extract_plan_from_manifest(man)

        _defaults = ProfileMetadata()
        prof = man.get("profile") or {}
        profile_dict = build_mobileconfig(
            plan=plan,
            layout_export=None,
            profile_meta=ProfileMetadata(
                top_identifier=prof.get("identifier", _defaults.top_identifier),
                hs_identifier=prof.get("hs_identifier", _defaults.hs_identifier),
                display_name=prof.get("display_name", _defaults.display_name),
                organization=prof.get("organization"),
            ),
        )

        out_path = _determine_profile_path(payload.out_path, man)
        profile_bytes = plistlib.dumps(
            profile_dict, fmt=plistlib.FMT_XML, sort_keys=False
        )
        install_cmd = _build_install_command(payload, man, out_path)

        return ManifestInstallResult(
            profile_path=out_path,
            profile_bytes=profile_bytes,
            dry_run=payload.dry_run,
            install_cmd=install_cmd,
        )


class ManifestInstallProducer(BaseProducer):
    def _produce_success(
        self, payload: ManifestInstallResult, diagnostics: dict[str, Any] | None
    ) -> None:
        import subprocess  # nosec B404

        # Write profile
        payload.profile_path.parent.mkdir(parents=True, exist_ok=True)
        payload.profile_path.write_bytes(payload.profile_bytes)
        print(f"Built profile: {payload.profile_path}")

        if payload.dry_run:
            print("Dry-run: skipping install")
            return

        if payload.install_cmd:
            print("Installing via:", " ".join(payload.install_cmd))
            try:
                subprocess.call(payload.install_cmd)  # nosec B603 - calling internal repo script with validated args
            except FileNotFoundError:
                print("Error: ios-install-profile not found", file=sys.stderr)


def _plan_from_layout(layout_obj: dict[str, Any]) -> dict[str, Any]:
    """Convert a layout object to a plan format."""
    plan: dict[str, Any] = {
        "dock": list(layout_obj.get("dock") or []),
        "pages": {},
        "folders": {},
    }
    pages = layout_obj.get("pages") or []
    page_map: dict[int, dict[str, Any]] = {}
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


# -----------------------------------------------------------------------------
# Identity verify pipeline
# -----------------------------------------------------------------------------


@dataclass
class IdentityVerifyRequest:
    p12_path: str | None
    p12_pass: str | None
    creds_profile: str | None
    config: str | None
    device_label: str | None
    udid: str | None
    expected_org: str | None


IdentityVerifyRequestConsumer = RequestConsumer[IdentityVerifyRequest]


@dataclass
class IdentityVerifyResult:
    p12_path: str
    cert_subject: str
    cert_issuer: str
    udid: str | None
    supervised: str | None
    expected_org: str | None
    org_match: bool | None


class IdentityVerifyProcessor(
    SafeProcessor[IdentityVerifyRequest, IdentityVerifyResult]
):
    def _process_safe(self, payload: IdentityVerifyRequest) -> IdentityVerifyResult:
        import os
        from .device import (
            read_credentials_ini,
            resolve_p12_path,
            extract_p12_cert_info,
            get_device_supervision_status,
            resolve_udid_from_label,
        )

        # Load credentials
        cfg_path, ini = read_credentials_ini(payload.config)
        creds_profile = payload.creds_profile or os.environ.get(
            "IOS_CREDS_PROFILE", "ios_layout_manager"
        )

        # Resolve p12
        p12_path, p12_pass = resolve_p12_path(
            payload.p12_path,
            payload.p12_pass,
            creds_profile,
            ini,
        )

        if not p12_path:
            raise ValueError("p12 path not provided (use --p12 or credentials.ini)")

        # Extract certificate info
        try:
            cert = extract_p12_cert_info(p12_path, p12_pass)
        except FileNotFoundError:
            raise ValueError(f"p12 file not found: {p12_path}")
        except RuntimeError as e:
            raise ValueError(f"Operation failed: {e}") from e

        # Resolve device UDID
        udid = payload.udid or os.environ.get("IOS_DEVICE_UDID")
        if not udid:
            label = payload.device_label or os.environ.get("IOS_DEVICE_LABEL")
            if label:
                udid = resolve_udid_from_label(label, cfg_path, ini)

        # Get supervision status
        supervised = get_device_supervision_status()

        # Check org match if expected
        org_match: bool | None = None
        if payload.expected_org:
            org_match = (payload.expected_org in cert.subject) or (
                payload.expected_org in cert.issuer
            )

        return IdentityVerifyResult(
            p12_path=p12_path,
            cert_subject=cert.subject,
            cert_issuer=cert.issuer,
            udid=udid,
            supervised=supervised,
            expected_org=payload.expected_org,
            org_match=org_match,
        )


class IdentityVerifyProducer(BaseProducer):
    def _produce_success(
        self, payload: IdentityVerifyResult, diagnostics: dict[str, Any] | None
    ) -> None:
        print("Identity Verification Summary")
        print(f"- p12: {payload.p12_path}")
        print(f"- cert.subject: {payload.cert_subject or '(unknown)'}")
        print(f"- cert.issuer:  {payload.cert_issuer or '(unknown)'}")
        if payload.expected_org:
            print(
                f"- expected org '{payload.expected_org}': {'MATCH' if payload.org_match else 'NO MATCH'}"
            )
        print(f"- device.udid: {payload.udid or '(not provided)'}")
        print(f"- device.supervised: {payload.supervised or '(unknown)'}")
        print("")
        print("Next steps:")
        print(
            "- Ensure the device shows 'Supervised by <Org>' matching the certificate subject/issuer above."
        )
        print("- If they match, no-touch installs should succeed using this identity.")
        print(
            "- If they do not match, Prepare again under the correct Organization, or export the matching Supervision Identity."
        )
