"""Pipeline primitives for derive and optimize config commands."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.cli_output import OutputWriter
from core.pipeline import (
    BaseProducer,
    RequestConsumer,
    SafeProcessor,
)


# -----------------------------------------------------------------------------
# Derive labels pipeline
# -----------------------------------------------------------------------------


@dataclass
class DeriveLabelsRequest:
    """Request for deriving labels."""

    in_path: str
    out_gmail: str
    out_outlook: str


@dataclass
class DeriveLabelsResult:
    """Result from deriving labels."""

    gmail_path: str
    outlook_path: str
    labels_count: int


# Type alias using generic RequestConsumer from core.pipeline
DeriveLabelsRequestConsumer = RequestConsumer[DeriveLabelsRequest]


class DeriveLabelsProcessor(SafeProcessor[DeriveLabelsRequest, DeriveLabelsResult]):
    def _process_safe(self, payload: DeriveLabelsRequest) -> DeriveLabelsResult:
        from core.yamlio import load_config, dump_config
        from ..dsl import normalize_labels_for_outlook

        doc = load_config(payload.in_path) if payload.in_path else {}
        labels = doc.get("labels") or []
        if not isinstance(labels, list):
            raise ValueError("Input missing labels: []")

        # Gmail: pass-through
        out_g = Path(payload.out_gmail)
        out_g.parent.mkdir(parents=True, exist_ok=True)
        dump_config(str(out_g), {"labels": labels})

        # Outlook: normalized names/colors
        out_o = Path(payload.out_outlook)
        out_o.parent.mkdir(parents=True, exist_ok=True)
        dump_config(str(out_o), {"labels": normalize_labels_for_outlook(labels)})

        return DeriveLabelsResult(
            gmail_path=str(out_g),
            outlook_path=str(out_o),
            labels_count=len(labels),
        )


class DeriveLabelsProducer(BaseProducer):
    def _produce_success(self, payload: DeriveLabelsResult, diagnostics: dict[str, Any] | None) -> None:
        print(f"Derived labels -> gmail:{payload.gmail_path} outlook:{payload.outlook_path}")


# -----------------------------------------------------------------------------
# Derive filters pipeline
# -----------------------------------------------------------------------------


@dataclass
class DeriveFiltersRequest:
    """Request for deriving filters."""

    in_path: str
    out_gmail: str
    out_outlook: str
    outlook_archive_on_remove_inbox: bool = False
    outlook_move_to_folders: bool = False


@dataclass
class DeriveFiltersResult:
    """Result from deriving filters."""

    gmail_path: str
    outlook_path: str
    filters_count: int


# Type alias using generic RequestConsumer from core.pipeline
DeriveFiltersRequestConsumer = RequestConsumer[DeriveFiltersRequest]


def _apply_archive_on_remove_inbox(out_specs: list, filters: list) -> None:
    """Mutate out_specs: replace 'add' with 'moveToFolder=Archive' when original removes INBOX."""
    for i, spec in enumerate(out_specs):
        orig = filters[i] if i < len(filters) else {}
        remove_list = ((orig or {}).get("action") or {}).get("remove") or []
        if isinstance(remove_list, list) and any(str(x).upper() == "INBOX" for x in remove_list):
            a = spec.get("action") or {}
            a["moveToFolder"] = "Archive"
            a.pop("add", None)
            spec["action"] = a


def _apply_move_to_folders(out_specs: list) -> None:
    """Mutate out_specs: set 'moveToFolder' from first 'add' label when not already set."""
    for spec in out_specs:
        a = spec.get("action") or {}
        adds = a.get("add") or []
        if adds and not a.get("moveToFolder"):
            a["moveToFolder"] = str(adds[0])
            spec["action"] = a


class DeriveFiltersProcessor(SafeProcessor[DeriveFiltersRequest, DeriveFiltersResult]):
    def _process_safe(self, payload: DeriveFiltersRequest) -> DeriveFiltersResult:
        from core.yamlio import load_config, dump_config
        from ..dsl import normalize_filters_for_outlook

        doc = load_config(payload.in_path) if payload.in_path else {}
        filters = doc.get("filters") or []
        if not isinstance(filters, list):
            raise ValueError("Input missing filters: []")

        # Gmail: pass-through
        out_g = Path(payload.out_gmail)
        out_g.parent.mkdir(parents=True, exist_ok=True)
        dump_config(str(out_g), {"filters": filters})

        # Outlook: normalized subset
        out_specs = normalize_filters_for_outlook(filters)
        if payload.outlook_archive_on_remove_inbox:
            _apply_archive_on_remove_inbox(out_specs, filters)
        elif payload.outlook_move_to_folders:
            _apply_move_to_folders(out_specs)

        out_o = Path(payload.out_outlook)
        out_o.parent.mkdir(parents=True, exist_ok=True)
        dump_config(str(out_o), {"filters": out_specs})

        return DeriveFiltersResult(
            gmail_path=str(out_g),
            outlook_path=str(out_o),
            filters_count=len(filters),
        )


class DeriveFiltersProducer(BaseProducer):
    def _produce_success(self, payload: DeriveFiltersResult, diagnostics: dict[str, Any] | None) -> None:
        print(f"Derived filters -> gmail:{payload.gmail_path} outlook:{payload.outlook_path}")


# -----------------------------------------------------------------------------
# Optimize filters pipeline
# -----------------------------------------------------------------------------


@dataclass
class OptimizeFiltersRequest:
    """Request for optimizing filters."""

    in_path: str
    out_path: str
    merge_threshold: int = 2
    preview: bool = False


@dataclass
class MergedGroup:
    """Info about a merged group."""

    destination: str
    rules_merged: int
    unique_from_terms: int


@dataclass
class OptimizeFiltersResult:
    """Result from optimizing filters."""

    out_path: str
    original_count: int
    optimized_count: int
    merged_groups: list[MergedGroup]


# Type alias using generic RequestConsumer from core.pipeline
OptimizeFiltersRequestConsumer = RequestConsumer[OptimizeFiltersRequest]


def _partition_rules_by_dest(rules: list) -> tuple:
    """Split filter rules into (groups_by_dest, passthrough) for merging."""
    from collections import defaultdict
    groups: dict[str, list] = defaultdict(list)
    passthrough = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        m = r.get("match") or {}
        a = r.get("action") or {}
        adds = a.get("add") or []
        has_only_from = bool(m.get("from")) and not any(m.get(k) for k in ("to", "subject", "query", "negatedQuery"))
        if adds and has_only_from:
            groups[str(adds[0])].append(r)
        else:
            passthrough.append(r)
    return groups, passthrough


def _merge_group(dest: str, items: list) -> tuple:
    """Build a merged rule for a dest group. Returns (merged_rule, MergedGroup) or (None, None)."""
    terms = []
    removes: set = set()
    for it in items:
        frm = str((it.get("match") or {}).get("from") or "").strip()
        if frm:
            terms.append(frm)
        for x in (it.get("action") or {}).get("remove") or []:
            removes.add(x)
    atoms = [p.strip() for t in terms for p in t.split("OR") if p.strip()]
    uniq = sorted(set(atoms))
    if not uniq:
        return None, None
    rule: dict[str, Any] = {
        "name": f"merged_{dest.replace('/', '_')}",
        "match": {"from": " OR ".join(uniq)},
        "action": {"add": [dest]},
    }
    if removes:
        rule["action"]["remove"] = sorted(removes)
    return rule, MergedGroup(destination=dest, rules_merged=len(items), unique_from_terms=len(uniq))


class OptimizeFiltersProcessor(SafeProcessor[OptimizeFiltersRequest, OptimizeFiltersResult]):
    def _process_safe(self, payload: OptimizeFiltersRequest) -> OptimizeFiltersResult:
        from core.yamlio import load_config, dump_config

        doc = load_config(payload.in_path) if payload.in_path else {}
        rules = doc.get("filters") or []
        if not isinstance(rules, list):
            raise ValueError("Input missing filters: []")

        groups, passthrough = _partition_rules_by_dest(rules)
        merged = []
        preview_info = []
        threshold = max(2, payload.merge_threshold)

        for dest, items in groups.items():
            if len(items) < threshold:
                passthrough.extend(items)
                continue
            merged_rule, info = _merge_group(dest, items)
            if merged_rule is None:
                passthrough.extend(items)
                continue
            merged.append(merged_rule)
            preview_info.append(info)

        optimized = {"filters": merged + passthrough}
        outp = Path(payload.out_path)
        outp.parent.mkdir(parents=True, exist_ok=True)
        dump_config(str(outp), optimized)

        return OptimizeFiltersResult(
            out_path=str(outp),
            original_count=len(rules),
            optimized_count=len(optimized["filters"]),
            merged_groups=preview_info,
        )


class OptimizeFiltersProducer(BaseProducer):
    def __init__(self, preview: bool = False, writer: OutputWriter | None = None) -> None:
        super().__init__(writer)
        self._preview = preview

    def _produce_success(self, payload: OptimizeFiltersResult, diagnostics: dict[str, Any] | None) -> None:
        if self._preview and payload.merged_groups:
            print('Merged groups:')
            for g in sorted(payload.merged_groups, key=lambda x: -x.rules_merged):
                print(f'- {g.destination}: merged {g.rules_merged} rules into 1 (unique from terms={g.unique_from_terms})')
        print(f"Optimized filters written to {payload.out_path}. Original={payload.original_count} Optimized={payload.optimized_count}")
