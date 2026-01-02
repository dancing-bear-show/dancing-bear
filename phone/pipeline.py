"""Phone assistant pipeline components (export, plan, checklist)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

from core.pipeline import (
    BaseProducer as _CoreBaseProducer,
    SafeProcessor,
    RequestConsumer,
    ResultEnvelope,
)

from .helpers import LayoutLoadError, load_layout, read_yaml, write_yaml
from .layout import checklist_from_plan, scaffold_plan, to_yaml_export


def _build_manifest_from_export(
    exp: Dict[str, Any],
    export_path: str,
) -> Dict[str, Any]:
    """Build a manifest dict from raw export data.

    Args:
        exp: Raw export dict with 'dock' and 'pages' keys
        export_path: Path string for source attribution

    Returns:
        Manifest dict with meta, device, layout, apps, counts, and source
    """
    import os

    dock = list(exp.get("dock") or [])
    pages_in = exp.get("pages") or []
    pages_out: List[Dict[str, Any]] = []
    all_apps: List[str] = []
    seen: set = set()
    folders_total = 0

    for p in pages_in:
        apps = list(p.get("apps") or [])
        folders = []
        for f in p.get("folders") or []:
            name = f.get("name") or "Folder"
            fapps = list(f.get("apps") or [])
            folders.append({"name": name, "apps": fapps})
            folders_total += 1
        pages_out.append({"apps": apps, "folders": folders})
        for a in apps:
            if a and a not in seen:
                seen.add(a)
                all_apps.append(a)
        for f in folders:
            for a in f["apps"]:
                if a and a not in seen:
                    seen.add(a)
                    all_apps.append(a)

    for a in dock:
        if a and a not in seen:
            seen.add(a)
            all_apps.append(a)

    return {
        "meta": {"name": "device_layout_manifest", "version": 1},
        "device": {
            "udid": os.environ.get("IOS_DEVICE_UDID"),
            "label": os.environ.get("IOS_DEVICE_LABEL"),
        },
        "layout": {"dock": dock, "pages": pages_out},
        "apps": {"all": all_apps},
        "counts": {
            "apps_total": len(all_apps),
            "pages_count": len(pages_out),
            "folders_count": folders_total,
        },
        "source": {"export_path": export_path},
    }


class BaseProducer(_CoreBaseProducer):
    """Phone-specific base producer that prints errors to stderr."""

    def produce(self, result: ResultEnvelope) -> None:
        """Template method: handle errors to stderr, delegate success to subclass."""
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg, file=sys.stderr)
            return
        if result.payload is not None:
            self._produce_success(result.payload, result.diagnostics)


@dataclass
class ExportRequest:
    backup: Optional[str]
    out_path: Path


# Type alias for backward compatibility
ExportRequestConsumer = RequestConsumer[ExportRequest]


@dataclass
class ExportResult:
    document: Dict[str, Any]
    out_path: Path


class ExportProcessor(SafeProcessor[ExportRequest, ExportResult]):
    def _process_safe(self, payload: ExportRequest) -> ExportResult:
        try:
            layout = load_layout(None, payload.backup)
        except LayoutLoadError as err:
            raise err
        except Exception as exc:  # pragma: no cover - unexpected IO errors
            raise ValueError(f"Error: {exc}")
        export = to_yaml_export(layout)
        return ExportResult(document=export, out_path=payload.out_path)


class ExportProducer(BaseProducer):
    def _produce_success(self, payload: ExportResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        write_yaml(payload.document, payload.out_path)
        print(f"Wrote layout export to {payload.out_path}")


@dataclass
class PlanRequest:
    layout: Optional[str]
    backup: Optional[str]
    out_path: Path


PlanRequestConsumer = RequestConsumer[PlanRequest]


@dataclass
class PlanResult:
    document: Dict[str, Any]
    out_path: Path


class PlanProcessor(SafeProcessor[PlanRequest, PlanResult]):
    def _process_safe(self, payload: PlanRequest) -> PlanResult:
        try:
            layout = load_layout(payload.layout, payload.backup)
        except LayoutLoadError as err:
            raise err
        plan = scaffold_plan(layout)
        return PlanResult(document=plan, out_path=payload.out_path)


class PlanProducer(BaseProducer):
    def _produce_success(self, payload: PlanResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        write_yaml(payload.document, payload.out_path)
        print(f"Wrote plan scaffold to {payload.out_path}")


@dataclass
class ChecklistRequest:
    plan_path: Path
    layout: Optional[str]
    backup: Optional[str]
    out_path: Path


ChecklistRequestConsumer = RequestConsumer[ChecklistRequest]


@dataclass
class ChecklistResult:
    steps: List[str]
    out_path: Path


class ChecklistProcessor(SafeProcessor[ChecklistRequest, ChecklistResult]):
    def _process_safe(self, payload: ChecklistRequest) -> ChecklistResult:
        try:
            layout = load_layout(payload.layout, payload.backup)
        except LayoutLoadError as err:
            raise err
        try:
            plan = read_yaml(payload.plan_path)
        except FileNotFoundError:
            raise ValueError(f"Plan not found: {payload.plan_path}")
        steps = checklist_from_plan(layout, plan)
        return ChecklistResult(steps=steps, out_path=payload.out_path)


class ChecklistProducer(BaseProducer):
    def _produce_success(self, payload: ChecklistResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        out = payload.out_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(payload.steps) + "\n", encoding="utf-8")
        print(f"Wrote checklist to {out}")


# -----------------------------------------------------------------------------
# Unused apps pipeline
# -----------------------------------------------------------------------------


@dataclass
class UnusedRequest:
    layout: Optional[str]
    backup: Optional[str]
    recent_path: Optional[str]
    keep_path: Optional[str]
    limit: int = 50
    threshold: float = 0.8
    format: str = "text"  # "text" or "csv"


UnusedRequestConsumer = RequestConsumer[UnusedRequest]


@dataclass
class UnusedResult:
    rows: List[tuple]  # (app_id, score, location)
    format: str


class UnusedProcessor(SafeProcessor[UnusedRequest, UnusedResult]):
    def _process_safe(self, payload: UnusedRequest) -> UnusedResult:
        from .layout import rank_unused_candidates

        try:
            layout = load_layout(payload.layout, payload.backup)
        except LayoutLoadError as err:
            raise err

        recent = _read_lines_file(payload.recent_path)
        keep = _read_lines_file(payload.keep_path)
        rows = rank_unused_candidates(layout, recent_ids=recent, keep_ids=keep)
        rows = [r for r in rows if r[1] >= payload.threshold][: payload.limit]

        return UnusedResult(rows=rows, format=payload.format)


class UnusedProducer(BaseProducer):
    def _produce_success(self, payload: UnusedResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        rows = payload.rows
        if payload.format == "csv":
            print("app,score,location")
            for app, score, loc in rows:
                print(f"{app},{score:.2f},{loc}")
        else:
            print("Likely unused app candidates (heuristic):")
            print("score  app                                   location")
            for app, score, loc in rows:
                print(f"{score:4.1f}  {app:36}  {loc}")


# -----------------------------------------------------------------------------
# Prune checklist pipeline
# -----------------------------------------------------------------------------


@dataclass
class PruneRequest:
    layout: Optional[str]
    backup: Optional[str]
    recent_path: Optional[str]
    keep_path: Optional[str]
    limit: int = 50
    threshold: float = 1.0
    mode: str = "offload"  # "offload" or "delete"
    out_path: Path = Path("out/ios.unused.prune_checklist.txt")


PruneRequestConsumer = RequestConsumer[PruneRequest]


@dataclass
class PruneResult:
    lines: List[str]
    out_path: Path


class PruneProcessor(SafeProcessor[PruneRequest, PruneResult]):
    def _process_safe(self, payload: PruneRequest) -> PruneResult:
        from .layout import rank_unused_candidates

        try:
            layout = load_layout(payload.layout, payload.backup)
        except LayoutLoadError as err:
            raise err

        recent = _read_lines_file(payload.recent_path)
        keep = _read_lines_file(payload.keep_path)
        rows = rank_unused_candidates(layout, recent_ids=recent, keep_ids=keep)
        rows = [r for r in rows if r[1] >= payload.threshold][: payload.limit]

        lines = []
        lines.append(f"Unused apps checklist — mode: {payload.mode.upper()}")
        lines.append("")
        lines.append("Instructions:")
        if payload.mode == "offload":
            lines.append("1) Settings → General → iPhone Storage → search for app → Offload App")
            lines.append("   or long‑press app icon → Remove App → Offload App")
        else:
            lines.append("1) Long‑press app icon → Remove App → Delete App")
            lines.append("   or Settings → General → iPhone Storage → Delete App")
        lines.append("")
        lines.append("Candidates:")
        for app, score, loc in rows:
            lines.append(f"- {app}  (score {score:.1f}; location: {loc})")

        return PruneResult(lines=lines, out_path=payload.out_path)


class PruneProducer(BaseProducer):
    def _produce_success(self, payload: PruneResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        out = payload.out_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(payload.lines) + "\n", encoding="utf-8")
        print(f"Wrote {out}")


# -----------------------------------------------------------------------------
# Analyze layout pipeline
# -----------------------------------------------------------------------------


@dataclass
class AnalyzeRequest:
    layout: Optional[str]
    backup: Optional[str]
    plan_path: Optional[str]
    format: str = "text"  # "text" or "json"


AnalyzeRequestConsumer = RequestConsumer[AnalyzeRequest]


@dataclass
class AnalyzeResult:
    metrics: Dict[str, Any]
    format: str


class AnalyzeProcessor(SafeProcessor[AnalyzeRequest, AnalyzeResult]):
    def _process_safe(self, payload: AnalyzeRequest) -> AnalyzeResult:
        from .layout import analyze_layout

        try:
            layout = load_layout(payload.layout, payload.backup)
        except LayoutLoadError as err:
            raise err

        plan = None
        if payload.plan_path:
            try:
                plan = read_yaml(Path(payload.plan_path))
            except FileNotFoundError:
                raise ValueError(f"Plan not found: {payload.plan_path}")

        metrics = analyze_layout(layout, plan)
        return AnalyzeResult(metrics=metrics, format=payload.format)


class AnalyzeProducer(BaseProducer):
    def _produce_success(self, payload: AnalyzeResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        metrics = payload.metrics

        if payload.format == "json":
            import json
            print(json.dumps(metrics, indent=2))
            return

        # Text output
        print("Layout Summary")
        print(f"Dock: {metrics['dock_count']} apps")
        if metrics.get("dock"):
            print("  - " + ", ".join(metrics["dock"]))
        print(f"Pages: {metrics['pages_count']}")
        for p in metrics.get("pages", []):
            print(f"  Page {p['page']}: {p['root_apps']} apps, {p['folders']} folders (items {p['items_total']})")
        print(f"Folders: {metrics['totals']['folders']}")
        if metrics.get("folders"):
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


# -----------------------------------------------------------------------------
# Device I/O pipelines (export-device, iconmap)
# -----------------------------------------------------------------------------


@dataclass
class ExportDeviceRequest:
    udid: Optional[str]
    ecid: Optional[str]
    out_path: Path


ExportDeviceRequestConsumer = RequestConsumer[ExportDeviceRequest]


@dataclass
class ExportDeviceResult:
    document: Dict[str, Any]
    out_path: Path


class ExportDeviceProcessor(SafeProcessor[ExportDeviceRequest, ExportDeviceResult]):
    def _process_safe(self, payload: ExportDeviceRequest) -> ExportDeviceResult:
        from .device import find_cfgutil_path, map_udid_to_ecid, export_from_device

        try:
            cfgutil = find_cfgutil_path()
        except FileNotFoundError as e:
            raise e

        ecid = payload.ecid
        if not ecid and payload.udid:
            ecid = map_udid_to_ecid(cfgutil, payload.udid) or None

        try:
            export = export_from_device(cfgutil, ecid)
        except RuntimeError as e:
            raise e

        if not export:
            raise ValueError("Could not derive export from device layout")

        return ExportDeviceResult(document=export, out_path=payload.out_path)


class ExportDeviceProducer(BaseProducer):
    def _produce_success(self, payload: ExportDeviceResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        payload.out_path.parent.mkdir(parents=True, exist_ok=True)
        write_yaml(payload.document, payload.out_path)
        print(f"Wrote layout export to {payload.out_path}")


@dataclass
class IconmapRequest:
    udid: Optional[str]
    ecid: Optional[str]
    format: str  # "json" or "plist"
    out_path: Path


IconmapRequestConsumer = RequestConsumer[IconmapRequest]


@dataclass
class IconmapResult:
    data: bytes
    out_path: Path


class IconmapProcessor(SafeProcessor[IconmapRequest, IconmapResult]):
    def _process_safe(self, payload: IconmapRequest) -> IconmapResult:
        import subprocess as _sp  # nosec B404
        from .device import find_cfgutil_path, map_udid_to_ecid

        try:
            cfgutil = find_cfgutil_path()
        except FileNotFoundError as e:
            raise e

        ecid = payload.ecid
        if not ecid and payload.udid:
            ecid = map_udid_to_ecid(cfgutil, payload.udid) or None

        cmd = [cfgutil]
        if ecid:
            cmd.extend(["--ecid", ecid])
        cmd.extend(["--format", payload.format, "get-icon-layout"])

        try:
            out = _sp.check_output(cmd, stderr=_sp.STDOUT)  # nosec B603 - trusted Apple cfgutil with validated args
        except _sp.CalledProcessError as e:
            raise ValueError(f"cfgutil get-icon-layout failed: {e}")
        except Exception as e:
            raise ValueError(f"cfgutil get-icon-layout failed: {e}")

        return IconmapResult(data=out, out_path=payload.out_path)


class IconmapProducer(BaseProducer):
    def _produce_success(self, payload: IconmapResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        payload.out_path.parent.mkdir(parents=True, exist_ok=True)
        payload.out_path.write_bytes(payload.data)
        print(f"Wrote icon map to {payload.out_path}")


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
    manifest: Dict[str, Any]
    out_path: Path


class ManifestFromExportProcessor(SafeProcessor[ManifestFromExportRequest, ManifestFromExportResult]):
    def _process_safe(self, payload: ManifestFromExportRequest) -> ManifestFromExportResult:
        try:
            exp = read_yaml(payload.export_path)
        except FileNotFoundError:
            raise ValueError(f"Export not found: {payload.export_path}")

        if not isinstance(exp, dict) or "dock" not in exp or "pages" not in exp:
            raise ValueError("Export file must contain 'dock' and 'pages' keys")

        manifest = _build_manifest_from_export(exp, str(payload.export_path))
        return ManifestFromExportResult(manifest=manifest, out_path=payload.out_path)


class ManifestFromExportProducer(BaseProducer):
    def _produce_success(self, payload: ManifestFromExportResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        write_yaml(payload.manifest, payload.out_path)
        print(f"Wrote device layout manifest to {payload.out_path}")


@dataclass
class ManifestFromDeviceRequest:
    udid: Optional[str]
    export_out: Optional[Path]
    out_path: Path


ManifestFromDeviceRequestConsumer = RequestConsumer[ManifestFromDeviceRequest]


@dataclass
class ManifestFromDeviceResult:
    manifest: Dict[str, Any]
    out_path: Path
    export_out: Optional[Path]
    export_document: Optional[Dict[str, Any]]


class ManifestFromDeviceProcessor(SafeProcessor[ManifestFromDeviceRequest, ManifestFromDeviceResult]):
    def _process_safe(self, payload: ManifestFromDeviceRequest) -> ManifestFromDeviceResult:
        import os
        from .device import find_cfgutil_path, map_udid_to_ecid, export_from_device

        try:
            cfgutil = find_cfgutil_path()
        except FileNotFoundError as e:
            raise e

        udid = payload.udid or os.environ.get("IOS_DEVICE_UDID")
        ecid = map_udid_to_ecid(cfgutil, udid) if udid else None

        try:
            exp = export_from_device(cfgutil, ecid)
        except RuntimeError as e:
            raise e

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
    def _produce_success(self, payload: ManifestFromDeviceResult, diagnostics: Optional[Dict[str, Any]]) -> None:
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
    out_path: Optional[Path]
    dry_run: bool
    udid: Optional[str]
    device_label: Optional[str]
    creds_profile: Optional[str]
    config: Optional[str]


ManifestInstallRequestConsumer = RequestConsumer[ManifestInstallRequest]


@dataclass
class ManifestInstallResult:
    profile_path: Path
    profile_bytes: bytes
    dry_run: bool
    install_cmd: Optional[List[str]]


class ManifestInstallProcessor(SafeProcessor[ManifestInstallRequest, ManifestInstallResult]):
    def _process_safe(self, payload: ManifestInstallRequest) -> ManifestInstallResult:
        import os
        import plistlib
        from .profile import build_mobileconfig

        try:
            man = read_yaml(payload.manifest_path)
        except FileNotFoundError:
            raise ValueError(f"Manifest not found: {payload.manifest_path}")

        if not isinstance(man, dict):
            raise ValueError("Invalid manifest")

        # Build plan from manifest
        plan = man.get("plan") or {}
        if not plan and man.get("layout"):
            plan = _plan_from_layout(man.get("layout") or {})
        if not plan:
            raise ValueError("Manifest missing 'plan' or 'layout' section")

        prof = man.get("profile") or {}
        profile_dict = build_mobileconfig(
            plan=plan,
            layout_export=None,
            top_identifier=prof.get("identifier", "com.example.profile"),
            hs_identifier=prof.get("hs_identifier", "com.example.hslayout"),
            display_name=prof.get("display_name", "Home Screen Layout"),
            organization=prof.get("organization"),
            dock_count=4,
        )

        # Determine output profile path
        if payload.out_path:
            out_path = payload.out_path
        else:
            dev = man.get("device") or {}
            suffix = dev.get("label") or dev.get("udid") or "device"
            out_path = Path("out") / f"{suffix}.hslayout.from_manifest.mobileconfig"

        # Serialize profile
        profile_bytes = plistlib.dumps(profile_dict, fmt=plistlib.FMT_XML, sort_keys=False)

        # Build install command if not dry-run
        install_cmd: Optional[List[str]] = None
        if not payload.dry_run:
            dev = man.get("device") or {}
            udid = payload.udid or dev.get("udid") or os.environ.get("IOS_DEVICE_UDID")
            label = payload.device_label or dev.get("label") or os.environ.get("IOS_DEVICE_LABEL")
            creds_profile = payload.creds_profile or dev.get("creds_profile") or os.environ.get("IOS_CREDS_PROFILE")

            repo_root = Path(__file__).resolve().parents[1]
            installer = str(repo_root / "bin" / "ios-install-profile")
            cmd = [installer, "--profile", str(out_path)]
            if creds_profile:
                cmd.extend(["--creds-profile", creds_profile])
            if payload.config:
                cmd.extend(["--config", payload.config])
            if udid:
                cmd.extend(["--udid", udid])
            elif label:
                cmd.extend(["--device-label", label])
            install_cmd = cmd

        return ManifestInstallResult(
                profile_path=out_path,
                profile_bytes=profile_bytes,
                dry_run=payload.dry_run,
                install_cmd=install_cmd,
            )


class ManifestInstallProducer(BaseProducer):
    def _produce_success(self, payload: ManifestInstallResult, diagnostics: Optional[Dict[str, Any]]) -> None:
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


def _plan_from_layout(layout_obj: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a layout object to a plan format."""
    plan: Dict[str, Any] = {"dock": list(layout_obj.get("dock") or []), "pages": {}, "folders": {}}
    pages = layout_obj.get("pages") or []
    page_map: Dict[int, Dict[str, Any]] = {}
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
    p12_path: Optional[str]
    p12_pass: Optional[str]
    creds_profile: Optional[str]
    config: Optional[str]
    device_label: Optional[str]
    udid: Optional[str]
    expected_org: Optional[str]


IdentityVerifyRequestConsumer = RequestConsumer[IdentityVerifyRequest]


@dataclass
class IdentityVerifyResult:
    p12_path: str
    cert_subject: str
    cert_issuer: str
    udid: Optional[str]
    supervised: Optional[str]
    expected_org: Optional[str]
    org_match: Optional[bool]


class IdentityVerifyProcessor(SafeProcessor[IdentityVerifyRequest, IdentityVerifyResult]):
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
        creds_profile = payload.creds_profile or os.environ.get("IOS_CREDS_PROFILE", "ios_layout_manager")

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
        org_match: Optional[bool] = None
        if payload.expected_org:
            org_match = (payload.expected_org in cert.subject) or (payload.expected_org in cert.issuer)

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
    def _produce_success(self, payload: IdentityVerifyResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        print("Identity Verification Summary")
        print(f"- p12: {payload.p12_path}")
        print(f"- cert.subject: {payload.cert_subject or '(unknown)'}")
        print(f"- cert.issuer:  {payload.cert_issuer or '(unknown)'}")
        if payload.expected_org:
            print(f"- expected org '{payload.expected_org}': {'MATCH' if payload.org_match else 'NO MATCH'}")
        print(f"- device.udid: {payload.udid or '(not provided)'}")
        print(f"- device.supervised: {payload.supervised or '(unknown)'}")
        print("")
        print("Next steps:")
        print("- Ensure the device shows 'Supervised by <Org>' matching the certificate subject/issuer above.")
        print("- If they match, no-touch installs should succeed using this identity.")
        print("- If they do not match, Prepare again under the correct Organization, or export the matching Supervision Identity.")


# -----------------------------------------------------------------------------
# Helper
# -----------------------------------------------------------------------------


def _read_lines_file(path: Optional[str]) -> List[str]:
    """Read non-empty, non-comment lines from a file."""
    if not path:
        return []
    p = Path(path).expanduser()
    if not p.exists():
        return []
    try:
        return [
            ln.strip()
            for ln in p.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
    except Exception:
        return []
