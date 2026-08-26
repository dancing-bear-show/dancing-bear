"""ICS Draft Consumer Pipeline — converts a plan YAML to a Gmail draft with .ics attachment.

Reads a canonical plan YAML file ({"events": [...]}) and produces an RFC 5545
VCALENDAR payload delivered as a Gmail DRAFT.  Never sends.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._base import (
    EventIterationProcessor,
    BaseProducer,
    RequestConsumer,
)


# ---------------------------------------------------------------------------
# Request / Result / Accumulator dataclasses
# ---------------------------------------------------------------------------


@dataclass
class IcsDraftRequest:
    """Input to the ICS draft pipeline."""

    config_path: Path
    """Path to the plan YAML file ({"events": [...]})."""

    recipient: str
    """Recipient email address for the draft."""

    subject: str
    """Subject line for the draft email."""

    dry_run: bool = False
    """When True, print what would be created but do NOT create the draft."""

    gmail_client: Any = field(default=None)
    """GmailClient instance.  None is allowed only on dry-run."""


# Type alias for backward compatibility / convenience
IcsDraftRequestConsumer = RequestConsumer[IcsDraftRequest]


@dataclass
class IcsDraftResult:
    """Output of the ICS draft pipeline."""

    ics_payload: str
    """The full RFC 5545 VCALENDAR text."""

    event_count: int
    """Number of VEVENT components generated."""

    draft_id: str | None
    """Gmail draft id returned by the API, or None on dry-run."""


@dataclass
class _IcsDraftAccumulator:
    """Mutable per-run accumulator for IcsDraftProcessor."""

    vevent_lines: list[str] = field(default_factory=list)
    event_count: int = 0


# ---------------------------------------------------------------------------
# ICS helpers
# ---------------------------------------------------------------------------

_CRLF = "\r\n"


def _fold(line: str) -> str:
    """RFC 5545 §3.1 line folding: split at 75 octets, continuation with HTAB.

    The limit is octets, not characters, and a fold must never land inside a
    multi-byte UTF-8 sequence. Slicing the str by character index satisfies
    neither: "é" is one character but two octets, so a 75-character chunk can
    exceed 75 octets — and an emoji in a SUMMARY could be split mid-sequence,
    producing bytes that do not decode. Accumulate encoded characters instead,
    closing a chunk before the next character would cross the limit.
    """
    if len(line.encode("utf-8")) <= 75:
        return line
    out: list[str] = []
    chunk: list[str] = []
    used = 0
    for ch in line:
        width = len(ch.encode("utf-8"))
        if used + width > 75 and chunk:
            out.append("".join(chunk))
            chunk, used = [], 0
        chunk.append(ch)
        used += width
    if chunk:
        out.append("".join(chunk))
    return ("\r\n\t").join(out)


def _ics_escape(value: str) -> str:
    """Escape special characters in TEXT property values (RFC 5545 §3.3.11)."""
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ical_dt(iso: str, tz: str | None) -> str:
    """Convert an ISO datetime string to the compact YYYYMMDDTHHMMSS[Z] form.

    Returns "TZID=X:YYYYMMDDTHHMMSS" when tz is set, else "YYYYMMDDTHHMMSSZ".
    """
    # iso might be YYYY-MM-DDTHH:MM:SS or YYYY-MM-DDTHH:MM
    clean = iso.rstrip("Z").split("+")[0]
    # Remove microseconds
    if "." in clean:
        clean = clean.split(".")[0]
    # Replace - and : to get compact form YYYYMMDDTHHMMSS
    compact = clean.replace("-", "").replace(":", "").replace(" ", "T")
    if tz:
        return f"TZID={tz}:{compact}"
    return f"{compact}Z"


def _ical_date(iso_date: str) -> str:
    """Convert YYYY-MM-DD to YYYYMMDD."""
    return iso_date.replace("-", "")


def _build_rrule(nev: dict[str, Any], *, date_valued: bool = False) -> str | None:
    """Build an RRULE string from a normalized event dict.

    Returns None when no recurrence info is present.

    ``date_valued`` must match the DTSTART this RRULE accompanies. RFC 5545
    §3.8.5.3 requires UNTIL to be a DATE when DTSTART is a DATE, and a
    DATE-TIME when DTSTART is a DATE-TIME; mixing them is malformed and strict
    parsers reject the whole calendar. An all-day recurring series (start_date
    with no start_time) is the reachable case.
    """
    repeat = nev.get("repeat")
    if not repeat:
        return None

    freq_map = {"daily": "DAILY", "weekly": "WEEKLY", "monthly": "MONTHLY"}
    freq = freq_map.get(repeat.lower())
    if not freq:
        return None

    parts: list[str] = [f"FREQ={freq}"]

    interval = nev.get("interval")
    if interval and int(interval) > 1:
        parts.append(f"INTERVAL={interval}")

    byday = nev.get("byday")
    if byday:
        # byday is already UPPERCASE 2-char codes ("MO","WE") — maps straight through
        parts.append(f"BYDAY={','.join(byday)}")

    rng = nev.get("range") or {}
    until = rng.get("until")
    if until:
        compact_until = _ical_date(until)
        # DATE-valued DTSTART -> DATE-valued UNTIL (no time, no Z).
        parts.append(
            f"UNTIL={compact_until}" if date_valued
            else f"UNTIL={compact_until}T235959Z"
        )

    count = nev.get("count")
    if count and not until:
        parts.append(f"COUNT={count}")

    return ";".join(parts)


def _build_vevent(nev: dict[str, Any]) -> list[str]:
    """Build VEVENT lines for one normalized event.

    Returns a list of RFC 5545 property lines (not yet folded or CRLF-terminated).
    """
    lines: list[str] = ["BEGIN:VEVENT"]
    uid = str(uuid.uuid4())
    lines.append(f"UID:{uid}")

    subj = nev.get("subject") or "Untitled"
    lines.append(f"SUMMARY:{_ics_escape(subj)}")

    tz = nev.get("tz")
    single_start = nev.get("start")
    single_end = nev.get("end")

    is_all_day = (
        single_start is not None
        and "T" not in str(single_start)
        and single_end is not None
        and "T" not in str(single_end)
    )

    # Tracks whether the DTSTART actually emitted is DATE-valued, so the RRULE's
    # UNTIL can match its type (RFC 5545 §3.8.5.3).
    dtstart_is_date = False

    if is_all_day:
        # All-day: VALUE=DATE
        lines.append(f"DTSTART;VALUE=DATE:{_ical_date(single_start)}")
        lines.append(f"DTEND;VALUE=DATE:{_ical_date(single_end)}")
        dtstart_is_date = True
    elif single_start and single_end:
        # One-off with time: use TZID param when tz is known, else plain UTC
        if tz:
            lines.append(f"DTSTART;{_ical_dt(single_start, tz)}")
            lines.append(f"DTEND;{_ical_dt(single_end, tz)}")
        else:
            lines.append(f"DTSTART:{_ical_dt(single_start, None)}")
            lines.append(f"DTEND:{_ical_dt(single_end, None)}")
    else:
        # Recurring: use start_time + range.start_date
        rng = nev.get("range") or {}
        start_date = rng.get("start_date")
        start_time = nev.get("start_time")
        end_time = nev.get("end_time")

        if start_date and start_time:
            compact_date = _ical_date(start_date)
            compact_start_t = start_time.replace(":", "")[:6].ljust(6, "0")
            dtstart_val = f"{compact_date}T{compact_start_t}"
            if tz:
                lines.append(f"DTSTART;TZID={tz}:{dtstart_val}")
            else:
                lines.append(f"DTSTART:{dtstart_val}Z")
        elif start_date:
            lines.append(f"DTSTART;VALUE=DATE:{_ical_date(start_date)}")
            dtstart_is_date = True

        if start_date and end_time:
            compact_date = _ical_date(start_date)
            compact_end_t = end_time.replace(":", "")[:6].ljust(6, "0")
            dtend_val = f"{compact_date}T{compact_end_t}"
            if tz:
                lines.append(f"DTEND;TZID={tz}:{dtend_val}")
            else:
                lines.append(f"DTEND:{dtend_val}Z")

    # Recurrence rule
    rrule = _build_rrule(nev, date_valued=dtstart_is_date)
    if rrule:
        lines.append(f"RRULE:{rrule}")

    # Exclusion dates
    exdates = nev.get("exdates")
    if exdates:
        exdate_vals = ",".join(_ical_date(d) for d in exdates)
        lines.append(f"EXDATE;VALUE=DATE:{exdate_vals}")

    # Location
    location = nev.get("location")
    if location:
        lines.append(f"LOCATION:{_ics_escape(location)}")

    lines.append("END:VEVENT")
    return lines


def _build_vcalendar(vevent_lines: list[str]) -> str:
    """Wrap VEVENT lines in a VCALENDAR component and return full ICS text."""
    header = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//dancing-bear//calendar-plan//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    footer = ["END:VCALENDAR"]
    all_lines = header + vevent_lines + footer
    return _CRLF.join(_fold(line) for line in all_lines) + _CRLF


def _build_draft_raw_bytes(
    recipient: str,
    subject: str,
    ics_text: str,
) -> bytes:
    """Build a raw RFC 2822 MIME message with an ICS attachment."""
    import email.mime.multipart as _mp
    import email.mime.base as _mb
    import email.mime.text as _mt
    from email import encoders as _enc

    msg = _mp.MIMEMultipart("mixed")
    msg["To"] = recipient
    msg["Subject"] = subject

    # Plain text body
    body_text = "Calendar plan attached as ICS. Import into your calendar application."
    msg.attach(_mt.MIMEText(body_text, "plain", "utf-8"))

    # ICS attachment
    ics_bytes = ics_text.encode("utf-8")
    part = _mb.MIMEBase("text", "calendar", method="PUBLISH", charset="utf-8")
    part.set_payload(ics_bytes)
    _enc.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename="calendar-plan.ics")
    msg.attach(part)

    return msg.as_bytes()


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class IcsDraftProcessor(EventIterationProcessor):
    """Converts a plan YAML to an ICS payload and creates a Gmail draft."""

    def __init__(self, config_loader=None) -> None:
        self._config_loader = config_loader

    def _init_accumulator(self, payload: IcsDraftRequest) -> _IcsDraftAccumulator:
        return _IcsDraftAccumulator()

    def _handle_event(
        self,
        payload: IcsDraftRequest,
        idx: int,
        nev: dict[str, Any],
        accumulator: _IcsDraftAccumulator,
    ) -> None:
        vevent = _build_vevent(nev)
        accumulator.vevent_lines.extend(vevent)
        accumulator.event_count += 1

    def _finalize_result(
        self,
        payload: IcsDraftRequest,
        accumulator: _IcsDraftAccumulator,
    ) -> IcsDraftResult:
        """Build the ICS and create the draft.

        Overrides the payload-aware hook rather than ``_finalize`` because
        creating the draft needs the request's gmail_client, dry_run flag,
        recipient and subject — none of which reach ``_finalize(accumulator)``.
        The base class's load/iterate/normalize loop is inherited unchanged.
        """
        ics_text = _build_vcalendar(accumulator.vevent_lines)

        if payload.dry_run:
            print(f"[dry-run] Would create Gmail draft to {payload.recipient!r}")
            print(f"[dry-run] Subject: {payload.subject!r}")
            print(f"[dry-run] Events: {accumulator.event_count}")
            print(f"[dry-run] ICS preview (first 500 chars):\n{ics_text[:500]}")
            return IcsDraftResult(
                ics_payload=ics_text,
                event_count=accumulator.event_count,
                draft_id=None,
            )

        if payload.gmail_client is None:
            raise ValueError("gmail_client is required when dry_run=False")

        raw_bytes = _build_draft_raw_bytes(
            recipient=payload.recipient,
            subject=payload.subject,
            ics_text=ics_text,
        )
        result = payload.gmail_client.create_draft_raw(raw_bytes)
        draft_id: str | None = (result or {}).get("id")
        return IcsDraftResult(
            ics_payload=ics_text,
            event_count=accumulator.event_count,
            draft_id=draft_id,
        )


# ---------------------------------------------------------------------------
# Producer
# ---------------------------------------------------------------------------


class IcsDraftProducer(BaseProducer):
    """Prints a summary of the ICS draft operation."""

    def _produce_success(
        self,
        payload: IcsDraftResult,
        diagnostics: dict[str, Any] | None,
    ) -> None:
        if payload.draft_id:
            self._writer.print(
                f"Draft created: id={payload.draft_id}  events={payload.event_count}"
            )
        else:
            self._writer.print(
                f"[dry-run] {payload.event_count} event(s) — draft not created"
            )


__all__ = [
    "IcsDraftRequest",
    "IcsDraftRequestConsumer",
    "IcsDraftResult",
    "IcsDraftProcessor",
    "IcsDraftProducer",
]
