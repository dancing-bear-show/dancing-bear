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
    _fetch_rules_with_resilience,
    _build_rule_criteria,
    _build_rule_action,
    _create_rule_key,
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


@dataclass
class OutlookRulesPlanResult:
    """Result of rules plan."""
    would_create: int = 0
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
            from ..yamlio import load_config
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
                    diagnostics={"error": f"Auth failed: {e}", "code": 2, "hint": "Run outlook auth ensure"},
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
            created, desired_keys = self._create_desired_rules(
                desired, existing, ctx, payload.dry_run
            )
            deleted = (
                self._delete_missing_rules(existing, desired_keys, payload) if payload.delete_missing else 0
            )

            return ResultEnvelope(
                status="success",
                payload=OutlookRulesSyncResult(created=created, deleted=deleted),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )

    def _create_rule_if_new(
        self, spec: dict[str, Any], existing: dict[str, Any], ctx: RuleContext, dry_run: bool
    ) -> tuple[str, bool] | None:
        """Build criteria/action/key for one spec and create it if missing.

        Returns (key, was_created) for specs with valid criteria, or None to skip
        (invalid criteria, so no key is contributed to the desired-keys set).
        """
        m = spec.get("match") or {}
        a_act = spec.get("action") or {}
        criteria = _build_rule_criteria(m)
        if not criteria:
            return None

        action = _build_rule_action(a_act, ctx)
        key = _create_rule_key(criteria, action)
        if key in existing:
            return key, False

        if not dry_run:
            try:
                ctx.client.create_filter(criteria, action)
            except Exception:  # nosec B110 - filter creation failure logged elsewhere
                pass
        return key, True

    def _create_desired_rules(
        self,
        desired: list[dict[str, Any]],
        existing: dict[str, Any],
        ctx: RuleContext,
        dry_run: bool,
    ) -> tuple[int, set]:
        """Create rules from desired specs that don't exist.

        Returns:
            Tuple of (created_count, desired_keys_set)
        """
        created = 0
        desired_keys: set = set()

        for spec in desired:
            result = self._create_rule_if_new(spec, existing, ctx, dry_run)
            if result is None:
                continue
            key, was_created = result
            desired_keys.add(key)
            if was_created:
                created += 1

        return created, desired_keys

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
        self, existing: dict[str, Any], desired_keys: set, payload: OutlookRulesSyncPayload
    ) -> int:
        """Delete rules that are not in desired set.

        Args:
            existing: Map of canonical rule keys to rule objects
            desired_keys: Set of canonical keys for desired rules
            payload: Sync request payload

        Returns:
            Number of rules deleted
        """
        to_delete = [rule for k, rule in existing.items() if k not in desired_keys]
        return sum(
            1 for rule in to_delete
            if self._delete_one_rule(payload.client, rule.get("id"), payload.dry_run)
        )


class OutlookRulesPlanProcessor(Processor[OutlookRulesPlanPayload, ResultEnvelope[OutlookRulesPlanResult]]):
    """Plan Outlook inbox rules sync (dry-run)."""

    def process(self, payload: OutlookRulesPlanPayload) -> ResultEnvelope[OutlookRulesPlanResult]:
        try:
            from ..yamlio import load_config
            from ..dsl import normalize_filters_for_outlook

            client = payload.client
            doc = load_config(payload.config_path)
            desired = normalize_filters_for_outlook(doc.get("filters") or [])

            existing = _fetch_rules_with_resilience(client)
            existing_keys = {_canon_rule(r) for r in existing}
            name_to_id = client.get_label_id_map()
            folder_map = client.get_folder_id_map() if payload.move_to_folders else {}

            plan_items = self._build_plan_items(
                desired, existing_keys, name_to_id, folder_map, payload.move_to_folders
            )

            return ResultEnvelope(
                status="success",
                payload=OutlookRulesPlanResult(would_create=len(plan_items), plan_items=plan_items),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )

    def _build_plan_items(
        self,
        desired: list[dict[str, Any]],
        existing_keys: set,
        name_to_id: dict[str, str],
        folder_map: dict[str, str],
        move_to_folders: bool,
    ) -> list[str]:
        """Build plan items for rules that would be created."""
        plan_items = []
        ctx = RuleContext.for_plan(name_to_id, folder_map, move_to_folders)

        for spec in desired:
            m = spec.get("match") or {}
            a_act = spec.get("action") or {}
            criteria = _build_rule_criteria(m)
            if not criteria:
                continue

            action = _build_plan_action(a_act, ctx)
            key = _create_rule_key(criteria, action)

            if key not in existing_keys:
                disp = _format_plan_action(action, folder_map)
                plan_items.append(f"Would create: criteria={criteria} action={disp}")

        return plan_items


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
            from ..yamlio import load_config
            from ..dsl import normalize_filters_for_outlook

            client = payload.client
            self._clear_cache_if_needed(client, payload.clear_cache)

            doc = load_config(payload.config_path)
            desired = normalize_filters_for_outlook(doc.get("filters") or [])
            folder_paths = client.get_folder_path_map(clear_cache=payload.clear_cache) if payload.move_to_folders else {}

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
