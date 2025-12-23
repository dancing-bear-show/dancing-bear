from __future__ import annotations

"""Consumers for mail filters pipelines."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from core.pipeline import Consumer

from ..context import MailContext
from ..yamlio import load_config


@dataclass
class FiltersBasePayload:
    desired_filters: List[dict]
    existing_filters: List[dict]
    id_to_name: Dict[str, str]
    name_to_id: Dict[str, str]
    delete_missing: bool


@dataclass
class FiltersPlanPayload(FiltersBasePayload):
    pass


@dataclass
class FiltersSyncPayload(FiltersBasePayload):
    require_forward_verified: bool
    verified_forward_addresses: set[str]


@dataclass
class FiltersImpactPayload:
    filters: List[dict]
    days: int | None
    only_inbox: bool
    pages: int
    client: object


@dataclass
class FiltersExportPayload:
    filters: List[dict]
    id_to_name: Dict[str, str]
    out_path: Path


@dataclass
class FiltersSweepPayload:
    filters: List[dict]
    days: int | None
    only_inbox: bool
    pages: int
    max_msgs: int | None
    batch_size: int
    dry_run: bool
    client: object


@dataclass
class FiltersSweepRangePayload:
    filters: List[dict]
    from_days: int
    to_days: int
    step_days: int
    pages: int
    max_msgs: int | None
    batch_size: int
    dry_run: bool
    client: object


@dataclass
class FiltersPrunePayload:
    filters: List[dict]
    days: int | None
    only_inbox: bool
    pages: int
    dry_run: bool
    client: object


@dataclass
class FiltersAddForwardPayload:
    filters: List[dict]
    id_to_name: Dict[str, str]
    label_prefix: str
    destination: str
    require_verified: bool
    verified_forward_addresses: set[str]
    dry_run: bool
    client: object


@dataclass
class FiltersAddTokenPayload:
    filters: List[dict]
    id_to_name: Dict[str, str]
    label_prefix: str
    needle: str
    tokens: List[str]
    dry_run: bool
    client: object


@dataclass
class FiltersRemoveTokenPayload:
    filters: List[dict]
    id_to_name: Dict[str, str]
    label_prefix: str
    needle: str
    tokens: List[str]
    dry_run: bool
    client: object


@dataclass
class FiltersSweepRangePayload:
    filters: List[dict]
    from_days: int
    to_days: int
    step_days: int
    pages: int
    max_msgs: int | None
    batch_size: int
    dry_run: bool
    client: object


class FiltersPlanConsumer(Consumer[FiltersPlanPayload]):
    """Load YAML + Gmail state for filters plan operations."""

    def __init__(self, context: MailContext):
        self.context = context

    def consume(self) -> FiltersPlanPayload:
        payload = _load_filters_payload(
            self.context,
            error_hint="Config missing 'filters' list; nothing to plan.",
            allow_missing=True,
        )
        return FiltersPlanPayload(**payload)


class FiltersSyncConsumer(Consumer[FiltersSyncPayload]):
    """Load YAML + Gmail state for filters sync operations."""

    def __init__(self, context: MailContext):
        self.context = context

    def consume(self) -> FiltersSyncPayload:
        payload = _load_filters_payload(
            self.context,
            error_hint="Config missing 'filters' list; nothing to sync.",
            allow_missing=False,
        )
        client = self.context.get_gmail_client()
        return FiltersSyncPayload(
            **payload,
            require_forward_verified=bool(getattr(self.context.args, "require_forward_verified", False)),
            verified_forward_addresses=set(client.get_verified_forwarding_addresses()),
        )


class FiltersImpactConsumer(Consumer[FiltersImpactPayload]):
    """Load YAML filters and Gmail client for impact calculations."""

    def __init__(self, context: MailContext):
        self.context = context

    def consume(self) -> FiltersImpactPayload:
        args = self.context.args
        doc = load_config(getattr(args, "config", None))
        filters = _load_desired_filters(
            doc,
            error_hint="Config missing 'filters' list; nothing to analyze.",
            allow_missing=False,
        )
        client = self.context.get_gmail_client()
        pages = int(getattr(args, "pages", 5) or 5)
        return FiltersImpactPayload(
            filters=filters,
            days=getattr(args, "days", None),
            only_inbox=bool(getattr(args, "only_inbox", False)),
            pages=pages,
            client=client,
        )


class FiltersExportConsumer(Consumer[FiltersExportPayload]):
    """Gather Gmail filters and label mapping for export."""

    def __init__(self, context: MailContext):
        self.context = context

    def consume(self) -> FiltersExportPayload:
        args = self.context.args
        out_path = getattr(args, "out", None)
        if not out_path:
            raise ValueError("Missing --out for filters export.")
        client = self.context.get_gmail_client()
        labels = client.list_labels()
        id_to_name = {
            str(label.get("id", "")): str(label.get("name", "") or "")
            for label in labels
            if label.get("id")
        }
        filters = client.list_filters()
        return FiltersExportPayload(filters=filters, id_to_name=id_to_name, out_path=Path(out_path))


class FiltersSweepConsumer(Consumer[FiltersSweepPayload]):
    """Gather filters and client options for sweep operations."""

    def __init__(self, context: MailContext):
        self.context = context

    def consume(self) -> FiltersSweepPayload:
        args = self.context.args
        doc = load_config(getattr(args, "config", None))
        filters = _load_desired_filters(
            doc,
            error_hint="Config missing 'filters' list; nothing to sweep.",
            allow_missing=False,
        )
        client = self.context.get_gmail_client()
        days = getattr(args, "days", None)
        pages = int(getattr(args, "pages", 50) or 50)
        batch_size = int(getattr(args, "batch_size", 500) or 500)
        max_msgs = getattr(args, "max_msgs", None)
        max_msgs_val = int(max_msgs) if max_msgs not in (None, "") else None
        return FiltersSweepPayload(
            filters=filters,
            days=days,
            only_inbox=bool(getattr(args, "only_inbox", False)),
            pages=pages,
            max_msgs=max_msgs_val,
            batch_size=batch_size,
            dry_run=bool(getattr(args, "dry_run", False)),
            client=client,
        )


class FiltersSweepRangeConsumer(Consumer[FiltersSweepRangePayload]):
    """Gather filters and options for sweep-range operations."""

    def __init__(self, context: MailContext):
        self.context = context

    def consume(self) -> FiltersSweepRangePayload:
        args = self.context.args
        doc = load_config(getattr(args, "config", None))
        filters = _load_desired_filters(
            doc,
            error_hint="Config missing 'filters' list; nothing to sweep.",
            allow_missing=False,
        )
        client = self.context.get_gmail_client()
        from_days = int(getattr(args, "from_days", 0))
        to_days = int(getattr(args, "to_days", 0))
        step_days = int(getattr(args, "step_days", 0))
        if step_days <= 0 or to_days <= from_days:
            raise ValueError("Invalid range/step.")
        pages = int(getattr(args, "pages", 50) or 50)
        batch_size = int(getattr(args, "batch_size", 500) or 500)
        max_msgs = getattr(args, "max_msgs", None)
        max_msgs_val = int(max_msgs) if max_msgs not in (None, "") else None
        return FiltersSweepRangePayload(
            filters=filters,
            from_days=from_days,
            to_days=to_days,
            step_days=step_days,
            pages=pages,
            max_msgs=max_msgs_val,
            batch_size=batch_size,
            dry_run=bool(getattr(args, "dry_run", False)),
            client=client,
        )


class FiltersPruneConsumer(Consumer[FiltersPrunePayload]):
    """Gather filters and options for prune-empty operations."""

    def __init__(self, context: MailContext):
        self.context = context

    def consume(self) -> FiltersPrunePayload:
        args = self.context.args
        client = self.context.get_gmail_client()
        filters = client.list_filters()
        pages = int(getattr(args, "pages", 2) or 2)
        days = getattr(args, "days", None)
        return FiltersPrunePayload(
            filters=filters,
            days=days,
            only_inbox=bool(getattr(args, "only_inbox", False)),
            pages=pages,
            dry_run=bool(getattr(args, "dry_run", False)),
            client=client,
        )


class FiltersAddForwardConsumer(Consumer[FiltersAddForwardPayload]):
    """Gather filters and label metadata for add-forward operations."""

    def __init__(self, context: MailContext):
        self.context = context

    def consume(self) -> FiltersAddForwardPayload:
        args = self.context.args
        dest = getattr(args, "email", None)
        if not dest:
            raise ValueError("Missing --email for add-forward-by-label.")
        label_prefix = str(getattr(args, "label_prefix", "")).strip()
        if not label_prefix:
            raise ValueError("Invalid --label-prefix")

        client = self.context.get_gmail_client()
        labels = client.list_labels()
        id_to_name = {
            str(label.get("id", "")): str(label.get("name", "") or "")
            for label in labels
            if label.get("id")
        }
        filters = client.list_filters()
        require_verified = bool(getattr(args, "require_forward_verified", False))
        verified = set(client.get_verified_forwarding_addresses())
        return FiltersAddForwardPayload(
            filters=filters,
            id_to_name=id_to_name,
            label_prefix=label_prefix,
            destination=dest,
            require_verified=require_verified,
            verified_forward_addresses=verified,
            dry_run=bool(getattr(args, "dry_run", False)),
            client=client,
        )


class FiltersAddTokenConsumer(Consumer[FiltersAddTokenPayload]):
    """Gather filters and options for add-from-token command."""

    def __init__(self, context: MailContext):
        self.context = context

    def consume(self) -> FiltersAddTokenPayload:
        args = self.context.args
        label_prefix = str(getattr(args, "label_prefix", "")).strip()
        if not label_prefix:
            raise ValueError("Invalid --label-prefix")
        needle = str(getattr(args, "needle", "")).strip().lower()
        tokens = [str(x).strip() for x in (getattr(args, "add", []) or []) if str(x).strip()]
        if not needle or not tokens:
            raise ValueError("Missing --needle or --add")
        client = self.context.get_gmail_client()
        labels = client.list_labels()
        id_to_name = {
            str(label.get("id", "")): str(label.get("name", "") or "")
            for label in labels
            if label.get("id")
        }
        filters = client.list_filters()
        return FiltersAddTokenPayload(
            filters=filters,
            id_to_name=id_to_name,
            label_prefix=label_prefix,
            needle=needle,
            tokens=tokens,
            dry_run=bool(getattr(args, "dry_run", False)),
            client=client,
        )


class FiltersRemoveTokenConsumer(Consumer[FiltersRemoveTokenPayload]):
    """Gather filters and options for rm-from-token command."""

    def __init__(self, context: MailContext):
        self.context = context

    def consume(self) -> FiltersRemoveTokenPayload:
        args = self.context.args
        label_prefix = str(getattr(args, "label_prefix", "")).strip()
        if not label_prefix:
            raise ValueError("Invalid --label-prefix")
        needle = str(getattr(args, "needle", "")).strip().lower()
        tokens = [str(x).strip().lower() for x in (getattr(args, "remove", []) or []) if str(x).strip()]
        if not needle or not tokens:
            raise ValueError("Missing --needle or --remove")
        client = self.context.get_gmail_client()
        labels = client.list_labels()
        id_to_name = {
            str(label.get("id", "")): str(label.get("name", "") or "")
            for label in labels
            if label.get("id")
        }
        filters = client.list_filters()
        return FiltersRemoveTokenPayload(
            filters=filters,
            id_to_name=id_to_name,
            label_prefix=label_prefix,
            needle=needle,
            tokens=tokens,
            dry_run=bool(getattr(args, "dry_run", False)),
            client=client,
        )


def _load_filters_payload(context: MailContext, *, error_hint: str, allow_missing: bool) -> dict:
    args = context.args
    config_path = getattr(args, "config", None)
    doc = load_config(config_path)
    desired = _load_desired_filters(doc, error_hint=error_hint, allow_missing=allow_missing)

    client = context.get_gmail_client()
    labels = client.list_labels()
    id_to_name = {
        str(label.get("id", "")): str(label.get("name", "") or "")
        for label in labels
        if label.get("id")
    }
    name_to_id = {name: lid for lid, name in id_to_name.items() if name}
    existing = client.list_filters()
    delete_missing = bool(getattr(args, "delete_missing", False))
    return {
        "desired_filters": desired,
        "existing_filters": existing,
        "id_to_name": id_to_name,
        "name_to_id": name_to_id,
        "delete_missing": delete_missing,
    }


def _load_desired_filters(doc: dict, *, error_hint: str, allow_missing: bool) -> List[dict]:
    raw = doc.get("filters")
    if raw is None:
        return []
    if not isinstance(raw, list):
        if allow_missing:
            return []
        raise ValueError(error_hint)
    desired: List[dict] = []
    for entry in raw:
        if isinstance(entry, dict):
            desired.append(entry)
    return desired
