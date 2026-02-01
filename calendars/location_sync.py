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

    def _extract_plan_fields(self, ev: Dict[str, Any], calendar: Optional[str]) -> Optional[Dict[str, Any]]:
        """Extract and validate fields needed for planning. Returns None if invalid."""
        nev = normalize_event(ev)
        subj = (nev.get("subject") or "").strip()
        if not subj:
            return None
        win = compute_window(nev)
        if not win:
            return None
        return {
            "nev": nev,
            "subj": subj,
            "cal_name": calendar or nev.get("calendar"),
            "yaml_loc": (nev.get("location") or "").strip(),
            "byday": nev.get("byday") or [],
            "start_time": (nev.get("start_time") or "").strip(),
            "end_time": (nev.get("end_time") or "").strip(),
            "win": win,
        }

    def plan_from_config(self, items: List[Dict[str, Any]], *, calendar: Optional[str], dry_run: bool = False) -> int:
        updated = 0
        for ev in items:
            if not isinstance(ev, dict):
                continue
            fields = self._extract_plan_fields(ev, calendar)
            if not fields:
                continue
            try:
                matches = self._select_matches(
                    cal_name=fields["cal_name"],
                    subj=fields["subj"],
                    win=fields["win"],
                    byday=fields["byday"],
                    start_time=fields["start_time"],
                    end_time=fields["end_time"],
                )
            except Exception:  # nosec B112 - skip events that fail to match
                continue
            if not matches:
                continue
            sel = matches[0]
            cur_str = self._current_location_str(sel)
            yaml_loc = fields["yaml_loc"]
            if yaml_loc and cur_str and yaml_loc != cur_str:
                if not dry_run:
                    ev["location"] = cur_str
                updated += 1
        return updated

    def _extract_apply_fields(self, ev: Dict[str, Any], calendar: Optional[str]) -> Optional[Dict[str, Any]]:
        """Extract and validate fields needed for applying. Returns None if invalid."""
        nev = normalize_event(ev)
        subj = (nev.get("subject") or "").strip()
        yaml_loc = (nev.get("location") or "").strip()
        if not (subj and yaml_loc):
            return None
        win = compute_window(nev)
        if not win:
            return None
        return {
            "subj": subj,
            "yaml_loc": yaml_loc,
            "cal_name": calendar or nev.get("calendar"),
            "byday": nev.get("byday") or [],
            "start_time": (nev.get("start_time") or "").strip(),
            "end_time": (nev.get("end_time") or "").strip(),
            "win": win,
        }

    def _collect_occurrence_ids(self, matches: List[Dict[str, Any]]) -> Tuple[set, List[str]]:
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
        return series_ids, occ_ids

    def _update_series_locations(self, series_ids: set, subj: str, yaml_loc: str, cal_name: Optional[str], dry_run: bool) -> int:
        """Update location for all series masters."""
        count = 0
        for sid in series_ids:
            if dry_run:
                print(f"[dry-run] would update series '{subj}' -> '{yaml_loc}' (seriesId={sid})")
            else:
                self.svc.update_event_location(event_id=sid, calendar_name=cal_name, location_str=yaml_loc)
                print(f"Updated series: {subj} -> {yaml_loc}")
            count += 1
        return count

    def _update_occurrence_locations(self, occ_ids: List[str], subj: str, yaml_loc: str, cal_name: Optional[str], dry_run: bool) -> int:
        """Update location for all occurrences."""
        count = 0
        for oid in occ_ids:
            if dry_run:
                print(f"[dry-run] would update occurrence '{subj}' -> '{yaml_loc}' (eventId={oid})")
            else:
                self.svc.update_event_location(event_id=oid, calendar_name=cal_name, location_str=yaml_loc)
                print(f"Updated occurrence: {subj} -> {yaml_loc}")
            count += 1
        return count

    def _apply_all_occurrences(self, matches: List[Dict[str, Any]], subj: str, yaml_loc: str, cal_name: Optional[str], dry_run: bool) -> int:
        """Apply location to all series masters and occurrences."""
        series_ids, occ_ids = self._collect_occurrence_ids(matches)
        count = self._update_series_locations(series_ids, subj, yaml_loc, cal_name, dry_run)
        count += self._update_occurrence_locations(occ_ids, subj, yaml_loc, cal_name, dry_run)
        return count

    def _apply_first_match(self, matches: List[Dict[str, Any]], subj: str, yaml_loc: str, cal_name: Optional[str], dry_run: bool) -> int:
        """Apply location to first match only."""
        sel = matches[0]
        cur = self._current_location_str(sel)
        if cur == yaml_loc:
            return 0
        tgt = sel.get("seriesMasterId") or sel.get("id")
        if not tgt:
            return 0
        if dry_run:
            print(f"[dry-run] would update '{subj}' -> '{yaml_loc}' (eventId={tgt})")
        else:
            self.svc.update_event_location(event_id=tgt, calendar_name=cal_name, location_str=yaml_loc)
            print(f"Updated: {subj} location -> {yaml_loc}")
        return 1

    def apply_from_config(self, items: List[Dict[str, Any]], *, calendar: Optional[str], all_occurrences: bool = False, dry_run: bool = False) -> int:
        updated = 0
        for ev in items:
            if not isinstance(ev, dict):
                continue
            fields = self._extract_apply_fields(ev, calendar)
            if not fields:
                continue
            try:
                matches = self._select_matches(
                    cal_name=fields["cal_name"],
                    subj=fields["subj"],
                    win=fields["win"],
                    byday=fields["byday"],
                    start_time=fields["start_time"],
                    end_time=fields["end_time"],
                )
            except Exception:  # nosec B112 - skip events that fail to match
                continue
            if not matches:
                continue
            if all_occurrences:
                updated += self._apply_all_occurrences(matches, fields["subj"], fields["yaml_loc"], fields["cal_name"], dry_run)
            else:
                updated += self._apply_first_match(matches, fields["subj"], fields["yaml_loc"], fields["cal_name"], dry_run)
        return updated
