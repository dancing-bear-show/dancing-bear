"""Higher-level helpers for location sync (plan/apply)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .selection import compute_window, filter_events_by_day_time
from .model import normalize_event


@dataclass
class MatchCriteria:
    """Criteria for matching calendar events."""

    cal_name: Optional[str]
    subj: str
    win: Tuple[str, str]
    byday: List[str]
    start_time: Optional[str]
    end_time: Optional[str]


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

    def _select_matches_from_criteria(self, criteria: MatchCriteria) -> List[Dict[str, Any]]:
        """Select matching events using MatchCriteria."""
        from calendars.outlook_service import ListEventsRequest
        events = self.svc.list_events_in_range(ListEventsRequest(
            start_iso=criteria.win[0],
            end_iso=criteria.win[1],
            calendar_name=criteria.cal_name,
            subject_filter=criteria.subj,
        ))
        return filter_events_by_day_time(
            events, byday=criteria.byday, start_time=criteria.start_time, end_time=criteria.end_time
        ) or events[:1]

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
        """Select matching events (legacy signature)."""
        criteria = MatchCriteria(
            cal_name=cal_name,
            subj=subj,
            win=win,
            byday=byday,
            start_time=start_time,
            end_time=end_time,
        )
        return self._select_matches_from_criteria(criteria)

    def _resolve_event_criteria(
        self, ev: Dict[str, Any], calendar: Optional[str]
    ) -> Optional["MatchCriteria"]:
        """Normalize event and return MatchCriteria, or None if insufficient data."""
        if not isinstance(ev, dict):
            return None
        nev = normalize_event(ev)
        subj = (nev.get("subject") or "").strip()
        if not subj:
            return None
        win = compute_window(nev)
        if not win:
            return None
        return MatchCriteria(
            cal_name=calendar or nev.get("calendar"),
            subj=subj,
            win=win,
            byday=nev.get("byday") or [],
            start_time=(nev.get("start_time") or "").strip(),
            end_time=(nev.get("end_time") or "").strip(),
        )

    def _resolve_event_location(
        self, ev: Dict[str, Any], calendar: Optional[str]
    ) -> Optional[Tuple[Dict[str, Any], str, str]]:
        """Return (nev, yaml_loc, cal_name) for an event, or None if not applicable."""
        if not isinstance(ev, dict):
            return None
        nev = normalize_event(ev)
        subj = (nev.get("subject") or "").strip()
        yaml_loc = (nev.get("location") or "").strip()
        if not (subj and yaml_loc):
            return None
        cal_name = calendar or nev.get("calendar")
        return nev, yaml_loc, cal_name

    def plan_from_config(self, items: List[Dict[str, Any]], *, calendar: Optional[str], dry_run: bool = False) -> int:
        updated = 0
        for ev in items:
            criteria = self._resolve_event_criteria(ev, calendar)
            if not criteria:
                continue
            yaml_loc = (normalize_event(ev).get("location") or "").strip()
            try:
                matches = self._select_matches_from_criteria(criteria)
            except Exception:  # nosec B112 - skip events that fail to match
                continue
            if not matches:
                continue
            cur_str = self._current_location_str(matches[0])
            if yaml_loc and cur_str and yaml_loc != cur_str:
                if not dry_run:
                    ev["location"] = cur_str
                updated += 1
        return updated

    def _apply_location_to_id(
        self, event_id: str, subj: str, yaml_loc: str, cal_name: Optional[str],
        dry_run: bool, label: str
    ) -> None:
        """Update a single event/series location (dry-run safe)."""
        if dry_run:
            print(f"[dry-run] would update {label} '{subj}' -> '{yaml_loc}' (id={event_id})")
        else:
            self.svc.update_event_location(event_id=event_id, calendar_name=cal_name, location_str=yaml_loc)
            print(f"Updated {label}: {subj} -> {yaml_loc}")

    def _apply_all_occurrences(
        self, matches: List[Dict[str, Any]], subj: str, yaml_loc: str,
        cal_name: Optional[str], dry_run: bool
    ) -> int:
        """Update all series/occurrence IDs from matches. Returns count updated."""
        series_ids: set = set()
        occ_ids: List[str] = []
        for m in matches:
            sid = m.get("seriesMasterId")
            if sid:
                series_ids.add(sid)
            else:
                oid = m.get("id")
                if oid:
                    occ_ids.append(oid)
        for sid in series_ids:
            self._apply_location_to_id(sid, subj, yaml_loc, cal_name, dry_run, "series")
        for oid in occ_ids:
            self._apply_location_to_id(oid, subj, yaml_loc, cal_name, dry_run, "occurrence")
        return len(series_ids) + len(occ_ids)

    def _apply_single_match(
        self, matches: List[Dict[str, Any]], subj: str, yaml_loc: str,
        cal_name: Optional[str], dry_run: bool
    ) -> int:
        """Update the first matching event only. Returns 1 if updated, 0 otherwise."""
        sel = matches[0]
        cur = self._current_location_str(sel)
        if cur == yaml_loc:
            return 0
        tgt = sel.get("seriesMasterId") or sel.get("id")
        if not tgt:
            return 0
        self._apply_location_to_id(tgt, subj, yaml_loc, cal_name, dry_run, "event")
        return 1

    def apply_from_config(self, items: List[Dict[str, Any]], *, calendar: Optional[str], all_occurrences: bool = False, dry_run: bool = False) -> int:
        updated = 0
        for ev in items:
            result = self._resolve_event_location(ev, calendar)
            if not result:
                continue
            nev, yaml_loc, cal_name = result
            subj = (nev.get("subject") or "").strip()
            criteria = self._resolve_event_criteria(ev, calendar)
            if not criteria:
                continue
            try:
                matches = self._select_matches_from_criteria(criteria)
            except Exception:  # nosec B112 - skip events that fail to match
                continue
            if not matches:
                continue
            if all_occurrences:
                updated += self._apply_all_occurrences(matches, subj, yaml_loc, cal_name, dry_run)
            else:
                updated += self._apply_single_match(matches, subj, yaml_loc, cal_name, dry_run)
        return updated
