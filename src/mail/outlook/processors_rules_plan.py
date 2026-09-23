"""Plan (dry-run preview) processor for Outlook rules pipelines."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.pipeline import Processor, ResultEnvelope

from .consumers import OutlookRulesPlanPayload
from .processors_rules_helpers import (
    RuleContext,
    _canon_rule,
    _criteria_key,
    _fetch_rules_with_resilience,
    _build_rule_criteria,
    _create_rule_key,
    _norm_create_rule_key,
    _build_plan_action,
    _format_plan_action,
    _has_explicit_destination,
)
from .processors_rules_index import (
    _build_norm_existing_keys,
    _build_unmappable_criteria_index,
)


@dataclass
class OutlookRulesPlanResult:
    """Result of rules plan."""
    would_create: int = 0
    would_reconcile: int = 0
    plan_items: list[str] = field(default_factory=list)


class OutlookRulesPlanProcessor(Processor[OutlookRulesPlanPayload, ResultEnvelope[OutlookRulesPlanResult]]):
    """Plan Outlook inbox rules sync (dry-run)."""

    def process(self, payload: OutlookRulesPlanPayload) -> ResultEnvelope[OutlookRulesPlanResult]:
        try:
            from core.yamlio import load_config
            from ..dsl import normalize_filters_for_outlook

            client = payload.client
            doc = load_config(payload.config_path)
            desired = normalize_filters_for_outlook(doc.get("filters") or [])

            existing_rules = _fetch_rules_with_resilience(
                client, payload.use_cache, payload.cache_ttl
            )
            existing_keys = {_canon_rule(r) for r in existing_rules}
            name_to_id = client.get_label_id_map()
            # Path-keyed, matching sync (line 83) and sweep (line 285). Plan used
            # get_folder_id_map, which keys displayName only, so an explicit
            # nested destination like `Security/Alerts` resolved to no id here
            # while sync resolved it through ensure_folder_path() -- the plan's
            # rule key diverged from apply's and reported an existing rule as
            # "Would create". A path map also reverses correctly for display in
            # _format_plan_action.
            #
            # Loaded whenever a destination needs resolving, not only when
            # automatic derivation is on: `_build_plan_action` honours an
            # explicit `moveToFolder` regardless of move_to_folders, and
            # `_build_rule_action` resolves it through ensure_folder_path()
            # either way. Gating solely on move_to_folders left the map empty
            # under --categories-only, so plan fell back to the literal path
            # while apply used the Graph id.
            # Call it exactly as sync does (line 83) -- no ttl argument -- so the
            # preview resolves destinations the same way the apply will.
            #
            # `--use-cache` / `--cache-ttl` exist on plan but not on sync, and
            # they are about the *rules* fetch (honoured at line 213). Threading
            # them into the folder map made `rules.plan --cache-ttl 1` read a
            # fresher map than the apply, which reintroduces the plan/sync rule
            # key divergence those flags have nothing to do with.
            #
            # Sync is itself cache-backed: `get_folder_path_map()` defaults to a
            # 600s TTL on the `folders_all` cache, and `_build_rule_action`
            # consults that map *before* falling back to `ensure_folder_path`
            # (processors_rules_helpers.py:86). Matching it is the goal; reading
            # fresher than it is the bug.
            #
            # There is no clean per-key bypass to reach for instead -- verified
            # against core/cache.py rather than assumed: `ttl=0` and any
            # negative ttl skip the `ttl > 0` guard and serve an entry of any
            # age, and `clear_cache=True` rmtree's the whole provider cache
            # directory (core/cache.py:86) including the rules cache used here
            # as an outage fallback. The residual folder staleness is therefore
            # shared with sync by construction; closing it needs identical
            # folder-cache controls plumbed through both commands, which is a
            # CLI change beyond this fix.
            need_folders = payload.move_to_folders or _has_explicit_destination(desired)
            folder_map = client.get_folder_path_map() if need_folders else {}

            existing_map = {_canon_rule(r): r for r in existing_rules}
            plan_items, would_reconcile = self._build_plan_items(
                desired, existing_keys, existing_map, name_to_id, folder_map,
                payload.move_to_folders, payload.reconcile,
                # Read-only client, for non-mutating folder lookups only. Without
                # it plan falls back to the folder path string on a cache miss
                # while sync resolves the real Graph id, so the two key the same
                # rule differently and plan promises a create sync will not make.
                client,
            )

            return ResultEnvelope(
                status="success",
                payload=OutlookRulesPlanResult(
                    would_create=len(plan_items) - would_reconcile,
                    would_reconcile=would_reconcile,
                    plan_items=plan_items,
                ),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )

    def _plan_item_for_spec(
        self,
        spec: dict[str, Any],
        existing_keys: set,
        ctx: RuleContext,
        folder_map: dict[str, str],
        reconcile_index: dict[str, Any] | None,
        norm_existing_keys: set[str] | None,
        unmappable_index: dict[str, list[str]] | None = None,
    ) -> tuple[str, bool] | None:
        """Classify one desired spec and return (plan_line, is_reconcile) or None.

        Returns None when the spec should produce no plan line (no criteria,
        no action, rule already satisfied by a live rule, or a live rule with
        unmappable conditions owns these criteria).  Returns (line, True) for a
        reconcile, (line, False) for a net-new create.
        """
        m = spec.get("match") or {}
        a_act = spec.get("action") or {}
        criteria = _build_rule_criteria(m)
        if not criteria:
            return None

        action = _build_plan_action(a_act, ctx)
        # Mirror the sync guard: an empty built action is skipped in
        # ``_create_rule_if_new``, so predicting it here would promise a
        # rule the apply will not create.
        if not action:
            return None
        key = _create_rule_key(criteria, action)

        if key in existing_keys:
            return None  # exact match: no action needed

        # Mirror the sync skip: a live rule with these criteria carries Graph
        # conditions this codebase cannot express, so sync neither reconciles it
        # nor creates a second rule beside it. Predicting a create here would
        # promise a rule the apply will not create.
        if unmappable_index and _criteria_key(criteria) in unmappable_index:
            return None

        # Case-normalised no-op: live rule already has the correct action;
        # only criteria case differs.
        if norm_existing_keys is not None:
            if _norm_create_rule_key(criteria, action) in norm_existing_keys:
                return None

        # Reconcile path: criteria match with a different action.
        if reconcile_index is not None:
            crit_k = _criteria_key(criteria)
            if crit_k in reconcile_index:
                live_rule = reconcile_index.pop(crit_k)
                live_id = live_rule.get("id", "<unknown>")
                disp = _format_plan_action(action, folder_map)
                return (
                    f"Would reconcile: delete rule id={live_id} "
                    f"criteria={criteria} action={disp}",
                    True,
                )

        disp = _format_plan_action(action, folder_map)
        return f"Would create: criteria={criteria} action={disp}", False

    def _build_plan_items(
        self,
        desired: list[dict[str, Any]],
        existing_keys: set,
        existing_map: dict[str, Any],
        name_to_id: dict[str, str],
        folder_map: dict[str, str],
        move_to_folders: bool,
        reconcile: bool = False,
        client: Any = None,
    ) -> tuple[list[str], int]:
        """Build plan items for rules that would be created or reconciled.

        In ``reconcile`` mode, rules that match a live rule by criteria but have
        a changed action are reported as ``Would reconcile`` (delete existing
        rule id, create replacement) rather than ``Would create``.  The live
        rule id and the replacement action are both shown so the user can see
        what will be deleted and what will replace it.

        Returns (plan_items, would_reconcile_count).  ``would_reconcile_count``
        is the number of ``Would reconcile`` lines so the caller can split the
        summary into distinct create and reconcile totals.

        The output of ``rules.plan --reconcile`` must agree with
        ``rules.sync --reconcile --dry-run`` on the same input.
        """
        plan_items = []
        would_reconcile = 0
        ctx = RuleContext.for_plan(name_to_id, folder_map, move_to_folders, client)

        # Build the same indexes that sync uses so plan and apply classify each
        # desired rule identically.
        reconcile_index = self._build_reconcile_index(existing_map) if reconcile else None
        norm_existing_keys = _build_norm_existing_keys(existing_map) if reconcile else None
        unmappable_index = _build_unmappable_criteria_index(existing_map) if reconcile else None

        for spec in desired:
            item = self._plan_item_for_spec(
                spec, existing_keys, ctx, folder_map, reconcile_index, norm_existing_keys,
                unmappable_index,
            )
            if item is None:
                continue
            line, is_reconcile = item
            plan_items.append(line)
            if is_reconcile:
                would_reconcile += 1

        return plan_items, would_reconcile


    def _build_reconcile_index(self, existing: dict[str, Any]) -> dict[str, Any]:
        """Build a criteria-only index of live rules for reconciliation.

        The first live rule for each criteria key wins; later duplicates are
        skipped.  Entries are popped as they are matched, so the same live rule
        cannot be reconciled twice.
        """
        index: dict[str, Any] = {}
        for live_rule in existing.values():
            ck = _criteria_key(live_rule.get("criteria") or {})
            if ck not in index:
                index[ck] = live_rule
        return index
