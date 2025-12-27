"""Outlook pipeline components for calendar assistant.

Provides pipelines for Outlook calendar operations: verify, add, remove,
share, reminders, settings, dedup, and more.
"""

# Re-export constants from _base
from ._base import (
    ERR_OUTLOOK_SERVICE_REQUIRED,
    ERR_CONFIG_MUST_CONTAIN_EVENTS,
    MSG_PREVIEW_COMPLETE,
)

# Import all pipeline components using star imports
from .verify import *  # noqa: F401, F403
from .add import *  # noqa: F401, F403
from .schedule_import import *  # noqa: F401, F403
from .events import *  # noqa: F401, F403
from .share import *  # noqa: F401, F403
from .add_event import *  # noqa: F401, F403
from .locations import *  # noqa: F401, F403
from .remove import *  # noqa: F401, F403
from .reminders import *  # noqa: F401, F403
from .settings import *  # noqa: F401, F403
from .dedup import *  # noqa: F401, F403
from .mail import *  # noqa: F401, F403

__all__ = [
    # Constants
    "ERR_OUTLOOK_SERVICE_REQUIRED",
    "ERR_CONFIG_MUST_CONTAIN_EVENTS",
    "MSG_PREVIEW_COMPLETE",
]
