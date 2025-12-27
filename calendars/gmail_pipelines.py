"""Gmail pipeline components for calendar assistant.

Provides pipelines for scanning Gmail for receipts, classes, and sender analysis.
"""
from __future__ import annotations

import collections
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.pipeline import Processor, ResultEnvelope

from .gmail_service import GmailService
from .text_utils import to_24h, extract_email_address
from core.text_utils import html_to_text
from .scan_common import (
    DAY_MAP,
    RANGE_PAT,
    CLASS_PAT,
    LOC_LABEL_PAT,
    FACILITIES,
    MONTH_MAP,
    DATE_RANGE_PAT,
    norm_time as _norm_time_common,
    infer_meta_from_text,
)
from .pipeline_base import (
    BaseProducer,
    GmailAuth,
    GmailServiceBuilder,
    RequestConsumer,
    dedupe_events,
    parse_month,
    DAY_TO_CODE,
)


# =============================================================================
# Gmail Receipts Pipeline
# =============================================================================

@dataclass
class GmailReceiptsRequest:
    auth: GmailAuth
    query: Optional[str]
    from_text: Optional[str]
    days: int
    pages: int
    page_size: int
    calendar: Optional[str]
    out_path: Path


GmailReceiptsRequestConsumer = RequestConsumer[GmailReceiptsRequest]


@dataclass
class GmailPlanResult:
    document: Dict[str, Sequence[Dict[str, object]]]
    out_path: Path


class GmailReceiptsProcessor(Processor[GmailReceiptsRequest, ResultEnvelope[GmailPlanResult]]):
    def __init__(self, service_builder=None) -> None:
        self._service_builder = service_builder or self._default_service_builder

    def _default_service_builder(self, auth: GmailAuth):
        return GmailServiceBuilder.build(auth, service_cls=GmailService)

    def process(self, payload: GmailReceiptsRequest) -> ResultEnvelope[GmailPlanResult]:
        try:
            svc = self._service_builder(payload.auth)
        except Exception as exc:  # pragma: no cover - passthrough
            return ResultEnvelope(status="error", diagnostics={"message": f"Gmail auth error: {exc}", "code": 1})

        query = GmailService.build_receipts_query(
            from_text=payload.from_text,
            days=payload.days,
            explicit=payload.query,
        )
        try:
            ids = svc.list_message_ids(query=query, max_pages=payload.pages, page_size=payload.page_size)
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Gmail list error: {exc}", "code": 2})
        if not ids:
            return ResultEnvelope(
                status="success",
                payload=GmailPlanResult(document={"events": []}, out_path=payload.out_path),
            )
        events = self._parse_receipts(svc, ids, payload.calendar)
        if not events:
            return ResultEnvelope(
                status="success",
                payload=GmailPlanResult(document={"events": []}, out_path=payload.out_path),
            )

        # Dedupe with child field included
        def key_fn(ev):
            return (
                ev.get("subject"),
                tuple(ev.get("byday") or []),
                ev.get("start_time"),
                ev.get("end_time"),
                (ev.get("range") or {}).get("start_date"),
                (ev.get("range") or {}).get("until"),
                ev.get("location"),
                ev.get("child"),
            )
        uniq = dedupe_events(events, key_fn)
        return ResultEnvelope(
            status="success",
            payload=GmailPlanResult(document={"events": uniq}, out_path=payload.out_path),
        )

    def _parse_receipts(self, svc, ids: List[str], calendar: Optional[str]):
        cls_pat = re.compile(r"Enrollment\s+in\s+(?P<cls>[A-Za-z][A-Za-z0-9 \-/+]+?)\s*(?:\(#|\(|-|\r|\n)", re.I)
        reg_pat_1 = re.compile(r"Registrant:\s*(?:\r?\n\s*)?(?P<name>[A-Za-z][A-Za-z\s'\-]+)", re.I)
        reg_pat_2 = re.compile(r"Order\s+Summary:\s*(?P<name>[A-Za-z][A-Za-z\s'\-]+?)\s+Enrollment\s+in", re.I)
        dates_pat = re.compile(r"Meeting\s+Dates:\s*From\s+(?P<m1>[A-Za-z]{3,9})\s+(?P<d1>\d{1,2}),\s*(?P<y1>\d{4})\s+to\s+(?P<m2>[A-Za-z]{3,9})\s+(?P<d2>\d{1,2}),\s*(?P<y2>\d{4})", re.I)
        sched_pat = re.compile(r"Each\s+(?P<day>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+from\s+(?P<t1>\d{1,2}:\d{2}\s*(?:am|pm))\s+to\s+(?P<t2>\d{1,2}:\d{2}\s*(?:am|pm))", re.I)
        loc_pat = re.compile(r"Location:\s*(?P<loc>.+)", re.I)

        events = []
        for mid in ids:
            try:
                text = svc.get_message_text(mid)
            except Exception:  # noqa: S112 - skip unreadable messages
                continue
            m_cls = cls_pat.search(text or "")
            m_dates = dates_pat.search(text or "")
            m_sched = sched_pat.search(text or "")
            m_loc = loc_pat.search(text or "")
            m_reg = reg_pat_1.search(text or "") or reg_pat_2.search(text or "")
            if not (m_cls and m_dates and m_sched):
                continue
            loc_hint = m_loc.group("loc") if m_loc else None
            cls = self._normalize_subject(m_cls.group("cls"), loc_hint)
            m1, d1, y1 = m_dates.group("m1"), int(m_dates.group("d1")), int(m_dates.group("y1"))
            m2, d2, y2 = m_dates.group("m2"), int(m_dates.group("d2")), int(m_dates.group("y2"))
            m1v = parse_month(m1)
            m2v = parse_month(m2)
            if not (m1v and m2v):
                continue
            start_date = f"{y1:04d}-{m1v:02d}-{d1:02d}"
            until = f"{y2:04d}-{m2v:02d}-{d2:02d}"
            day = DAY_TO_CODE[(m_sched.group("day") or "").lower()]
            t1 = to_24h(m_sched.group("t1"))
            t2 = to_24h(m_sched.group("t2"))
            loc = (m_loc.group("loc").strip() if m_loc else None)
            child_full = None
            child_first = None
            if m_reg:
                child_full = (m_reg.group("name") or "").strip()
                child_first = child_full.split()[0].title() if child_full else None
            ev = {
                "calendar": calendar,
                "subject": cls,
                "repeat": "weekly",
                "byday": [day],
                "start_time": t1,
                "end_time": t2,
                "range": {"start_date": start_date, "until": until},
            }
            if loc:
                ev["location"] = loc
            if child_first:
                ev["child"] = child_first
                ev["child_full"] = child_full
            events.append(ev)
        return events

    def _normalize_subject(self, raw: Optional[str], loc_hint: Optional[str]) -> str:
        base = (raw or "").strip().split(" - ", 1)[0].strip()
        lower = base.lower()
        if lower.startswith("swimmer "):
            return base.title()
        if lower.startswith("swim kids"):
            return base.title()
        if lower.startswith("chess"):
            return "Chess"
        if lower == "c":
            return "Chess"
        if lower == "s":
            if loc_hint and "pool" in loc_hint.lower():
                return "Swimmer"
            return "Sports"
        return base.title()


class GmailPlanProducer(BaseProducer):
    def _produce_success(self, payload: GmailPlanResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        from calendars.yamlio import dump_config

        dump_config(str(payload.out_path), payload.document)
        events = payload.document.get("events", [])
        print(f"Wrote {len(events)} events to {payload.out_path}")


# =============================================================================
# Gmail Scan Classes Pipeline
# =============================================================================

@dataclass
class GmailScanClassesRequest:
    auth: GmailAuth
    from_text: Optional[str]
    query: Optional[str]
    days: int
    pages: int
    page_size: int
    inbox_only: bool
    calendar: Optional[str]
    out_path: Optional[Path]


GmailScanClassesRequestConsumer = RequestConsumer[GmailScanClassesRequest]


@dataclass
class GmailScanClassesResult:
    events: List[Dict[str, Any]]
    message_count: int
    out_path: Optional[Path]


class GmailScanClassesProcessor(Processor[GmailScanClassesRequest, ResultEnvelope[GmailScanClassesResult]]):
    def __init__(self, service_builder=None) -> None:
        self._service_builder = service_builder or self._default_service_builder
        self._day_map = DAY_MAP
        self._range_pat = RANGE_PAT
        self._class_pat = CLASS_PAT
        self._loc_label_pat = LOC_LABEL_PAT
        self._facilities = FACILITIES
        self._month_map = MONTH_MAP
        self._date_range_pat = DATE_RANGE_PAT

    def _default_service_builder(self, auth: GmailAuth):
        return GmailServiceBuilder.build(auth)

    def process(self, payload: GmailScanClassesRequest) -> ResultEnvelope[GmailScanClassesResult]:
        try:
            svc = self._service_builder(payload.auth)
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Gmail auth error: {exc}", "code": 1})
        query = GmailService.build_query(
            explicit=payload.query,
            from_text=payload.from_text,
            days=payload.days,
            inbox_only=payload.inbox_only,
        )
        try:
            ids = svc.list_message_ids(query=query, max_pages=payload.pages, page_size=payload.page_size)
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Gmail list error: {exc}", "code": 2})
        if not ids:
            result = GmailScanClassesResult(events=[], message_count=0, out_path=payload.out_path)
            return ResultEnvelope(status="success", payload=result)
        extracted: List[Dict[str, Any]] = []
        for mid in ids:
            try:
                text = svc.get_message_text(mid)
            except Exception:  # noqa: S112 - skip unreadable messages
                continue
            extracted.extend(self._extract_events(text, payload.calendar))
        events = dedupe_events(extracted)
        if not events:
            result = GmailScanClassesResult(events=[], message_count=len(ids), out_path=payload.out_path)
            return ResultEnvelope(status="success", payload=result)
        result = GmailScanClassesResult(events=events, message_count=len(ids), out_path=payload.out_path)
        return ResultEnvelope(status="success", payload=result)

    def _extract_events(self, message_text: str, calendar: Optional[str]) -> List[Dict[str, Any]]:
        plain = self._html_to_text(message_text)
        matches = list(self._range_pat.finditer(plain))
        if not matches:
            return []
        meta = self._infer_meta(plain)
        events: List[Dict[str, Any]] = []
        for match in matches:
            day_raw = (match.group("day") or "").lower()
            byday = [self._day_map.get(day_raw, day_raw[:2].upper())]
            start_time = self._norm_time(match.group("h1"), match.group("m1"), match.group("ampm1"))
            end_time = self._norm_time(match.group("h2"), match.group("m2"), match.group("ampm2"))
            ev: Dict[str, Any] = {
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

    def _norm_time(self, hour: str, minute: Optional[str], ampm: Optional[str]) -> str:
        return _norm_time_common(hour, minute, ampm)

    def _infer_meta(self, text: str) -> Dict[str, Any]:
        return infer_meta_from_text(
            text,
            facilities=self._facilities,
            date_range_pat=self._date_range_pat,
            class_pat=self._class_pat,
            loc_label_pat=self._loc_label_pat,
        )


class GmailScanClassesProducer(BaseProducer):
    def _produce_success(self, payload: GmailScanClassesResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        events = payload.events
        if not events:
            if payload.message_count:
                print("No schedule-like lines found in matching emails.")
            else:
                print("No matching messages found.")
            if not payload.out_path:
                print("Use --out plan.yaml to write YAML.")
            return
        print(f"Found {len(events)} candidate recurring class entries from {payload.message_count} messages.")
        if payload.out_path:
            from calendars.yamlio import dump_config

            dump_config(str(payload.out_path), {"events": events})
            print(f"Wrote plan to {payload.out_path}")
            return
        for ev in events:
            byday = ",".join(ev.get("byday") or [])
            print(f"- {byday} {ev.get('start_time')}-{ev.get('end_time')} calendar={ev.get('calendar') or '<default>'}")
        print("Use --out plan.yaml to write YAML.")


# =============================================================================
# Gmail Mail List Pipeline
# =============================================================================

@dataclass
class GmailMailListRequest:
    auth: GmailAuth
    query: Optional[str]
    from_text: Optional[str]
    days: int
    pages: int
    page_size: int
    inbox_only: bool


GmailMailListRequestConsumer = RequestConsumer[GmailMailListRequest]


@dataclass
class GmailMailListResult:
    messages: List[Dict[str, str]]


class GmailMailListProcessor(Processor[GmailMailListRequest, ResultEnvelope[GmailMailListResult]]):
    def __init__(self, service_builder=None) -> None:
        self._service_builder = service_builder or self._default_service_builder

    def _default_service_builder(self, auth: GmailAuth):
        return GmailServiceBuilder.build(auth)

    def process(self, payload: GmailMailListRequest) -> ResultEnvelope[GmailMailListResult]:
        try:
            svc = self._service_builder(payload.auth)
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Gmail auth error: {exc}", "code": 1})
        query = GmailService.build_query(
            explicit=payload.query,
            from_text=payload.from_text,
            days=payload.days,
            inbox_only=payload.inbox_only,
        )
        try:
            ids = svc.list_message_ids(query=query, max_pages=payload.pages, page_size=payload.page_size)
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"List error: {exc}", "code": 2})
        if not ids:
            result = GmailMailListResult(messages=[])
            return ResultEnvelope(status="success", payload=result)
        messages: List[Dict[str, str]] = []
        for mid in ids:
            try:
                text = svc.get_message_text(mid)
            except Exception as exc:
                messages.append({"id": mid, "snippet": f"<failed to fetch: {exc}>"})
                continue
            first_line = (text or "").splitlines()[0] if text else ""
            messages.append({"id": mid, "snippet": first_line[:100]})
        result = GmailMailListResult(messages=messages)
        return ResultEnvelope(status="success", payload=result)


class GmailMailListProducer(BaseProducer):
    def _produce_success(self, payload: GmailMailListResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        messages = payload.messages
        if not messages:
            print("No messages matched.")
            return
        for msg in messages:
            print(f"- {msg.get('id')} | {msg.get('snippet')}")
        print(f"Listed {len(messages)} Gmail message(s).")


# =============================================================================
# Gmail Sweep Top Senders Pipeline
# =============================================================================

@dataclass
class GmailSweepTopRequest:
    auth: GmailAuth
    query: Optional[str]
    from_text: Optional[str]
    days: int
    pages: int
    page_size: int
    inbox_only: bool
    top: int
    out_path: Optional[Path]


GmailSweepTopRequestConsumer = RequestConsumer[GmailSweepTopRequest]


@dataclass
class GmailSweepTopResult:
    top_senders: List[Tuple[str, int]]
    freq_days: int
    inbox_only: bool
    out_path: Optional[Path]


class GmailSweepTopProcessor(Processor[GmailSweepTopRequest, ResultEnvelope[GmailSweepTopResult]]):
    def __init__(self, service_builder=None) -> None:
        self._service_builder = service_builder or self._default_service_builder

    def _default_service_builder(self, auth: GmailAuth):
        return GmailServiceBuilder.build(auth)

    def process(self, payload: GmailSweepTopRequest) -> ResultEnvelope[GmailSweepTopResult]:
        try:
            svc = self._service_builder(payload.auth)
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Gmail auth error: {exc}", "code": 1})
        query = GmailService.build_query(
            explicit=payload.query,
            from_text=payload.from_text,
            days=payload.days,
            inbox_only=payload.inbox_only,
        )
        try:
            ids = svc.list_message_ids(query=query, max_pages=payload.pages, page_size=payload.page_size)
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"List error: {exc}", "code": 2})
        if not ids:
            result = GmailSweepTopResult(top_senders=[], freq_days=payload.days, inbox_only=payload.inbox_only, out_path=payload.out_path)
            return ResultEnvelope(status="success", payload=result)
        freq = collections.Counter()
        for mid in ids:
            sender = None
            try:
                msg = svc.get_message(mid)
                payload_data = msg.get("payload") or {}
                headers = payload_data.get("headers") or []
                for header in headers:
                    if (header.get("name") or "").lower() == "from":
                        sender = extract_email_address(header.get("value") or "")
                        break
                if not sender and isinstance(msg, dict):
                    sender = extract_email_address(str(msg.get("from") or ""))
            except Exception:
                sender = None
            if not sender:
                continue
            freq[sender] += 1
        top = freq.most_common(max(1, payload.top))
        result = GmailSweepTopResult(
            top_senders=top,
            freq_days=payload.days,
            inbox_only=payload.inbox_only,
            out_path=payload.out_path,
        )
        return ResultEnvelope(status="success", payload=result)


class GmailSweepTopProducer(BaseProducer):
    def _produce_success(self, payload: GmailSweepTopResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        top = payload.top_senders
        if not top:
            print("No sender stats available.")
            return
        print(f"Top {len(top)} sender(s) in last {payload.freq_days}d (Inbox={payload.inbox_only}):")
        for sender, count in top:
            print(f"- {sender}: {count}")
        if payload.out_path:
            from calendars.yamlio import dump_config

            filters = []
            for sender, _ in top:
                filters.append(
                    {
                        "name": f"Auto-archive {sender}",
                        "provider": "gmail",
                        "query": f"from:{sender}",
                        "actions": {
                            "archive": True,
                            "mark_read": True,
                            "labels": ["Sweep/Auto-Archive"],
                        },
                    }
                )
            dump_config(str(payload.out_path), {"filters": filters})
            print(f"Wrote suggested Gmail filters to {payload.out_path}")
