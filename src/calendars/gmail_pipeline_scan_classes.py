"""Gmail scan-classes pipeline for calendar assistant."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.pipeline import SafeProcessor
from core.text_utils import html_to_text

from .gmail_service import QueryParams
from .scan_common import RANGE_PAT, MONTH_MAP, norm_time as _norm_time_common, infer_meta_from_text
from .pipeline_base import (
    BaseProducer,
    GmailAuth,
    GmailServiceBuilderMixin,
    RequestConsumer,
    dedupe_events,
    DAY_MAP,
)


# =============================================================================
# Gmail Scan Classes Pipeline
# =============================================================================

@dataclass
class GmailScanClassesRequest:
    auth: GmailAuth
    from_text: str | None
    query: str | None
    days: int
    pages: int
    page_size: int
    inbox_only: bool
    calendar: str | None
    out_path: Path | None


GmailScanClassesRequestConsumer = RequestConsumer[GmailScanClassesRequest]


@dataclass
class GmailScanClassesResult:
    events: list[dict[str, Any]]
    message_count: int
    out_path: Path | None


class GmailScanClassesProcessor(
    GmailServiceBuilderMixin, SafeProcessor[GmailScanClassesRequest, GmailScanClassesResult]
):
    def __init__(self, service_builder=None) -> None:
        from .scan_common import MetaParserConfig

        super().__init__(service_builder)
        self._day_map = DAY_MAP
        self._range_pat = RANGE_PAT
        self._month_map = MONTH_MAP
        self._meta_config = MetaParserConfig()

    def _process_safe(self, payload: GmailScanClassesRequest) -> GmailScanClassesResult:
        svc = self._service_builder(payload.auth)
        ids = svc.query_and_list_ids(
            QueryParams(
                explicit=payload.query,
                from_text=payload.from_text,
                days=payload.days,
                inbox_only=payload.inbox_only,
            ),
            max_pages=payload.pages,
            page_size=payload.page_size,
        )
        if not ids:
            return GmailScanClassesResult(events=[], message_count=0, out_path=payload.out_path)
        extracted: list[dict[str, Any]] = []
        for mid in ids:
            try:
                text = svc.get_message_text(mid)
            except Exception:  # nosec B112 - skip unreadable messages
                continue
            extracted.extend(self._extract_events(text, payload.calendar))
        events = dedupe_events(extracted)
        if not events:
            return GmailScanClassesResult(events=[], message_count=len(ids), out_path=payload.out_path)
        return GmailScanClassesResult(events=events, message_count=len(ids), out_path=payload.out_path)

    def _extract_events(self, message_text: str, calendar: str | None) -> list[dict[str, Any]]:
        plain = self._html_to_text(message_text)
        matches = list(self._range_pat.finditer(plain))
        if not matches:
            return []
        meta = self._infer_meta(plain)
        events: list[dict[str, Any]] = []
        for match in matches:
            day_raw = (match.group("day") or "").lower()
            byday = [self._day_map.get(day_raw, day_raw[:2].upper())]
            start_time = self._norm_time(match.group("h1"), match.group("m1"), match.group("ampm1"))
            end_time = self._norm_time(match.group("h2"), match.group("m2"), match.group("ampm2"))
            ev: dict[str, Any] = {
                "calendar": calendar,
                "subject": "Class",
                "repeat": "weekly",
                "byday": byday,
                "start_time": start_time,
                "end_time": end_time,
            }
            if meta.get("subject"):
                ev["subject"] = meta["subject"]
            if meta.get("location"):
                ev["location"] = meta["location"]
            if meta.get("range"):
                ev.setdefault("range", {}).update(meta["range"])
            events.append(ev)
        return events

    def _html_to_text(self, html: str) -> str:
        return html_to_text(html)

    def _norm_time(self, hour: str, minute: str | None, ampm: str | None) -> str:
        return _norm_time_common(hour, minute, ampm)

    def _infer_meta(self, text: str) -> dict[str, Any]:
        return infer_meta_from_text(text, config=self._meta_config)


class GmailScanClassesProducer(BaseProducer):
    def _produce_success(self, payload: GmailScanClassesResult, diagnostics: dict[str, Any] | None) -> None:
        events = payload.events
        if not events:
            if payload.message_count:
                self._writer.print("No schedule-like lines found in matching emails.")
            else:
                self._writer.print("No matching messages found.")
            if not payload.out_path:
                self._writer.print("Use --out plan.yaml to write YAML.")
            return
        self._writer.print(f"Found {len(events)} candidate recurring class entries from {payload.message_count} messages.")
        if payload.out_path:
            from core.yamlio import dump_config

            dump_config(str(payload.out_path), {"events": events})
            self._writer.print(f"Wrote plan to {payload.out_path}")
            return
        for ev in events:
            byday = ",".join(ev.get("byday") or [])
            self._writer.print(f"- {byday} {ev.get('start_time')}-{ev.get('end_time')} calendar={ev.get('calendar') or '<default>'}")
        self._writer.print("Use --out plan.yaml to write YAML.")
