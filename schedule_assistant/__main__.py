"""Schedule Assistant CLI

Follows the LLM patterns used in cars-sre-utils:
- plan then apply (apply requires --apply; default is dry-run)
- small, dependency-light modules with lazy imports
- YAML IO helpers kept minimal and human-friendly

Initial scope: generate a canonical schedule plan from simple sources
(CSV/XLSX/PDF/website via calendar_assistant.importer) and simulate
application (dry-run by default). This provides a stable CLI surface
to extend later with real calendar integrations.
"""
from __future__ import annotations

import argparse
import datetime as _dt
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.assistant import BaseAssistant
from core.auth import build_outlook_service_from_args
from core.cli_framework import CLIApp
from core.yamlio import dump_config as _dump_yaml, load_config as _load_yaml

from .pipeline import (
    ApplyProducer,
    ApplyProcessor,
    ApplyRequest,
    ApplyRequestConsumer,
    OutlookAuth,
    PlanProducer,
    PlanProcessor,
    PlanRequest,
    PlanRequestConsumer,
    SyncProducer,
    SyncProcessor,
    SyncRequest,
    SyncRequestConsumer,
    VerifyProducer,
    VerifyProcessor,
    VerifyRequest,
    VerifyRequestConsumer,
    _expand_recurring_occurrences,  # noqa: F401 - re-exported for tests
)


def _read_yaml(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"YAML file not found: {p}")
    data = _load_yaml(str(p)) or {}
    if not isinstance(data, dict):
        raise ValueError("Top-level YAML must be a mapping (dict)")
    return data


def _write_yaml(path: str | Path, data: Dict[str, Any]) -> None:
    p = Path(path)
    _dump_yaml(str(p), data)


# Create the CLI app
app = CLIApp(
    "schedule-assistant",
    "Schedule Assistant CLI for calendar plan generation and application.",
    add_common_args=True,
)

# Create assistant for agentic support
assistant = BaseAssistant(
    "schedule_assistant",
    "agentic: schedule_assistant\npurpose: Generate/verify/apply calendar plans (dry-run first)",
)


def _emit_agentic(fmt: str, compact: bool) -> int:
    from .agentic import emit_agentic_context

    return emit_agentic_context(fmt, compact)


@app.command("plan", help="Generate a canonical schedule plan from sources")
@app.argument("--source", action="append", default=[], help="Source path/URL (repeatable); supports CSV/XLSX/PDF/website")
@app.argument("--kind", choices=["auto", "csv", "xlsx", "pdf", "website"], default="auto", help="Force parser kind (default auto)")
@app.argument("--out", default="out/schedule.plan.yaml", help="Output YAML path (default out/schedule.plan.yaml)")
def cmd_plan(args: argparse.Namespace) -> int:
    out_path = Path(getattr(args, "out", "out/schedule.plan.yaml"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sources = getattr(args, "source", []) or []
    request = PlanRequest(sources=sources, kind=getattr(args, "kind", None), out_path=out_path)
    envelope = PlanProcessor().process(PlanRequestConsumer(request).consume())
    PlanProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


def _build_outlook_service_from_args(args: argparse.Namespace):
    """Construct an OutlookService instance via shared auth helpers."""
    try:
        return build_outlook_service_from_args(args)
    except RuntimeError as exc:
        print(str(exc))
        return None
    except Exception as exc:
        print(f"Outlook provider unavailable: {exc}")
        return None


@app.command("verify", help="Verify a schedule plan against Outlook calendar within a window")
@app.argument("--plan", required=True, help="Plan YAML path")
@app.argument("--calendar", required=True, help="Target calendar name")
@app.argument("--from", dest="from_date", required=True, help="Start date (YYYY-MM-DD)")
@app.argument("--to", dest="to_date", required=True, help="End date (YYYY-MM-DD)")
@app.argument("--match", choices=["subject", "subject-time"], default="subject", help="Verification mode (default subject)")
@app.argument("--client-id", help="Outlook client ID")
@app.argument("--tenant", help="Azure tenant (default consumers)")
@app.argument("--token", help="Path to Outlook token cache")
def cmd_verify(args: argparse.Namespace) -> int:
    auth = OutlookAuth(
        profile=getattr(args, "profile", None),
        client_id=getattr(args, "client_id", None),
        tenant=getattr(args, "tenant", None),
        token_path=getattr(args, "token", None),
    )
    request = VerifyRequest(
        plan_path=Path(getattr(args, "plan")),
        calendar=getattr(args, "calendar", None),
        from_date=getattr(args, "from_date", None),
        to_date=getattr(args, "to_date", None),
        match=getattr(args, "match", "subject"),
        auth=auth,
    )
    envelope = VerifyProcessor().process(VerifyRequestConsumer(request).consume())
    VerifyProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


@app.command("sync", help="Create missing items from plan; optionally delete extraneous one-offs (dry-run by default)")
@app.argument("--plan", required=True, help="Plan YAML path")
@app.argument("--calendar", required=True, help="Target calendar name")
@app.argument("--from", dest="from_date", required=True, help="Start date (YYYY-MM-DD)")
@app.argument("--to", dest="to_date", required=True, help="End date (YYYY-MM-DD)")
@app.argument("--match", choices=["subject", "subject-time"], default="subject-time", help="Matching mode for sync (default subject-time)")
@app.argument("--delete-missing", action="store_true", help="Delete calendar items not present in plan (respects --match)")
@app.argument("--delete-unplanned-series", action="store_true", help="Also delete entire recurring series with no matching occurrences in window")
@app.argument("--apply", action="store_true", help="Perform changes (omit for dry-run)")
@app.argument("--client-id", help="Outlook client ID")
@app.argument("--tenant", help="Azure tenant (default consumers)")
@app.argument("--token", help="Path to Outlook token cache")
def cmd_sync(args: argparse.Namespace) -> int:
    auth = OutlookAuth(
        profile=getattr(args, "profile", None),
        client_id=getattr(args, "client_id", None),
        tenant=getattr(args, "tenant", None),
        token_path=getattr(args, "token", None),
    )
    request = SyncRequest(
        plan_path=Path(getattr(args, "plan")),
        calendar=getattr(args, "calendar", None),
        from_date=getattr(args, "from_date", None),
        to_date=getattr(args, "to_date", None),
        match=getattr(args, "match", "subject-time"),
        delete_missing=bool(getattr(args, "delete_missing", False)),
        delete_unplanned_series=bool(getattr(args, "delete_unplanned_series", False)),
        apply=bool(getattr(args, "apply", False)),
        auth=auth,
    )
    envelope = SyncProcessor().process(SyncRequestConsumer(request).consume())
    SyncProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


@app.command("export", help="Export Outlook calendar events to a plan YAML (one-offs for backup)")
@app.argument("--calendar", required=True, help="Outlook calendar name (e.g., 'Activities')")
@app.argument("--from", dest="from_date", required=True, help="Start date YYYY-MM-DD")
@app.argument("--to", dest="to_date", required=True, help="End date YYYY-MM-DD")
@app.argument("--out", required=True, help="Output YAML path (e.g., config/calendar/activities.yaml)")
@app.argument("--client-id", help="Outlook client ID")
@app.argument("--tenant", help="Azure tenant (default consumers)")
@app.argument("--token", help="Path to Outlook token cache")
def cmd_export(args: argparse.Namespace) -> int:
    import datetime as _dt
    svc = _build_outlook_service_from_args(args)
    if not svc:
        return 2
    cal_name = getattr(args, 'calendar', None)
    if not cal_name:
        print("--calendar is required")
        return 2
    try:
        start_iso = _dt.datetime.fromisoformat(args.from_date).strftime("%Y-%m-%dT00:00:00")
        end_iso = _dt.datetime.fromisoformat(args.to_date).strftime("%Y-%m-%dT23:59:59")
    except Exception:
        print("Invalid --from/--to date format; expected YYYY-MM-DD")
        return 2
    try:
        evs = svc.list_events_in_range(calendar_name=cal_name, start_iso=start_iso, end_iso=end_iso, top=800)
    except Exception as e:
        print(f"Failed to list events: {e}")
        return 3
    rows: List[Dict[str, Any]] = []
    for ev in evs:
        sub = (ev.get('subject') or '').strip()
        st = ((ev.get('start') or {}).get('dateTime') or '').strip()
        en = ((ev.get('end') or {}).get('dateTime') or '').strip()
        loc = (ev.get('location') or {}).get('displayName') or ''
        if not sub or not st or not en:
            continue
        rows.append({'calendar': cal_name, 'subject': sub, 'start': st, 'end': en, 'location': loc})
    # Sort by start ascending for readability
    def _key(ev: Dict[str, Any]) -> str:
        return ev.get('start', '')
    rows.sort(key=_key)
    out_path = Path(getattr(args, 'out'))
    _write_yaml(out_path, {'events': rows})
    print(f"Exported {len(rows)} events from '{cal_name}' to {out_path}")
    print("Note: export writes occurrences as one-offs for backup. Use verify/sync to manage plan application.")
    return 0


@app.command("compress", help="Infer recurring weekly series from one-off plan events")
@app.argument("--in", dest="in_path", required=True, help="Input plan YAML with one-offs (events: [])")
@app.argument("--out", required=True, help="Output compressed plan YAML")
@app.argument("--calendar", help="Calendar name to set on series (optional)")
@app.argument("--min-occur", type=int, default=2, help="Minimum occurrences to form a series (default 2)")
def cmd_compress(args: argparse.Namespace) -> int:
    inp = Path(getattr(args, 'in_path'))
    if not inp.exists():
        print(f"Input not found: {inp}")
        return 2
    data = _read_yaml(inp)
    items = data.get('events') or []
    if not isinstance(items, list):
        print("Invalid input: events must be a list")
        return 2
    # Separate one-offs and ignore existing series entries
    one_offs: List[Dict[str, Any]] = []
    for ev in items:
        if ev.get('start') and ev.get('end'):
            one_offs.append(ev)
    if not one_offs:
        print("No one-off events found to compress.")
        return 0
    # Group by (subject, start_time, end_time, weekday-code, location)
    import datetime as _dt
    def iso_to_date(iso: Any) -> _dt.date:
        s = str(iso).replace('Z','').strip()
        if 'T' in s:
            s = s.split('T', 1)[0]
        elif ' ' in s:
            s = s.split(' ', 1)[0]
        return _dt.date.fromisoformat(s)
    def iso_to_time(iso: Any) -> str:
        s = str(iso).replace('Z','').strip()
        t = s
        if 'T' in s:
            t = s.split('T',1)[1]
        elif ' ' in s:
            t = s.split(' ',1)[1]
        # Extract HH:MM prefix
        return t[:5]
    def weekday_code(d: _dt.date) -> str:
        return ['MO','TU','WE','TH','FR','SA','SU'][d.weekday()]

    groups: Dict[tuple, List[_dt.date]] = {}
    meta: Dict[tuple, Dict[str, Any]] = {}
    for ev in one_offs:
        subj = (ev.get('subject') or '').strip()
        st = str(ev.get('start') or '')
        en = str(ev.get('end') or '')
        if not subj or not st or not en:
            continue
        d = iso_to_date(st)
        st_time = iso_to_time(st)
        en_time = iso_to_time(en)
        dow = weekday_code(d)
        loc = (ev.get('location') or '').strip()
        cal = ev.get('calendar')
        key = (subj, st_time, en_time, dow, loc)
        groups.setdefault(key, []).append(d)
        if key not in meta:
            meta[key] = {'calendar': cal, 'subject': subj, 'location': loc}

    min_occur = max(1, int(getattr(args, 'min_occur', 2)))
    out_events: List[Dict[str, Any]] = []
    # Build series for groups with >= min_occur, else keep as one-offs
    for key, dates in groups.items():
        subj, st_time, en_time, dow, loc = key
        dates_sorted = sorted(set(dates))
        if len(dates_sorted) < min_occur:
            # Re-emit as one-offs
            for d in dates_sorted:
                start_iso = f"{d.isoformat()}T{st_time}"
                end_iso = f"{d.isoformat()}T{en_time}"
                ev = {'subject': subj, 'start': start_iso, 'end': end_iso}
                if loc:
                    ev['location'] = loc
                cal = getattr(args, 'calendar', None) or meta[key].get('calendar')
                if cal:
                    ev['calendar'] = cal
                out_events.append(ev)
            continue
        # Compute range and exdates (weekly cadence for this weekday)
        start_date = dates_sorted[0]
        end_date = dates_sorted[-1]
        exdates: List[str] = []
        cur = start_date
        while cur <= end_date:
            if cur not in dates_sorted:
                exdates.append(cur.isoformat())
            cur = cur + _dt.timedelta(days=7)
        ev: Dict[str, Any] = {
            'subject': subj,
            'repeat': 'weekly',
            'byday': [dow],
            'start_time': st_time,
            'end_time': en_time,
            'range': {'start_date': start_date.isoformat(), 'until': end_date.isoformat()},
        }
        if loc:
            ev['location'] = loc
        if exdates:
            ev['exdates'] = exdates
        cal = getattr(args, 'calendar', None) or meta[key].get('calendar')
        if cal:
            ev['calendar'] = cal
        out_events.append(ev)

    # Sort by subject, weekday, start_date
    def sort_key(e: Dict[str, Any]) -> tuple:
        subj = (e.get('subject') or '')
        if e.get('repeat'):
            dow = (e.get('byday') or [''])[0]
            sd = ((e.get('range') or {}).get('start_date') or '')
            tm = e.get('start_time') or ''
            return (subj, dow, sd, tm)
        # one-off
        st = e.get('start') or ''
        return (subj, '', st, '')
    out_events.sort(key=sort_key)

    _write_yaml(Path(getattr(args, 'out')), {'events': out_events})
    print(f"Compressed {sum(len(v) for v in groups.values())} one-offs into {len(out_events)} entries → {getattr(args, 'out')}")
    return 0


@app.command("apply", help="Apply a schedule plan (dry-run by default)")
@app.argument("--plan", "--config", dest="plan", help="Plan YAML path")
@app.argument("--calendar", help="Target calendar name (optional)")
@app.argument("--provider", choices=["outlook", "gmail"], help="Provider (default outlook)")
@app.argument("--apply", action="store_true", help="Perform changes (omit for dry-run)")
@app.argument("--client-id", help="Outlook client ID")
@app.argument("--tenant", help="Azure tenant (default consumers)")
@app.argument("--token", help="Path to Outlook token cache")
def cmd_apply(args: argparse.Namespace) -> int:
    plan_value = getattr(args, "plan", None)
    if not plan_value:
        print("Missing --plan PATH")
        return 2
    auth = OutlookAuth(
        profile=getattr(args, "profile", None),
        client_id=getattr(args, "client_id", None),
        tenant=getattr(args, "tenant", None),
        token_path=getattr(args, "token", None),
    )
    request = ApplyRequest(
        plan_path=Path(plan_value),
        calendar=getattr(args, "calendar", None),
        provider=getattr(args, "provider", None) or "outlook",
        apply=bool(getattr(args, "apply", False)),
        auth=auth,
    )
    envelope = ApplyProcessor().process(ApplyRequestConsumer(request).consume())
    ApplyProducer().produce(envelope)
    if envelope.ok():
        return 0
    return int((envelope.diagnostics or {}).get("code", 2))


# Backward compatibility aliases for tests
_cmd_plan = cmd_plan
_cmd_verify = cmd_verify
_cmd_sync = cmd_sync
_cmd_export = cmd_export
_cmd_compress = cmd_compress
_cmd_apply = cmd_apply


def main(argv: Optional[List[str]] = None) -> int:
    """Run the CLI."""
    # Build parser and add agentic flags
    parser = app.build_parser()
    assistant.add_agentic_flags(parser)

    # Parse args
    args = parser.parse_args(argv)

    # Handle agentic output
    agentic_result = assistant.maybe_emit_agentic(args, emit_func=_emit_agentic)
    if agentic_result is not None:
        return int(agentic_result)

    # Get the command function
    cmd_func = getattr(args, "_cmd_func", None)
    if cmd_func is None:
        parser.print_help()
        return 0

    # Run the command
    return int(cmd_func(args))


if __name__ == "__main__":
    raise SystemExit(main())
