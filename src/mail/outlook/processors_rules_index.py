"""Reconcile index builders shared by the Outlook rules sync and plan processors."""
from __future__ import annotations

from typing import Any

from .processors_rules_helpers import _criteria_key, _norm_create_rule_key


# Reconcile index builders.
#
# Module-level, and shared by both OutlookRulesSyncProcessor and
# OutlookRulesPlanProcessor, because plan and sync MUST classify every desired
# spec identically -- that parity is the invariant this PR keeps having to
# re-fix. `_build_norm_existing_keys` previously existed as two byte-identical
# copies, one per processor: exactly the shape that lets preview and apply drift
# apart when only one copy is updated.

def _build_norm_existing_keys(existing: dict[str, Any]) -> set[str]:
    """Case-normalised (criteria + action) keys of every live rule.

    Used in reconcile mode to detect a desired rule that already matches a live
    rule modulo criteria case: live rules store criteria UPPERCASE while derive
    emits lowercase.  A desired rule whose normalised key is in this set already
    has the correct action and must be left alone -- no delete, no create.
    """
    return {
        _norm_create_rule_key(
            r.get("criteria") or {},
            r.get("action") or {},
        )
        for r in existing.values()
    }


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
