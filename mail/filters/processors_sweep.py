"""Processors for filters sweep, prune, and token pipelines."""
from __future__ import annotations

from dataclasses import dataclass

from core.pipeline import Processor, ResultEnvelope

from ..utils.filters import (
    build_gmail_query,
    expand_categories,
    action_to_label_changes,
)
from .consumers import (
    FiltersSweepPayload,
    FiltersSweepRangePayload,
    FiltersPrunePayload,
    FiltersAddForwardPayload,
    FiltersAddTokenPayload,
    FiltersRemoveTokenPayload,
)


@dataclass
class SweepConfig:
    """Configuration for sweep operations."""
    days: int | None = None
    only_inbox: bool = False
    older_than_days: int | None = None


@dataclass
class FiltersSweepInstruction:
    query: str
    add_label_ids: list[str]
    remove_label_ids: list[str]


@dataclass
class FiltersSweepResult:
    instructions: list[FiltersSweepInstruction]


class FiltersSweepProcessor(Processor[FiltersSweepPayload, ResultEnvelope[FiltersSweepResult]]):
    """Prepare sweep instructions from YAML filters."""

    def process(self, payload: FiltersSweepPayload) -> ResultEnvelope[FiltersSweepResult]:
        instructions = [
            _build_sweep_instruction(spec, payload.client, payload.sweep_config)
            for spec in payload.filters
        ]
        return ResultEnvelope(status="success", payload=FiltersSweepResult(instructions=instructions))


@dataclass
class FiltersSweepWindowResult:
    label: str
    instructions: list[FiltersSweepInstruction]


@dataclass
class FiltersSweepRangeResult:
    windows: list[FiltersSweepWindowResult]


class FiltersSweepRangeProcessor(Processor[FiltersSweepRangePayload, ResultEnvelope[FiltersSweepRangeResult]]):
    """Prepare sweep instructions for ranged windows."""

    def process(self, payload: FiltersSweepRangePayload) -> ResultEnvelope[FiltersSweepRangeResult]:
        windows: list[FiltersSweepWindowResult] = []
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
    filter_obj: dict
    query: str
    is_empty: bool


@dataclass
class FiltersPruneResult:
    candidates: list[FilterPruneCandidate]


class FiltersPruneProcessor(Processor[FiltersPrunePayload, ResultEnvelope[FiltersPruneResult]]):
    """Determine filters that match zero messages."""

    def process(self, payload: FiltersPrunePayload) -> ResultEnvelope[FiltersPruneResult]:
        candidates: list[FilterPruneCandidate] = []
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
    filter_obj: dict
    criteria: dict
    action: dict
    label_prefix: str


@dataclass
class FiltersAddForwardResult:
    updates: list[FilterForwardUpdate]
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

        updates: list[FilterForwardUpdate] = []
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
    filter_obj: dict
    criteria: dict
    action: dict
    new_from: str
    old_from: str


@dataclass
class FiltersAddTokenResult:
    updates: list[FilterTokenUpdate]


class FiltersAddTokenProcessor(Processor[FiltersAddTokenPayload, ResultEnvelope[FiltersAddTokenResult]]):
    """Compute new 'from' clauses when adding tokens."""

    def process(self, payload: FiltersAddTokenPayload) -> ResultEnvelope[FiltersAddTokenResult]:
        updates: list[FilterTokenUpdate] = []
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
    updates: list[FilterTokenUpdate]


class FiltersRemoveTokenProcessor(Processor[FiltersRemoveTokenPayload, ResultEnvelope[FiltersRemoveTokenResult]]):
    """Compute new 'from' clauses when removing tokens."""

    def process(self, payload: FiltersRemoveTokenPayload) -> ResultEnvelope[FiltersRemoveTokenResult]:
        updates: list[FilterTokenUpdate] = []
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
    spec: dict,
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
    filters: list[dict],
    id_to_name: dict[str, str],
    *,
    label_prefix: str,
    needle: str,
) -> list[tuple[dict, str]]:
    matches: list[tuple[dict, str]] = []

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


def _split_or_clause(clause: str) -> list[str]:
    return [part.strip() for part in clause.split("OR") if part.strip()]
