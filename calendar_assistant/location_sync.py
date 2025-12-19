from __future__ import annotations

"""Higher-level helpers for location sync (plan/apply)."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .selection import compute_window, filter_events_by_day_time
from .model import normalize_event


@dataclass
class LocationSync:
    svc: Any  # OutlookService

    def _current_location_str(self, ev: Dict[str, Any]) -> str:
        loc = ev.get("location") or {}
        addr = loc.get("address") or {}
        disp = (loc.get("displayName") or "").strip()
        parts = [addr.get("street"), addr.get("city"), addr.get("state"), addr.get("postalCode"), addr.get("countryOrRegion")]
        addr_str = ", ".join([p for p in parts if p])
        return addr_str or disp

    def _select_matches(
        self,
        *,
        cal_name: Optional[str],
        subj: str,
        win: Tuple[str, str],
        byday: List[str],
        start_time: Optional[str],
        end_time: Optional[str],
    ) -> List[Dict[str, Any]]:
        start_iso, end_iso = win
        events = self.svc.list_events_in_range(calendar_name=cal_name, start_iso=start_iso, end_iso=end_iso, subject_filter=subj)
        return filter_events_by_day_time(events, byday=byday, start_time=start_time, end_time=end_time) or events[:1]

    def plan_from_config(self, items: List[Dict[str, Any]], *, calendar: Optional[str], dry_run: bool = False) -> int:
        updated = 0
        for i, ev in enumerate(items, start=1):
            if not isinstance(ev, dict):
                continue
            nev = normalize_event(ev)
            subj = (nev.get("subject") or "").strip()
            if not subj:
                continue
            cal_name = calendar or nev.get("calendar")
            yaml_loc = (nev.get("location") or "").strip()
            byday = nev.get("byday") or []
            start_time = (nev.get("start_time") or "").strip()
            end_time = (nev.get("end_time") or "").strip()
            win = compute_window(nev)
            if not win:
                continue
            try:
                matches = self._select_matches(cal_name=cal_name, subj=subj, win=win, byday=byday, start_time=start_time, end_time=end_time)
            except Exception:
                continue
            if not matches:
                continue
            sel = matches[0]
            cur_str = self._current_location_str(sel)
            if yaml_loc and cur_str and yaml_loc != cur_str:
                if dry_run:
                    updated += 1
                else:
                    ev["location"] = cur_str
                    updated += 1
        return updated

    def apply_from_config(self, items: List[Dict[str, Any]], *, calendar: Optional[str], all_occurrences: bool = False, dry_run: bool = False) -> int:
        updated = 0
        for i, ev in enumerate(items, start=1):
            if not isinstance(ev, dict):
                continue
            nev = normalize_event(ev)
            subj = (nev.get("subject") or "").strip()
            yaml_loc = (nev.get("location") or "").strip()
            if not (subj and yaml_loc):
                continue
            cal_name = calendar or nev.get("calendar")
            byday = nev.get("byday") or []
            start_time = (nev.get("start_time") or "").strip()
            end_time = (nev.get("end_time") or "").strip()
            win = compute_window(nev)
            if not win:
                continue
            try:
                matches = self._select_matches(cal_name=cal_name, subj=subj, win=win, byday=byday, start_time=start_time, end_time=end_time)
            except Exception:
                continue
            if not matches:
                continue
            if all_occurrences:
                series_ids = set()
                occ_ids = []
                for m in matches:
                    sid = m.get("seriesMasterId")
                    if sid:
                        series_ids.add(sid)
                    else:
                        oid = m.get("id")
                        if oid:
                            occ_ids.append(oid)
                for sid in series_ids:
                    if dry_run:
                        updated += 1
                        print(f"[dry-run] would update series '{subj}' -> '{yaml_loc}' (seriesId={sid})")
                    else:
                        self.svc.update_event_location(event_id=sid, calendar_name=cal_name, location_str=yaml_loc)
                        updated += 1
                        print(f"Updated series: {subj} -> {yaml_loc}")
                for oid in occ_ids:
                    if dry_run:
                        updated += 1
                        print(f"[dry-run] would update occurrence '{subj}' -> '{yaml_loc}' (eventId={oid})")
                    else:
                        self.svc.update_event_location(event_id=oid, calendar_name=cal_name, location_str=yaml_loc)
                        updated += 1
                        print(f"Updated occurrence: {subj} -> {yaml_loc}")
            else:
                sel = matches[0]
                cur = self._current_location_str(sel)
                if cur == yaml_loc:
                    continue
                tgt = sel.get("seriesMasterId") or sel.get("id")
                if not tgt:
                    continue
                if dry_run:
                    updated += 1
                    print(f"[dry-run] would update '{subj}' -> '{yaml_loc}' (eventId={tgt})")
                else:
                    self.svc.update_event_location(event_id=tgt, calendar_name=cal_name, location_str=yaml_loc)
                    updated += 1
                    print(f"Updated: {subj} location -> {yaml_loc}")
        return updated
