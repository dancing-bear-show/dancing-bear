"""Processors for mail filters pipelines."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Tuple

from core.pipeline import Processor, ResultEnvelope

from ..utils.filters import (
    build_criteria_from_match,
    expand_categories,
    build_gmail_query,
    action_to_label_changes,
)
from .consumers import (
    FiltersPlanPayload,
    FiltersSyncPayload,
    FiltersImpactPayload,
    FiltersExportPayload,
    FiltersSweepPayload,
    FiltersSweepRangePayload,
    FiltersPrunePayload,
    FiltersAddForwardPayload,
    FiltersAddTokenPayload,
    FiltersRemoveTokenPayload,
)


@dataclass
class FilterPlanEntry:
    criteria: Dict
    action_names: Dict[str, object]


@dataclass
class FiltersPlanResult:
    to_create: List[FilterPlanEntry]
    to_delete: List[Dict]
    add_counts: Counter
    id_to_name: Dict[str, str]


class FiltersPlanProcessor(Processor[FiltersPlanPayload, ResultEnvelope[FiltersPlanResult]]):
    """Compute plan results from the gathered payload."""

    def process(self, payload: FiltersPlanPayload) -> ResultEnvelope[FiltersPlanResult]:
        existing_map = {_canon_existing(f): f for f in payload.existing_filters}
        desired_entries: List[Tuple[str, FilterPlanEntry]] = []
        desired_keys: set[str] = set()
        add_counter: Counter = Counter()

        for spec in payload.desired_filters:
            key, entry = _canon_desired(spec, payload.name_to_id)
            desired_entries.append((key, entry))
            desired_keys.add(key)
            for name in entry.action_names.get("add", []) or []:
                add_counter[name] += 1

        to_create = [entry for key, entry in desired_entries if key not in existing_map]
        to_delete: List[Dict] = []
        if payload.delete_missing:
            extra_keys = set(existing_map.keys()) - desired_keys
            to_delete = [existing_map[k] for k in extra_keys]

        result = FiltersPlanResult(
            to_create=to_create,
            to_delete=to_delete,
            add_counts=add_counter,
            id_to_name=payload.id_to_name,
        )
        return ResultEnvelope(status="success", payload=result)


@dataclass
class FiltersSyncResult:
    to_create: List[FilterPlanEntry]
    to_delete: List[Dict]


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

        desired_entries: List[tuple[str, FilterPlanEntry]] = []
        desired_keys: set[str] = set()
        for spec in payload.desired_filters:
            key, entry = _canon_desired_with_names(spec)
            desired_entries.append((key, entry))
            desired_keys.add(key)

        existing_map = {
            _canon_existing_with_names(f, payload.id_to_name): f for f in payload.existing_filters
        }
        to_create = [entry for key, entry in desired_entries if key not in existing_map]
        to_delete: List[Dict] = []
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
    records: List[FilterImpactRecord]
    total: int


class FiltersImpactProcessor(Processor[FiltersImpactPayload, ResultEnvelope[FiltersImpactResult]]):
    """Compute impact counts for desired filters."""

    def process(self, payload: FiltersImpactPayload) -> ResultEnvelope[FiltersImpactResult]:
        records: List[FilterImpactRecord] = []
        total = 0
        for spec in payload.filters:
            match = spec.get("match") or {}
            query = build_gmail_query(match, days=payload.days, only_inbox=payload.only_inbox)
            ids = payload.client.list_message_ids(query=query, max_pages=payload.pages)
            count = len(ids)
            total += count
            records.append(FilterImpactRecord(query=query, count=count))
        return ResultEnvelope(
            status="success",
            payload=FiltersImpactResult(records=records, total=total),
        )


@dataclass
class FiltersExportResult:
    filters: List[dict]
    out_path: str


class FiltersExportProcessor(Processor[FiltersExportPayload, ResultEnvelope[FiltersExportResult]]):
    """Convert Gmail filters into DSL export format."""

    def process(self, payload: FiltersExportPayload) -> ResultEnvelope[FiltersExportResult]:
        entries: List[dict] = []
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
        return ResultEnvelope(
            status="success",
            payload=FiltersExportResult(filters=entries, out_path=str(payload.out_path)),
        )

    def _export_criteria(self, criteria: Dict) -> Dict:
        out: Dict = {}
        for key in ("from", "to", "subject", "query", "negatedQuery"):
            if criteria.get(key):
                out[key] = criteria[key]
        if criteria.get("hasAttachment") is not None:
            out["hasAttachment"] = bool(criteria.get("hasAttachment"))
        if criteria.get("excludeChats") is not None:
            out["excludeChats"] = bool(criteria.get("excludeChats"))
        if criteria.get("size") is not None:
            size_entry: Dict[str, object] = {"bytes": int(criteria.get("size") or 0)}
            if criteria.get("sizeComparison"):
                size_entry["comparison"] = criteria.get("sizeComparison")
            out["size"] = size_entry
        return out

    def _export_action(self, action: Dict, id_to_name: Dict[str, str]) -> Dict:
        out: Dict = {}
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


def _canon_existing(filter_entry: Dict) -> str:
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


def _canon_desired(spec: Dict, name_to_id: Dict[str, str]) -> Tuple[str, FilterPlanEntry]:
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


def _map_label_name(name: str, name_to_id: Dict[str, str]) -> str:
    return name_to_id.get(name, name)


def _canon_existing_with_names(filter_entry: Dict, id_to_name: Dict[str, str]) -> str:
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


def _canon_desired_with_names(spec: Dict) -> tuple[str, FilterPlanEntry]:
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


def _build_action_names(spec: Dict, *, include_categories: bool = False) -> Dict[str, object]:
    action = spec.get("action") or {}
    add = list(action.get("add") or [])
    if include_categories:
        add.extend(expand_categories(action))
    remove = list(action.get("remove") or [])
    forward = action.get("forward")
    act: Dict[str, object] = {}
    if add:
        act["add"] = add
    if remove:
        act["remove"] = remove
    if forward:
        act["forward"] = forward
    return act


def _find_unverified_forward(desired: List[Dict], verified: set[str]) -> str | None:
    for spec in desired:
        if not isinstance(spec, dict):
            continue
        action = spec.get("action") or {}
        forward = action.get("forward")
        if forward and forward not in verified:
            return forward
    return None


def _ids_to_names(ids: List[str] | None, id_to_name: Dict[str, str]) -> List[str]:
    names: List[str] = []
    for lid in ids or []:
        name = id_to_name.get(lid)
        if name:
            names.append(name)
    return names


@dataclass
class SweepConfig:
    """Configuration for sweep operations."""
    days: int | None = None
    only_inbox: bool = False
    older_than_days: int | None = None


@dataclass
class FiltersSweepInstruction:
    query: str
    add_label_ids: List[str]
    remove_label_ids: List[str]


@dataclass
class FiltersSweepResult:
    instructions: List[FiltersSweepInstruction]


class FiltersSweepProcessor(Processor[FiltersSweepPayload, ResultEnvelope[FiltersSweepResult]]):
    """Prepare sweep instructions from YAML filters."""

    def process(self, payload: FiltersSweepPayload) -> ResultEnvelope[FiltersSweepResult]:
        config = SweepConfig(days=payload.days, only_inbox=payload.only_inbox)
        instructions = [
            _build_sweep_instruction(spec, payload.client, config)
            for spec in payload.filters
        ]
        return ResultEnvelope(status="success", payload=FiltersSweepResult(instructions=instructions))


@dataclass
class FiltersSweepWindowResult:
    label: str
    instructions: List[FiltersSweepInstruction]


@dataclass
class FiltersSweepRangeResult:
    windows: List[FiltersSweepWindowResult]


class FiltersSweepRangeProcessor(Processor[FiltersSweepRangePayload, ResultEnvelope[FiltersSweepRangeResult]]):
    """Prepare sweep instructions for ranged windows."""

    def process(self, payload: FiltersSweepRangePayload) -> ResultEnvelope[FiltersSweepRangeResult]:
        windows: List[FiltersSweepWindowResult] = []
        cur = payload.from_days
        while cur < payload.to_days:
            newer = min(cur + payload.step_days, payload.to_days)
            label = f"newer_than:{newer}d older_than:{cur}d"
            config = SweepConfig(days=newer, only_inbox=False, older_than_days=cur)
            instructions = [
                _build_sweep_instruction(spec, payload.client, config)
                for spec in payload.filters
            ]
            windows.append(FiltersSweepWindowResult(label=label, instructions=instructions))
            cur += payload.step_days
        return ResultEnvelope(status="success", payload=FiltersSweepRangeResult(windows=windows))


@dataclass
class FilterPruneCandidate:
    filter_obj: Dict
    query: str
    is_empty: bool


@dataclass
class FiltersPruneResult:
    candidates: List[FilterPruneCandidate]


class FiltersPruneProcessor(Processor[FiltersPrunePayload, ResultEnvelope[FiltersPruneResult]]):
    """Determine filters that match zero messages."""

    def process(self, payload: FiltersPrunePayload) -> ResultEnvelope[FiltersPruneResult]:
        candidates: List[FilterPruneCandidate] = []
        for filter_entry in payload.filters:
            criteria = filter_entry.get("criteria", {}) or {}
            query = build_gmail_query(criteria, days=payload.days, only_inbox=payload.only_inbox)
            ids = payload.client.list_message_ids(query=query, max_pages=payload.pages)
            candidates.append(
                FilterPruneCandidate(
                    filter_obj=filter_entry,
                    query=query,
                    is_empty=len(ids) == 0,
                )
            )
        return ResultEnvelope(status="success", payload=FiltersPruneResult(candidates=candidates))


@dataclass
class FilterForwardUpdate:
    filter_obj: Dict
    criteria: Dict
    action: Dict
    label_prefix: str


@dataclass
class FiltersAddForwardResult:
    updates: List[FilterForwardUpdate]
    destination: str


class FiltersAddForwardProcessor(Processor[FiltersAddForwardPayload, ResultEnvelope[FiltersAddForwardResult]]):
    """Determine which filters should receive forward actions."""

    def process(self, payload: FiltersAddForwardPayload) -> ResultEnvelope[FiltersAddForwardResult]:
        dest = payload.destination.strip()
        if payload.require_verified and dest not in payload.verified_forward_addresses:
            return ResultEnvelope(
                status="error",
                diagnostics={
                    "message": f"Error: forward address not verified: {dest}",
                    "code": 2,
                },
            )

        updates: List[FilterForwardUpdate] = []
        prefix = payload.label_prefix

        def matches_prefix(name: str) -> bool:
            return name == prefix or name.startswith(prefix + "/")

        for filt in payload.filters:
            action = dict(filt.get("action", {}) or {})
            add_label_ids = action.get("addLabelIds") or []
            add_names = [payload.id_to_name.get(lid, "") for lid in add_label_ids]
            if not any(matches_prefix(name) for name in add_names if name):
                continue
            existing_forward = str(action.get("forward") or "")
            if existing_forward.strip().lower() == dest.lower():
                continue
            updates.append(
                FilterForwardUpdate(
                    filter_obj=filt,
                    criteria=filt.get("criteria", {}) or {},
                    action=action,
                    label_prefix=prefix,
                )
            )

        return ResultEnvelope(
            status="success",
            payload=FiltersAddForwardResult(updates=updates, destination=dest),
        )


@dataclass
class FilterTokenUpdate:
    filter_obj: Dict
    criteria: Dict
    action: Dict
    new_from: str
    old_from: str


@dataclass
class FiltersAddTokenResult:
    updates: List[FilterTokenUpdate]


class FiltersAddTokenProcessor(Processor[FiltersAddTokenPayload, ResultEnvelope[FiltersAddTokenResult]]):
    """Compute new 'from' clauses when adding tokens."""

    def process(self, payload: FiltersAddTokenPayload) -> ResultEnvelope[FiltersAddTokenResult]:
        updates: List[FilterTokenUpdate] = []
        matches = _matching_filters_for_token_ops(
            payload.filters,
            payload.id_to_name,
            label_prefix=payload.label_prefix,
            needle=payload.needle,
        )
        for filt, from_clause in matches:
            tokens = _split_or_clause(from_clause)
            existing_lower = {tok.lower() for tok in tokens}
            changed = False
            for tok in payload.tokens:
                if tok.lower() not in existing_lower:
                    tokens.append(tok)
                    existing_lower.add(tok.lower())
                    changed = True
            if not changed:
                continue
            new_from = " OR ".join(tokens)
            crit2 = dict(filt.get("criteria", {}) or {})
            crit2["from"] = new_from
            updates.append(
                FilterTokenUpdate(
                    filter_obj=filt,
                    criteria=crit2,
                    action=filt.get("action", {}) or {},
                    new_from=new_from,
                    old_from=from_clause,
                )
            )
        return ResultEnvelope(status="success", payload=FiltersAddTokenResult(updates=updates))


@dataclass
class FiltersRemoveTokenResult:
    updates: List[FilterTokenUpdate]


class FiltersRemoveTokenProcessor(Processor[FiltersRemoveTokenPayload, ResultEnvelope[FiltersRemoveTokenResult]]):
    """Compute new 'from' clauses when removing tokens."""

    def process(self, payload: FiltersRemoveTokenPayload) -> ResultEnvelope[FiltersRemoveTokenResult]:
        updates: List[FilterTokenUpdate] = []
        tokens_to_remove = {tok.lower() for tok in payload.tokens}
        matches = _matching_filters_for_token_ops(
            payload.filters,
            payload.id_to_name,
            label_prefix=payload.label_prefix,
            needle=payload.needle,
        )
        for filt, from_clause in matches:
            tokens = _split_or_clause(from_clause)
            new_tokens = [tok for tok in tokens if tok.lower() not in tokens_to_remove]
            if new_tokens == tokens or not new_tokens:
                continue
            new_from = " OR ".join(new_tokens)
            crit2 = dict(filt.get("criteria", {}) or {})
            crit2["from"] = new_from
            updates.append(
                FilterTokenUpdate(
                    filter_obj=filt,
                    criteria=crit2,
                    action=filt.get("action", {}) or {},
                    new_from=new_from,
                    old_from=from_clause,
                )
            )
        return ResultEnvelope(status="success", payload=FiltersRemoveTokenResult(updates=updates))


def _build_sweep_instruction(
    spec: Dict,
    client: object,
    config: SweepConfig,
) -> FiltersSweepInstruction:
    match = spec.get("match") or {}
    query = build_gmail_query(
        match,
        days=config.days,
        only_inbox=config.only_inbox,
        older_than_days=config.older_than_days,
    )
    action_spec = dict(spec.get("action") or {})
    add_names = list(action_spec.get("add") or [])
    add_names.extend(expand_categories(action_spec))
    rem_names = list(action_spec.get("remove") or [])
    add_ids, rem_ids = action_to_label_changes(
        client,
        {"add": add_names, "remove": rem_names},
    )
    return FiltersSweepInstruction(
        query=query,
        add_label_ids=add_ids,
        remove_label_ids=rem_ids,
    )


def _matching_filters_for_token_ops(
    filters: List[Dict],
    id_to_name: Dict[str, str],
    *,
    label_prefix: str,
    needle: str,
) -> List[tuple[Dict, str]]:
    matches: List[tuple[Dict, str]] = []

    def matches_prefix(name: str) -> bool:
        return name == label_prefix or name.startswith(label_prefix + "/")

    for filt in filters:
        criteria = filt.get("criteria", {}) or {}
        action = filt.get("action", {}) or {}
        add_label_ids = action.get("addLabelIds") or []
        add_names = [id_to_name.get(lid, "") for lid in add_label_ids]
        if not any(matches_prefix(name) for name in add_names if name):
            continue
        from_clause = str(criteria.get("from") or "")
        if needle not in from_clause.lower():
            continue
        matches.append((filt, from_clause))
    return matches


def _split_or_clause(clause: str) -> List[str]:
    return [part.strip() for part in clause.split("OR") if part.strip()]
