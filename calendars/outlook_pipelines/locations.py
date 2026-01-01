"""Outlook Locations Pipelines - enrich, update, and apply location data."""

from ._base import (
    Any,
    BaseProducer,
    DateWindowResolver,
    Dict,
    List,
    LocationSync,
    LOG_DRY_RUN,
    MSG_PREVIEW_COMPLETE,
    Optional,
    Path,
    RequestConsumer,
    ResultEnvelope,
    SafeProcessor,
    check_service_required,
    dataclass,
    load_events_config,
)


# =============================================================================
# Outlook Locations Enrich Pipeline
# =============================================================================

@dataclass
class OutlookLocationsEnrichRequest:
    service: Any
    calendar: str
    from_date: Optional[str]
    to_date: Optional[str]
    dry_run: bool


OutlookLocationsEnrichRequestConsumer = RequestConsumer[OutlookLocationsEnrichRequest]


@dataclass
class OutlookLocationsEnrichResult:
    updated: int
    dry_run: bool


class CalendarNotFoundError(ValueError):
    """Raised when a calendar is not found."""

    def __init__(self, calendar_name: str):
        self.calendar_name = calendar_name
        super().__init__(f"Calendar not found: {calendar_name}")


class OutlookLocationsEnrichProcessor(SafeProcessor[OutlookLocationsEnrichRequest, OutlookLocationsEnrichResult]):
    def __init__(self, today_factory=None, enricher=None) -> None:
        self._window = DateWindowResolver(today_factory)
        self._enricher = enricher
        self._logs: List[str] = []

    def _process_safe(self, payload: OutlookLocationsEnrichRequest) -> OutlookLocationsEnrichResult:
        check_service_required(payload.service)
        svc = payload.service
        cal_id = svc.find_calendar_id(payload.calendar)
        if not cal_id:
            raise CalendarNotFoundError(payload.calendar)

        start_iso, end_iso = self._window.resolve_year_end(payload.from_date, payload.to_date)
        from calendars.outlook_service import ListEventsRequest
        events = svc.list_events_in_range(ListEventsRequest(
            start_iso=start_iso,
            end_iso=end_iso,
            calendar_id=cal_id,
        ))

        enricher = self._enricher
        if enricher is None:
            from calendars.locations_map import enrich_location as default_enrich

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
            return OutlookLocationsEnrichResult(updated=0, dry_run=payload.dry_run)

        updated = 0
        self._logs = []
        for sid, ev in series.items():
            loc = ((ev.get("location") or {}).get("displayName") or "") or ""
            new_loc = enricher(loc)
            if not new_loc or new_loc == loc:
                continue
            if payload.dry_run:
                self._logs.append(f"{LOG_DRY_RUN} would update series {sid} location '{loc}' -> '{new_loc}'")
                continue
            try:
                svc.update_event_location(event_id=sid, calendar_id=cal_id, location_str=new_loc)
                updated += 1
                self._logs.append(f"Updated series {sid} location -> {new_loc}")
            except Exception as exc:
                self._logs.append(f"Failed to update series {sid}: {exc}")

        return OutlookLocationsEnrichResult(updated=updated, dry_run=payload.dry_run)

    def process(self, payload: OutlookLocationsEnrichRequest) -> ResultEnvelope[OutlookLocationsEnrichResult]:
        """Override to add logs to diagnostics."""
        self._logs = []
        env = super().process(payload)
        if env.ok() and self._logs:
            env = ResultEnvelope(status="success", payload=env.payload, diagnostics={"logs": self._logs})
        return env


class OutlookLocationsEnrichProducer(BaseProducer):
    def _produce_success(self, payload: OutlookLocationsEnrichResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        logs = (diagnostics or {}).get("logs") or []
        self.print_logs(logs)
        if payload.dry_run:
            print(MSG_PREVIEW_COMPLETE)
        else:
            print(f"Updated locations on {payload.updated} series.")


# =============================================================================
# Outlook Locations Update/Apply Pipeline
# =============================================================================

@dataclass
class OutlookLocationsRequest:
    config_path: Path
    calendar: Optional[str]
    dry_run: bool
    all_occurrences: bool = False
    service: Any = None


OutlookLocationsRequestConsumer = RequestConsumer[OutlookLocationsRequest]


@dataclass
class OutlookLocationsResult:
    message: str


class OutlookLocationsUpdateProcessor(SafeProcessor[OutlookLocationsRequest, OutlookLocationsResult]):
    def __init__(self, config_loader=None) -> None:
        self._config_loader = config_loader

    def _process_safe(self, payload: OutlookLocationsRequest) -> OutlookLocationsResult:
        items = load_events_config(payload.config_path, self._config_loader)
        sync = LocationSync(payload.service)
        updated = sync.plan_from_config(items, calendar=payload.calendar, dry_run=payload.dry_run)
        if payload.dry_run:
            msg = "Preview complete. No changes written."
            return OutlookLocationsResult(message=msg)
        from calendars.yamlio import dump_config

        if updated:
            dump_config(str(payload.config_path), {"events": items})
            msg = f"Wrote updated locations to {payload.config_path} (updated {updated})."
        else:
            msg = "No location changes detected."
        return OutlookLocationsResult(message=msg)


class OutlookLocationsApplyProcessor(SafeProcessor[OutlookLocationsRequest, OutlookLocationsResult]):
    def __init__(self, config_loader=None) -> None:
        self._config_loader = config_loader

    def _process_safe(self, payload: OutlookLocationsRequest) -> OutlookLocationsResult:
        items = load_events_config(payload.config_path, self._config_loader)
        sync = LocationSync(payload.service)
        updated = sync.apply_from_config(
            items,
            calendar=payload.calendar,
            all_occurrences=payload.all_occurrences,
            dry_run=payload.dry_run,
        )
        if payload.dry_run:
            msg = MSG_PREVIEW_COMPLETE
        else:
            msg = f"Applied {updated} location update(s)."
        return OutlookLocationsResult(message=msg)


class OutlookLocationsProducer(BaseProducer):
    def _produce_success(self, payload: OutlookLocationsResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        print(payload.message)


__all__ = [
    "OutlookLocationsEnrichRequest",
    "OutlookLocationsEnrichRequestConsumer",
    "OutlookLocationsEnrichResult",
    "OutlookLocationsEnrichProcessor",
    "OutlookLocationsEnrichProducer",
    "OutlookLocationsRequest",
    "OutlookLocationsRequestConsumer",
    "OutlookLocationsResult",
    "OutlookLocationsUpdateProcessor",
    "OutlookLocationsApplyProcessor",
    "OutlookLocationsProducer",
]
