"""Gmail scan-classes pipeline for calendar assistant."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.pipeline import SafeProcessor
from core.text_utils import html_to_text

from .gmail_service import GmailService, QueryParams
from .scan_common import (
    DEFAULT_CLASS_SUBJECT,
    RANGE_PAT,
    MONTH_MAP,
    infer_meta_from_text,
    is_enrollment_notice,
    is_plausible_session,
    norm_time as _norm_time_common,
    parse_clock_time,
)
from .pipeline_base import (
    BaseProducer,
    GmailAuth,
    GmailServiceBuilder,
    RequestConsumer,
    dedupe_events,
    DAY_MAP,
)


# Transfer notices restate the superseded enrollment alongside the new one.
# Everything from "New Enrollment:" onward is the authoritative block; the
# preceding text describes the slot the student is leaving.
_NEW_ENROLLMENT_PAT = re.compile(r"New\s+Enrollment:", re.I)

# Makeup-token notices reference a single dated makeup slot, not a recurring
# class, so they must not produce a weekly event.
_MAKEUP_TOKEN_PAT = re.compile(r"\bmakeup\s+token\b", re.I)


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


class GmailScanClassesProcessor(SafeProcessor[GmailScanClassesRequest, GmailScanClassesResult]):
    def __init__(self, service_builder=None) -> None:
        from .scan_common import MetaParserConfig

        self._service_builder = service_builder or self._default_service_builder
        self._day_map = DAY_MAP
        self._range_pat = RANGE_PAT
        self._month_map = MONTH_MAP
        self._meta_config = MetaParserConfig()

    def _default_service_builder(self, auth: GmailAuth):
        return GmailServiceBuilder.build(auth)

    def _process_safe(self, payload: GmailScanClassesRequest) -> GmailScanClassesResult:
        svc = self._service_builder(payload.auth)
        query = GmailService.build_query_from_params(QueryParams(
            explicit=payload.query,
            from_text=payload.from_text,
            days=payload.days,
            inbox_only=payload.inbox_only,
        ))
        ids = svc.list_message_ids(query=query, max_pages=payload.pages, page_size=payload.page_size)
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
        if _MAKEUP_TOKEN_PAT.search(plain):
            # A makeup token is a one-off dated slot, not a recurring class.
            return []
        if not is_enrollment_notice(plain):
            # Newsletters, marketing announcements, payment receipts and skills
            # reports all carry day/time text but enroll nobody.
            return []
        scope = self._authoritative_scope(plain)
        matches = list(self._range_pat.finditer(scope))
        if not matches:
            return []
        # Subject/child/location come from the whole body (headers and greeting
        # carry them), while times come only from the authoritative scope.
        meta = self._infer_meta(plain)
        events = (self._build_event(match, meta, calendar) for match in matches)
        return [ev for ev in events if ev is not None]

    def _authoritative_scope(self, plain: str) -> str:
        """Narrow a transfer notice to the enrollment that is actually in effect.

        Transfer emails restate the superseded enrollment before the new one, so
        parsing the full body emits the stale slot alongside the current one.
        """
        m_new = _NEW_ENROLLMENT_PAT.search(plain)
        return plain[m_new.end():] if m_new else plain

    def _build_event(
        self, match: re.Match[str], meta: dict[str, Any], calendar: str | None
    ) -> dict[str, Any] | None:
        """Assemble one recurring event, or None if the match is not a class.

        RANGE_PAT scans free-form prose, so a match can pair digits that are not
        clock times or two unrelated times far apart. Both are dropped rather
        than emitted with clamped values, since a silently corrected time is
        indistinguishable from a real one downstream.
        """
        start_time = parse_clock_time(
            match.group("h1"), match.group("m1"), match.group("ampm1")
        )
        end_time = parse_clock_time(
            match.group("h2"), match.group("m2"), match.group("ampm2")
        )
        if not (start_time and end_time):
            return None
        if not is_plausible_session(start_time, end_time):
            return None
        day_raw = (match.group("day") or "").lower()
        ev: dict[str, Any] = {
            "calendar": calendar,
            "subject": meta.get("subject") or DEFAULT_CLASS_SUBJECT,
            "repeat": "weekly",
            "byday": [self._day_map.get(day_raw, day_raw[:2].upper())],
            "start_time": start_time,
            "end_time": end_time,
        }
        if meta.get("child"):
            ev["child"] = meta["child"]
        if meta.get("location"):
            ev["location"] = meta["location"]
        if meta.get("range"):
            ev.setdefault("range", {}).update(meta["range"])
        return ev

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
