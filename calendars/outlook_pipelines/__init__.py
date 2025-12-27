"""Outlook pipeline components for calendar assistant.

Provides pipelines for Outlook calendar operations: verify, add, remove,
share, reminders, settings, dedup, and more.

This package was refactored from a single module into smaller, focused modules
for better maintainability.
"""

# Re-export constants from _base
from ._base import (
    ERR_OUTLOOK_SERVICE_REQUIRED,
    ERR_CONFIG_MUST_CONTAIN_EVENTS,
    MSG_PREVIEW_COMPLETE,
)

# Verify pipeline
from .verify import (
    OutlookVerifyRequest,
    OutlookVerifyRequestConsumer,
    OutlookVerifyResult,
    OutlookVerifyProcessor,
    OutlookVerifyProducer,
)

# Add pipeline
from .add import (
    OutlookAddRequest,
    OutlookAddRequestConsumer,
    OutlookAddResult,
    OutlookAddProcessor,
    OutlookAddProducer,
)

# Schedule import pipeline
from .schedule_import import (
    OutlookScheduleImportRequest,
    OutlookScheduleImportRequestConsumer,
    OutlookScheduleImportResult,
    OutlookScheduleImportProcessor,
    OutlookScheduleImportProducer,
)

# List one-offs pipeline
from .events import (
    OutlookListOneOffsRequest,
    OutlookListOneOffsRequestConsumer,
    OutlookListOneOffsResult,
    OutlookListOneOffsProcessor,
    OutlookListOneOffsProducer,
)

# Calendar share pipeline
from .share import (
    OutlookCalendarShareRequest,
    OutlookCalendarShareRequestConsumer,
    OutlookCalendarShareResult,
    OutlookCalendarShareProcessor,
    OutlookCalendarShareProducer,
)

# Add event pipelines (single and recurring)
from .add_event import (
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
)

# Locations pipelines (enrich, update, apply)
from .locations import (
    OutlookLocationsEnrichRequest,
    OutlookLocationsEnrichRequestConsumer,
    OutlookLocationsEnrichResult,
    OutlookLocationsEnrichProcessor,
    OutlookLocationsEnrichProducer,
    OutlookLocationsRequest,
    OutlookLocationsRequestConsumer,
    OutlookLocationsResult,
    OutlookLocationsUpdateProcessor,
    OutlookLocationsApplyProcessor,
    OutlookLocationsProducer,
)

# Remove pipeline
from .remove import (
    OutlookRemoveRequest,
    OutlookRemoveRequestConsumer,
    OutlookRemovePlanEntry,
    OutlookRemoveResult,
    OutlookRemoveProcessor,
    OutlookRemoveProducer,
)

# Reminders pipeline
from .reminders import (
    OutlookRemindersRequest,
    OutlookRemindersRequestConsumer,
    OutlookRemindersResult,
    OutlookRemindersProcessor,
    OutlookRemindersProducer,
)

# Settings pipeline
from .settings import (
    OutlookSettingsRequest,
    OutlookSettingsRequestConsumer,
    OutlookSettingsResult,
    OutlookSettingsProcessor,
    OutlookSettingsProducer,
)

# Dedup pipeline
from .dedup import (
    OutlookDedupRequest,
    OutlookDedupRequestConsumer,
    OutlookDedupDuplicate,
    OutlookDedupResult,
    OutlookDedupProcessor,
    OutlookDedupProducer,
)

# Mail list pipeline (misplaced - kept for backward compatibility)
from .mail import (
    OutlookMailListRequest,
    OutlookMailListRequestConsumer,
    OutlookMailListResult,
    OutlookMailListProcessor,
    OutlookMailListProducer,
)

__all__ = [
    # Constants
    "ERR_OUTLOOK_SERVICE_REQUIRED",
    "ERR_CONFIG_MUST_CONTAIN_EVENTS",
    "MSG_PREVIEW_COMPLETE",
    # Verify
    "OutlookVerifyRequest",
    "OutlookVerifyRequestConsumer",
    "OutlookVerifyResult",
    "OutlookVerifyProcessor",
    "OutlookVerifyProducer",
    # Add
    "OutlookAddRequest",
    "OutlookAddRequestConsumer",
    "OutlookAddResult",
    "OutlookAddProcessor",
    "OutlookAddProducer",
    # Schedule Import
    "OutlookScheduleImportRequest",
    "OutlookScheduleImportRequestConsumer",
    "OutlookScheduleImportResult",
    "OutlookScheduleImportProcessor",
    "OutlookScheduleImportProducer",
    # List One-Offs
    "OutlookListOneOffsRequest",
    "OutlookListOneOffsRequestConsumer",
    "OutlookListOneOffsResult",
    "OutlookListOneOffsProcessor",
    "OutlookListOneOffsProducer",
    # Calendar Share
    "OutlookCalendarShareRequest",
    "OutlookCalendarShareRequestConsumer",
    "OutlookCalendarShareResult",
    "OutlookCalendarShareProcessor",
    "OutlookCalendarShareProducer",
    # Add Event
    "OutlookAddEventRequest",
    "OutlookAddEventRequestConsumer",
    "OutlookAddEventResult",
    "OutlookAddEventProcessor",
    "OutlookAddEventProducer",
    # Add Recurring
    "OutlookAddRecurringRequest",
    "OutlookAddRecurringRequestConsumer",
    "OutlookAddRecurringResult",
    "OutlookAddRecurringProcessor",
    "OutlookAddRecurringProducer",
    # Locations Enrich
    "OutlookLocationsEnrichRequest",
    "OutlookLocationsEnrichRequestConsumer",
    "OutlookLocationsEnrichResult",
    "OutlookLocationsEnrichProcessor",
    "OutlookLocationsEnrichProducer",
    # Locations Update/Apply
    "OutlookLocationsRequest",
    "OutlookLocationsRequestConsumer",
    "OutlookLocationsResult",
    "OutlookLocationsUpdateProcessor",
    "OutlookLocationsApplyProcessor",
    "OutlookLocationsProducer",
    # Remove
    "OutlookRemoveRequest",
    "OutlookRemoveRequestConsumer",
    "OutlookRemovePlanEntry",
    "OutlookRemoveResult",
    "OutlookRemoveProcessor",
    "OutlookRemoveProducer",
    # Reminders
    "OutlookRemindersRequest",
    "OutlookRemindersRequestConsumer",
    "OutlookRemindersResult",
    "OutlookRemindersProcessor",
    "OutlookRemindersProducer",
    # Settings
    "OutlookSettingsRequest",
    "OutlookSettingsRequestConsumer",
    "OutlookSettingsResult",
    "OutlookSettingsProcessor",
    "OutlookSettingsProducer",
    # Dedup
    "OutlookDedupRequest",
    "OutlookDedupRequestConsumer",
    "OutlookDedupDuplicate",
    "OutlookDedupResult",
    "OutlookDedupProcessor",
    "OutlookDedupProducer",
    # Mail List (misplaced - kept for backward compatibility)
    "OutlookMailListRequest",
    "OutlookMailListRequestConsumer",
    "OutlookMailListResult",
    "OutlookMailListProcessor",
    "OutlookMailListProducer",
]
