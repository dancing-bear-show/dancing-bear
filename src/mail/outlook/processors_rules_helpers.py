"""Helper and builder functions for Outlook rules processors."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .helpers import norm_label_name_outlook


# Context dataclasses

@dataclass
class RuleContext:
    """Shared context for rule building operations."""
    client: Any
    name_to_id: dict[str, str]
    folder_map: dict[str, str]
    move_to_folders: bool

    @classmethod
    def for_plan(cls, name_to_id: dict[str, str], folder_map: dict[str, str], move_to_folders: bool) -> "RuleContext":
        """Create context for plan operations (no client needed)."""
        return cls(client=None, name_to_id=name_to_id, folder_map=folder_map, move_to_folders=move_to_folders)


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


def _fetch_rules_with_resilience(client: Any) -> list[dict[str, Any]]:
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


def _build_rule_criteria(match_spec: dict[str, Any]) -> dict[str, Any]:
    """Build criteria dict from match spec."""
    return {k: v for k, v in match_spec.items() if k in ("from", "to", "subject") and v}


def _build_rule_action(action_spec: dict[str, Any], ctx: RuleContext) -> dict[str, Any]:
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


def _create_rule_key(criteria: dict[str, Any], action: dict[str, Any]) -> str:
    """Create canonical key for a rule."""
    return str({
        "from": criteria.get("from"),
        "to": criteria.get("to"),
        "subject": criteria.get("subject"),
        "add": tuple(sorted(action.get("addLabelIds", []) or [])),
        "forward": action.get("forward"),
        "move": action.get("moveToFolderId"),
    })


def _build_plan_action(action_spec: dict[str, Any], ctx: RuleContext) -> dict[str, Any]:
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


def _format_plan_action(action: dict[str, Any], folder_map: dict[str, str]) -> dict[str, Any]:
    """Format action dict for plan display (resolve folder IDs to names)."""
    disp = dict(action)
    if action.get("moveToFolderId"):
        rev = {v: k for k, v in (folder_map or {}).items()}
        disp["moveToFolder"] = rev.get(action["moveToFolderId"], action["moveToFolderId"])
    return disp


def _build_search_query(match_spec: dict[str, Any]) -> str:
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
    action_spec: dict[str, Any],
    move_to_folders: bool,
    folder_paths: dict[str, str],
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


def _export_rule_entry(r: dict, id_to_name: dict, folder_rev: dict) -> dict:
    """Convert a raw rule to export format."""
    crit = r.get("criteria") or {}
    act = r.get("action") or {}
    entry: dict = {"match": {}}
    for k in ("from", "to", "subject"):
        if crit.get(k):
            entry["match"][k] = crit.get(k)
    a: dict = {}
    add_ids = act.get("addLabelIds") or []
    if add_ids:
        a["add"] = [id_to_name.get(i) or i for i in add_ids]
    if act.get("forward"):
        a["forward"] = act.get("forward")
    if act.get("moveToFolderId"):
        a["moveToFolder"] = folder_rev.get(act.get("moveToFolderId")) or act.get("moveToFolderId")
    if a:
        entry["action"] = a
    return entry
