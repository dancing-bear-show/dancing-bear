from __future__ import annotations

"""Consumers for Outlook pipelines."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.pipeline import Consumer


@dataclass
class OutlookRulesListPayload:
    """Payload for rules list."""
    client: Any
    use_cache: bool = False
    cache_ttl: int = 600


@dataclass
class OutlookRulesExportPayload:
    """Payload for rules export."""
    client: Any
    out_path: str
    use_cache: bool = False
    cache_ttl: int = 600


@dataclass
class OutlookRulesSyncPayload:
    """Payload for rules sync."""
    client: Any
    config_path: str
    dry_run: bool = False
    delete_missing: bool = False
    move_to_folders: bool = False
    verbose: bool = False


@dataclass
class OutlookRulesPlanPayload:
    """Payload for rules plan."""
    client: Any
    config_path: str
    move_to_folders: bool = False
    use_cache: bool = False
    cache_ttl: int = 600


@dataclass
class OutlookRulesDeletePayload:
    """Payload for rules delete."""
    client: Any
    rule_id: str


@dataclass
class OutlookRulesSweepPayload:
    """Payload for rules sweep."""
    client: Any
    config_path: str
    dry_run: bool = False
    move_to_folders: bool = False
    clear_cache: bool = False
    days: int = 30
    top: int = 25
    pages: int = 2


@dataclass
class OutlookCategoriesListPayload:
    """Payload for categories list."""
    client: Any
    use_cache: bool = False
    cache_ttl: int = 600


@dataclass
class OutlookCategoriesExportPayload:
    """Payload for categories export."""
    client: Any
    out_path: str
    use_cache: bool = False
    cache_ttl: int = 600


@dataclass
class OutlookCategoriesSyncPayload:
    """Payload for categories sync."""
    client: Any
    config_path: str
    dry_run: bool = False


@dataclass
class OutlookFoldersSyncPayload:
    """Payload for folders sync."""
    client: Any
    config_path: str
    dry_run: bool = False


@dataclass
class OutlookCalendarAddPayload:
    """Payload for calendar add."""
    client: Any
    subject: str
    start_iso: str
    end_iso: str
    calendar_name: Optional[str] = None
    tz: Optional[str] = None
    body_html: Optional[str] = None
    all_day: bool = False
    location: Optional[str] = None
    no_reminder: bool = False


@dataclass
class OutlookCalendarAddRecurringPayload:
    """Payload for calendar add recurring."""
    client: Any
    subject: str
    start_time: str
    end_time: str
    repeat: str
    range_start: str
    calendar_name: Optional[str] = None
    tz: Optional[str] = None
    interval: int = 1
    byday: Optional[List[str]] = None
    until: Optional[str] = None
    count: Optional[int] = None
    body_html: Optional[str] = None
    location: Optional[str] = None
    exdates: Optional[List[str]] = None
    no_reminder: bool = False


@dataclass
class OutlookCalendarAddFromConfigPayload:
    """Payload for calendar add from config."""
    client: Any
    config_path: str
    no_reminder: bool = False


# Consumer classes

class OutlookRulesListConsumer(Consumer[OutlookRulesListPayload]):
    """Consume args to create rules list payload."""

    def __init__(self, client: Any, use_cache: bool = False, cache_ttl: int = 600):
        self._client = client
        self._use_cache = use_cache
        self._cache_ttl = cache_ttl

    def consume(self) -> OutlookRulesListPayload:
        return OutlookRulesListPayload(
            client=self._client,
            use_cache=self._use_cache,
            cache_ttl=self._cache_ttl,
        )


class OutlookRulesExportConsumer(Consumer[OutlookRulesExportPayload]):
    """Consume args to create rules export payload."""

    def __init__(self, client: Any, out_path: str, use_cache: bool = False, cache_ttl: int = 600):
        self._client = client
        self._out_path = out_path
        self._use_cache = use_cache
        self._cache_ttl = cache_ttl

    def consume(self) -> OutlookRulesExportPayload:
        return OutlookRulesExportPayload(
            client=self._client,
            out_path=self._out_path,
            use_cache=self._use_cache,
            cache_ttl=self._cache_ttl,
        )


class OutlookRulesSyncConsumer(Consumer[OutlookRulesSyncPayload]):
    """Consume args to create rules sync payload."""

    def __init__(
        self,
        client: Any,
        config_path: str,
        dry_run: bool = False,
        delete_missing: bool = False,
        move_to_folders: bool = False,
        verbose: bool = False,
    ):
        self._client = client
        self._config_path = config_path
        self._dry_run = dry_run
        self._delete_missing = delete_missing
        self._move_to_folders = move_to_folders
        self._verbose = verbose

    def consume(self) -> OutlookRulesSyncPayload:
        return OutlookRulesSyncPayload(
            client=self._client,
            config_path=self._config_path,
            dry_run=self._dry_run,
            delete_missing=self._delete_missing,
            move_to_folders=self._move_to_folders,
            verbose=self._verbose,
        )


class OutlookRulesPlanConsumer(Consumer[OutlookRulesPlanPayload]):
    """Consume args to create rules plan payload."""

    def __init__(
        self,
        client: Any,
        config_path: str,
        move_to_folders: bool = False,
        use_cache: bool = False,
        cache_ttl: int = 600,
    ):
        self._client = client
        self._config_path = config_path
        self._move_to_folders = move_to_folders
        self._use_cache = use_cache
        self._cache_ttl = cache_ttl

    def consume(self) -> OutlookRulesPlanPayload:
        return OutlookRulesPlanPayload(
            client=self._client,
            config_path=self._config_path,
            move_to_folders=self._move_to_folders,
            use_cache=self._use_cache,
            cache_ttl=self._cache_ttl,
        )


class OutlookRulesDeleteConsumer(Consumer[OutlookRulesDeletePayload]):
    """Consume args to create rules delete payload."""

    def __init__(self, client: Any, rule_id: str):
        self._client = client
        self._rule_id = rule_id

    def consume(self) -> OutlookRulesDeletePayload:
        return OutlookRulesDeletePayload(client=self._client, rule_id=self._rule_id)


class OutlookRulesSweepConsumer(Consumer[OutlookRulesSweepPayload]):
    """Consume args to create rules sweep payload."""

    def __init__(
        self,
        client: Any,
        config_path: str,
        dry_run: bool = False,
        move_to_folders: bool = False,
        clear_cache: bool = False,
        days: int = 30,
        top: int = 25,
        pages: int = 2,
    ):
        self._client = client
        self._config_path = config_path
        self._dry_run = dry_run
        self._move_to_folders = move_to_folders
        self._clear_cache = clear_cache
        self._days = days
        self._top = top
        self._pages = pages

    def consume(self) -> OutlookRulesSweepPayload:
        return OutlookRulesSweepPayload(
            client=self._client,
            config_path=self._config_path,
            dry_run=self._dry_run,
            move_to_folders=self._move_to_folders,
            clear_cache=self._clear_cache,
            days=self._days,
            top=self._top,
            pages=self._pages,
        )


class OutlookCategoriesListConsumer(Consumer[OutlookCategoriesListPayload]):
    """Consume args to create categories list payload."""

    def __init__(self, client: Any, use_cache: bool = False, cache_ttl: int = 600):
        self._client = client
        self._use_cache = use_cache
        self._cache_ttl = cache_ttl

    def consume(self) -> OutlookCategoriesListPayload:
        return OutlookCategoriesListPayload(
            client=self._client,
            use_cache=self._use_cache,
            cache_ttl=self._cache_ttl,
        )


class OutlookCategoriesExportConsumer(Consumer[OutlookCategoriesExportPayload]):
    """Consume args to create categories export payload."""

    def __init__(self, client: Any, out_path: str, use_cache: bool = False, cache_ttl: int = 600):
        self._client = client
        self._out_path = out_path
        self._use_cache = use_cache
        self._cache_ttl = cache_ttl

    def consume(self) -> OutlookCategoriesExportPayload:
        return OutlookCategoriesExportPayload(
            client=self._client,
            out_path=self._out_path,
            use_cache=self._use_cache,
            cache_ttl=self._cache_ttl,
        )


class OutlookCategoriesSyncConsumer(Consumer[OutlookCategoriesSyncPayload]):
    """Consume args to create categories sync payload."""

    def __init__(self, client: Any, config_path: str, dry_run: bool = False):
        self._client = client
        self._config_path = config_path
        self._dry_run = dry_run

    def consume(self) -> OutlookCategoriesSyncPayload:
        return OutlookCategoriesSyncPayload(
            client=self._client,
            config_path=self._config_path,
            dry_run=self._dry_run,
        )


class OutlookFoldersSyncConsumer(Consumer[OutlookFoldersSyncPayload]):
    """Consume args to create folders sync payload."""

    def __init__(self, client: Any, config_path: str, dry_run: bool = False):
        self._client = client
        self._config_path = config_path
        self._dry_run = dry_run

    def consume(self) -> OutlookFoldersSyncPayload:
        return OutlookFoldersSyncPayload(
            client=self._client,
            config_path=self._config_path,
            dry_run=self._dry_run,
        )


class OutlookCalendarAddConsumer(Consumer[OutlookCalendarAddPayload]):
    """Consume args to create calendar add payload."""

    def __init__(
        self,
        client: Any,
        subject: str,
        start_iso: str,
        end_iso: str,
        calendar_name: Optional[str] = None,
        tz: Optional[str] = None,
        body_html: Optional[str] = None,
        all_day: bool = False,
        location: Optional[str] = None,
        no_reminder: bool = False,
    ):
        self._client = client
        self._subject = subject
        self._start_iso = start_iso
        self._end_iso = end_iso
        self._calendar_name = calendar_name
        self._tz = tz
        self._body_html = body_html
        self._all_day = all_day
        self._location = location
        self._no_reminder = no_reminder

    def consume(self) -> OutlookCalendarAddPayload:
        return OutlookCalendarAddPayload(
            client=self._client,
            subject=self._subject,
            start_iso=self._start_iso,
            end_iso=self._end_iso,
            calendar_name=self._calendar_name,
            tz=self._tz,
            body_html=self._body_html,
            all_day=self._all_day,
            location=self._location,
            no_reminder=self._no_reminder,
        )


class OutlookCalendarAddRecurringConsumer(Consumer[OutlookCalendarAddRecurringPayload]):
    """Consume args to create calendar add recurring payload."""

    def __init__(
        self,
        client: Any,
        subject: str,
        start_time: str,
        end_time: str,
        repeat: str,
        range_start: str,
        calendar_name: Optional[str] = None,
        tz: Optional[str] = None,
        interval: int = 1,
        byday: Optional[List[str]] = None,
        until: Optional[str] = None,
        count: Optional[int] = None,
        body_html: Optional[str] = None,
        location: Optional[str] = None,
        exdates: Optional[List[str]] = None,
        no_reminder: bool = False,
    ):
        self._client = client
        self._subject = subject
        self._start_time = start_time
        self._end_time = end_time
        self._repeat = repeat
        self._range_start = range_start
        self._calendar_name = calendar_name
        self._tz = tz
        self._interval = interval
        self._byday = byday
        self._until = until
        self._count = count
        self._body_html = body_html
        self._location = location
        self._exdates = exdates
        self._no_reminder = no_reminder

    def consume(self) -> OutlookCalendarAddRecurringPayload:
        return OutlookCalendarAddRecurringPayload(
            client=self._client,
            subject=self._subject,
            start_time=self._start_time,
            end_time=self._end_time,
            repeat=self._repeat,
            range_start=self._range_start,
            calendar_name=self._calendar_name,
            tz=self._tz,
            interval=self._interval,
            byday=self._byday,
            until=self._until,
            count=self._count,
            body_html=self._body_html,
            location=self._location,
            exdates=self._exdates,
            no_reminder=self._no_reminder,
        )


class OutlookCalendarAddFromConfigConsumer(Consumer[OutlookCalendarAddFromConfigPayload]):
    """Consume args to create calendar add from config payload."""

    def __init__(self, client: Any, config_path: str, no_reminder: bool = False):
        self._client = client
        self._config_path = config_path
        self._no_reminder = no_reminder

    def consume(self) -> OutlookCalendarAddFromConfigPayload:
        return OutlookCalendarAddFromConfigPayload(
            client=self._client,
            config_path=self._config_path,
            no_reminder=self._no_reminder,
        )
