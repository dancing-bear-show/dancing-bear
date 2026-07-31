"""Processors for filters plan, sync, impact, and export pipelines."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from core.pipeline import Processor, SafeProcessor, ResultEnvelope

from ..utils.filters import (
    build_criteria_from_match,
    expand_categories,
    build_gmail_query,
)
from .consumers import (
    FiltersPlanPayload,
    FiltersSyncPayload,
    FiltersImpactPayload,
    FiltersExportPayload,
)


@dataclass
class FilterPlanEntry:
    criteria: dict
    action_names: dict[str, object]


@dataclass
class FiltersPlanResult:
    to_create: list[FilterPlanEntry]
    to_delete: list[dict]
    add_counts: Counter
    id_to_name: dict[str, str]


class FiltersPlanProcessor(SafeProcessor[FiltersPlanPayload, FiltersPlanResult]):
    """Compute plan results from the gathered payload."""

    def _process_safe(self, payload: FiltersPlanPayload) -> FiltersPlanResult:
        existing_map = {_canon_existing(f): f for f in payload.existing_filters}
        desired_entries: list[tuple[str, FilterPlanEntry]] = []
        desired_keys: set[str] = set()
        add_counter: Counter = Counter()

        for spec in payload.desired_filters:
            key, entry = _canon_desired(spec, payload.name_to_id)
            desired_entries.append((key, entry))
            desired_keys.add(key)
            for name in entry.action_names.get("add", []) or []:
                add_counter[name] += 1

        to_create = [entry for key, entry in desired_entries if key not in existing_map]
        to_delete: list[dict] = []
        if payload.delete_missing:
            extra_keys = set(existing_map.keys()) - desired_keys
            to_delete = [existing_map[k] for k in extra_keys]

        return FiltersPlanResult(
            to_create=to_create,
            to_delete=to_delete,
            add_counts=add_counter,
            id_to_name=payload.id_to_name,
        )


@dataclass
class FiltersSyncResult:
    to_create: list[FilterPlanEntry]
    to_delete: list[dict]


class FiltersSyncProcessor(Processor[FiltersSyncPayload, ResultEnvelope[FiltersSyncResult]]):
    """Determine create/delete operations for filters sync."""

    def process(self, payload: FiltersSyncPayload) -> ResultEnvelope[FiltersSyncResult]:
        if payload.require_forward_verified:
            invalid = _find_unverified_forward(payload.desired_filters, payload.verified_forward_addresses)
            if invalid:
                return ResultEnvelope(
                    status="error",
                    diagnostics={
                        "message": f"Error: forward address not verified: {invalid}",
                        "code": 2,
                    },
                )

        desired_entries: list[tuple[str, FilterPlanEntry]] = []
        desired_keys: set[str] = set()
        for spec in payload.desired_filters:
            key, entry = _canon_desired_with_names(spec)
            desired_entries.append((key, entry))
            desired_keys.add(key)

        existing_map = {
            _canon_existing_with_names(f, payload.id_to_name): f for f in payload.existing_filters
        }
        to_create = [entry for key, entry in desired_entries if key not in existing_map]
        to_delete: list[dict] = []
        if payload.delete_missing:
            extra_keys = set(existing_map.keys()) - desired_keys
            to_delete = [existing_map[k] for k in extra_keys]

        return ResultEnvelope(
            status="success",
            payload=FiltersSyncResult(to_create=to_create, to_delete=to_delete),
        )


@dataclass
class FilterImpactRecord:
    query: str
    count: int


@dataclass
class FiltersImpactResult:
    records: list[FilterImpactRecord]
    total: int


class FiltersImpactProcessor(SafeProcessor[FiltersImpactPayload, FiltersImpactResult]):
    """Compute impact counts for desired filters."""

    def _process_safe(self, payload: FiltersImpactPayload) -> FiltersImpactResult:
        records: list[FilterImpactRecord] = []
        total = 0
        for spec in payload.filters:
            match = spec.get("match") or {}
            query = build_gmail_query(match, days=payload.days, only_inbox=payload.only_inbox)
            ids = payload.client.list_message_ids(query=query, max_pages=payload.pages)
            count = len(ids)
            total += count
            records.append(FilterImpactRecord(query=query, count=count))
        return FiltersImpactResult(records=records, total=total)


@dataclass
class FiltersExportResult:
    filters: list[dict]
    out_path: str


class FiltersExportProcessor(SafeProcessor[FiltersExportPayload, FiltersExportResult]):
    """Convert Gmail filters into DSL export format."""

    def _process_safe(self, payload: FiltersExportPayload) -> FiltersExportResult:
        entries: list[dict] = []
        for filt in payload.filters:
            entry: dict = {}
            criteria = self._export_criteria(filt.get("criteria") or {})
            if criteria:
                entry["criteria"] = criteria
            action = self._export_action(filt.get("action") or {}, payload.id_to_name)
            if action:
                entry["action"] = action
            if filt.get("id"):
                entry["id"] = filt.get("id")
            entries.append(entry)
        return FiltersExportResult(filters=entries, out_path=str(payload.out_path))

    def _export_criteria(self, criteria: dict) -> dict:
        out: dict = {}
        for key in ("from", "to", "subject", "query", "negatedQuery"):
            if criteria.get(key):
                out[key] = criteria[key]
        if criteria.get("hasAttachment") is not None:
            out["hasAttachment"] = bool(criteria.get("hasAttachment"))
        if criteria.get("excludeChats") is not None:
            out["excludeChats"] = bool(criteria.get("excludeChats"))
        if criteria.get("size") is not None:
            size_entry: dict[str, object] = {"bytes": int(criteria.get("size") or 0)}
            if criteria.get("sizeComparison"):
                size_entry["comparison"] = criteria.get("sizeComparison")
            out["size"] = size_entry
        return out

    def _export_action(self, action: dict, id_to_name: dict[str, str]) -> dict:
        out: dict = {}
        add_names = _ids_to_names(action.get("addLabelIds"), id_to_name)
        if add_names:
            out["addLabels"] = add_names
        rem_names = _ids_to_names(action.get("removeLabelIds"), id_to_name)
        if rem_names:
            out["removeLabels"] = rem_names
        for key in (
            "forward",
            "markRead",
            "archive",
            "delete",
            "neverSpam",
            "star",
            "important",
            "categorizeAs",
            "markImportant",
            "neverMarkImportant",
        ):
            if key in action:
                out[key] = action[key]
        return out


def _canon_existing(filter_entry: dict) -> str:
    criteria = filter_entry.get("criteria", {}) or {}
    action = filter_entry.get("action", {}) or {}
    key = {
        "from": criteria.get("from"),
        "to": criteria.get("to"),
        "subject": criteria.get("subject"),
        "query": criteria.get("query"),
        "negatedQuery": criteria.get("negatedQuery"),
        "add": tuple(sorted((action.get("addLabelIds") or []))),
        "remove": tuple(sorted((action.get("removeLabelIds") or []))),
        "forward": action.get("forward"),
    }
    return str(key)


def _canon_desired(spec: dict, name_to_id: dict[str, str]) -> tuple[str, FilterPlanEntry]:
    match = spec.get("match") or {}
    action = spec.get("action") or {}
    criteria = build_criteria_from_match(match)

    add_names = list(action.get("add") or [])
    rem_names = list(action.get("remove") or [])
    forward = action.get("forward")

    add_ids = [_map_label_name(name, name_to_id) for name in add_names]
    rem_ids = [_map_label_name(name, name_to_id) for name in rem_names]

    key = str(
        {
            "from": criteria.get("from"),
            "to": criteria.get("to"),
            "subject": criteria.get("subject"),
            "query": criteria.get("query"),
            "negatedQuery": criteria.get("negatedQuery"),
            "add": tuple(sorted(add_ids)),
            "remove": tuple(sorted(rem_ids)),
            "forward": forward,
        }
    )

    entry = FilterPlanEntry(
        criteria=criteria,
        action_names={
            "add": add_names,
            "remove": rem_names,
            "forward": forward,
        },
    )
    return key, entry


def _map_label_name(name: str, name_to_id: dict[str, str]) -> str:
    return name_to_id.get(name, name)


def _canon_existing_with_names(filter_entry: dict, id_to_name: dict[str, str]) -> str:
    criteria = filter_entry.get("criteria", {}) or {}
    action = filter_entry.get("action", {}) or {}
    add_names = [
        id_to_name.get(label_id, label_id) for label_id in (action.get("addLabelIds") or [])
    ]
    rem_names = [
        id_to_name.get(label_id, label_id) for label_id in (action.get("removeLabelIds") or [])
    ]
    key = {
        "from": criteria.get("from"),
        "to": criteria.get("to"),
        "subject": criteria.get("subject"),
        "query": criteria.get("query"),
        "negatedQuery": criteria.get("negatedQuery"),
        "add": tuple(sorted(add_names)),
        "remove": tuple(sorted(rem_names)),
        "forward": action.get("forward"),
    }
    return str(key)


def _canon_desired_with_names(spec: dict) -> tuple[str, FilterPlanEntry]:
    criteria = build_criteria_from_match(spec.get("match") or {})
    action_names = _build_action_names(spec, include_categories=True)
    key = str(
        {
            "from": criteria.get("from"),
            "to": criteria.get("to"),
            "subject": criteria.get("subject"),
            "query": criteria.get("query"),
            "negatedQuery": criteria.get("negatedQuery"),
            "add": tuple(sorted(action_names.get("add") or [])),
            "remove": tuple(sorted(action_names.get("remove") or [])),
            "forward": action_names.get("forward"),
        }
    )
    return key, FilterPlanEntry(criteria=criteria, action_names=action_names)


def _build_action_names(spec: dict, *, include_categories: bool = False) -> dict[str, object]:
    action = spec.get("action") or {}
    add = list(action.get("add") or [])
    if include_categories:
        add.extend(expand_categories(action))
    remove = list(action.get("remove") or [])
    forward = action.get("forward")
    act: dict[str, object] = {}
    if add:
        act["add"] = add
    if remove:
        act["remove"] = remove
    if forward:
        act["forward"] = forward
    return act


def _find_unverified_forward(desired: list[dict], verified: set[str]) -> str | None:
    for spec in desired:
        if not isinstance(spec, dict):
            continue
        action = spec.get("action") or {}
        forward = action.get("forward")
        if forward and forward not in verified:
            return forward
    return None


def _ids_to_names(ids: list[str] | None, id_to_name: dict[str, str]) -> list[str]:
    names: list[str] = []
    for lid in ids or []:
        name = id_to_name.get(lid)
        if name:
            names.append(name)
    return names
