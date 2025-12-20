from __future__ import annotations

"""Calendar assistant pipeline components (Gmail receipts, etc.)."""

import datetime as _dt
from collections import defaultdict
from dataclasses import dataclass
from html import unescape as _html_unescape
from pathlib import Path
import collections
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.pipeline import Consumer, Processor, Producer, ResultEnvelope
from core.auth import build_gmail_service as _build_gmail_service

from calendar_assistant.yamlio import load_config as _load_yaml
from calendar_assistant.model import normalize_event
from calendar_assistant.selection import compute_window, filter_events_by_day_time
from calendar_assistant.scan_common import (
    DAY_MAP,
    RANGE_PAT,
    CLASS_PAT,
    LOC_LABEL_PAT,
    FACILITIES,
    MONTH_MAP,
    DATE_RANGE_PAT,
    html_to_text as _html_to_text_common,
    norm_time as _norm_time_common,
    infer_meta_from_text,
)

from .gmail_service import GmailService
from .location_sync import LocationSync
from .text_utils import to_24h, extract_email_address

@dataclass
class GmailAuth:
    profile: Optional[str]
    credentials: Optional[str]
    token: Optional[str]
    cache_dir: Optional[str]


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


class GmailReceiptsRequestConsumer(Consumer[GmailReceiptsRequest]):
    def __init__(self, request: GmailReceiptsRequest) -> None:
        self._request = request

    def consume(self) -> GmailReceiptsRequest:  # pragma: no cover - trivial
        return self._request


@dataclass
class GmailPlanResult:
    document: Dict[str, Sequence[Dict[str, object]]]
    out_path: Path


class GmailReceiptsProcessor(Processor[GmailReceiptsRequest, ResultEnvelope[GmailPlanResult]]):
    def __init__(self, service_builder=None) -> None:
        self._service_builder = service_builder or self._default_service_builder

    def _default_service_builder(self, auth: GmailAuth):
        return _build_gmail_service(
            profile=auth.profile,
            cache_dir=auth.cache_dir,
            credentials_path=auth.credentials,
            token_path=auth.token,
            service_cls=GmailService,
        )

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
        uniq, seen = [], set()
        for ev in events:
            key = (
                ev.get("subject"),
                tuple(ev.get("byday") or []),
                ev.get("start_time"),
                ev.get("end_time"),
                (ev.get("range") or {}).get("start_date"),
                (ev.get("range") or {}).get("until"),
                ev.get("location"),
                ev.get("child"),
            )
            if key in seen:
                continue
            seen.add(key)
            uniq.append(ev)
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
        month_map = {m.lower(): i for i, m in enumerate(["January","February","March","April","May","June","July","August","September","October","November","December"], start=1)}
        month_map3 = {k[:3]: v for k, v in list(month_map.items())}
        day_to_code = {
            "monday": "MO","tuesday": "TU","wednesday": "WE","thursday": "TH","friday": "FR","saturday": "SA","sunday": "SU",
        }
        events = []
        for mid in ids:
            try:
                text = svc.get_message_text(mid)
            except Exception:
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
            m1v = month_map.get((m1 or "").strip().lower()) or month_map3.get((m1 or "").strip().lower()[:3])
            m2v = month_map.get((m2 or "").strip().lower()) or month_map3.get((m2 or "").strip().lower()[:3])
            if not (m1v and m2v):
                continue
            start_date = f"{y1:04d}-{m1v:02d}-{d1:02d}"
            until = f"{y2:04d}-{m2v:02d}-{d2:02d}"
            day = day_to_code[(m_sched.group("day") or "").lower()]
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


class GmailScanClassesRequestConsumer(Consumer[GmailScanClassesRequest]):
    def __init__(self, request: GmailScanClassesRequest) -> None:
        self._request = request

    def consume(self) -> GmailScanClassesRequest:  # pragma: no cover - trivial
        return self._request


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
        return _build_gmail_service(
            profile=auth.profile,
            cache_dir=auth.cache_dir,
            credentials_path=auth.credentials,
            token_path=auth.token,
        )

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
            except Exception:
                continue
            extracted.extend(self._extract_events(text, payload.calendar))
        events = self._dedupe_events(extracted)
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

    def _dedupe_events(self, events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        uniq: List[Dict[str, Any]] = []
        seen = set()
        for ev in events:
            key = (
                ev.get("subject"),
                tuple(ev.get("byday") or []),
                ev.get("start_time"),
                ev.get("end_time"),
                (ev.get("range") or {}).get("start_date"),
                (ev.get("range") or {}).get("until"),
                ev.get("location"),
            )
            if key in seen:
                continue
            seen.add(key)
            uniq.append(ev)
        return uniq

    def _html_to_text(self, html: str) -> str:
        return _html_to_text_common(html)

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


class GmailScanClassesProducer(Producer[ResultEnvelope[GmailScanClassesResult]]):
    def produce(self, result: ResultEnvelope[GmailScanClassesResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        assert result.payload is not None
        events = result.payload.events
        if not events:
            if result.payload.message_count:
                print("No schedule-like lines found in matching emails.")
            else:
                print("No matching messages found.")
            if not result.payload.out_path:
                print("Use --out plan.yaml to write YAML.")
            return
        print(f"Found {len(events)} candidate recurring class entries from {result.payload.message_count} messages.")
        if result.payload.out_path:
            from calendar_assistant.yamlio import dump_config

            dump_config(str(result.payload.out_path), {"events": events})
            print(f"Wrote plan to {result.payload.out_path}")
            return
        for ev in events:
            byday = ",".join(ev.get("byday") or [])
            print(f"- {byday} {ev.get('start_time')}-{ev.get('end_time')} calendar={ev.get('calendar') or '<default>'}")
        print("Use --out plan.yaml to write YAML.")


@dataclass
class GmailMailListRequest:
    auth: GmailAuth
    query: Optional[str]
    from_text: Optional[str]
    days: int
    pages: int
    page_size: int
    inbox_only: bool


class GmailMailListRequestConsumer(Consumer[GmailMailListRequest]):
    def __init__(self, request: GmailMailListRequest) -> None:
        self._request = request

    def consume(self) -> GmailMailListRequest:  # pragma: no cover - trivial
        return self._request


@dataclass
class GmailMailListResult:
    messages: List[Dict[str, str]]


class GmailMailListProcessor(Processor[GmailMailListRequest, ResultEnvelope[GmailMailListResult]]):
    def __init__(self, service_builder=None) -> None:
        self._service_builder = service_builder or self._default_service_builder

    def _default_service_builder(self, auth: GmailAuth):
        return _build_gmail_service(
            profile=auth.profile,
            cache_dir=auth.cache_dir,
            credentials_path=auth.credentials,
            token_path=auth.token,
        )

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


class GmailMailListProducer(Producer[ResultEnvelope[GmailMailListResult]]):
    def produce(self, result: ResultEnvelope[GmailMailListResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        assert result.payload is not None
        messages = result.payload.messages
        if not messages:
            print("No messages matched.")
            return
        for msg in messages:
            print(f"- {msg.get('id')} | {msg.get('snippet')}")
        print(f"Listed {len(messages)} Gmail message(s).")


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


class GmailSweepTopRequestConsumer(Consumer[GmailSweepTopRequest]):
    def __init__(self, request: GmailSweepTopRequest) -> None:
        self._request = request

    def consume(self) -> GmailSweepTopRequest:  # pragma: no cover - trivial
        return self._request


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
        return _build_gmail_service(
            profile=auth.profile,
            cache_dir=auth.cache_dir,
            credentials_path=auth.credentials,
            token_path=auth.token,
        )

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


class GmailSweepTopProducer(Producer[ResultEnvelope[GmailSweepTopResult]]):
    def produce(self, result: ResultEnvelope[GmailSweepTopResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        assert result.payload is not None
        top = result.payload.top_senders
        if not top:
            print("No sender stats available.")
            return
        print(
            f"Top {len(top)} sender(s) in last {result.payload.freq_days}d (Inbox={result.payload.inbox_only}):"
        )
        for sender, count in top:
            print(f"- {sender}: {count}")
        if result.payload.out_path:
            from calendar_assistant.yamlio import dump_config

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
            dump_config(str(result.payload.out_path), {"filters": filters})
            print(f"Wrote suggested Gmail filters to {result.payload.out_path}")


    def _parse_receipts(self, svc, ids: List[str], calendar: Optional[str]):
        cls_pat = re.compile(r"Enrollment\s+in\s+(?P<cls>[A-Za-z][A-Za-z0-9 \-/+]+?)\s*(?:\(#|\(|-|\r|\n)", re.I)
        reg_pat_1 = re.compile(r"Registrant:\s*(?:\r?\n\s*)?(?P<name>[A-Za-z][A-Za-z\s'\-]+)", re.I)
        reg_pat_2 = re.compile(r"Order\s+Summary:\s*(?P<name>[A-Za-z][A-Za-z\s'\-]+?)\s+Enrollment\s+in", re.I)
        dates_pat = re.compile(r"Meeting\s+Dates:\s*From\s+(?P<m1>[A-Za-z]{3,9})\s+(?P<d1>\d{1,2}),\s*(?P<y1>\d{4})\s+to\s+(?P<m2>[A-Za-z]{3,9})\s+(?P<d2>\d{1,2}),\s*(?P<y2>\d{4})", re.I)
        sched_pat = re.compile(r"Each\s+(?P<day>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+from\s+(?P<t1>\d{1,2}:\d{2}\s*(?:am|pm))\s+to\s+(?P<t2>\d{1,2}:\d{2}\s*(?:am|pm))", re.I)
        loc_pat = re.compile(r"Location:\s*(?P<loc>.+)", re.I)
        month_map = {m.lower(): i for i, m in enumerate(["January","February","March","April","May","June","July","August","September","October","November","December"], start=1)}
        month_map3 = {k[:3]: v for k, v in list(month_map.items())}
        day_to_code = {
            "monday": "MO","tuesday": "TU","wednesday": "WE","thursday": "TH","friday": "FR","saturday": "SA","sunday": "SU",
        }
        events = []
        for mid in ids:
            try:
                text = svc.get_message_text(mid)
            except Exception:
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
            m1v = month_map.get((m1 or "").strip().lower()) or month_map3.get((m1 or "").strip().lower()[:3])
            m2v = month_map.get((m2 or "").strip().lower()) or month_map3.get((m2 or "").strip().lower()[:3])
            if not (m1v and m2v):
                continue
            start_date = f"{y1:04d}-{m1v:02d}-{d1:02d}"
            until = f"{y2:04d}-{m2v:02d}-{d2:02d}"
            day = day_to_code[(m_sched.group("day") or "").lower()]
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


class GmailPlanProducer(Producer[ResultEnvelope[GmailPlanResult]]):
    def produce(self, result: ResultEnvelope[GmailPlanResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        assert result.payload is not None
        path = result.payload.out_path
        from calendar_assistant.yamlio import dump_config

        dump_config(str(path), result.payload.document)
        events = result.payload.document.get("events", [])
        print(f"Wrote {len(events)} events to {path}")


@dataclass
class OutlookVerifyRequest:
    config_path: Path
    calendar: Optional[str]
    service: Any


class OutlookVerifyRequestConsumer(Consumer[OutlookVerifyRequest]):
    def __init__(self, request: OutlookVerifyRequest) -> None:
        self._request = request

    def consume(self) -> OutlookVerifyRequest:  # pragma: no cover - trivial
        return self._request


@dataclass
class OutlookVerifyResult:
    logs: List[str]
    total: int
    duplicates: int
    missing: int


class OutlookVerifyProcessor(Processor[OutlookVerifyRequest, ResultEnvelope[OutlookVerifyResult]]):
    def __init__(self, config_loader=_load_yaml) -> None:
        self._config_loader = config_loader

    def process(self, payload: OutlookVerifyRequest) -> ResultEnvelope[OutlookVerifyResult]:
        try:
            cfg = self._config_loader(str(payload.config_path))
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to read config: {exc}", "code": 2})
        items = cfg.get("events") if isinstance(cfg, dict) else None
        if not isinstance(items, list):
            return ResultEnvelope(status="error", diagnostics={"message": "Config must contain events: [] list", "code": 2})
        svc = payload.service
        logs: List[str] = []
        total = duplicates = missing = 0
        for i, ev in enumerate(items, start=1):
            if not isinstance(ev, dict):
                continue
            nev = normalize_event(ev)
            subj = (nev.get("subject") or "").strip()
            byday = nev.get("byday") or []
            rt = nev.get("repeat") or ""
            if not (subj and rt == "weekly" and byday):
                continue
            total += 1
            cal_name = payload.calendar or nev.get("calendar")
            win = compute_window(nev)
            if not win:
                continue
            start_iso, end_iso = win
            try:
                events = svc.list_events_in_range(calendar_name=cal_name, start_iso=start_iso, end_iso=end_iso, subject_filter=subj)
            except Exception as e:
                logs.append(f"[{i}] Unable to list events for '{subj}': {e}")
                continue
            want_start = (nev.get("start_time") or "").strip()
            want_end = (nev.get("end_time") or "").strip()
            matches = filter_events_by_day_time(events, byday=byday, start_time=want_start, end_time=want_end)
            if matches:
                duplicates += 1
                logs.append(f"[{i}] duplicate: {subj} {','.join(byday)} {want_start}-{want_end} in '{cal_name or '<primary>'}'")
            else:
                missing += 1
                logs.append(f"[{i}] missing:   {subj} {','.join(byday)} {want_start}-{want_end} in '{cal_name or '<primary>'}'")
        result = OutlookVerifyResult(logs=logs, total=total, duplicates=duplicates, missing=missing)
        return ResultEnvelope(status="success", payload=result)


class OutlookVerifyProducer(Producer[ResultEnvelope[OutlookVerifyResult]]):
    def produce(self, result: ResultEnvelope[OutlookVerifyResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        assert result.payload is not None
        for line in result.payload.logs:
            print(line)
        print(
            f"Checked {result.payload.total} recurring entries. "
            f"Duplicates: {result.payload.duplicates}, Missing: {result.payload.missing}."
        )


@dataclass
class OutlookAddRequest:
    config_path: Path
    dry_run: bool
    force_no_reminder: bool
    service: Any


class OutlookAddRequestConsumer(Consumer[OutlookAddRequest]):
    def __init__(self, request: OutlookAddRequest) -> None:
        self._request = request

    def consume(self) -> OutlookAddRequest:  # pragma: no cover - trivial
        return self._request


@dataclass
class OutlookAddResult:
    logs: List[str]
    created: int
    dry_run: bool


class OutlookAddProcessor(Processor[OutlookAddRequest, ResultEnvelope[OutlookAddResult]]):
    def __init__(self, config_loader=_load_yaml) -> None:
        self._config_loader = config_loader

    def process(self, payload: OutlookAddRequest) -> ResultEnvelope[OutlookAddResult]:
        try:
            cfg = self._config_loader(str(payload.config_path))
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to read config: {exc}", "code": 2})
        items = cfg.get("events") if isinstance(cfg, dict) else None
        if not isinstance(items, list):
            return ResultEnvelope(status="error", diagnostics={"message": "Config must contain events: [] list", "code": 2})
        svc = payload.service
        logs: List[str] = []
        created = 0
        for idx, ev in enumerate(items, start=1):
            if not isinstance(ev, dict):
                continue
            nev = normalize_event(ev)
            cal_name = nev.get("calendar")
            subj = (nev.get("subject") or "").strip()
            if not subj:
                logs.append(f"[{idx}] Skipping event: missing subject")
                continue
            yaml_is_off = (nev.get("is_reminder_on") is False)
            rem_minutes = nev.get("reminder_minutes")
            no_rem_effective = payload.force_no_reminder or yaml_is_off
            if rem_minutes is not None:
                no_rem_effective = False
            if nev.get("repeat"):
                if payload.dry_run:
                    logs.append(
                        f"[dry-run][{idx}] would create recurring: subj='{subj}', cal='{cal_name or '<primary>'}', "
                        f"byday={nev.get('byday')}, time={nev.get('start_time')}-{nev.get('end_time')}, range={nev.get('range')}"
                    )
                    created += 1
                    continue
                try:
                    evt = svc.create_recurring_event(
                        calendar_id=None,
                        calendar_name=cal_name,
                        subject=subj,
                        start_time=nev.get("start_time"),
                        end_time=nev.get("end_time"),
                        tz=nev.get("tz"),
                        repeat=nev.get("repeat"),
                        interval=int(nev.get("interval", 1) or 1),
                        byday=nev.get("byday"),
                        range_start_date=(nev.get("range") or {}).get("start_date"),
                        range_until=(nev.get("range") or {}).get("until"),
                        count=nev.get("count"),
                        body_html=nev.get("body_html"),
                        location=nev.get("location"),
                        exdates=nev.get("exdates") or [],
                        no_reminder=no_rem_effective,
                        reminder_minutes=rem_minutes,
                    )
                    created += 1
                    logs.append(f"[{idx}] Created series: {evt.get('id')} {subj}")
                except Exception as exc:
                    logs.append(f"[{idx}] Failed to create series '{subj}': {exc}")
                continue
            start_iso = nev.get("start")
            end_iso = nev.get("end")
            if not (start_iso and end_iso):
                logs.append(f"[{idx}] Skipping one-time event '{subj}': missing start/end")
                continue
            if payload.dry_run:
                logs.append(
                    f"[dry-run][{idx}] would create single: subj='{subj}', cal='{cal_name or '<primary>'}', "
                    f"start={start_iso}, end={end_iso}"
                )
                created += 1
                continue
            try:
                evt = svc.create_event(
                    calendar_id=None,
                    calendar_name=cal_name,
                    subject=subj,
                    start_iso=_to_iso_str(start_iso),
                    end_iso=_to_iso_str(end_iso),
                    tz=nev.get("tz"),
                    body_html=nev.get("body_html"),
                    all_day=bool(nev.get("all_day") or nev.get("allDay")),
                    location=nev.get("location"),
                    no_reminder=no_rem_effective,
                    reminder_minutes=rem_minutes,
                )
                created += 1
                logs.append(f"[{idx}] Created event: {evt.get('id')} {subj}")
            except Exception as exc:
                logs.append(f"[{idx}] Failed to create event '{subj}': {exc}")
        result = OutlookAddResult(logs=logs, created=created, dry_run=payload.dry_run)
        return ResultEnvelope(status="success", payload=result)


class OutlookAddProducer(Producer[ResultEnvelope[OutlookAddResult]]):
    def produce(self, result: ResultEnvelope[OutlookAddResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        assert result.payload is not None
        for line in result.payload.logs:
            print(line)
        suffix = " (dry-run)" if result.payload.dry_run else ""
        print(f"Planned {result.payload.created} events/series from config{suffix}")


@dataclass
class OutlookScheduleImportRequest:
    source: str
    kind: Optional[str]
    calendar: Optional[str]
    tz: Optional[str]
    until: Optional[str]
    dry_run: bool
    no_reminder: bool
    service: Any


class OutlookScheduleImportRequestConsumer(Consumer[OutlookScheduleImportRequest]):
    def __init__(self, request: OutlookScheduleImportRequest) -> None:
        self._request = request

    def consume(self) -> OutlookScheduleImportRequest:  # pragma: no cover - trivial
        return self._request


@dataclass
class OutlookScheduleImportResult:
    logs: List[str]
    created: int
    dry_run: bool
    calendar: str


class OutlookScheduleImportProcessor(
    Processor[OutlookScheduleImportRequest, ResultEnvelope[OutlookScheduleImportResult]]
):
    def __init__(self, schedule_loader=None) -> None:
        self._schedule_loader = schedule_loader

    def process(self, payload: OutlookScheduleImportRequest) -> ResultEnvelope[OutlookScheduleImportResult]:
        svc = payload.service
        if svc is None:  # pragma: no cover - defensive
            return ResultEnvelope(status="error", diagnostics={"message": "Outlook service is required", "code": 1})
        cal_name = payload.calendar or "Imported Schedules"
        try:
            cal_id = svc.ensure_calendar_exists(cal_name)
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to ensure calendar '{cal_name}': {exc}", "code": 3})
        loader = self._schedule_loader
        if loader is None:
            from calendar_assistant.importer import load_schedule as default_loader
            loader = default_loader
        try:
            items = loader(payload.source, kind=payload.kind)
        except ValueError as exc:
            return ResultEnvelope(status="error", diagnostics={"message": str(exc), "code": 4})
        except NotImplementedError as exc:
            return ResultEnvelope(status="error", diagnostics={"message": str(exc), "code": 4})
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to load schedule: {exc}", "code": 4})
        if not items:
            return ResultEnvelope(
                status="success",
                payload=OutlookScheduleImportResult(logs=["No schedule items parsed."], created=0, dry_run=payload.dry_run, calendar=cal_name),
            )
        logs: List[str] = []
        created = 0
        for item in items:
            if item.start_iso and item.end_iso:
                if payload.dry_run:
                    logs.append(
                        f"[dry-run] would create one-off '{item.subject}' {item.start_iso}→{item.end_iso} cal='{cal_name}'"
                    )
                    created += 1
                    continue
                try:
                    svc.create_event(
                        calendar_id=cal_id,
                        calendar_name=None,
                        subject=item.subject,
                        start_iso=item.start_iso,
                        end_iso=item.end_iso,
                        tz=payload.tz,
                        body_html=item.notes,
                        all_day=False,
                        location=item.location,
                        no_reminder=payload.no_reminder,
                    )
                    created += 1
                    logs.append(f"Created one-off '{item.subject}'")
                except Exception as exc:
                    logs.append(f"Failed to create one-off '{item.subject}': {exc}")
                continue
            rec = item.recurrence or ("weekly" if item.byday else None)
            if rec in ("weekly", "daily", "monthly") and item.start_time and item.end_time and item.range_start:
                range_until = payload.until or item.range_until
                if payload.dry_run:
                    extra = f" {','.join(item.byday or [])}" if item.byday else ""
                    logs.append(
                        f"[dry-run] would create {rec} '{item.subject}'{extra} {item.start_time}-{item.end_time} start={item.range_start} cal='{cal_name}'"
                    )
                    created += 1
                    continue
                try:
                    svc.create_recurring_event(
                        calendar_id=cal_id,
                        calendar_name=None,
                        subject=item.subject,
                        start_time=item.start_time,
                        end_time=item.end_time,
                        tz=payload.tz,
                        repeat=rec,
                        interval=1,
                        byday=item.byday,
                        range_start_date=item.range_start,
                        range_until=range_until,
                        count=item.count,
                        body_html=item.notes,
                        location=item.location,
                        no_reminder=payload.no_reminder,
                    )
                    created += 1
                    logs.append(f"Created recurring '{item.subject}'")
                except Exception as exc:
                    logs.append(f"Failed to create recurring '{item.subject}': {exc}")
                continue
            logs.append(f"Skip non-recurring or incomplete row: {item.subject}")
        result = OutlookScheduleImportResult(logs=logs, created=created, dry_run=payload.dry_run, calendar=cal_name)
        return ResultEnvelope(status="success", payload=result)


class OutlookScheduleImportProducer(Producer[ResultEnvelope[OutlookScheduleImportResult]]):
    def produce(self, result: ResultEnvelope[OutlookScheduleImportResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        assert result.payload is not None
        for line in result.payload.logs:
            print(line)
        if result.payload.dry_run:
            print("Preview complete.")
        else:
            print(f"Created {result.payload.created} event series in '{result.payload.calendar}'.")


@dataclass
class OutlookListOneOffsRequest:
    service: Any
    calendar: Optional[str]
    from_date: Optional[str]
    to_date: Optional[str]
    limit: int
    out_path: Optional[Path]


class OutlookListOneOffsRequestConsumer(Consumer[OutlookListOneOffsRequest]):
    def __init__(self, request: OutlookListOneOffsRequest) -> None:
        self._request = request

    def consume(self) -> OutlookListOneOffsRequest:  # pragma: no cover - trivial
        return self._request


@dataclass
class OutlookListOneOffsResult:
    rows: List[Dict[str, str]]
    start: str
    end: str
    limit: int
    out_path: Optional[Path]


class OutlookListOneOffsProcessor(Processor[OutlookListOneOffsRequest, ResultEnvelope[OutlookListOneOffsResult]]):
    def __init__(self, today_factory=None) -> None:
        self._today_factory = today_factory or _dt.date.today

    def process(self, payload: OutlookListOneOffsRequest) -> ResultEnvelope[OutlookListOneOffsResult]:
        svc = payload.service
        if svc is None:  # pragma: no cover - defensive
            return ResultEnvelope(status="error", diagnostics={"message": "Outlook service is required", "code": 1})
        start_iso, end_iso, start_date, end_date = self._resolve_window(payload)
        try:
            evs = svc.list_events_in_range(
                calendar_name=payload.calendar,
                start_iso=start_iso,
                end_iso=end_iso,
            )
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to list events: {exc}", "code": 3})
        one_offs = []
        for ev in evs or []:
            etype = (ev.get("type") or "").lower()
            if (etype == "singleinstance") or not ev.get("seriesMasterId"):
                one_offs.append(ev)
        rows: List[Dict[str, str]] = []
        for ev in one_offs[: max(0, payload.limit)]:
            subj = ev.get("subject") or ""
            st = ((ev.get("start") or {}).get("dateTime") or "") or ""
            en = ((ev.get("end") or {}).get("dateTime") or "") or ""
            loc = ((ev.get("location") or {}).get("displayName") or "") or ""
            rows.append({"subject": subj, "start": st, "end": en, "location": loc})
        result = OutlookListOneOffsResult(
            rows=rows,
            start=start_date,
            end=end_date,
            limit=payload.limit,
            out_path=payload.out_path,
        )
        return ResultEnvelope(status="success", payload=result)

    def _resolve_window(self, payload: OutlookListOneOffsRequest) -> Tuple[str, str, str, str]:
        today = self._today_factory()
        start = payload.from_date or (today - _dt.timedelta(days=30)).isoformat()
        end = payload.to_date or (today + _dt.timedelta(days=180)).isoformat()
        return f"{start}T00:00:00", f"{end}T23:59:59", start, end


class OutlookListOneOffsProducer(Producer[ResultEnvelope[OutlookListOneOffsResult]]):
    def produce(self, result: ResultEnvelope[OutlookListOneOffsResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        assert result.payload is not None
        rows = result.payload.rows
        print(f"Found {len(rows)} single events from {result.payload.start} to {result.payload.end}.")
        for ev in rows[: result.payload.limit]:
            st = (ev.get("start") or "")[:16]
            en = (ev.get("end") or "")[:16]
            subj = ev.get("subject") or ""
            loc = ev.get("location") or ""
            arrow = "→"
            print(f"- {st} {arrow} {en} | {subj} | {loc}")
        if result.payload.out_path:
            from calendar_assistant.yamlio import dump_config

            dump_config(str(result.payload.out_path), {"events": rows})
            print(f"Wrote one-offs to {result.payload.out_path}")


@dataclass
class OutlookCalendarShareRequest:
    service: Any
    calendar: str
    recipient: str
    role: str


class OutlookCalendarShareRequestConsumer(Consumer[OutlookCalendarShareRequest]):
    def __init__(self, request: OutlookCalendarShareRequest) -> None:
        self._request = request

    def consume(self) -> OutlookCalendarShareRequest:  # pragma: no cover - trivial
        return self._request


@dataclass
class OutlookCalendarShareResult:
    calendar: str
    recipient: str
    role: str


class OutlookCalendarShareProcessor(Processor[OutlookCalendarShareRequest, ResultEnvelope[OutlookCalendarShareResult]]):
    def process(self, payload: OutlookCalendarShareRequest) -> ResultEnvelope[OutlookCalendarShareResult]:
        svc = payload.service
        if svc is None:  # pragma: no cover - defensive
            return ResultEnvelope(status="error", diagnostics={"message": "Outlook service is required", "code": 1})
        cal_name = payload.calendar
        try:
            cal_id = svc.find_calendar_id(cal_name)
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to resolve calendar '{cal_name}': {exc}", "code": 3})
        if not cal_id:
            try:
                cal_id = svc.ensure_calendar_exists(cal_name)
            except Exception as exc:
                return ResultEnvelope(
                    status="error",
                    diagnostics={"message": f"Failed to ensure calendar '{cal_name}': {exc}", "code": 3},
                )
        role = self._normalize_role(payload.role)
        try:
            svc.ensure_calendar_permission(cal_id, payload.recipient, role)
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                diagnostics={"message": f"Failed to share calendar '{cal_name}' with {payload.recipient}: {exc}", "code": 3},
            )
        result = OutlookCalendarShareResult(calendar=cal_name, recipient=payload.recipient, role=role)
        return ResultEnvelope(status="success", payload=result)

    def _normalize_role(self, role: str) -> str:
        cleaned = (role or "write").strip().lower()
        if cleaned in ("admin", "owner", "editor"):
            cleaned = "write"
        allowed = {
            "read",
            "write",
            "limitedread",
            "freebusyread",
            "delegatewithoutprivateeventaccess",
            "delegatewithprivateeventaccess",
            "custom",
        }
        # exact match or camel-case forms
        camel_map = {
            "limitedread": "limitedRead",
            "freebusyread": "freeBusyRead",
            "delegatewithoutprivateeventaccess": "delegateWithoutPrivateEventAccess",
            "delegatewithprivateeventaccess": "delegateWithPrivateEventAccess",
        }
        if cleaned not in allowed:
            return "write"
        return camel_map.get(cleaned, cleaned)


class OutlookCalendarShareProducer(Producer[ResultEnvelope[OutlookCalendarShareResult]]):
    def produce(self, result: ResultEnvelope[OutlookCalendarShareResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        assert result.payload is not None
        print(f"Shared '{result.payload.calendar}' with {result.payload.recipient} role={result.payload.role}")


@dataclass
class OutlookAddEventRequest:
    service: Any
    calendar: Optional[str]
    subject: str
    start_iso: str
    end_iso: str
    tz: Optional[str]
    body_html: Optional[str]
    all_day: bool
    location: Optional[str]
    no_reminder: bool
    reminder_minutes: Optional[int]


class OutlookAddEventRequestConsumer(Consumer[OutlookAddEventRequest]):
    def __init__(self, request: OutlookAddEventRequest) -> None:
        self._request = request

    def consume(self) -> OutlookAddEventRequest:  # pragma: no cover - trivial
        return self._request


@dataclass
class OutlookAddEventResult:
    event_id: str
    subject: str


class OutlookAddEventProcessor(Processor[OutlookAddEventRequest, ResultEnvelope[OutlookAddEventResult]]):
    def process(self, payload: OutlookAddEventRequest) -> ResultEnvelope[OutlookAddEventResult]:
        svc = payload.service
        if svc is None:  # pragma: no cover - defensive
            return ResultEnvelope(status="error", diagnostics={"message": "Outlook service is required", "code": 1})
        try:
            evt = svc.create_event(
                calendar_id=None,
                calendar_name=payload.calendar,
                subject=payload.subject,
                start_iso=payload.start_iso,
                end_iso=payload.end_iso,
                tz=payload.tz,
                body_html=payload.body_html,
                all_day=payload.all_day,
                location=payload.location,
                no_reminder=payload.no_reminder,
                reminder_minutes=payload.reminder_minutes,
            )
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to create event: {exc}", "code": 3})
        evt_id = (evt or {}).get("id") or ""
        result = OutlookAddEventResult(event_id=evt_id, subject=(evt or {}).get("subject") or payload.subject)
        return ResultEnvelope(status="success", payload=result)


class OutlookAddEventProducer(Producer[ResultEnvelope[OutlookAddEventResult]]):
    def produce(self, result: ResultEnvelope[OutlookAddEventResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        assert result.payload is not None
        print(f"Created event: {result.payload.event_id} subject={result.payload.subject}")


@dataclass
class OutlookAddRecurringRequest:
    service: Any
    calendar: Optional[str]
    subject: str
    start_time: str
    end_time: str
    tz: Optional[str]
    repeat: str
    interval: int
    byday: Optional[List[str]]
    range_start_date: str
    range_until: Optional[str]
    count: Optional[int]
    body_html: Optional[str]
    location: Optional[str]
    exdates: Optional[List[str]]
    no_reminder: bool
    reminder_minutes: Optional[int]


class OutlookAddRecurringRequestConsumer(Consumer[OutlookAddRecurringRequest]):
    def __init__(self, request: OutlookAddRecurringRequest) -> None:
        self._request = request

    def consume(self) -> OutlookAddRecurringRequest:  # pragma: no cover - trivial
        return self._request


@dataclass
class OutlookAddRecurringResult:
    event_id: str
    subject: str


class OutlookAddRecurringProcessor(
    Processor[OutlookAddRecurringRequest, ResultEnvelope[OutlookAddRecurringResult]]
):
    def process(self, payload: OutlookAddRecurringRequest) -> ResultEnvelope[OutlookAddRecurringResult]:
        svc = payload.service
        if svc is None:  # pragma: no cover - defensive
            return ResultEnvelope(status="error", diagnostics={"message": "Outlook service is required", "code": 1})
        try:
            evt = svc.create_recurring_event(
                calendar_id=None,
                calendar_name=payload.calendar,
                subject=payload.subject,
                start_time=payload.start_time,
                end_time=payload.end_time,
                tz=payload.tz,
                repeat=payload.repeat,
                interval=payload.interval,
                byday=payload.byday,
                range_start_date=payload.range_start_date,
                range_until=payload.range_until,
                count=payload.count,
                body_html=payload.body_html,
                location=payload.location,
                exdates=payload.exdates or None,
                no_reminder=payload.no_reminder,
                reminder_minutes=payload.reminder_minutes,
            )
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to create recurring event: {exc}", "code": 3})
        evt_id = (evt or {}).get("id") or ""
        subject = (evt or {}).get("subject") or payload.subject
        result = OutlookAddRecurringResult(event_id=evt_id, subject=subject)
        return ResultEnvelope(status="success", payload=result)


class OutlookAddRecurringProducer(Producer[ResultEnvelope[OutlookAddRecurringResult]]):
    def produce(self, result: ResultEnvelope[OutlookAddRecurringResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        assert result.payload is not None
        print(f"Created recurring series: {result.payload.event_id} subject={result.payload.subject}")


@dataclass
class OutlookLocationsEnrichRequest:
    service: Any
    calendar: str
    from_date: Optional[str]
    to_date: Optional[str]
    dry_run: bool


class OutlookLocationsEnrichRequestConsumer(Consumer[OutlookLocationsEnrichRequest]):
    def __init__(self, request: OutlookLocationsEnrichRequest) -> None:
        self._request = request

    def consume(self) -> OutlookLocationsEnrichRequest:  # pragma: no cover - trivial
        return self._request


@dataclass
class OutlookLocationsEnrichResult:
    updated: int
    dry_run: bool


class OutlookLocationsEnrichProcessor(
    Processor[OutlookLocationsEnrichRequest, ResultEnvelope[OutlookLocationsEnrichResult]]
):
    def __init__(self, today_factory=None, enricher=None) -> None:
        self._today_factory = today_factory or _dt.date.today
        self._enricher = enricher

    def process(self, payload: OutlookLocationsEnrichRequest) -> ResultEnvelope[OutlookLocationsEnrichResult]:
        svc = payload.service
        if svc is None:  # pragma: no cover - defensive
            return ResultEnvelope(status="error", diagnostics={"message": "Outlook service is required", "code": 1})
        cal_id = svc.find_calendar_id(payload.calendar)
        if not cal_id:
            return ResultEnvelope(status="error", diagnostics={"message": f"Calendar not found: {payload.calendar}", "code": 3})

        start_iso, end_iso = self._resolve_window(payload)
        try:
            events = svc.list_events_in_range(calendar_id=cal_id, start_iso=start_iso, end_iso=end_iso)
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to list events: {exc}", "code": 3})

        enricher = self._enricher
        if enricher is None:
            from calendar_assistant.locations_map import enrich_location as default_enrich

            enricher = default_enrich

        series: Dict[str, Dict[str, Any]] = {}
        for ev in events or []:
            sid = ev.get("seriesMasterId") or ev.get("id")
            if not sid or sid in series:
                continue
            subj = (ev.get("subject") or "").strip().lower()
            if subj.startswith(("public skating", "leisure swim", "fun n fit")):
                series[sid] = ev

        if not series:
            return ResultEnvelope(
                status="success",
                payload=OutlookLocationsEnrichResult(updated=0, dry_run=payload.dry_run),
                diagnostics={"message": "No matching series found."} if payload.dry_run else None,
            )

        updated = 0
        logs: List[str] = []
        for sid, ev in series.items():
            loc = ((ev.get("location") or {}).get("displayName") or "") or ""
            new_loc = enricher(loc)
            if not new_loc or new_loc == loc:
                continue
            if payload.dry_run:
                logs.append(f"[dry-run] would update series {sid} location '{loc}' -> '{new_loc}'")
                continue
            try:
                svc.update_event_location(event_id=sid, calendar_id=cal_id, location_str=new_loc)
                updated += 1
                logs.append(f"Updated series {sid} location -> {new_loc}")
            except Exception as exc:
                logs.append(f"Failed to update series {sid}: {exc}")

        result = OutlookLocationsEnrichResult(updated=updated, dry_run=payload.dry_run)
        env = ResultEnvelope(status="success", payload=result, diagnostics={"logs": logs})
        return env

    def _resolve_window(self, payload: OutlookLocationsEnrichRequest) -> Tuple[str, str]:
        today = self._today_factory()
        start = payload.from_date or today.isoformat()
        end = payload.to_date or today.replace(month=12, day=31).isoformat()
        return f"{start}T00:00:00", f"{end}T23:59:59"


class OutlookLocationsEnrichProducer(Producer[ResultEnvelope[OutlookLocationsEnrichResult]]):
    def produce(self, result: ResultEnvelope[OutlookLocationsEnrichResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        assert result.payload is not None
        logs = (result.diagnostics or {}).get("logs") or []
        for line in logs:
            print(line)
        if result.payload.dry_run:
            print("Preview complete.")
        else:
            print(f"Updated locations on {result.payload.updated} series.")


@dataclass
class OutlookMailListRequest:
    service: Any
    folder: str
    top: int
    pages: int


class OutlookMailListRequestConsumer(Consumer[OutlookMailListRequest]):
    def __init__(self, request: OutlookMailListRequest) -> None:
        self._request = request

    def consume(self) -> OutlookMailListRequest:  # pragma: no cover - trivial
        return self._request


@dataclass
class OutlookMailListResult:
    messages: List[Dict[str, Any]]
    folder: str


class OutlookMailListProcessor(Processor[OutlookMailListRequest, ResultEnvelope[OutlookMailListResult]]):
    def process(self, payload: OutlookMailListRequest) -> ResultEnvelope[OutlookMailListResult]:
        svc = payload.service
        if svc is None:  # pragma: no cover - defensive
            return ResultEnvelope(status="error", diagnostics={"message": "Outlook service is required", "code": 1})
        try:
            msgs = svc.list_messages(folder=payload.folder, top=payload.top, pages=payload.pages)
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to list messages: {exc}", "code": 2})
        msgs = msgs or []
        result = OutlookMailListResult(messages=msgs, folder=payload.folder)
        return ResultEnvelope(status="success", payload=result)


class OutlookMailListProducer(Producer[ResultEnvelope[OutlookMailListResult]]):
    def produce(self, result: ResultEnvelope[OutlookMailListResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        assert result.payload is not None
        msgs = result.payload.messages
        if not msgs:
            print("No messages.")
            return
        for msg in msgs:
            sub = (msg.get("subject") or "").strip()
            recv = (msg.get("receivedDateTime") or "")[:19]
            frm = (((msg.get("from") or {}).get("emailAddress") or {}).get("address") or "")
            print(f"- {recv} | {sub[:80]} | {frm}")
        print(f"Listed {len(msgs)} message(s).")


@dataclass
class OutlookLocationsRequest:
    config_path: Path
    calendar: Optional[str]
    dry_run: bool
    all_occurrences: bool = False
    service: Any = None


class OutlookLocationsRequestConsumer(Consumer[OutlookLocationsRequest]):
    def __init__(self, request: OutlookLocationsRequest) -> None:
        self._request = request

    def consume(self) -> OutlookLocationsRequest:  # pragma: no cover - trivial
        return self._request


@dataclass
class OutlookLocationsResult:
    message: str


class OutlookLocationsUpdateProcessor(Processor[OutlookLocationsRequest, ResultEnvelope[OutlookLocationsResult]]):
    def __init__(self, config_loader=_load_yaml) -> None:
        self._config_loader = config_loader

    def process(self, payload: OutlookLocationsRequest) -> ResultEnvelope[OutlookLocationsResult]:
        try:
            cfg = self._config_loader(str(payload.config_path))
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to read config: {exc}", "code": 2})
        items = cfg.get("events") if isinstance(cfg, dict) else None
        if not isinstance(items, list):
            return ResultEnvelope(status="error", diagnostics={"message": "Config must contain events: [] list", "code": 2})
        sync = LocationSync(payload.service)
        updated = sync.plan_from_config(items, calendar=payload.calendar, dry_run=payload.dry_run)
        if payload.dry_run:
            msg = "Preview complete. No changes written."
            return ResultEnvelope(status="success", payload=OutlookLocationsResult(message=msg))
        from calendar_assistant.yamlio import dump_config

        if updated:
            dump_config(str(payload.config_path), {"events": items})
            msg = f"Wrote updated locations to {payload.config_path} (updated {updated})."
        else:
            msg = "No location changes detected."
        return ResultEnvelope(status="success", payload=OutlookLocationsResult(message=msg))


class OutlookLocationsApplyProcessor(Processor[OutlookLocationsRequest, ResultEnvelope[OutlookLocationsResult]]):
    def __init__(self, config_loader=_load_yaml) -> None:
        self._config_loader = config_loader

    def process(self, payload: OutlookLocationsRequest) -> ResultEnvelope[OutlookLocationsResult]:
        try:
            cfg = self._config_loader(str(payload.config_path))
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to read config: {exc}", "code": 2})
        items = cfg.get("events") if isinstance(cfg, dict) else None
        if not isinstance(items, list):
            return ResultEnvelope(status="error", diagnostics={"message": "Config must contain events: [] list", "code": 2})
        sync = LocationSync(payload.service)
        updated = sync.apply_from_config(
            items,
            calendar=payload.calendar,
            all_occurrences=payload.all_occurrences,
            dry_run=payload.dry_run,
        )
        if payload.dry_run:
            msg = "Preview complete."
        else:
            msg = f"Applied {updated} location update(s)."
        return ResultEnvelope(status="success", payload=OutlookLocationsResult(message=msg))


class OutlookLocationsProducer(Producer[ResultEnvelope[OutlookLocationsResult]]):
    def produce(self, result: ResultEnvelope[OutlookLocationsResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        assert result.payload is not None
        print(result.payload.message)


@dataclass
class OutlookRemoveRequest:
    config_path: Path
    calendar: Optional[str]
    subject_only: bool
    apply: bool
    service: Any


class OutlookRemoveRequestConsumer(Consumer[OutlookRemoveRequest]):
    def __init__(self, request: OutlookRemoveRequest) -> None:
        self._request = request

    def consume(self) -> OutlookRemoveRequest:  # pragma: no cover - trivial
        return self._request


@dataclass
class OutlookRemovePlanEntry:
    subject: str
    series_ids: List[str]
    event_ids: List[str]


@dataclass
class OutlookRemoveResult:
    plan: List[OutlookRemovePlanEntry]
    apply: bool
    deleted: int
    logs: List[str]


class OutlookRemoveProcessor(Processor[OutlookRemoveRequest, ResultEnvelope[OutlookRemoveResult]]):
    def __init__(self, config_loader=_load_yaml) -> None:
        self._config_loader = config_loader

    def process(self, payload: OutlookRemoveRequest) -> ResultEnvelope[OutlookRemoveResult]:
        try:
            cfg = self._config_loader(str(payload.config_path))
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to read config: {exc}", "code": 2})
        items = cfg.get("events") if isinstance(cfg, dict) else None
        if not isinstance(items, list):
            return ResultEnvelope(status="error", diagnostics={"message": "Config must contain events: [] list", "code": 2})
        svc = payload.service
        if svc is None:  # pragma: no cover - defensive
            return ResultEnvelope(status="error", diagnostics={"message": "Outlook service is required", "code": 1})

        plan: List[OutlookRemovePlanEntry] = []
        logs: List[str] = []
        deleted_total = 0

        for idx, raw in enumerate(items, start=1):
            if not isinstance(raw, dict):
                continue
            nev = normalize_event(raw)
            subj = (nev.get("subject") or "").strip()
            window = self._resolve_window(nev)
            if not window:
                continue
            start_iso, end_iso = window
            cal_name = payload.calendar or nev.get("calendar")
            try:
                occ = svc.list_events_in_range(
                    calendar_name=cal_name,
                    start_iso=start_iso,
                    end_iso=end_iso,
                    subject_filter=subj,
                )
            except Exception as exc:
                logs.append(f"[{idx}] list error: {exc}")
                continue
            matches = self._match_events(occ or [], nev, payload.subject_only)
            series_ids, event_ids = self._collect_ids(matches)
            if not series_ids and not event_ids:
                continue
            entry = OutlookRemovePlanEntry(subject=subj, series_ids=series_ids, event_ids=event_ids)
            plan.append(entry)
            if payload.apply:
                deleted_total += self._apply_deletions(entry, svc, logs)

        result = OutlookRemoveResult(plan=plan, apply=payload.apply, deleted=deleted_total, logs=logs)
        return ResultEnvelope(status="success", payload=result)

    def _resolve_window(self, event: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        single_start = (event.get("start") or "").strip()
        single_end = (event.get("end") or "").strip()
        if single_start and single_end:
            return single_start, single_end
        rng = event.get("range") or {}
        start_date = (rng.get("start_date") or "").strip()
        until = (rng.get("until") or "").strip()
        if not start_date:
            return None
        start_iso = f"{start_date[:10]}T00:00:00"
        end_iso = f"{(until or start_date)[:10]}T23:59:59"
        return start_iso, end_iso

    def _match_events(self, occ: Sequence[Dict[str, Any]], event: Dict[str, Any], subject_only: bool):
        matches = []
        single_start = (event.get("start") or "").strip()
        single_end = (event.get("end") or "").strip()
        start_time = (event.get("start_time") or "").strip()
        end_time = (event.get("end_time") or "").strip()
        want_days = set(d.lower() for d in (event.get("byday") or []) if d)
        for ex in occ:
            st = ((ex.get("start") or {}).get("dateTime") or "")
            en = ((ex.get("end") or {}).get("dateTime") or "")
            if single_start and single_end:
                if not (st.startswith(single_start[:16]) and en.startswith(single_end[:16])):
                    continue
            elif not subject_only:
                t1 = st.split("T", 1)[1][:5] if "T" in st else ""
                t2 = en.split("T", 1)[1][:5] if "T" in en else ""
                try:
                    dt = _dt.datetime.fromisoformat(st.replace("Z", "+00:00"))
                    wcode = ["mo", "tu", "we", "th", "fr", "sa", "su"][dt.weekday()]
                except Exception:
                    wcode = ""
                if want_days and wcode and wcode.lower() not in want_days:
                    continue
                if start_time and t1 and start_time != t1:
                    continue
                if end_time and t2 and end_time != t2:
                    continue
            matches.append(ex)
        return matches

    def _collect_ids(self, matches: Sequence[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
        series_ids: List[str] = []
        event_ids: List[str] = []
        for match in matches:
            sid = match.get("seriesMasterId")
            if sid:
                if sid not in series_ids:
                    series_ids.append(sid)
                continue
            mid = match.get("id")
            if mid and mid not in event_ids:
                event_ids.append(mid)
        return series_ids, event_ids

    def _apply_deletions(self, entry: OutlookRemovePlanEntry, svc, logs: List[str]) -> int:
        deleted = 0
        subj = entry.subject
        for sid in entry.series_ids:
            try:
                ok = bool(svc.delete_event_by_id(sid))
            except Exception as exc:
                logs.append(f"Failed to delete series {sid}: {exc}")
                continue
            if ok:
                deleted += 1
                logs.append(f"Deleted series master: {sid} ({subj})")
            else:
                logs.append(f"Failed to delete series {sid}")
        for eid in entry.event_ids:
            try:
                ok2 = bool(svc.delete_event_by_id(eid))
            except Exception as exc:
                logs.append(f"Failed to delete event {eid}: {exc}")
                continue
            if ok2:
                deleted += 1
                logs.append(f"Deleted event: {eid} ({subj})")
            else:
                logs.append(f"Failed to delete event {eid}")
        return deleted


class OutlookRemoveProducer(Producer[ResultEnvelope[OutlookRemoveResult]]):
    def produce(self, result: ResultEnvelope[OutlookRemoveResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        assert result.payload is not None
        payload = result.payload
        if not payload.apply:
            print("Planned deletions:")
            for entry in payload.plan:
                if entry.series_ids:
                    print(f"- {entry.subject}: delete series {len(entry.series_ids)}")
                if entry.event_ids:
                    print(f"- {entry.subject}: delete events {len(entry.event_ids)}")
            print("Re-run with --apply to delete.")
            return
        for line in payload.logs:
            print(line)
        print(f"Deleted {payload.deleted} items.")




@dataclass
class OutlookRemindersRequest:
    service: Any
    calendar: Optional[str]
    from_date: Optional[str]
    to_date: Optional[str]
    dry_run: bool
    all_occurrences: bool
    set_off: bool
    minutes: Optional[int] = None


class OutlookRemindersRequestConsumer(Consumer[OutlookRemindersRequest]):
    def __init__(self, request: OutlookRemindersRequest) -> None:
        self._request = request

    def consume(self) -> OutlookRemindersRequest:  # pragma: no cover - trivial
        return self._request


@dataclass
class OutlookRemindersResult:
    logs: List[str]
    updated: int
    dry_run: bool
    set_off: bool


class OutlookRemindersProcessor(Processor[OutlookRemindersRequest, ResultEnvelope[OutlookRemindersResult]]):
    def __init__(self, today_factory=None) -> None:
        self._today_factory = today_factory or _dt.date.today

    def process(self, payload: OutlookRemindersRequest) -> ResultEnvelope[OutlookRemindersResult]:
        svc = payload.service
        if svc is None:  # pragma: no cover - defensive
            return ResultEnvelope(status="error", diagnostics={"message": "Outlook service is required", "code": 1})

        calendar_name = payload.calendar
        cal_id = None
        if calendar_name:
            cal_id = svc.get_calendar_id_by_name(calendar_name)
            if not cal_id:
                return ResultEnvelope(
                    status="error",
                    diagnostics={"message": f"Calendar not found: {calendar_name}", "code": 3},
                )

        start_iso, end_iso = self._resolve_window(payload)
        try:
            events = svc.list_events_in_range(calendar_id=cal_id, start_iso=start_iso, end_iso=end_iso)
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to list events: {exc}", "code": 4})

        series_ids: set[str] = set()
        occurrence_ids: set[str] = set()
        single_ids: set[str] = set()
        for ev in events or []:
            et = (ev.get("type") or "").lower()
            eid = ev.get("id")
            sid = ev.get("seriesMasterId")
            if et == "seriesmaster" and eid:
                series_ids.add(eid)
            elif et == "occurrence":
                if payload.all_occurrences and eid:
                    occurrence_ids.add(eid)
                if sid:
                    series_ids.add(sid)
            else:
                if eid:
                    single_ids.add(eid)

        logs: List[str] = []
        updated = 0
        updated += self._update_ids(sorted(series_ids), "series master", cal_id, svc, payload, logs)
        if payload.all_occurrences:
            updated += self._update_ids(sorted(occurrence_ids), "occurrence", cal_id, svc, payload, logs)
        updated += self._update_ids(sorted(single_ids), "single", cal_id, svc, payload, logs)

        result = OutlookRemindersResult(logs=logs, updated=updated, dry_run=payload.dry_run, set_off=payload.set_off)
        return ResultEnvelope(status="success", payload=result)

    def _resolve_window(self, payload: OutlookRemindersRequest) -> Tuple[str, str]:
        today = self._today_factory()
        start = payload.from_date or (today - _dt.timedelta(days=30)).isoformat()
        end = payload.to_date or (today + _dt.timedelta(days=180)).isoformat()
        return f"{start}T00:00:00", f"{end}T23:59:59"

    def _update_ids(
        self,
        ids: Sequence[str],
        label: str,
        cal_id: Optional[str],
        svc,
        payload: OutlookRemindersRequest,
        logs: List[str],
    ) -> int:
        if not ids:
            return 0
        updated = 0
        for eid in ids:
            if payload.dry_run:
                if payload.set_off:
                    logs.append(f"[dry-run] would disable reminder for {label} {eid}")
                else:
                    logs.append(
                        f"[dry-run] would set reminderMinutesBeforeStart={payload.minutes} for {label} {eid}"
                    )
                continue
            try:
                if payload.set_off:
                    svc.update_event_reminder(
                        event_id=eid,
                        calendar_id=cal_id,
                        calendar_name=payload.calendar,
                        is_on=False,
                    )
                else:
                    svc.update_event_reminder(
                        event_id=eid,
                        calendar_id=cal_id,
                        calendar_name=payload.calendar,
                        is_on=True,
                        minutes_before_start=payload.minutes,
                    )
                updated += 1
            except Exception as exc:
                logs.append(f"Failed to update {label} {eid}: {exc}")
        return updated


class OutlookRemindersProducer(Producer[ResultEnvelope[OutlookRemindersResult]]):
    def produce(self, result: ResultEnvelope[OutlookRemindersResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        assert result.payload is not None
        for line in result.payload.logs:
            print(line)
        if result.payload.dry_run:
            print("Preview complete.")
        else:
            if result.payload.set_off:
                print(f"Disabled reminders on {result.payload.updated} item(s).")
            else:
                print(f"Updated reminders on {result.payload.updated} item(s).")


@dataclass
class OutlookSettingsRequest:
    config_path: Path
    calendar: Optional[str]
    from_date: Optional[str]
    to_date: Optional[str]
    dry_run: bool
    service: Any


class OutlookSettingsRequestConsumer(Consumer[OutlookSettingsRequest]):
    def __init__(self, request: OutlookSettingsRequest) -> None:
        self._request = request

    def consume(self) -> OutlookSettingsRequest:  # pragma: no cover - trivial
        return self._request


@dataclass
class OutlookSettingsResult:
    logs: List[str]
    selected: int
    changed: int
    dry_run: bool


class OutlookSettingsProcessor(Processor[OutlookSettingsRequest, ResultEnvelope[OutlookSettingsResult]]):
    def __init__(self, config_loader=_load_yaml, regex_module=re, today_factory=None) -> None:
        self._config_loader = config_loader
        self._regex = regex_module
        self._today_factory = today_factory or _dt.date.today

    def process(self, payload: OutlookSettingsRequest) -> ResultEnvelope[OutlookSettingsResult]:
        try:
            doc = self._config_loader(str(payload.config_path)) or {}
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to load config: {exc}", "code": 2})
        root = doc.get("settings") if isinstance(doc, dict) and "settings" in doc else doc
        defaults = (root.get("defaults") if isinstance(root, dict) else {}) or {}
        rules = (root.get("rules") if isinstance(root, dict) else None) or []
        if not isinstance(rules, list):
            return ResultEnvelope(
                status="error",
                diagnostics={"message": "Config must contain settings.rules: [] or top-level rules: []", "code": 2},
            )

        svc = payload.service
        if svc is None:  # pragma: no cover - defensive
            return ResultEnvelope(status="error", diagnostics={"message": "Outlook service is required", "code": 1})

        start_iso, end_iso = self._resolve_window(payload)
        try:
            events = svc.list_events_in_range(
                calendar_name=payload.calendar,
                start_iso=start_iso,
                end_iso=end_iso,
            )
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Failed to list events: {exc}", "code": 3})

        logs: List[str] = []
        selected = 0
        changed = 0

        for event in events or []:
            eid = event.get("id")
            if not eid:
                continue
            cfg = self._evaluate_config(defaults, rules, event)
            if cfg is None:
                continue
            selected += 1
            patch = self._build_patch(cfg)
            if not patch:
                continue
            if payload.dry_run:
                parts = []
                if patch.get("categories") is not None:
                    parts.append(f"categories={patch['categories']}")
                if patch.get("show_as"):
                    parts.append(f"showAs={patch['show_as']}")
                if patch.get("sensitivity"):
                    parts.append(f"sensitivity={patch['sensitivity']}")
                if patch.get("is_reminder_on") is not None:
                    parts.append(f"isReminderOn={patch['is_reminder_on']}")
                if patch.get("reminder_minutes") is not None:
                    parts.append(f"reminderMinutes={patch['reminder_minutes']}")
                subject = (event.get("subject") or "").strip()
                logs.append(f"[dry-run] would update {eid} | {subject} -> {{" + ", ".join(parts) + "}}")
                continue
            try:
                svc.update_event_settings(
                    event_id=eid,
                    calendar_name=payload.calendar,
                    categories=patch.get("categories"),
                    show_as=patch.get("show_as"),
                    sensitivity=patch.get("sensitivity"),
                    is_reminder_on=patch.get("is_reminder_on"),
                    reminder_minutes=patch.get("reminder_minutes"),
                )
                changed += 1
            except Exception as exc:
                logs.append(f"Failed to update {eid}: {exc}")

        result = OutlookSettingsResult(logs=logs, selected=selected, changed=changed, dry_run=payload.dry_run)
        return ResultEnvelope(status="success", payload=result)

    def _resolve_window(self, payload: OutlookSettingsRequest) -> Tuple[str, str]:
        today = self._today_factory()
        start = payload.from_date or (today - _dt.timedelta(days=30)).isoformat()
        end = payload.to_date or (today + _dt.timedelta(days=180)).isoformat()
        return f"{start}T00:00:00", f"{end}T23:59:59"

    def _evaluate_config(self, defaults, rules, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        subject = (event.get("subject") or "").strip()
        location = ((event.get("location") or {}).get("displayName") or "").strip()
        apply_set = None
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            if self._match_rule(rule, subject, location):
                apply_set = (rule.get("set") or {})
                break
        if apply_set is None and not defaults:
            return None
        cfg = {}
        cfg.update(defaults or {})
        if apply_set:
            cfg.update(apply_set)
        return cfg

    def _match_rule(self, rule: Dict[str, Any], subject: str, location: str) -> bool:
        matcher = rule.get("match") or {}
        sc = self._to_list(matcher.get("subject_contains"))
        if sc and not any(s.lower() in subject.lower() for s in sc):
            return False
        sr = self._to_list(matcher.get("subject_regex"))
        if sr and not any(self._regex.search(p, subject, self._regex.I) for p in sr):
            return False
        lc = self._to_list(matcher.get("location_contains"))
        if lc and not any(s.lower() in location.lower() for s in lc):
            return False
        return True

    def _build_patch(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        cats = cfg.get("categories")
        if isinstance(cats, str):
            cats = [s.strip() for s in cats.split(",") if s.strip()]
        elif isinstance(cats, (list, tuple)):
            cats = [str(s).strip() for s in cats if str(s).strip()]
        else:
            cats = None if cats is None else [str(cats)]
        show_as = cfg.get("show_as") or cfg.get("showAs")
        sensitivity = cfg.get("sensitivity")
        is_rem_on = self._coerce_bool(cfg.get("is_reminder_on"))
        rem_min = cfg.get("reminder_minutes")
        try:
            rem_min = int(rem_min) if rem_min is not None else None
        except Exception:
            rem_min = None
        return {
            "categories": cats,
            "show_as": show_as,
            "sensitivity": sensitivity,
            "is_reminder_on": is_rem_on,
            "reminder_minutes": rem_min,
        }

    def _coerce_bool(self, value: Any) -> Optional[bool]:
        if isinstance(value, bool):
            return value
        if value is None:
            return None
        s = str(value).strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off"):
            return False
        return None

    def _to_list(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [str(v) for v in value if str(v).strip()]
        return [str(value)] if str(value).strip() else []


class OutlookSettingsProducer(Producer[ResultEnvelope[OutlookSettingsResult]]):
    def produce(self, result: ResultEnvelope[OutlookSettingsResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return
        assert result.payload is not None
        for line in result.payload.logs:
            print(line)
        if result.payload.dry_run:
            print(f"Preview complete. {result.payload.selected} item(s) matched.")
        else:
            print(f"Applied settings to {result.payload.changed} item(s).")


@dataclass
class OutlookDedupRequest:
    service: Any
    calendar: Optional[str] = None
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    apply: bool = False
    keep_newest: bool = False
    prefer_delete_nonstandard: bool = False
    delete_standardized: bool = False


class OutlookDedupRequestConsumer(Consumer[OutlookDedupRequest]):
    def __init__(self, request: OutlookDedupRequest) -> None:
        self._request = request

    def consume(self) -> OutlookDedupRequest:  # pragma: no cover - trivial
        return self._request


@dataclass
class OutlookDedupDuplicate:
    subject: str
    weekday: str
    start_time: str
    end_time: str
    keep: str
    delete: List[str]


@dataclass
class OutlookDedupResult:
    duplicates: List[OutlookDedupDuplicate]
    apply: bool
    deleted: int
    logs: List[str]


class OutlookDedupProcessor(Processor[OutlookDedupRequest, ResultEnvelope[OutlookDedupResult]]):
    def __init__(self, today_factory=None) -> None:
        self._today_factory = today_factory or _dt.date.today

    def process(self, payload: OutlookDedupRequest) -> ResultEnvelope[OutlookDedupResult]:
        svc = payload.service
        if svc is None:  # pragma: no cover - defensive
            return ResultEnvelope(status="error", diagnostics={"message": "Outlook service is required", "code": 1})

        start_iso, end_iso = self._resolve_window(payload)
        cal_id = None
        if payload.calendar:
            cal_id = svc.find_calendar_id(payload.calendar)
        try:
            occ = svc.list_calendar_view(calendar_id=cal_id, start_iso=start_iso, end_iso=end_iso)
        except Exception as exc:
            return ResultEnvelope(status="error", diagnostics={"message": f"Graph error: {exc}", "code": 4})

        duplicates = self._find_duplicates(occ or [], payload)
        logs: List[str] = []
        deleted = 0
        if payload.apply and duplicates:
            for group in duplicates:
                for sid in group.delete:
                    ok = False
                    try:
                        ok = bool(svc.delete_event_by_id(sid))
                    except Exception as exc:
                        logs.append(f"Failed to delete {sid}: {exc}")
                        continue
                    if ok:
                        deleted += 1
                        logs.append(f"Deleted series master {sid}")

        result = OutlookDedupResult(duplicates=duplicates, apply=payload.apply, deleted=deleted, logs=logs)
        return ResultEnvelope(status="success", payload=result)

    def _resolve_window(self, payload: OutlookDedupRequest) -> Tuple[str, str]:
        today = self._today_factory()
        start = payload.from_date or (today - _dt.timedelta(days=30)).isoformat()
        end = payload.to_date or (today + _dt.timedelta(days=180)).isoformat()
        return f"{start}T00:00:00", f"{end}T23:59:59"

    def _find_duplicates(
        self,
        occ: List[Dict[str, Any]],
        payload: OutlookDedupRequest,
    ) -> List[OutlookDedupDuplicate]:
        groups: Dict[Tuple[str, str, str, str], Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        for event in occ:
            sid = event.get("seriesMasterId")
            if not sid:
                continue
            key = self._key_for_event(event)
            if not key:
                continue
            groups[key][sid].append(event)

        duplicates: List[OutlookDedupDuplicate] = []
        for key, masters in groups.items():
            if len(masters) <= 1:
                continue
            selection = self._select_series(list(masters.keys()), masters, payload)
            if not selection:
                continue
            keep, delete = selection
            subject, weekday, start_time, end_time = key
            duplicates.append(
                OutlookDedupDuplicate(
                    subject=subject,
                    weekday=weekday,
                    start_time=start_time,
                    end_time=end_time,
                    keep=keep,
                    delete=delete,
                )
            )
        return duplicates

    def _key_for_event(self, event: Dict[str, Any]) -> Optional[Tuple[str, str, str, str]]:
        subject = (event.get("subject") or "").strip().lower()
        start = ((event.get("start") or {}).get("dateTime") or "")
        end = ((event.get("end") or {}).get("dateTime") or "")
        t1 = start.split("T", 1)[1][:5] if "T" in start else ""
        t2 = end.split("T", 1)[1][:5] if "T" in end else ""
        weekday = ""
        try:
            dt = _dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
            weekday = ["mo", "tu", "we", "th", "fr", "sa", "su"][dt.weekday()]
        except Exception:
            weekday = ""
        return subject, weekday, t1, t2

    def _select_series(
        self,
        series_ids: List[str],
        masters: Dict[str, List[Dict[str, Any]]],
        payload: OutlookDedupRequest,
    ) -> Optional[Tuple[str, List[str]]]:
        def created_at(sid: str) -> str:
            vals = [o.get("createdDateTime") or "" for o in masters.get(sid, []) if o.get("createdDateTime")]
            if not vals:
                return ""
            return min(vals)

        def is_standardized(sid: str) -> bool:
            occs = masters.get(sid) or []
            for occ in occs:
                loc = occ.get("location") or {}
                disp = loc.get("displayName") or ""
                addr = loc.get("address") or {}
                if addr and any(addr.get(k) for k in ("street", "city", "state", "postalCode", "countryOrRegion")):
                    return True
                if "(" in disp and ")" in disp:
                    return True
            return False

        sorted_sids = sorted(series_ids, key=lambda sid: created_at(sid) or "Z")
        if not sorted_sids:
            return None
        newest = sorted_sids[-1]
        oldest = sorted_sids[0]
        std = [sid for sid in sorted_sids if is_standardized(sid)]
        non = [sid for sid in sorted_sids if sid not in std]

        keep = oldest
        delete = [sid for sid in sorted_sids if sid != keep]

        if payload.prefer_delete_nonstandard:
            if non and std:
                keep = newest if payload.keep_newest else oldest
                delete = list(non)
            else:
                keep = newest if payload.keep_newest else oldest
                delete = [sid for sid in sorted_sids if sid != keep]
        elif payload.delete_standardized:
            if std and non:
                if payload.keep_newest:
                    keep = non[-1] if len(non) > 1 else non[0]
                else:
                    keep = non[0]
                delete = list(std)
            else:
                keep = newest if payload.keep_newest else oldest
                delete = [sid for sid in sorted_sids if sid != keep]
        else:
            keep = newest if payload.keep_newest else oldest
            delete = [sid for sid in sorted_sids if sid != keep]

        return keep, delete


class OutlookDedupProducer(Producer[ResultEnvelope[OutlookDedupResult]]):
    def produce(self, result: ResultEnvelope[OutlookDedupResult]) -> None:
        if not result.ok():
            msg = (result.diagnostics or {}).get("message")
            if msg:
                print(msg)
            return

        assert result.payload is not None
        duplicates = result.payload.duplicates
        if not duplicates:
            print("No duplicate series detected in window.")
            return

        print("Found {0} duplicate groups. (subject,day,time)-> keep + delete list".format(len(duplicates)))
        for dup in duplicates:
            deletes = ", ".join(dup.delete)
            print(f"- {dup.subject} {dup.weekday} {dup.start_time}-{dup.end_time}: keep {dup.keep} delete {deletes}")

        if not result.payload.apply:
            print("Dry plan only. Re-run with --apply to delete duplicates (keep oldest).")
            return

        for line in result.payload.logs:
            print(line)
        print(f"Deleted {result.payload.deleted} duplicate series.")


def _to_iso_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    try:
        import datetime as _dt
        if isinstance(v, _dt.datetime):
            return v.strftime("%Y-%m-%dT%H:%M:%S")
        if isinstance(v, _dt.date):
            return v.strftime("%Y-%m-%dT00:00:00")
    except Exception:
        pass
    return str(v)
def _load_schedule_sources(sources, kind):
    from calendar_assistant.importer import load_schedule
    from calendar_assistant.model import normalize_event

    out = []
    for src in sources:
        items = load_schedule(src, kind)
        for it in items:
            ev = {
                "subject": getattr(it, "subject", None),
                "start": getattr(it, "start_iso", None),
                "end": getattr(it, "end_iso", None),
            }
            out.append(normalize_event(ev))
    return out
