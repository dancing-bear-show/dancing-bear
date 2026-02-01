"""Processors for Outlook pipelines."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

from core.outlook.models import EventCreationParams, RecurringEventCreationParams
from core.pipeline import Processor, ResultEnvelope

from .consumers import (
    OutlookRulesListPayload,
    OutlookRulesExportPayload,
    OutlookRulesSyncPayload,
    OutlookRulesPlanPayload,
    OutlookRulesDeletePayload,
    OutlookRulesSweepPayload,
    OutlookCategoriesListPayload,
    OutlookCategoriesExportPayload,
    OutlookCategoriesSyncPayload,
    OutlookFoldersSyncPayload,
    OutlookCalendarAddPayload,
    OutlookCalendarAddRecurringPayload,
    OutlookCalendarAddFromConfigPayload,
)
from .helpers import norm_label_name_outlook


# Context dataclasses

@dataclass
class RuleContext:
    """Shared context for rule building operations."""
    client: Any
    name_to_id: Dict[str, str]
    folder_map: Dict[str, str]
    move_to_folders: bool

    @classmethod
    def for_plan(cls, name_to_id: Dict[str, str], folder_map: Dict[str, str], move_to_folders: bool) -> "RuleContext":
        """Create context for plan operations (no client needed)."""
        return cls(client=None, name_to_id=name_to_id, folder_map=folder_map, move_to_folders=move_to_folders)


# Result dataclasses

@dataclass
class OutlookRulesListResult:
    """Result of rules list."""
    rules: List[Dict[str, Any]] = field(default_factory=list)
    id_to_name: Dict[str, str] = field(default_factory=dict)
    folder_path_rev: Dict[str, str] = field(default_factory=dict)


@dataclass
class OutlookRulesExportResult:
    """Result of rules export."""
    count: int = 0
    out_path: str = ""


@dataclass
class OutlookRulesSyncResult:
    """Result of rules sync."""
    created: int = 0
    deleted: int = 0


@dataclass
class OutlookRulesPlanResult:
    """Result of rules plan."""
    would_create: int = 0
    plan_items: List[str] = field(default_factory=list)


@dataclass
class OutlookRulesDeleteResult:
    """Result of rules delete."""
    rule_id: str = ""


@dataclass
class OutlookRulesSweepResult:
    """Result of rules sweep."""
    moved: int = 0


@dataclass
class OutlookCategoriesListResult:
    """Result of categories list."""
    categories: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class OutlookCategoriesExportResult:
    """Result of categories export."""
    count: int = 0
    out_path: str = ""


@dataclass
class OutlookCategoriesSyncResult:
    """Result of categories sync."""
    created: int = 0
    skipped: int = 0


@dataclass
class OutlookFoldersSyncResult:
    """Result of folders sync."""
    created: int = 0
    skipped: int = 0


@dataclass
class OutlookCalendarAddResult:
    """Result of calendar add."""
    event_id: str = ""
    subject: str = ""


@dataclass
class OutlookCalendarAddRecurringResult:
    """Result of calendar add recurring."""
    event_id: str = ""
    subject: str = ""


@dataclass
class OutlookCalendarAddFromConfigResult:
    """Result of calendar add from config."""
    created: int = 0


def _canon_rule(rule: dict) -> str:
    """Create a canonical key for comparing rules."""
    crit = rule.get("criteria") or {}
    act = rule.get("action") or {}
    return str({
        "from": crit.get("from"),
        "to": crit.get("to"),
        "subject": crit.get("subject"),
        "add": tuple(sorted((act.get("addLabelIds") or []))),
        "forward": act.get("forward"),
        "move": act.get("moveToFolderId"),
    })


def _fetch_rules_with_resilience(client: Any) -> List[Dict[str, Any]]:
    """Fetch existing rules with auth error handling and cache fallback."""
    try:
        return client.list_filters()
    except Exception as e:
        resp = getattr(e, 'response', None)
        status = getattr(resp, 'status_code', None) if resp else None
        if status in (401, 403):
            raise
        try:
            return client.list_filters(use_cache=True, ttl=600)
        except Exception:
            return []


def _build_rule_criteria(match_spec: Dict[str, Any]) -> Dict[str, Any]:
    """Build criteria dict from match spec."""
    return {k: v for k, v in match_spec.items() if k in ("from", "to", "subject") and v}


def _build_rule_action(action_spec: Dict[str, Any], ctx: RuleContext) -> Dict[str, Any]:
    """Build action dict from action spec."""
    action = {}
    add_labs = action_spec.get("add") or []

    if action_spec.get("moveToFolder"):
        fid = ctx.client.ensure_folder_path(str(action_spec.get("moveToFolder")))
        action["moveToFolderId"] = fid
    elif ctx.move_to_folders and add_labs:
        lab_name = str(add_labs[0])
        fid = ctx.folder_map.get(lab_name) or ctx.client.ensure_folder_path(lab_name)
        action["moveToFolderId"] = fid
    elif add_labs:
        ids = [ctx.name_to_id.get(x) or ctx.name_to_id.get(norm_label_name_outlook(x)) for x in add_labs]
        ids = [x for x in ids if x]
        if ids:
            action["addLabelIds"] = ids

    if action_spec.get("forward"):
        action["forward"] = action_spec["forward"]

    return action


def _create_rule_key(criteria: Dict[str, Any], action: Dict[str, Any]) -> str:
    """Create canonical key for a rule."""
    return str({
        "from": criteria.get("from"),
        "to": criteria.get("to"),
        "subject": criteria.get("subject"),
        "add": tuple(sorted(action.get("addLabelIds", []) or [])),
        "forward": action.get("forward"),
        "move": action.get("moveToFolderId"),
    })


def _build_plan_action(action_spec: Dict[str, Any], ctx: RuleContext) -> Dict[str, Any]:
    """Build action dict for plan (without creating folders)."""
    action = {}
    adds = action_spec.get("add") or []

    if ctx.move_to_folders and adds:
        lab_name = norm_label_name_outlook(adds[0])
        fid = ctx.folder_map.get(lab_name) or lab_name
        action["moveToFolderId"] = fid
    elif adds:
        ids = [ctx.name_to_id.get(x) or ctx.name_to_id.get(norm_label_name_outlook(x)) for x in adds]
        ids = [x for x in ids if x]
        if ids:
            action["addLabelIds"] = ids

    if action_spec.get("forward"):
        action["forward"] = action_spec["forward"]

    return action


def _format_plan_action(action: Dict[str, Any], folder_map: Dict[str, str]) -> Dict[str, Any]:
    """Format action dict for plan display (resolve folder IDs to names)."""
    disp = dict(action)
    if action.get("moveToFolderId"):
        rev = {v: k for k, v in (folder_map or {}).items()}
        disp["moveToFolder"] = rev.get(action["moveToFolderId"], action["moveToFolderId"])
    return disp


def _build_search_query(match_spec: Dict[str, Any]) -> str:
    """Build search query from match spec."""
    qparts = []
    if match_spec.get("from"):
        qparts.append(f"from:{match_spec.get('from')}")
    if match_spec.get("subject"):
        subj = str(match_spec.get("subject"))
        if ' ' in subj:
            qparts.append(f"subject:\"{subj}\"")
        else:
            qparts.append(f"subject:{subj}")
    return " ".join(qparts)


def _resolve_destination_folder(
    action_spec: Dict[str, Any],
    move_to_folders: bool,
    folder_paths: Dict[str, str],
    client: Any,
    dry_run: bool,
) -> str | None:
    """Resolve destination folder ID for sweep operation."""
    if action_spec.get("moveToFolder"):
        pth = str(action_spec.get("moveToFolder"))
        if dry_run:
            return folder_paths.get(pth)
        return client.ensure_folder_path(pth)

    if move_to_folders and (action_spec.get("add") or []):
        pth = str((action_spec.get("add") or ["Inbox"])[0])
        if dry_run:
            return folder_paths.get(pth)
        return client.ensure_folder_path(pth)

    return None


# Processor classes

class OutlookRulesListProcessor(Processor[OutlookRulesListPayload, ResultEnvelope[OutlookRulesListResult]]):
    """List Outlook inbox rules."""

    def process(self, payload: OutlookRulesListPayload) -> ResultEnvelope[OutlookRulesListResult]:
        try:
            client = payload.client
            rules = client.list_filters(use_cache=payload.use_cache, ttl=payload.cache_ttl)
            name_to_id = client.get_label_id_map()
            id_to_name = {v: k for k, v in name_to_id.items() if v}
            folder_path_rev = {fid: path for path, fid in (client.get_folder_path_map() or {}).items()}
            return ResultEnvelope(
                status="success",
                payload=OutlookRulesListResult(
                    rules=rules,
                    id_to_name=id_to_name,
                    folder_path_rev=folder_path_rev,
                ),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )


class OutlookRulesExportProcessor(Processor[OutlookRulesExportPayload, ResultEnvelope[OutlookRulesExportResult]]):
    """Export Outlook inbox rules to YAML."""

    def process(self, payload: OutlookRulesExportPayload) -> ResultEnvelope[OutlookRulesExportResult]:
        try:
            client = payload.client
            rules = client.list_filters(use_cache=payload.use_cache, ttl=payload.cache_ttl)
            id_to_name = {v: k for k, v in client.get_label_id_map().items() if v}
            folder_path_map = client.get_folder_path_map() or {}
            folder_rev = {fid: path for path, fid in folder_path_map.items()}

            out_filters = [
                self._export_rule(rule, id_to_name, folder_rev)
                for rule in rules
            ]

            out_path = self._write_export_file(payload.out_path, out_filters)

            return ResultEnvelope(
                status="success",
                payload=OutlookRulesExportResult(count=len(out_filters), out_path=out_path),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )

    def _export_rule(
        self, rule: Dict[str, Any], id_to_name: Dict[str, str], folder_rev: Dict[str, str]
    ) -> Dict[str, Any]:
        """Convert a rule to export format."""
        crit = rule.get("criteria") or {}
        act = rule.get("action") or {}

        entry = {"match": self._extract_criteria(crit)}
        action = self._extract_action(act, id_to_name, folder_rev)
        if action:
            entry["action"] = action

        return entry

    def _extract_criteria(self, criteria: Dict[str, Any]) -> Dict[str, Any]:
        """Extract match criteria from rule."""
        match = {}
        for k in ("from", "to", "subject"):
            val = criteria.get(k)
            if val:
                match[k] = val
        return match

    def _extract_action(
        self, action: Dict[str, Any], id_to_name: Dict[str, str], folder_rev: Dict[str, str]
    ) -> Dict[str, Any]:
        """Extract action from rule."""
        result = {}

        add_ids = action.get("addLabelIds") or []
        if add_ids:
            result["add"] = [id_to_name.get(i) or i for i in add_ids]

        forward = action.get("forward")
        if forward:
            result["forward"] = forward

        move_id = action.get("moveToFolderId")
        if move_id:
            result["moveToFolder"] = folder_rev.get(move_id) or move_id

        return result

    def _write_export_file(self, out_path: str, filters: List[Dict[str, Any]]) -> str:
        """Write filters to YAML file."""
        from ..config_resolver import expand_path
        from ..yamlio import dump_config

        data = {"filters": filters}
        outp = Path(expand_path(out_path))
        outp.parent.mkdir(parents=True, exist_ok=True)
        dump_config(str(outp), data)
        return str(outp)


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

            created, desired_keys = self._create_desired_rules(
                desired, existing, client, name_to_id, folder_path_map, payload
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

    def _create_desired_rules(
        self,
        desired: List[Dict[str, Any]],
        existing: Dict[str, Any],
        client: Any,
        name_to_id: Dict[str, str],
        folder_path_map: Dict[str, str],
        payload: OutlookRulesSyncPayload,
    ) -> Tuple[int, set]:
        """Create rules from desired specs that don't exist.

        Returns:
            Tuple of (created_count, desired_keys_set)
        """
        created = 0
        desired_keys: set = set()
        ctx = RuleContext(
            client=client,
            name_to_id=name_to_id,
            folder_map=folder_path_map,
            move_to_folders=payload.move_to_folders,
        )

        for spec in desired:
            m = spec.get("match") or {}
            a_act = spec.get("action") or {}
            criteria = _build_rule_criteria(m)
            if not criteria:
                continue

            action = _build_rule_action(a_act, ctx)
            key = _create_rule_key(criteria, action)
            desired_keys.add(key)

            if key in existing:
                continue

            if not payload.dry_run:
                try:
                    client.create_filter(criteria, action)
                except Exception:  # nosec B110 - filter creation failure logged elsewhere
                    pass
            created += 1

        return created, desired_keys

    def _delete_missing_rules(
        self, existing: Dict[str, Any], desired_keys: set, payload: OutlookRulesSyncPayload
    ) -> int:
        """Delete rules that are not in desired set.

        Args:
            existing: Map of canonical rule keys to rule objects
            desired_keys: Set of canonical keys for desired rules
            payload: Sync request payload

        Returns:
            Number of rules deleted
        """
        deleted = 0
        for k, rule in existing.items():
            if k not in desired_keys:
                rid = rule.get("id")
                if not payload.dry_run and rid:
                    try:
                        payload.client.delete_filter(rid)
                        deleted += 1
                    except Exception:  # nosec B110 - filter deletion failure
                        pass
                else:
                    deleted += 1
        return deleted


class OutlookRulesPlanProcessor(Processor[OutlookRulesPlanPayload, ResultEnvelope[OutlookRulesPlanResult]]):
    """Plan Outlook inbox rules sync (dry-run)."""

    def process(self, payload: OutlookRulesPlanPayload) -> ResultEnvelope[OutlookRulesPlanResult]:
        try:
            from ..yamlio import load_config
            from ..dsl import normalize_filters_for_outlook

            client = payload.client
            doc = load_config(payload.config_path)
            desired = normalize_filters_for_outlook(doc.get("filters") or [])

            existing = self._fetch_existing_rules(client, payload.use_cache, payload.cache_ttl)
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

    def _fetch_existing_rules(
        self, client: Any, use_cache: bool, cache_ttl: int
    ) -> List[Dict[str, Any]]:
        """Fetch existing rules with fallback."""
        try:
            return client.list_filters(use_cache=use_cache, ttl=cache_ttl)
        except Exception:
            try:
                return client.list_filters(use_cache=True, ttl=cache_ttl)
            except Exception:
                return []

    def _build_plan_items(
        self,
        desired: List[Dict[str, Any]],
        existing_keys: set,
        name_to_id: Dict[str, str],
        folder_map: Dict[str, str],
        move_to_folders: bool,
    ) -> List[str]:
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
        desired: List[Dict[str, Any]],
        folder_paths: Dict[str, str],
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
    ) -> List[str]:
        """Search for messages matching query."""
        from core.outlook.mail import SearchParams
        try:
            return client.search_inbox_messages(
                SearchParams(
                    search_query=query,
                    days=payload.days,
                    top=payload.top,
                    pages=payload.pages,
                    use_cache=not payload.clear_cache,
                )
            )
        except Exception:
            return client.search_inbox_messages(
                SearchParams(
                    search_query=query,
                    days=None,
                    top=payload.top,
                    pages=payload.pages,
                    use_cache=not payload.clear_cache,
                )
            )

    def _move_messages(
        self, client: Any, message_ids: List[str], dest_id: str, dry_run: bool
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


class OutlookCategoriesListProcessor(Processor[OutlookCategoriesListPayload, ResultEnvelope[OutlookCategoriesListResult]]):
    """List Outlook categories."""

    def process(self, payload: OutlookCategoriesListPayload) -> ResultEnvelope[OutlookCategoriesListResult]:
        try:
            cats = payload.client.list_labels(use_cache=payload.use_cache, ttl=payload.cache_ttl)
            return ResultEnvelope(
                status="success",
                payload=OutlookCategoriesListResult(categories=cats),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )


class OutlookCategoriesExportProcessor(Processor[OutlookCategoriesExportPayload, ResultEnvelope[OutlookCategoriesExportResult]]):
    """Export Outlook categories to YAML."""

    def process(self, payload: OutlookCategoriesExportPayload) -> ResultEnvelope[OutlookCategoriesExportResult]:
        try:
            cats = payload.client.list_labels(use_cache=payload.use_cache, ttl=payload.cache_ttl)
            labels = []
            for c in cats:
                entry = {"name": c.get("name", "")}
                col = c.get("color")
                if isinstance(col, dict) and col.get("name"):
                    entry["color"] = {"name": col.get("name")}
                labels.append(entry)

            data = {"labels": labels}
            outp = Path(payload.out_path)
            outp.parent.mkdir(parents=True, exist_ok=True)
            from ..yamlio import dump_config
            dump_config(str(outp), data)

            return ResultEnvelope(
                status="success",
                payload=OutlookCategoriesExportResult(count=len(labels), out_path=str(outp)),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )


class OutlookCategoriesSyncProcessor(Processor[OutlookCategoriesSyncPayload, ResultEnvelope[OutlookCategoriesSyncResult]]):
    """Sync Outlook categories from YAML config."""

    def process(self, payload: OutlookCategoriesSyncPayload) -> ResultEnvelope[OutlookCategoriesSyncResult]:
        try:
            from ..yamlio import load_config
            from ..dsl import normalize_labels_for_outlook

            client = payload.client
            doc = load_config(payload.config_path)
            labels = doc.get("labels") or []

            validation_error = self._validate_labels(labels)
            if validation_error:
                return validation_error

            desired = normalize_labels_for_outlook(labels)
            existing = {c.get("name"): c for c in client.list_labels()}

            created, skipped = self._sync_categories(desired, existing, client, payload.dry_run)

            return ResultEnvelope(
                status="success",
                payload=OutlookCategoriesSyncResult(created=created, skipped=skipped),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )

    def _validate_labels(self, labels: Any) -> ResultEnvelope[OutlookCategoriesSyncResult] | None:
        """Validate labels structure."""
        if not isinstance(labels, list):
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": "Labels YAML must contain a labels: [] list", "code": 2},
            )
        return None

    def _sync_categories(
        self,
        desired: List[Any],
        existing: Dict[str, Any],
        client: Any,
        dry_run: bool,
    ) -> Tuple[int, int]:
        """Sync categories and return (created, skipped) counts."""
        created = 0
        skipped = 0

        for entry in desired:
            name = self._extract_category_name(entry)
            if not name:
                continue

            if name in existing:
                skipped += 1
                continue

            if self._create_category(entry, name, client, dry_run):
                created += 1

        return created, skipped

    def _extract_category_name(self, entry: Any) -> str | None:
        """Extract category name from entry."""
        if isinstance(entry, dict):
            return entry.get("name")
        return entry

    def _create_category(
        self, entry: Any, name: str, client: Any, dry_run: bool
    ) -> bool:
        """Create a category if not dry run."""
        if dry_run:
            return True

        try:
            color = entry.get("color") if isinstance(entry, dict) else None
            client.create_label(name, color=color)
            return True
        except Exception:  # nosec B110 - category creation failure
            return False


class OutlookFoldersSyncProcessor(Processor[OutlookFoldersSyncPayload, ResultEnvelope[OutlookFoldersSyncResult]]):
    """Sync Outlook folders from YAML config."""

    def process(self, payload: OutlookFoldersSyncPayload) -> ResultEnvelope[OutlookFoldersSyncResult]:
        try:
            from ..yamlio import load_config

            client = payload.client
            doc = load_config(payload.config_path)
            labels = doc.get("labels") or []

            validation_error = self._validate_labels(labels)
            if validation_error:
                return validation_error

            path_map = client.get_folder_path_map()
            created, skipped = self._sync_folders(labels, path_map, client, payload.dry_run)

            return ResultEnvelope(
                status="success",
                payload=OutlookFoldersSyncResult(created=created, skipped=skipped),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )

    def _validate_labels(self, labels: Any) -> ResultEnvelope[OutlookFoldersSyncResult] | None:
        """Validate labels structure."""
        if not isinstance(labels, list):
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": "Labels YAML must contain a labels: [] list", "code": 2},
            )
        return None

    def _sync_folders(
        self,
        labels: List[Any],
        path_map: Dict[str, str],
        client: Any,
        dry_run: bool,
    ) -> Tuple[int, int]:
        """Sync folders and return (created, skipped) counts."""
        created = 0
        skipped = 0

        for entry in labels:
            name = self._extract_folder_name(entry)
            if not name:
                continue

            if self._should_skip_folder(name, path_map):
                skipped += 1
                continue

            if self._create_folder(name, path_map, client, dry_run):
                created += 1

        return created, skipped

    def _extract_folder_name(self, entry: Any) -> str | None:
        """Extract folder name from entry."""
        if isinstance(entry, dict):
            return entry.get("name")
        if isinstance(entry, str):
            return entry
        return None

    def _should_skip_folder(self, name: str, path_map: Dict[str, str]) -> bool:
        """Check if folder should be skipped."""
        if str(name).startswith("["):
            return True
        if name in path_map:
            return True
        return False

    def _create_folder(
        self, name: str, path_map: Dict[str, str], client: Any, dry_run: bool
    ) -> bool:
        """Create folder if not dry run."""
        if dry_run:
            return True

        fid = client.ensure_folder_path(name)
        if fid:
            path_map[name] = fid
            return True
        return False


class OutlookCalendarAddProcessor(Processor[OutlookCalendarAddPayload, ResultEnvelope[OutlookCalendarAddResult]]):
    """Add a calendar event."""

    def process(self, payload: OutlookCalendarAddPayload) -> ResultEnvelope[OutlookCalendarAddResult]:
        try:
            evt = payload.client.create_event(EventCreationParams(
                calendar_name=payload.calendar_name,
                subject=payload.subject,
                start_iso=payload.start_iso,
                end_iso=payload.end_iso,
                tz=payload.tz,
                body_html=payload.body_html,
                all_day=payload.all_day,
                location=payload.location,
                no_reminder=payload.no_reminder,
            ))
            return ResultEnvelope(
                status="success",
                payload=OutlookCalendarAddResult(
                    event_id=evt.get("id", ""),
                    subject=evt.get("subject", ""),
                ),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 3},
            )


class OutlookCalendarAddRecurringProcessor(Processor[OutlookCalendarAddRecurringPayload, ResultEnvelope[OutlookCalendarAddRecurringResult]]):
    """Add a recurring calendar event."""

    def process(self, payload: OutlookCalendarAddRecurringPayload) -> ResultEnvelope[OutlookCalendarAddRecurringResult]:
        try:
            evt = payload.client.create_recurring_event(RecurringEventCreationParams(
                calendar_name=payload.calendar_name,
                subject=payload.subject,
                start_time=payload.start_time,
                end_time=payload.end_time,
                tz=payload.tz,
                repeat=payload.repeat,
                interval=payload.interval,
                byday=payload.byday,
                range_start_date=payload.range_start,
                range_until=payload.until,
                count=payload.count,
                body_html=payload.body_html,
                location=payload.location,
                exdates=payload.exdates,
                no_reminder=payload.no_reminder,
            ))
            return ResultEnvelope(
                status="success",
                payload=OutlookCalendarAddRecurringResult(
                    event_id=evt.get("id", ""),
                    subject=evt.get("subject", ""),
                ),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 3},
            )


class OutlookCalendarAddFromConfigProcessor(Processor[OutlookCalendarAddFromConfigPayload, ResultEnvelope[OutlookCalendarAddFromConfigResult]]):
    """Add calendar events from a config file."""

    def process(self, payload: OutlookCalendarAddFromConfigPayload) -> ResultEnvelope[OutlookCalendarAddFromConfigResult]:
        try:
            from ..yamlio import load_config

            cfg = load_config(payload.config_path)
            items = cfg.get("events") if isinstance(cfg, dict) else None
            if not isinstance(items, list):
                return ResultEnvelope(
                    status="error",
                    payload=None,
                    diagnostics={"error": "Config must contain events: [] list", "code": 2},
                )

            created = self._create_events_from_config(items, payload.client, payload.no_reminder)

            return ResultEnvelope(
                status="success",
                payload=OutlookCalendarAddFromConfigResult(created=created),
            )
        except Exception as exc:
            return ResultEnvelope(
                status="error",
                payload=None,
                diagnostics={"error": str(exc), "code": 1},
            )

    def _create_events_from_config(
        self, events: List[Dict[str, Any]], client: Any, no_reminder: bool
    ) -> int:
        """Create events from config list."""
        created = 0
        for ev in events:
            if not isinstance(ev, dict):
                continue
            subj = ev.get("subject")
            if not subj:
                continue

            if ev.get("repeat"):
                if self._create_recurring_event(ev, client, no_reminder):
                    created += 1
            else:
                if self._create_single_event(ev, client, no_reminder):
                    created += 1

        return created

    def _create_recurring_event(self, ev: Dict[str, Any], client: Any, no_reminder: bool) -> bool:
        """Create a recurring event from config dict."""
        try:
            client.create_recurring_event(RecurringEventCreationParams(
                calendar_name=ev.get("calendar"),
                subject=ev.get("subject") or "",
                start_time=ev.get("start_time") or ev.get("startTime") or ev.get("start-time") or "",
                end_time=ev.get("end_time") or ev.get("endTime") or ev.get("end-time") or "",
                tz=ev.get("tz"),
                repeat=ev.get("repeat") or "",
                interval=int(ev.get("interval", 1)),
                byday=ev.get("byday") or ev.get("byDay"),
                range_start_date=(ev.get("range", {}) or {}).get("start_date") or ev.get("start_date") or ev.get("startDate") or "",
                range_until=(ev.get("range", {}) or {}).get("until") or ev.get("until"),
                count=ev.get("count"),
                body_html=ev.get("body_html") or ev.get("bodyHtml"),
                location=ev.get("location"),
                exdates=ev.get("exdates") or ev.get("exceptions") or [],
                no_reminder=no_reminder,
            ))
            return True
        except Exception:  # nosec B110 - recurring event creation failure
            return False

    def _create_single_event(self, ev: Dict[str, Any], client: Any, no_reminder: bool) -> bool:
        """Create a single event from config dict."""
        start_iso = ev.get("start")
        end_iso = ev.get("end")
        if not (start_iso and end_iso):
            return False

        try:
            client.create_event(EventCreationParams(
                calendar_name=ev.get("calendar"),
                subject=ev.get("subject") or "",
                start_iso=start_iso,
                end_iso=end_iso,
                tz=ev.get("tz"),
                body_html=ev.get("body_html") or ev.get("bodyHtml"),
                all_day=bool(ev.get("all_day") or ev.get("allDay")),
                location=ev.get("location"),
                no_reminder=no_reminder,
            ))
            return True
        except Exception:  # nosec B110 - event creation failure
            return False
