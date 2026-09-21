"""Calendar assistant pipeline components.

This module re-exports all pipeline components from their implementation modules:
- pipeline_base.py: Shared utilities and base classes
- gmail_types.py, gmail_pipeline_receipts.py, gmail_pipeline_scan_classes.py,
  gmail_pipeline_mail_list.py, gmail_pipeline_sweep_top.py: Gmail-related pipelines
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

# Re-export Gmail pipelines
from .gmail_types import CalendarEvent
from .gmail_pipeline_receipts import (
    GmailReceiptsRequest,
    GmailReceiptsRequestConsumer,
    GmailScanResult,
    GmailScanProducer,
    # Backwards-compatible aliases (C10 rename)
    GmailPlanResult,
    GmailPlanProducer,
    GmailReceiptsProcessor,
)
from .gmail_pipeline_scan_classes import (
    GmailScanClassesRequest,
    GmailScanClassesRequestConsumer,
    GmailScanClassesResult,
    GmailScanClassesProcessor,
    GmailScanClassesProducer,
)
from .gmail_pipeline_mail_list import (
    GmailMailListRequest,
    GmailMailListRequestConsumer,
    GmailMailListResult,
    GmailMailListProcessor,
    GmailMailListProducer,
)
from .gmail_pipeline_sweep_top import (
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
    # Gmail pipelines
    "CalendarEvent",
    "GmailReceiptsRequest",
    "GmailReceiptsRequestConsumer",
    "GmailScanResult",
    "GmailScanProducer",
    "GmailPlanResult",  # backwards-compatible alias
    "GmailPlanProducer",  # backwards-compatible alias
    "GmailReceiptsProcessor",
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
    "_load_schedule_sources",
]
