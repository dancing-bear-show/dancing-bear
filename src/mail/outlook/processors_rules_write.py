"""Write/mutation processors for Outlook rules pipelines."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.pipeline import Processor, ResultEnvelope

from .consumers import (
    OutlookRulesSyncPayload,
    OutlookRulesPlanPayload,
    OutlookRulesDeletePayload,
    OutlookRulesSweepPayload,
)
from .processors_rules_helpers import (
    RuleContext,
    _canon_rule,
    _criteria_key,
    _fetch_rules_with_resilience,
    _build_rule_criteria,
    _build_rule_action,
    _create_rule_key,
    _norm_create_rule_key,
    _build_plan_action,
    _format_plan_action,
    _build_search_query,
    _resolve_destination_folder,
)


# Result dataclasses

@dataclass
class OutlookRulesSyncResult:
    """Result of rules sync."""
    created: int = 0
    deleted: int = 0
    reconciled: int = 0
    failed: int = 0
    """Number of reconcile attempts that failed (delete or create raised).

    A failed delete is not followed by a create (no duplicate created).  A
    failed create after a successful delete means the rule is lost; the user
    must re-run after the transient error clears.  In both cases the operation
    is counted here rather than in reconciled so the caller always sees an
    accurate tally.
    """


@dataclass
class OutlookRulesPlanResult:
    """Result of rules plan."""
    would_create: int = 0
    would_reconcile: int = 0
    plan_items: list[str] = field(default_factory=list)


@dataclass
class OutlookRulesDeleteResult:
    """Result of rules delete."""
    rule_id: str = ""


@dataclass
class OutlookRulesSweepResult:
    """Result of rules sweep."""
    moved: int = 0


# Processor classes

class OutlookRulesSyncProcessor(Processor[OutlookRulesSyncPayload, ResultEnvelope[OutlookRulesSyncResult]]):
    """Sync Outlook inbox rules from YAML config."""

    def process(self, payload: OutlookRulesSyncPayload) -> ResultEnvelope[OutlookRulesSyncResult]:
        try:
            from core.yamlio import load_config
            from ..dsl import normalize_filters_for_outlook

            client = payload.client
            doc = load_config(payload.config_path)
            desired = normalize_filters_for_outlook(doc.get("filters") or [])

            # Fetch existing rules with resilience
            try:
                existing_rules = _fetch_rules_with_resilience(client)
            except Exception as e:
                return ResultEnvelope(
                    status="error",
                    payload=None,
                    diagnostics={"error": f"Auth failed: {e}", "code": 2, "hint": "Run outlook auth.ensure"},
                )

            existing = {_canon_rule(r): r for r in existing_rules}
            name_to_id = client.get_label_id_map()
            folder_path_map = client.get_folder_path_map() if payload.move_to_folders else {}

            ctx = RuleContext(
                client=client,
                name_to_id=name_to_id,
                folder_map=folder_path_map,
                move_to_folders=payload.move_to_folders,
            )
            created, reconciled, failed, desired_keys, reconciled_rule_ids = self._create_desired_rules(
                desired, existing, ctx, payload.dry_run, payload.reconcile
            )
            deleted = (
                self._delete_missing_rules(
                    existing, desired_keys, payload, reconciled_rule_ids
                ) if payload.delete_missing else 0
            )

            return ResultEnvelope(
                status="success",
                payload=OutlookRulesSyncResult(
                    created=created, deleted=deleted, reconciled=reconciled, failed=failed
                ),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )

    def _apply_reconcile_update(
        self,
        criteria: dict[str, Any],
        action: dict[str, Any],
        reconcile_index: dict[str, Any],
        ctx: RuleContext,
        dry_run: bool,
    ) -> tuple[str, str | None]:
        """Apply a reconcile update when a criteria match exists with a different action.

        Returns ``(status, deleted_rule_id)``.  ``deleted_rule_id`` is the id of
        the live rule this call actually deleted, or None when no delete landed
        ("no_match", "delete_failed", or dry_run).  The caller needs it to keep
        ``--delete-missing`` from issuing a second delete against an id that is
        already gone -- which would otherwise be tallied as a separate deletion,
        reporting two affected rules where there was one.

        Status values:
        - ``"no_match"``     : criteria key not in index; caller should treat as new.
        - ``"ok"``           : delete and create both succeeded (or dry_run).
        - ``"delete_failed"``: delete raised; create was NOT attempted (no duplicate).
        - ``"create_failed"``: delete succeeded but create raised; rule is now lost.

        Failure semantics:
        - A failed delete must not be followed by a create.  Proceeding after a
          failed delete creates a duplicate rule for the same criteria; the stale
          rule survives alongside the new one and both are matched by the Graph
          API.  The caller counts this as ``failed``, not ``reconciled``.
        - A failed create after a successful delete means the rule is gone and
          the replacement was never created.  This is the most severe path: the
          user must re-run after the transient error clears.  The caller counts
          this as ``failed``, not ``reconciled``, so the loss is never silent.
        - Retry / re-create from the stale live copy is intentionally NOT done
          here.  Re-creating from the stale action would resurrect an outdated
          rule; the caller has no access to the original live rule at this point
          (it was already popped from the index).  The right recovery is a
          subsequent ``rules.sync --reconcile`` after the API error resolves.

        Pops the matched entry from ``reconcile_index`` so the same live rule
        cannot be reconciled twice (duplicate criteria case).
        """
        crit_k = _criteria_key(criteria)
        if crit_k not in reconcile_index:
            return "no_match", None
        live_rule = reconcile_index.pop(crit_k)
        live_id = live_rule.get("id")
        if dry_run:
            return "ok", None
        try:
            ctx.client.delete_filter(live_id)
        except Exception:  # nosec B110 - delete failed; abort to prevent duplicate creation
            return "delete_failed", None
        try:
            # Pass the live rule's sequence and stopProcessingRules so the
            # replacement lands at the same position in the rule chain with the
            # same stop-processing setting. create_filter defaults to
            # sequence=1 / stopProcessingRules=True when not supplied, which
            # silently reorders the chain and forces a hard stop on all later
            # rules for this mailbox.
            #
            # The Graph API exposes sequence on read (_map_rule preserves it).
            # If list_filters returned a cached value that predates this PR
            # (sequence not in the cached doc), live_rule.get("sequence") is
            # None and create_filter falls back to its default -- identical to
            # previous behaviour, not worse.
            ctx.client.create_filter(
                criteria,
                action,
                sequence=live_rule.get("sequence"),
                stop_processing_rules=live_rule.get("stopProcessingRules"),
            )
        except Exception:  # nosec B110 - create failed after delete; rule is lost, surfaced as failed
            return "create_failed", live_id
        return "ok", live_id

    def _find_live_rule_id(self, spec: dict[str, Any], existing: dict[str, Any]) -> str | None:
        """Find the id of the live rule whose criteria match a spec's criteria.

        Used after a reconcile to record which live rule was deleted, so
        ``_delete_missing_rules`` can skip it and avoid a double-delete attempt.
        """
        desired_crit = _build_rule_criteria(spec.get("match") or {})
        target_ck = _criteria_key(desired_crit)
        for live_rule in existing.values():
            if _criteria_key(live_rule.get("criteria") or {}) == target_ck:
                return live_rule.get("id")
        return None

    def _reconcile_result(
        self,
        key: str,
        criteria: dict[str, Any],
        action: dict[str, Any],
        reconcile_index: dict[str, Any],
        ctx: RuleContext,
        dry_run: bool,
    ) -> tuple[str, bool, bool, bool, str | None] | None:
        """Map a reconcile-update status to its (key, created, reconciled, failed, protected_id) tuple.

        Returns None when there is no criteria match in the index ("no_match"),
        signalling the caller to fall through to fresh creation.  A non-None
        result should be returned directly by the caller.

        ``protected_id`` semantics per status:

        - "ok": None.  The caller recovers the deleted id itself via
          ``_find_live_rule_id`` on the reconciled branch.
        - "delete_failed": None.  The live rule survives on the OLD action, so it
          does not satisfy the desired spec and ``--delete-missing`` *should*
          retry it.
        - "create_failed": the deleted id.  The rule is already gone, so a second
          delete has nothing to remove.  This was previously left unprotected on
          the reasoning that the redundant call "would spuriously 404 but is
          otherwise harmless".  It is not harmless: ``_delete_one_rule`` swallows
          the exception and tallies from the call's outcome, so one rule was
          reported as both ``Failed: 1`` and ``Deleted: 1`` -- two affected rules
          where there was one -- and which number appeared depended on whether
          Graph 404s or succeeds against the dead id.
        """
        status, deleted_id = self._apply_reconcile_update(
            criteria, action, reconcile_index, ctx, dry_run
        )
        if status == "ok":
            return key, False, True, False, None
        if status == "delete_failed":
            return key, False, False, True, None
        if status == "create_failed":
            return key, False, False, True, deleted_id
        return None  # "no_match"

    def _find_live_rule_id_by_norm_key(
        self, criteria: dict[str, Any], action: dict[str, Any], existing: dict[str, Any]
    ) -> str | None:
        """Find the id of the live rule whose case-normalised key matches the desired spec.

        Used for the case-only no-op path in ``_create_rule_if_new`` so that
        ``--delete-missing`` can be told to skip the live rule: it already has
        the correct action; only criteria case differs from the desired spec.
        """
        target = _norm_create_rule_key(criteria, action)
        for live_rule in existing.values():
            if _norm_create_rule_key(
                live_rule.get("criteria") or {},
                live_rule.get("action") or {},
            ) == target:
                return live_rule.get("id")
        return None

    def _create_rule_if_new(
        self,
        spec: dict[str, Any],
        existing: dict[str, Any],
        ctx: RuleContext,
        dry_run: bool,
        reconcile_index: dict[str, Any] | None = None,
        norm_existing_keys: set[str] | None = None,
    ) -> tuple[str, bool, bool, bool, str | None] | None:
        """Build criteria/action/key for one spec and create it if missing.

        Returns (key, was_created, was_reconciled, was_failed, protected_rule_id)
        for specs with valid criteria and a real action, or None to skip — no key
        is contributed to the desired-keys set in that case, so ``--delete-missing``
        does not treat a skipped spec as something to preserve.

        ``protected_rule_id``: id of the live rule that already satisfies this
        desired spec (case-only no-op path), or None.  The caller adds it to
        ``reconciled_rule_ids_set`` so ``--delete-missing`` does not delete a
        live rule that is already correct.  Without this protection,
        ``_delete_missing_rules`` compares each live rule's ``_canon_rule`` key
        (built from raw UPPERCASE criteria) against ``desired_keys`` (which holds
        the desired lowercase key); they never match, and the live rule is deleted
        silently even though its action is already correct.

        ``reconcile_index``: when provided (``--reconcile`` mode), maps a
        criteria-only key to the live rule it came from. When a desired rule's
        criteria key matches an entry in this index but the full key (criteria +
        action) does not match, the live rule is deleted and a fresh one created
        with the desired action. The entry is removed from the index after use so
        the same live rule cannot be reconciled twice (handles duplicate criteria
        among live rules — first desired spec wins).
        """
        m = spec.get("match") or {}
        a_act = spec.get("action") or {}
        criteria = _build_rule_criteria(m)
        if not criteria:
            return None

        action = _build_rule_action(a_act, ctx)
        # Guard the BUILT action, not the source spec. ``create_filter`` sets
        # ``stopProcessingRules: True`` unconditionally
        # (core/outlook/_mail_labels.py:202), so an empty action becomes a rule
        # that matches mail, does nothing, and halts every later inbox rule.
        #
        # Derive drops such specs (``_drop_actionless_specs``), but ``rules.sync``
        # also accepts the RAW unified config directly, where nothing has run
        # that filter — a ``keepInInbox`` + ``remove: [INBOX]`` rule with no
        # category normalizes to ``action: {}`` and arrived here intact. Checking
        # the built action covers both config shapes, and anything else that
        # empties an action on the way in.
        if not action:
            return None
        key = _create_rule_key(criteria, action)
        if key in existing:
            return key, False, False, False, None

        # Case-normalised no-op check (reconcile mode only): if the desired
        # rule's normalised key already exists among live rules, the action is
        # already correct -- only the criteria case differs. Treat as matching,
        # and record the live rule's id so --delete-missing does not delete it.
        # Without the protected_rule_id, _delete_missing_rules compares the
        # live rule's _canon_rule key (UPPERCASE criteria verbatim) against
        # desired_keys (lowercase desired key); they never match, and the live
        # rule is deleted even though its action is already correct.
        if norm_existing_keys is not None:
            norm_key = _norm_create_rule_key(criteria, action)
            if norm_key in norm_existing_keys:
                protected_id = self._find_live_rule_id_by_norm_key(criteria, action, existing)
                return key, False, False, False, protected_id

        # Reconcile path: check whether criteria match a live rule with a
        # different action (action-change case). When reconcile_index is None
        # this branch is never entered and behaviour is identical to pre-reconcile.
        if reconcile_index is not None:
            reconcile_result = self._reconcile_result(
                key, criteria, action, reconcile_index, ctx, dry_run
            )
            if reconcile_result is not None:
                return reconcile_result
            # None: no criteria match; fall through to fresh creation below

        if not dry_run:
            try:
                ctx.client.create_filter(criteria, action)
            except Exception:  # nosec B110 - filter creation failure logged elsewhere
                pass
        return key, True, False, False, None

    def _build_reconcile_index(
        self, existing: dict[str, Any]
    ) -> dict[str, Any]:
        """Build a criteria-only index of live rules for reconciliation.

        The first live rule for each criteria key wins; later duplicates are
        skipped (their canon keys remain in ``existing`` and are eligible for
        ``--delete-missing``).  Entries are popped as they are matched, so the
        same live rule cannot be reconciled twice.
        """
        index: dict[str, Any] = {}
        for live_rule in existing.values():
            ck = _criteria_key(live_rule.get("criteria") or {})
            if ck not in index:
                index[ck] = live_rule
        return index

    def _build_norm_existing_keys(self, existing: dict[str, Any]) -> set[str]:
        """Build a set of case-normalised rule keys from existing live rules.

        Used in reconcile mode to detect a desired rule that already matches a
        live rule modulo criteria case.  Each live rule contributes one entry
        keyed by ``_norm_create_rule_key`` (case-folded criteria, raw action
        fields).  A desired rule whose normalised key is in this set already has
        the correct action and must be left alone -- no delete, no create.
        """
        return {
            _norm_create_rule_key(
                r.get("criteria") or {},
                r.get("action") or {},
            )
            for r in existing.values()
        }

    def _create_desired_rules(
        self,
        desired: list[dict[str, Any]],
        existing: dict[str, Any],
        ctx: RuleContext,
        dry_run: bool,
        reconcile: bool = False,
    ) -> tuple[int, int, int, set[str], set[str]]:
        """Create rules from desired specs that don't exist.

        When ``reconcile`` is True, rules that match an existing rule by criteria
        but differ in action are handled as an in-place update (delete old,
        create new) rather than as a fresh creation. The reconcile count reflects
        the number of rules updated this way; the created count reflects only
        genuinely new rules.  The failed count reflects reconcile attempts where
        either the delete or the create raised -- these are never counted as
        reconciled so the caller always sees an accurate tally.

        Returns:
            Tuple of (created_count, reconciled_count, failed_count,
                      desired_keys_set, reconciled_rule_ids_set)
        """
        created = 0
        reconciled = 0
        failed = 0
        desired_keys: set[str] = set()
        reconciled_rule_ids_set: set[str] = set()
        reconcile_index = self._build_reconcile_index(existing) if reconcile else None
        norm_existing_keys = self._build_norm_existing_keys(existing) if reconcile else None

        for spec in desired:
            result = self._create_rule_if_new(
                spec, existing, ctx, dry_run, reconcile_index, norm_existing_keys
            )
            if result is None:
                continue
            key, was_created, was_reconciled, was_failed, protected_id = result
            desired_keys.add(key)
            if was_created:
                created += 1
            elif was_reconciled:
                reconciled += 1
                rid = self._find_live_rule_id(spec, existing)
                if rid:
                    reconciled_rule_ids_set.add(rid)
            elif was_failed:
                failed += 1
            # protected_id: --delete-missing must not issue a delete for this id.
            # Two distinct reasons produce it:
            #   - case-only no-op: the live rule already satisfies the desired
            #     spec, so deleting it would destroy a correct rule.
            #   - create_failed: the rule was already deleted during reconcile,
            #     so a second delete has nothing to remove and would tally the
            #     same rule twice (Failed: 1 AND Deleted: 1).
            if protected_id:
                reconciled_rule_ids_set.add(protected_id)

        return created, reconciled, failed, desired_keys, reconciled_rule_ids_set

    def _delete_one_rule(self, client: Any, rid: str | None, dry_run: bool) -> bool:
        """Delete a single rule by id; return True if it counted as deleted."""
        if dry_run or not rid:
            return True
        try:
            client.delete_filter(rid)
            return True
        except Exception:  # nosec B110 - filter deletion failure
            return False

    def _delete_missing_rules(
        self,
        existing: dict[str, Any],
        desired_keys: set,
        payload: OutlookRulesSyncPayload,
        reconciled_rule_ids: set[str] | None = None,
    ) -> int:
        """Delete rules that are not in desired set.

        ``reconciled_rule_ids``: IDs of live rules that were already deleted
        during reconciliation.  Excluded here to avoid a double-delete attempt
        (the rule no longer exists; the API call would 404 and count as 0, but
        the extra round-trip is unnecessary and noisy in logs).

        Args:
            existing: Map of canonical rule keys to rule objects
            desired_keys: Set of canonical keys for desired rules
            payload: Sync request payload
            reconciled_rule_ids: Set of rule IDs already deleted during reconcile

        Returns:
            Number of rules deleted
        """
        skip_ids = reconciled_rule_ids or set()
        to_delete = [
            rule for k, rule in existing.items()
            if k not in desired_keys and rule.get("id") not in skip_ids
        ]
        return sum(
            1 for rule in to_delete
            if self._delete_one_rule(payload.client, rule.get("id"), payload.dry_run)
        )


def _has_explicit_destination(desired: list[dict[str, Any]]) -> bool:
    """True when any spec names a ``moveToFolder`` outright.

    Such a destination is honoured regardless of ``move_to_folders``, so its id
    has to be resolvable even under ``--categories-only``.
    """
    return any((spec.get("action") or {}).get("moveToFolder") for spec in desired)


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
                payload.move_to_folders, payload.reconcile
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
    ) -> tuple[str, bool] | None:
        """Classify one desired spec and return (plan_line, is_reconcile) or None.

        Returns None when the spec should produce no plan line (no criteria,
        no action, or rule already satisfied by a live rule).  Returns
        (line, True) for a reconcile, (line, False) for a net-new create.
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
        ctx = RuleContext.for_plan(name_to_id, folder_map, move_to_folders)

        # Build the same indexes that sync uses so plan and apply classify each
        # desired rule identically.
        reconcile_index = self._build_reconcile_index(existing_map) if reconcile else None
        norm_existing_keys = self._build_norm_existing_keys(existing_map) if reconcile else None

        for spec in desired:
            item = self._plan_item_for_spec(
                spec, existing_keys, ctx, folder_map, reconcile_index, norm_existing_keys
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

    def _build_norm_existing_keys(self, existing: dict[str, Any]) -> set[str]:
        """Build a set of case-normalised rule keys from existing live rules.

        Used to detect a desired rule that already matches a live rule modulo
        criteria case.  A desired rule whose normalised key is in this set
        already has the correct action and must be left alone.
        """
        return {
            _norm_create_rule_key(
                r.get("criteria") or {},
                r.get("action") or {},
            )
            for r in existing.values()
        }

class OutlookRulesDeleteProcessor(Processor[OutlookRulesDeletePayload, ResultEnvelope[OutlookRulesDeleteResult]]):
    """Delete an Outlook inbox rule."""

    def process(self, payload: OutlookRulesDeletePayload) -> ResultEnvelope[OutlookRulesDeleteResult]:
        try:
            payload.client.delete_filter(payload.rule_id)
            return ResultEnvelope(
                status="success",
                payload=OutlookRulesDeleteResult(rule_id=payload.rule_id),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 3},
            )


class OutlookRulesSweepProcessor(Processor[OutlookRulesSweepPayload, ResultEnvelope[OutlookRulesSweepResult]]):
    """Sweep inbox messages based on rules."""

    def process(self, payload: OutlookRulesSweepPayload) -> ResultEnvelope[OutlookRulesSweepResult]:
        try:
            from core.yamlio import load_config
            from ..dsl import normalize_filters_for_outlook

            client = payload.client
            self._clear_cache_if_needed(client, payload.clear_cache)

            doc = load_config(payload.config_path)
            desired = normalize_filters_for_outlook(doc.get("filters") or [])
            # Same condition as the plan processor, and for a sharper reason:
            # `_resolve_destination_folder` reads the map only on the dry-run
            # branch and calls ensure_folder_path() on the live one. Gating on
            # move_to_folders alone left the map empty under --categories-only,
            # so a rule with an explicit `moveToFolder` resolved None in dry-run
            # and a real id live — `sweep --dry-run` reported zero moves while
            # the real run moved mail. A dry run that under-reports is worse
            # than no dry run at all.
            folder_paths = (
                client.get_folder_path_map(clear_cache=payload.clear_cache)
                if payload.move_to_folders or _has_explicit_destination(desired)
                else {}
            )

            total_moves = self._process_sweep_rules(desired, folder_paths, client, payload)

            return ResultEnvelope(
                status="success",
                payload=OutlookRulesSweepResult(moved=total_moves),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )

    def _clear_cache_if_needed(self, client: Any, clear_cache: bool) -> None:
        """Clear client cache if requested."""
        if clear_cache:
            try:
                client.cfg_clear()
            except Exception:  # nosec B110 - non-critical cache clear
                pass

    def _process_sweep_rules(
        self,
        desired: list[dict[str, Any]],
        folder_paths: dict[str, str],
        client: Any,
        payload: OutlookRulesSweepPayload,
    ) -> int:
        """Process all sweep rules and return count of moved messages."""
        total_moves = 0
        for spec in desired:
            m = spec.get("match") or {}
            a_act = spec.get("action") or {}
            srch = _build_search_query(m)
            if not srch:
                continue

            dest_id = _resolve_destination_folder(
                a_act, payload.move_to_folders, folder_paths, client, payload.dry_run
            )
            if not dest_id:
                continue

            ids = self._search_messages(client, srch, payload)
            if not ids:
                continue

            total_moves += self._move_messages(client, ids, dest_id, payload.dry_run)

        return total_moves

    def _search_messages(
        self, client: Any, query: str, payload: OutlookRulesSweepPayload
    ) -> list[str]:
        """Search for messages matching query.

        ``query`` is a RAW, unquoted KQL term -- ``_build_search_url`` owns the
        quoting and percent-encoding.
        """
        from core.outlook.models import SearchParams
        return client.search_inbox_messages(
            SearchParams(
                search_query=query,
                days=payload.days,
                top=payload.top,
                pages=payload.pages,
                use_cache=not payload.clear_cache,
            )
        )

    def _move_messages(
        self, client: Any, message_ids: list[str], dest_id: str, dry_run: bool
    ) -> int:
        """Move messages to destination folder."""
        if dry_run:
            return len(message_ids)

        moved = 0
        for mid in message_ids:
            try:
                client.move_message(mid, dest_id)
                moved += 1
            except Exception:  # nosec B110 - individual move failure
                pass
        return moved
