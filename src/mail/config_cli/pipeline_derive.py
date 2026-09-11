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


def _strip_keep_in_inbox(out_specs: list[dict]) -> None:
    """Convert the ``keepInInbox`` input marker to the internal ``noMoveToFolder`` marker.

    ``keepInInbox`` is a user-facing input directive that must never appear in the
    provider payload.  When present it is replaced with ``noMoveToFolder: true``,
    which the plan and sweep stages read to suppress folder derivation even when
    ``move_to_folders`` is True.  When absent the key is removed so normal rules
    are unaffected.

    The conversion happens unconditionally — outside the move/archive branches —
    so the marker is always handled regardless of which flags are active.  Without
    this conversion the plan/sweep stage cannot distinguish a keepInInbox rule
    (no folder wanted) from a rule where no folder was specified.
    """
    for spec in out_specs:
        action = spec.get("action")
        if isinstance(action, dict) and action.pop("keepInInbox", None):
            action["noMoveToFolder"] = True


def _pair_specs_with_sources(
    out_specs: list[dict], filters: list[dict]
) -> list[tuple[dict, dict]]:
    """Pair each normalized spec with the source filter it came from.

    ``normalize_filters_for_outlook`` drops entries that normalize to ``None``
    (non-dicts, and specs carrying neither criteria nor action), so ``out_specs``
    is **not** positionally aligned with ``filters``. Indexing ``filters[i]``
    therefore reads the wrong source rule once anything ahead of it is dropped —
    verified with a leading non-dict entry: ``len(filters)=2``,
    ``len(out_specs)=1``, and ``filters[0]`` is the malformed entry rather than
    the rule that survived.

    Re-normalizing each source filter and keeping only those that survive
    reproduces the same skip decisions, so the pairing is exact rather than
    positional. Consumers need the source because Gmail-side directives such as
    ``remove`` are not carried onto the normalized spec.
    """
    from ..dsl import normalize_filter_for_outlook

    sources = [f for f in (filters or []) if normalize_filter_for_outlook(f)]
    return list(zip(out_specs, sources))


def _apply_archive_on_remove_inbox(out_specs: list[dict], filters: list[dict]) -> None:
    """Mutate out_specs: replace 'add' with 'moveToFolder=Archive' when original removes INBOX.

    ``keepInInbox`` wins over this branch, matching ``_apply_move_to_folders``:
    Archive is a destination *derived* from ``remove: [INBOX]``, and the marker's
    documented job is to suppress a derived move ("suppress the derived Outlook
    moveToFolder", config/filters_unified.example.yaml:30). An explicitly
    authored ``moveToFolder`` is untouched here and still overrides the marker
    downstream.

    Without this check the two sibling derive branches disagreed: the
    move-to-folders branch skipped marked rules while this one archived them
    anyway, so a rule carrying both `remove: [INBOX]` and `keepInInbox: true`
    left the inbox through all three consumers despite the marker being present.
    """
    for spec, orig in _pair_specs_with_sources(out_specs, filters):
        orig_action = (orig or {}).get("action") or {}
        spec_action = spec.get("action") or {}
        # Read the marker from EITHER side. The source always carries it, and is
        # the only side that does for an archive-only rule: normalization keeps
        # `keepInInbox` solely when add/forward/moveToFolder has content, so
        # `remove: [INBOX]` + `keepInInbox` with no category normalizes to
        # `action: {}` and a spec-only check missed it — then archived the rule,
        # which is precisely what the directive forbids. `remove` pairs with the
        # marker legitimately here because, under this flag, it is what produces
        # the moveToFolder there is to suppress.
        if orig_action.get("keepInInbox") or spec_action.get("keepInInbox"):
            continue
        remove_list = orig_action.get("remove") or []
        if isinstance(remove_list, list) and any(str(x).upper() == "INBOX" for x in remove_list):
            a = spec.get("action") or {}
            a["moveToFolder"] = "Archive"
            a.pop("add", None)
            spec["action"] = a


def _apply_move_to_folders(out_specs: list[dict]) -> None:
    """Mutate out_specs: set 'moveToFolder' from first 'add' label when not already set.

    Rules marked ``keepInInbox`` are skipped: on Outlook a moveToFolder is a real
    move, so deriving one would pull mail the user wants to see out of the inbox.
    The marker is only read here; :func:`_strip_keep_in_inbox` removes it from the
    output on every path.
    """
    for spec in out_specs:
        a = spec.get("action") or {}
        adds = a.get("add") or []
        if a.get("keepInInbox"):
            continue
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
        # Unconditional: neither branch above runs when both flags are off, and
        # keepInInbox is an input directive that must never reach the provider.
        _strip_keep_in_inbox(out_specs)

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
