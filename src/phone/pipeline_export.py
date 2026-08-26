"""Phone pipeline components for layout export, plan, checklist, unused, prune, analyze, and device I/O."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.cli_output import emit_one
from core.paths import output_dir
from core.pipeline import (
    BaseProducer as _CoreBaseProducer,
    RequestConsumer,
    ResultEnvelope,
    SafeProcessor,
)

from .helpers import load_layout, read_lines_file, read_yaml, write_yaml
from .layout_normalize import to_yaml_export
from .layout_plan_scaffold import checklist_from_plan, scaffold_plan


def _collect_unique_app(app_id: str, seen: set, all_apps: list[str]) -> None:
    """Add an app to the all_apps list if not already seen."""
    if app_id and app_id not in seen:
        seen.add(app_id)
        all_apps.append(app_id)


def _process_page_folders(
    folders_in: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Process folders from a page and return normalized folders list and count."""
    folders_out = []
    for f in folders_in:
        name = f.get("name") or "Folder"
        fapps = list(f.get("apps") or [])
        folders_out.append({"name": name, "apps": fapps})
    return folders_out, len(folders_out)


def _process_pages(
    pages_in: list[dict[str, Any]],
    seen: set,
    all_apps: list[str],
) -> tuple[list[dict[str, Any]], int]:
    """Process pages and collect unique apps, returning normalized pages and folder count."""
    pages_out: list[dict[str, Any]] = []
    folders_total = 0

    for p in pages_in:
        apps = list(p.get("apps") or [])
        folders, folder_count = _process_page_folders(p.get("folders") or [])
        folders_total += folder_count
        pages_out.append({"apps": apps, "folders": folders})

        page_app_ids = apps + [a for f in folders for a in f["apps"]]
        for a in page_app_ids:
            _collect_unique_app(a, seen, all_apps)

    return pages_out, folders_total


def _build_manifest_from_export(
    exp: dict[str, Any],
    export_path: str,
) -> dict[str, Any]:
    """Build a manifest dict from raw export data.

    Args:
        exp: Raw export dict with 'dock' and 'pages' keys
        export_path: Path string for source attribution

    Returns:
        Manifest dict with meta, device, layout, apps, counts, and source
    """
    import os

    dock = list(exp.get("dock") or [])
    all_apps: list[str] = []
    seen: set = set()

    # Process pages and collect apps
    pages_out, folders_total = _process_pages(exp.get("pages") or [], seen, all_apps)

    # Collect dock apps
    for a in dock:
        _collect_unique_app(a, seen, all_apps)

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
    backup: str | None
    out_path: Path


# Type alias for backward compatibility
ExportRequestConsumer = RequestConsumer[ExportRequest]


@dataclass
class ExportResult:
    document: dict[str, Any]
    out_path: Path


class ExportProcessor(SafeProcessor[ExportRequest, ExportResult]):
    def _process_safe(self, payload: ExportRequest) -> ExportResult:
        layout = load_layout(None, payload.backup)
        export = to_yaml_export(layout)
        return ExportResult(document=export, out_path=payload.out_path)


class ExportProducer(BaseProducer):
    def _produce_success(
        self, payload: ExportResult, diagnostics: dict[str, Any] | None
    ) -> None:
        write_yaml(payload.document, payload.out_path)
        print(f"Wrote layout export to {payload.out_path}")


@dataclass
class PlanRequest:
    layout: str | None
    backup: str | None
    out_path: Path


PlanRequestConsumer = RequestConsumer[PlanRequest]


@dataclass
class PlanResult:
    document: dict[str, Any]
    out_path: Path


class PlanProcessor(SafeProcessor[PlanRequest, PlanResult]):
    def _process_safe(self, payload: PlanRequest) -> PlanResult:
        layout = load_layout(payload.layout, payload.backup)
        plan = scaffold_plan(layout)
        return PlanResult(document=plan, out_path=payload.out_path)


class PlanProducer(BaseProducer):
    def _produce_success(
        self, payload: PlanResult, diagnostics: dict[str, Any] | None
    ) -> None:
        write_yaml(payload.document, payload.out_path)
        print(f"Wrote plan scaffold to {payload.out_path}")


@dataclass
class ChecklistRequest:
    plan_path: Path
    layout: str | None
    backup: str | None
    out_path: Path


ChecklistRequestConsumer = RequestConsumer[ChecklistRequest]


@dataclass
class ChecklistResult:
    steps: list[str]
    out_path: Path


class ChecklistProcessor(SafeProcessor[ChecklistRequest, ChecklistResult]):
    def _process_safe(self, payload: ChecklistRequest) -> ChecklistResult:
        layout = load_layout(payload.layout, payload.backup)
        try:
            plan = read_yaml(payload.plan_path)
        except FileNotFoundError:
            raise ValueError(f"Plan not found: {payload.plan_path}")
        steps = checklist_from_plan(layout, plan)
        return ChecklistResult(steps=steps, out_path=payload.out_path)


class ChecklistProducer(BaseProducer):
    def _produce_success(
        self, payload: ChecklistResult, diagnostics: dict[str, Any] | None
    ) -> None:
        out = payload.out_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(payload.steps) + "\n", encoding="utf-8")
        print(f"Wrote checklist to {out}")


# -----------------------------------------------------------------------------
# Unused apps pipeline
# -----------------------------------------------------------------------------


@dataclass
class UnusedRequest:
    layout: str | None
    backup: str | None
    recent_path: str | None
    keep_path: str | None
    limit: int = 50
    threshold: float = 0.8
    format: str = "text"  # "text" or "csv"


UnusedRequestConsumer = RequestConsumer[UnusedRequest]


@dataclass
class UnusedResult:
    rows: list[tuple]  # (app_id, score, location)
    format: str


class UnusedProcessor(SafeProcessor[UnusedRequest, UnusedResult]):
    def _process_safe(self, payload: UnusedRequest) -> UnusedResult:
        from .layout_plan_analyze import rank_unused_candidates

        layout = load_layout(payload.layout, payload.backup)
        recent = read_lines_file(payload.recent_path)
        keep = read_lines_file(payload.keep_path)
        rows = rank_unused_candidates(layout, recent_ids=recent, keep_ids=keep)
        rows = [r for r in rows if r[1] >= payload.threshold][: payload.limit]

        return UnusedResult(rows=rows, format=payload.format)


class UnusedProducer(BaseProducer):
    def _produce_success(
        self, payload: UnusedResult, diagnostics: dict[str, Any] | None
    ) -> None:
        rows = payload.rows
        if payload.format == "csv":
            self._writer.print("app,score,location")
            for app, score, loc in rows:
                self._writer.print(f"{app},{score:.2f},{loc}")
        else:
            self._writer.print("Likely unused app candidates (heuristic):")
            self._writer.print("score  app                                   location")
            for app, score, loc in rows:
                self._writer.print(f"{score:4.1f}  {app:36}  {loc}")


# -----------------------------------------------------------------------------
# Prune checklist pipeline
# -----------------------------------------------------------------------------


@dataclass
class PruneRequest:
    layout: str | None
    backup: str | None
    recent_path: str | None
    keep_path: str | None
    limit: int = 50
    threshold: float = 1.0
    mode: str = "offload"  # "offload" or "delete"
    out_path: Path = field(default_factory=lambda: output_dir("phone") / "ios.unused.prune_checklist.txt")


PruneRequestConsumer = RequestConsumer[PruneRequest]


@dataclass
class PruneResult:
    lines: list[str]
    out_path: Path


class PruneProcessor(SafeProcessor[PruneRequest, PruneResult]):
    def _process_safe(self, payload: PruneRequest) -> PruneResult:
        from .layout_plan_analyze import rank_unused_candidates

        layout = load_layout(payload.layout, payload.backup)
        recent = read_lines_file(payload.recent_path)
        keep = read_lines_file(payload.keep_path)
        rows = rank_unused_candidates(layout, recent_ids=recent, keep_ids=keep)
        rows = [r for r in rows if r[1] >= payload.threshold][: payload.limit]

        lines = []
        lines.append(f"Unused apps checklist — mode: {payload.mode.upper()}")
        lines.append("")
        lines.append("Instructions:")
        if payload.mode == "offload":
            lines.append(
                "1) Settings → General → iPhone Storage → search for app → Offload App"
            )
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
    def _produce_success(
        self, payload: PruneResult, diagnostics: dict[str, Any] | None
    ) -> None:
        out = payload.out_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(payload.lines) + "\n", encoding="utf-8")
        print(f"Wrote {out}")


# -----------------------------------------------------------------------------
# Analyze layout pipeline
# -----------------------------------------------------------------------------


@dataclass
class AnalyzeRequest:
    layout: str | None
    backup: str | None
    plan_path: str | None
    format: str = "text"  # "text" or "json"


AnalyzeRequestConsumer = RequestConsumer[AnalyzeRequest]


@dataclass
class AnalyzeResult:
    metrics: dict[str, Any]
    format: str


class AnalyzeProcessor(SafeProcessor[AnalyzeRequest, AnalyzeResult]):
    def _process_safe(self, payload: AnalyzeRequest) -> AnalyzeResult:
        from .layout_plan_analyze import analyze_layout

        layout = load_layout(payload.layout, payload.backup)
        plan = None
        if payload.plan_path:
            try:
                plan = read_yaml(Path(payload.plan_path))
            except FileNotFoundError:
                raise ValueError(f"Plan not found: {payload.plan_path}")

        metrics = analyze_layout(layout, plan)
        return AnalyzeResult(metrics=metrics, format=payload.format)


class AnalyzeProducer(BaseProducer):
    def _produce_success(
        self, payload: AnalyzeResult, diagnostics: dict[str, Any] | None
    ) -> None:
        metrics = payload.metrics

        if payload.format == "json":
            emit_one(metrics)
            return

        # Text output
        print("Layout Summary")
        print(f"Dock: {metrics['dock_count']} apps")
        if metrics.get("dock"):
            print("  - " + ", ".join(metrics["dock"]))
        print(f"Pages: {metrics['pages_count']}")
        for p in metrics.get("pages", []):
            print(
                f"  Page {p['page']}: {p['root_apps']} apps, {p['folders']} folders (items {p['items_total']})"
            )
        print(f"Folders: {metrics['totals']['folders']}")
        if metrics.get("folders"):
            top = sorted(
                metrics["folders"], key=lambda x: x.get("app_count", 0), reverse=True
            )[:5]
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
    udid: str | None
    ecid: str | None
    out_path: Path


ExportDeviceRequestConsumer = RequestConsumer[ExportDeviceRequest]


@dataclass
class ExportDeviceResult:
    document: dict[str, Any]
    out_path: Path


class ExportDeviceProcessor(SafeProcessor[ExportDeviceRequest, ExportDeviceResult]):
    def _process_safe(self, payload: ExportDeviceRequest) -> ExportDeviceResult:
        from .device import find_cfgutil_path, map_udid_to_ecid, export_from_device

        cfgutil = find_cfgutil_path()
        ecid = payload.ecid
        if not ecid and payload.udid:
            ecid = map_udid_to_ecid(cfgutil, payload.udid) or None

        export = export_from_device(cfgutil, ecid)

        if not export:
            raise ValueError("Could not derive export from device layout")

        return ExportDeviceResult(document=export, out_path=payload.out_path)


class ExportDeviceProducer(BaseProducer):
    def _produce_success(
        self, payload: ExportDeviceResult, diagnostics: dict[str, Any] | None
    ) -> None:
        payload.out_path.parent.mkdir(parents=True, exist_ok=True)
        write_yaml(payload.document, payload.out_path)
        print(f"Wrote layout export to {payload.out_path}")


@dataclass
class IconmapRequest:
    udid: str | None
    ecid: str | None
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

        cfgutil = find_cfgutil_path()
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
    def _produce_success(
        self, payload: IconmapResult, diagnostics: dict[str, Any] | None
    ) -> None:
        payload.out_path.parent.mkdir(parents=True, exist_ok=True)
        payload.out_path.write_bytes(payload.data)
        print(f"Wrote icon map to {payload.out_path}")
