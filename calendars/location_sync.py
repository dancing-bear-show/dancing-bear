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

    def _parse_config_item(self, ev: Dict[str, Any], calendar: Optional[str]) -> Optional[MatchCriteria]:
        """Parse config item into MatchCriteria, returns None if invalid."""
        if not isinstance(ev, dict):
            return None
        nev = normalize_event(ev)
        subj = (nev.get("subject") or "").strip()
        if not subj:
            return None
        cal_name = calendar or nev.get("calendar")
        win = compute_window(nev)
        if not win:
            return None
        return MatchCriteria(
            cal_name=cal_name,
            subj=subj,
            win=win,
            byday=nev.get("byday") or [],
            start_time=(nev.get("start_time") or "").strip(),
            end_time=(nev.get("end_time") or "").strip(),
        )

    def _find_matches_safe(self, criteria: MatchCriteria) -> List[Dict[str, Any]]:
        """Find matching events, returns empty list on error."""
        try:
            return self._select_matches_from_criteria(criteria)
        except Exception:  # nosec B112 - skip events that fail to match
            return []

    def _collect_event_ids(self, matches: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
        """Collect series IDs and occurrence IDs from matches."""
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
        return list(series_ids), occ_ids

    def _update_all_occurrences(self, subj: str, yaml_loc: str, cal_name: Optional[str],
                                matches: List[Dict[str, Any]], dry_run: bool) -> int:
        """Update all occurrences (series and standalone events)."""
        series_ids, occ_ids = self._collect_event_ids(matches)
        updated = 0
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
        return updated

    def _update_first_match(self, subj: str, yaml_loc: str, cal_name: Optional[str],
                           sel: Dict[str, Any], dry_run: bool) -> int:
        """Update the first matching event."""
        cur = self._current_location_str(sel)
        if cur == yaml_loc:
            return 0
        tgt = sel.get("seriesMasterId") or sel.get("id")
        if not tgt:
            return 0
        if dry_run:
            print(f"[dry-run] would update '{subj}' -> '{yaml_loc}' (eventId={tgt})")
            return 1
        else:
            self.svc.update_event_location(event_id=tgt, calendar_name=cal_name, location_str=yaml_loc)
            print(f"Updated: {subj} location -> {yaml_loc}")
            return 1

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

    def plan_from_config(self, items: List[Dict[str, Any]], *, calendar: Optional[str], dry_run: bool = False) -> int:
        updated = 0
        for i, ev in enumerate(items, start=1):
            criteria = self._parse_config_item(ev, calendar)
            if not criteria:
                continue
            nev = normalize_event(ev)
            yaml_loc = (nev.get("location") or "").strip()
            matches = self._find_matches_safe(criteria)
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
            criteria = self._parse_config_item(ev, calendar)
            if not criteria:
                continue
            nev = normalize_event(ev)
            yaml_loc = (nev.get("location") or "").strip()
            if not yaml_loc:
                continue
            matches = self._find_matches_safe(criteria)
            if not matches:
                continue
            if all_occurrences:
                updated += self._update_all_occurrences(criteria.subj, yaml_loc, criteria.cal_name, matches, dry_run)
            else:
                updated += self._update_first_match(criteria.subj, yaml_loc, criteria.cal_name, matches[0], dry_run)
        return updated
