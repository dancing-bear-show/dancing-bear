"""Calendar assistant pipeline components.

This module re-exports all pipeline components for backward compatibility.
The actual implementations are organized into:
- pipeline_base.py: Shared utilities and base classes
- gmail_pipelines.py: Gmail-related pipelines
- outlook_pipelines.py: Outlook-related pipelines
"""
from __future__ import annotations

# Re-export base utilities
from .pipeline_base import (
    GmailAuth,
    GmailServiceBuilder,
    DateWindowResolver,
    BaseProducer,
    RequestConsumer,
    to_iso_str,
    dedupe_events,
    parse_month,
    MONTH_MAP,
    DAY_MAP,
)

# Backwards-compatible aliases (maintained in this re-export module)
MONTH_MAP_FULL = MONTH_MAP
MONTH_MAP_ABBREV = MONTH_MAP
DAY_TO_CODE = DAY_MAP

# Re-export Gmail pipelines
from .gmail_pipelines import (
    GmailReceiptsRequest,
    GmailReceiptsRequestConsumer,
    GmailPlanResult,
    GmailReceiptsProcessor,
    GmailPlanProducer,
    GmailScanClassesRequest,
    GmailScanClassesRequestConsumer,
    GmailScanClassesResult,
    GmailScanClassesProcessor,
    GmailScanClassesProducer,
    GmailMailListRequest,
    GmailMailListRequestConsumer,
    GmailMailListResult,
    GmailMailListProcessor,
    GmailMailListProducer,
    GmailSweepTopRequest,
    GmailSweepTopRequestConsumer,
    GmailSweepTopResult,
    GmailSweepTopProcessor,
    GmailSweepTopProducer,
)

# Re-export Outlook pipelines
from .outlook_pipelines import (
    OutlookVerifyRequest,
    OutlookVerifyRequestConsumer,
    OutlookVerifyResult,
    OutlookVerifyProcessor,
    OutlookVerifyProducer,
    OutlookAddRequest,
    OutlookAddRequestConsumer,
    OutlookAddResult,
    OutlookAddProcessor,
    OutlookAddProducer,
    OutlookScheduleImportRequest,
    OutlookScheduleImportRequestConsumer,
    OutlookScheduleImportResult,
    OutlookScheduleImportProcessor,
    OutlookScheduleImportProducer,
    OutlookListOneOffsRequest,
    OutlookListOneOffsRequestConsumer,
    OutlookListOneOffsResult,
    OutlookListOneOffsProcessor,
    OutlookListOneOffsProducer,
    OutlookCalendarShareRequest,
    OutlookCalendarShareRequestConsumer,
    OutlookCalendarShareResult,
    OutlookCalendarShareProcessor,
    OutlookCalendarShareProducer,
    OutlookAddEventRequest,
    OutlookAddEventRequestConsumer,
    OutlookAddEventResult,
    OutlookAddEventProcessor,
    OutlookAddEventProducer,
    OutlookAddRecurringRequest,
    OutlookAddRecurringRequestConsumer,
    OutlookAddRecurringResult,
    OutlookAddRecurringProcessor,
    OutlookAddRecurringProducer,
    OutlookLocationsEnrichRequest,
    OutlookLocationsEnrichRequestConsumer,
    OutlookLocationsEnrichResult,
    OutlookLocationsEnrichProcessor,
    OutlookLocationsEnrichProducer,
    OutlookMailListRequest,
    OutlookMailListRequestConsumer,
    OutlookMailListResult,
    OutlookMailListProcessor,
    OutlookMailListProducer,
    OutlookLocationsRequest,
    OutlookLocationsRequestConsumer,
    OutlookLocationsResult,
    OutlookLocationsUpdateProcessor,
    OutlookLocationsApplyProcessor,
    OutlookLocationsProducer,
    OutlookRemoveRequest,
    OutlookRemoveRequestConsumer,
    OutlookRemovePlanEntry,
    OutlookRemoveResult,
    OutlookRemoveProcessor,
    OutlookRemoveProducer,
    OutlookRemindersRequest,
    OutlookRemindersRequestConsumer,
    OutlookRemindersResult,
    OutlookRemindersProcessor,
    OutlookRemindersProducer,
    OutlookSettingsRequest,
    OutlookSettingsRequestConsumer,
    OutlookSettingsResult,
    OutlookSettingsProcessor,
    OutlookSettingsProducer,
    OutlookDedupRequest,
    OutlookDedupRequestConsumer,
    OutlookDedupDuplicate,
    OutlookDedupResult,
    OutlookDedupProcessor,
    OutlookDedupProducer,
)

# Backward-compatible alias
_to_iso_str = to_iso_str


def _load_schedule_sources(sources, kind):
    """Load schedule items from multiple sources."""
    from calendars.importer import load_schedule
    from calendars.model import normalize_event

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


__all__ = [
    # Base utilities
    "GmailAuth",
    "GmailServiceBuilder",
    "DateWindowResolver",
    "BaseProducer",
    "RequestConsumer",
    "to_iso_str",
    "dedupe_events",
    "parse_month",
    "MONTH_MAP",
    "DAY_MAP",
    "MONTH_MAP_FULL",  # Backwards-compatible alias
    "MONTH_MAP_ABBREV",  # Backwards-compatible alias
    "DAY_TO_CODE",  # Backwards-compatible alias
    # Gmail pipelines
    "GmailReceiptsRequest",
    "GmailReceiptsRequestConsumer",
    "GmailPlanResult",
    "GmailReceiptsProcessor",
    "GmailPlanProducer",
    "GmailScanClassesRequest",
    "GmailScanClassesRequestConsumer",
    "GmailScanClassesResult",
    "GmailScanClassesProcessor",
    "GmailScanClassesProducer",
    "GmailMailListRequest",
    "GmailMailListRequestConsumer",
    "GmailMailListResult",
    "GmailMailListProcessor",
    "GmailMailListProducer",
    "GmailSweepTopRequest",
    "GmailSweepTopRequestConsumer",
    "GmailSweepTopResult",
    "GmailSweepTopProcessor",
    "GmailSweepTopProducer",
    # Outlook pipelines
    "OutlookVerifyRequest",
    "OutlookVerifyRequestConsumer",
    "OutlookVerifyResult",
    "OutlookVerifyProcessor",
    "OutlookVerifyProducer",
    "OutlookAddRequest",
    "OutlookAddRequestConsumer",
    "OutlookAddResult",
    "OutlookAddProcessor",
    "OutlookAddProducer",
    "OutlookScheduleImportRequest",
    "OutlookScheduleImportRequestConsumer",
    "OutlookScheduleImportResult",
    "OutlookScheduleImportProcessor",
    "OutlookScheduleImportProducer",
    "OutlookListOneOffsRequest",
    "OutlookListOneOffsRequestConsumer",
    "OutlookListOneOffsResult",
    "OutlookListOneOffsProcessor",
    "OutlookListOneOffsProducer",
    "OutlookCalendarShareRequest",
    "OutlookCalendarShareRequestConsumer",
    "OutlookCalendarShareResult",
    "OutlookCalendarShareProcessor",
    "OutlookCalendarShareProducer",
    "OutlookAddEventRequest",
    "OutlookAddEventRequestConsumer",
    "OutlookAddEventResult",
    "OutlookAddEventProcessor",
    "OutlookAddEventProducer",
    "OutlookAddRecurringRequest",
    "OutlookAddRecurringRequestConsumer",
    "OutlookAddRecurringResult",
    "OutlookAddRecurringProcessor",
    "OutlookAddRecurringProducer",
    "OutlookLocationsEnrichRequest",
    "OutlookLocationsEnrichRequestConsumer",
    "OutlookLocationsEnrichResult",
    "OutlookLocationsEnrichProcessor",
    "OutlookLocationsEnrichProducer",
    "OutlookMailListRequest",
    "OutlookMailListRequestConsumer",
    "OutlookMailListResult",
    "OutlookMailListProcessor",
    "OutlookMailListProducer",
    "OutlookLocationsRequest",
    "OutlookLocationsRequestConsumer",
    "OutlookLocationsResult",
    "OutlookLocationsUpdateProcessor",
    "OutlookLocationsApplyProcessor",
    "OutlookLocationsProducer",
    "OutlookRemoveRequest",
    "OutlookRemoveRequestConsumer",
    "OutlookRemovePlanEntry",
    "OutlookRemoveResult",
    "OutlookRemoveProcessor",
    "OutlookRemoveProducer",
    "OutlookRemindersRequest",
    "OutlookRemindersRequestConsumer",
    "OutlookRemindersResult",
    "OutlookRemindersProcessor",
    "OutlookRemindersProducer",
    "OutlookSettingsRequest",
    "OutlookSettingsRequestConsumer",
    "OutlookSettingsResult",
    "OutlookSettingsProcessor",
    "OutlookSettingsProducer",
    "OutlookDedupRequest",
    "OutlookDedupRequestConsumer",
    "OutlookDedupDuplicate",
    "OutlookDedupResult",
    "OutlookDedupProcessor",
    "OutlookDedupProducer",
    # Utilities
    "_to_iso_str",
    "_load_schedule_sources",
]
