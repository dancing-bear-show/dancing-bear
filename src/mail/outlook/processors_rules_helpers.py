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



def _norm_criteria_field(value: str | None) -> tuple[str, ...] | None:
    """Normalise one criteria field for case-insensitive, order-insensitive comparison.

    Live rules store criteria in UPPERCASE; desired rules use lowercase from the
    derive step. Outlook also permits inconsistent whitespace around the OR
    separator. This function returns a sorted tuple of case-folded tokens so
    both sides compare equal regardless of case or token order.

    Returns None when value is None so the outer key stays None-comparable.
    """
    if value is None:
        return None
    return tuple(sorted(tok.strip().casefold() for tok in value.split(" OR ")))


def _criteria_key(criteria: dict[str, Any]) -> str:
    """Create a criteria-only key for reconciliation matching.

    Used alongside ``_canon_rule`` / ``_create_rule_key`` for the
    ``--reconcile`` path only.  Matching by criteria alone lets a rule whose
    action changed be recognised as the same rule rather than a new one.

    Case-insensitive: live rules store criteria in UPPERCASE; desired rules use
    lowercase from the derive step.  ``_norm_criteria_field`` case-folds and
    sorts the OR-joined token list so both sides compare equal.

    Do NOT use this for the non-reconcile path — it intentionally ignores the
    action, which is incorrect for the default behaviour where an action change
    is treated as a new rule.
    """
    return str({
        "from": _norm_criteria_field(criteria.get("from")),
        "to": _norm_criteria_field(criteria.get("to")),
        "subject": _norm_criteria_field(criteria.get("subject")),
    })


def _fetch_rules_with_resilience(
    client: Any,
    use_cache: bool = False,
    cache_ttl: int = 600,
) -> list[dict[str, Any]]:
    """Fetch existing rules with auth error handling and cache fallback.

    Auth failures (401/403) propagate; any other error falls back to a cached
    read so a transient outage does not look like an empty rule set.
    """
    try:
        return client.list_filters(use_cache=use_cache, ttl=cache_ttl)
    except Exception as e:
        resp = getattr(e, 'response', None)
        status = getattr(resp, 'status_code', None) if resp else None
        if status in (401, 403):
            raise
        try:
            return client.list_filters(use_cache=True, ttl=cache_ttl)
        except Exception:
            return []


def _build_rule_criteria(match_spec: dict[str, Any]) -> dict[str, Any]:
    """Build criteria dict from match spec."""
    return {k: v for k, v in match_spec.items() if k in ("from", "to", "subject") and v}


def _build_rule_action(action_spec: dict[str, Any], ctx: RuleContext) -> dict[str, Any]:
    """Build action dict from action spec.

    ``noMoveToFolder`` is an internal marker written by the derive step for rules
    that carried ``keepInInbox: true`` in the unified config.  It signals that
    the rule must categorise/label mail without moving it, even when
    ``ctx.move_to_folders`` is True.  The marker is read here but never written
    to the output ``action`` dict — it must not appear in the Graph API payload.
    """
    action = {}
    add_labs = action_spec.get("add") or []

    if action_spec.get("moveToFolder"):
        fid = ctx.client.ensure_folder_path(str(action_spec.get("moveToFolder")))
        action["moveToFolderId"] = fid
    elif ctx.move_to_folders and add_labs and not action_spec.get("noMoveToFolder"):
        # Normal rule with move_to_folders: derive folder from first add label.
        lab_name = str(add_labs[0])
        fid = ctx.folder_map.get(lab_name) or ctx.client.ensure_folder_path(lab_name)
        action["moveToFolderId"] = fid
    elif add_labs:
        # Categorise only: either noMoveToFolder (keepInInbox) or move_to_folders=False.
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


def _resolve_folder_id(path: str, folder_map: dict[str, str]) -> str:
    """Resolve a folder path to an id for planning, by raw path only.

    The raw path is what ``_build_rule_action`` passes to
    ``ensure_folder_path()``, so matching it is what keeps the plan's rule key
    equal to apply's. Normalizing first turned ``Security/Alerts`` into
    ``Security-Alerts``, matched nothing, and left that string to be used as the
    folder id — the plan then reported an existing rule as "Would create" with
    the wrong destination displayed.

    The normalized alias is tried **only for a flat name**, where normalization
    is a no-op. For a nested path it is unsafe: ``Security/Alerts`` flattens to
    ``Security-Alerts``, which may be a genuinely different, top-level folder.
    Resolving to that folder's id would make the plan name a destination apply
    never touches — a wrong answer, where a miss is merely an unresolved one.

    Falling back to the path itself keeps planning possible when the map has no
    entry (apply would create the folder); it is not a Graph id, so a caller
    comparing keys against live rules still sees a difference rather than a
    false match.
    """
    if path in folder_map:
        return folder_map[path]
    if "/" not in path:
        alias = norm_label_name_outlook(path)
        if alias in folder_map:
            return folder_map[alias]
    return path


def _build_plan_action(action_spec: dict[str, Any], ctx: RuleContext) -> dict[str, Any]:
    """Build action dict for plan (without creating folders).

    ``noMoveToFolder: true`` is the internal marker set by the derive step for
    rules that had ``keepInInbox: true`` in the unified config.  When present,
    the folder derivation branch is skipped and the rule categorises/labels
    without a folder move.

    An explicit ``moveToFolder`` still wins over the marker, matching
    ``_build_rule_action`` and ``_resolve_destination_folder``: the marker
    suppresses a folder *derived* from ``add[0]``, not a destination the config
    named outright. The two can legitimately co-occur — ``derive.filters
    --outlook-archive-on-remove-inbox`` emits ``moveToFolder: Archive``
    alongside the marker. This branch was previously absent here, so the plan
    reported "no move" for a rule that sync and sweep would move: the plan
    contradicted the apply it is supposed to preview.
    """
    action = {}
    adds = action_spec.get("add") or []

    if action_spec.get("moveToFolder"):
        action["moveToFolderId"] = _resolve_folder_id(
            str(action_spec["moveToFolder"]), ctx.folder_map
        )
    elif ctx.move_to_folders and adds and not action_spec.get("noMoveToFolder"):
        # Derive from the first add label — raw path first, for the same reason
        # as the explicit branch above. `add: [Lists/Commercial]` in a raw
        # config is a nested path, and `_build_rule_action` resolves that raw
        # value, so normalizing first here made the plan key diverge from
        # apply's for every nested rule.
        action["moveToFolderId"] = _resolve_folder_id(str(adds[0]), ctx.folder_map)
    elif adds:
        # Categorise only: either noMoveToFolder (keepInInbox) or move_to_folders=False.
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
    """Resolve destination folder ID for sweep operation.

    Returns None for rules that carry ``noMoveToFolder: true``, which is the
    internal marker set by the derive step for rules that had ``keepInInbox``
    in the unified config.  Returning None causes the sweep loop to skip the
    move step, leaving the message in the inbox.

    Dry-run resolves through the cached ``folder_paths`` snapshot because the
    live call, ``ensure_folder_path``, *creates* missing folders — a preview
    must not mutate the mailbox.  A cache miss therefore falls back to the path
    itself rather than None: the sweep loop only tests truthiness to decide
    whether a move happens, and returning None for a folder the live run would
    resolve made ``sweep --dry-run`` report zero moves while the real run moved
    mail.  The returned value is not a Graph id, but nothing in the dry-run path
    sends it anywhere.
    """
    if action_spec.get("moveToFolder"):
        pth = str(action_spec.get("moveToFolder"))
        if dry_run:
            return folder_paths.get(pth) or pth
        return client.ensure_folder_path(pth)

    # noMoveToFolder is the internal marker for keepInInbox rules: no move wanted.
    if action_spec.get("noMoveToFolder"):
        return None

    if move_to_folders and (action_spec.get("add") or []):
        pth = str((action_spec.get("add") or ["Inbox"])[0])
        if dry_run:
            return folder_paths.get(pth) or pth
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
