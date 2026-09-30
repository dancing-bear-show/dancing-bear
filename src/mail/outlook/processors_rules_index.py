"""Reconcile index builders shared by the Outlook rules sync and plan processors."""
from __future__ import annotations

from typing import Any

from .processors_rules_helpers import _canon_rule, _criteria_key


# Live-rule and reconcile index builders.
#
# Module-level, and shared by both OutlookRulesSyncProcessor and
# OutlookRulesPlanProcessor, because plan and sync MUST classify every desired
# spec identically. Index logic that existed as one copy per processor is
# exactly the shape that lets preview and apply drift apart when only one copy
# is updated.

def _index_live_rules(rules: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Key live rules by ``_canon_rule``, the key desired specs are compared to.

    Known limitation: live rules sharing a canon key collapse to ONE entry, so
    the others are invisible to every later step -- neither matched, reconciled
    nor deleted (``--delete-missing`` under-deletes them).  Case-insensitive
    criteria make more rules collapse than raw-string keys did (``FROM=A.COM``
    and ``from=a.com`` with the same action now share a key).

    On a collision a rule carrying ``unmappedConditions`` wins over a mappable
    one.  Otherwise whichever sibling Graph listed last would win, and a hidden
    unmappable rule drops out of ``_build_unmappable_criteria_index``: reconcile
    would then rewrite its visible mappable sibling and leave the unmappable
    rule running beside the replacement.  Keeping it visible preserves the
    protection that index exists for.  Collapse only ever HIDES rules, so it
    cannot cause a deletion; the cost is under-deletion, never data loss.
    """
    index: dict[str, dict[str, Any]] = {}
    for rule in rules:
        key = _canon_rule(rule)
        current = index.get(key)
        if current is None or not current.get("unmappedConditions"):
            index[key] = rule
    return index


def _build_reconcile_index(existing: dict[str, Any]) -> dict[str, Any]:
    """Build a criteria-only index of live rules for reconciliation.

    The first live rule for each criteria key wins; later duplicates are
    skipped (their canon keys remain in ``existing`` and are eligible for
    ``--delete-missing``).  Entries are popped as they are matched, so the
    same live rule cannot be reconciled twice.

    Live rules carrying conditions this codebase cannot express are excluded
    entirely.  ``_criteria_key`` keys on from/to/subject only, so a UI-created
    rule that is ALSO scoped by ``bodyContains`` is indistinguishable here
    from a sender-only rule.  Reconcile recreates by delete+create from the
    mapped criteria, so rewriting such a rule silently drops the extra
    condition and the replacement matches *more* mail than the original --
    e.g. a rule for "from bank.example AND body contains 'wire transfer'"
    becomes one for every message from that sender.  Broadening a filter
    without being asked is the dangerous direction, so these rules are left
    exactly as they are: not reconciled, and (because their canon key stays
    in ``existing``) not silently rewritten by any other path either.
    """
    index: dict[str, Any] = {}
    for live_rule in existing.values():
        if live_rule.get("unmappedConditions"):
            continue
        ck = _criteria_key(live_rule.get("criteria") or {})
        if ck not in index:
            index[ck] = live_rule
    return index


def _build_unmappable_criteria_index(existing: dict[str, Any]) -> dict[str, list[str]]:
    """Map criteria key -> live rule ids, for rules that must not be touched.

    A live rule carrying Graph conditions this codebase cannot express (see
    ``_build_reconcile_index``) is excluded from the reconcile index so reconcile
    never rewrites it.  Two further protections are required, and both are easy
    to get wrong:

    1. The desired spec must not be created fresh.  With the live rule out of the
       reconcile index the spec finds no criteria match and would fall through to
       creation, adding a second, BROADER rule beside the protected one -- two
       rules acting on the same mail, when the user asked for one.

    2. The live rule must be protected from ``--delete-missing`` explicitly.
       Skipping the desired spec contributes no key to ``desired_keys``, and
       ``_delete_missing_rules`` deletes precisely those live rules whose canon
       key is absent from that set -- so skipping ALONE marks the rule stale and
       deletes it.  That is why this returns ids rather than a bare key set: the
       id goes into the protected set that ``--delete-missing`` honours.
    """
    index: dict[str, list[str]] = {}
    for rule in existing.values():
        if not rule.get("unmappedConditions"):
            continue
        rid = rule.get("id")
        if not rid:
            continue
        # EVERY matching id, not just the first. Two unmappable rules can share a
        # criteria key, and protection is per RULE: each one is individually
        # impossible to recreate faithfully, so keeping only the first would leave
        # the rest exposed to --delete-missing.
        index.setdefault(_criteria_key(rule.get("criteria") or {}), []).append(rid)
    return index


def _all_unmappable_ids(index: dict[str, list[str]] | None) -> set[str]:
    """Every protected id in an unmappable index, flattened.

    Seeded into the protected set before any desired spec is processed, so an
    unmappable rule is protected because it EXISTS rather than because some spec
    happened to reach the per-spec check.
    """
    if not index:
        return set()
    return {rid for ids in index.values() for rid in ids}
