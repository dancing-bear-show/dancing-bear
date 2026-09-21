"""Helper and builder functions for Outlook rules processors."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .helpers import norm_label_name_outlook


# Context dataclasses

@dataclass
class RuleContext:
    """Shared context for rule building operations.

    ``dry_run`` exists because folder resolution can MUTATE: the fallback in
    ``_build_rule_action`` is ``ensure_folder_path``, which creates missing
    folders via Graph.  Without this flag the resolver had no way to know it was
    running under a preview, so ``rules.sync --dry-run`` created folders whenever
    the cached folder map missed an ``add`` destination -- no rule was created,
    but the mailbox changed.  Defaults False so every existing construction keeps
    today's behaviour; the sync processor passes its own ``dry_run`` through.
    """
    client: Any
    name_to_id: dict[str, str]
    folder_map: dict[str, str]
    move_to_folders: bool
    dry_run: bool = False

    @classmethod
    def for_plan(
        cls,
        name_to_id: dict[str, str],
        folder_map: dict[str, str],
        move_to_folders: bool,
        client: Any = None,
    ) -> "RuleContext":
        """Create context for plan operations.

        ``dry_run=True`` always: plan is read-only by definition, so folder
        resolution must never reach the mutating ``ensure_folder_path``.

        ``client`` is optional and used only for NON-mutating lookups
        (``resolve_folder_path``).  It was omitted entirely at first, on the
        reasoning that plan needs no client -- but that forced plan to fall back
        to the folder path string whenever the cached snapshot missed, while the
        apply resolved the real Graph id.  The two then keyed the same rule
        differently and plan reported ``Would create`` for a rule sync treated as
        a no-op.  Passing a read-only client is what closes that gap; ``dry_run``
        still guarantees nothing is created.
        """
        return cls(
            client=client, name_to_id=name_to_id, folder_map=folder_map,
            move_to_folders=move_to_folders, dry_run=True,
        )


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


def _fetch_rules_with_provenance(
    client: Any,
    use_cache: bool = False,
    cache_ttl: int = 600,
) -> tuple[list[dict[str, Any]], str]:
    """Fetch existing rules, reporting where the data came from.

    Returns ``(rules, source)`` where ``source`` is one of:

    - ``"live"``     : the requested read succeeded.
    - ``"fallback"`` : the read failed and a cached snapshot was served instead.
    - ``"empty"``    : both reads failed; the list is ``[]`` and means "unknown",
      NOT "the mailbox has no rules".

    Auth failures (401/403) still propagate -- a credential problem must not be
    papered over with cached data.

    Callers that only display rules can ignore ``source``.  Callers that MUTATE
    must not: ``--reconcile`` decides what to delete by comparing desired rules
    against this list, so acting on ``"empty"`` creates a duplicate of every rule
    beside live rules it cannot see, and acting on ``"fallback"`` can delete
    against IDs that no longer exist.  Both were probed on PR #359:

        total failure -> created=2, status=success, 0 rules ever read
        stale cache   -> delete_filter('OLD-ID-no-longer-exists')
    """
    try:
        return client.list_filters(use_cache=use_cache, ttl=cache_ttl), "live"
    except Exception as e:
        resp = getattr(e, 'response', None)
        status = getattr(resp, 'status_code', None) if resp else None
        if status in (401, 403):
            raise
        try:
            return client.list_filters(use_cache=True, ttl=cache_ttl), "fallback"
        except Exception:
            return [], "empty"


def _fetch_rules_with_resilience(
    client: Any,
    use_cache: bool = False,
    cache_ttl: int = 600,
) -> list[dict[str, Any]]:
    """Fetch existing rules with auth error handling and cache fallback.

    Thin wrapper over ``_fetch_rules_with_provenance`` for read-only callers,
    which cannot do harm with fallback data.  Anything that mutates the mailbox
    should call ``_fetch_rules_with_provenance`` and refuse to act on a
    non-``"live"`` source.
    """
    return _fetch_rules_with_provenance(client, use_cache, cache_ttl)[0]


def _build_rule_criteria(match_spec: dict[str, Any]) -> dict[str, Any]:
    """Build criteria dict from match spec."""
    return {k: v for k, v in match_spec.items() if k in ("from", "to", "subject") and v}


def _resolve_folder_for_action(path: str, ctx: RuleContext) -> str:
    """Resolve a folder path to an id, never creating a folder under dry-run.

    The live resolver is ``ensure_folder_path``, which CREATES missing folders via
    Graph.  ``_build_rule_action`` runs before the caller's ``dry_run`` check, so
    without this guard ``rules.sync --dry-run`` created folders whenever the cached
    folder map missed a destination: no rule was created, but the mailbox changed.

    Resolution order under a preview:

    1. the cached folder map, when it has the path;
    2. ``resolve_folder_path`` -- a LIVE lookup that creates nothing and returns
       ``""`` for a folder that genuinely does not exist;
    3. the path itself, when no client is available (``RuleContext.for_plan``
       passes ``client=None``) or the lookup found nothing.

    Step 2 is what keeps preview and apply in agreement.  Falling straight from a
    stale cache to the path string made both previews key the rule on
    ``'Archive/News'`` while the live run keyed it on the real Graph id, so
    ``plan`` and ``sync --dry-run`` reported ``Would create`` for a rule the apply
    treated as a no-op.  A folder that exists is now resolved to the same id both
    sides use; only a folder that does not exist yet falls through to the path,
    where "would create" is the honest answer.
    """
    if not ctx.dry_run:
        return ctx.client.ensure_folder_path(path)

    cached = ctx.folder_map.get(path)
    if cached:
        return cached

    resolver = getattr(ctx.client, "resolve_folder_path", None)
    if resolver is not None:
        try:
            live = resolver(path)
        except Exception:  # nosec B110 - preview must degrade, never fail the run
            live = ""
        if live:
            return live

    return path


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
        fid = _resolve_folder_for_action(str(action_spec.get("moveToFolder")), ctx)
        action["moveToFolderId"] = fid
    elif ctx.move_to_folders and add_labs and not action_spec.get("noMoveToFolder"):
        # Normal rule with move_to_folders: derive folder from first add label.
        lab_name = str(add_labs[0])
        fid = ctx.folder_map.get(lab_name) or _resolve_folder_for_action(lab_name, ctx)
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


def _norm_create_rule_key(criteria: dict[str, Any], action: dict[str, Any]) -> str:
    """Create a case-normalised canonical key for a rule.

    Identical to ``_create_rule_key`` except that the criteria fields are passed
    through ``_norm_criteria_field`` for case-insensitive, order-insensitive
    comparison.  Used to detect a live rule that already satisfies a desired spec
    where the only difference is criteria case (e.g. live stores UPPERCASE
    criteria, desired emits lowercase from the derive step).

    Action fields (addLabelIds, moveToFolderId, forward) are Graph ids or email
    addresses and are kept as-is; the case mismatch is criteria-specific.
    """
    return str({
        "from": _norm_criteria_field(criteria.get("from")),
        "to": _norm_criteria_field(criteria.get("to")),
        "subject": _norm_criteria_field(criteria.get("subject")),
        "add": tuple(sorted(action.get("addLabelIds", []) or [])),
        "forward": action.get("forward"),
        "move": action.get("moveToFolderId"),
    })


def _resolve_folder_id(path: str, folder_map: dict[str, str], client: Any = None) -> str:
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
    if client is not None:
        # Live, NON-mutating lookup before giving up on the path string. A folder
        # that exists but is absent from the cached snapshot (created after it)
        # otherwise left plan keying the rule on 'Archive/News' while apply keyed
        # it on the real Graph id -- plan reported "Would create" for a rule the
        # live run treated as a no-op. Probed on #359 and deferred from it.
        resolver = getattr(client, "resolve_folder_path", None)
        if resolver is not None:
            try:
                live = resolver(path)
            except Exception:  # nosec B110 - preview must degrade, never fail the run
                live = ""
            if live:
                return live
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
            str(action_spec["moveToFolder"]), ctx.folder_map, ctx.client
        )
    elif ctx.move_to_folders and adds and not action_spec.get("noMoveToFolder"):
        # Derive from the first add label — raw path first, for the same reason
        # as the explicit branch above. `add: [Lists/Commercial]` in a raw
        # config is a nested path, and `_build_rule_action` resolves that raw
        # value, so normalizing first here made the plan key diverge from
        # apply's for every nested rule.
        action["moveToFolderId"] = _resolve_folder_id(str(adds[0]), ctx.folder_map, ctx.client)
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
