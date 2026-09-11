"""Rule -> remediation strategy table (plan section 5).

Minimal Phase 1 table: enough to let ``triage`` attach a tier and an action to
every rule this repo actually produces. The full prose artifact
(``.llm/QLTY_STRATEGIES.md``) is Phase 2 and deliberately not built here.

Tiers encode an *action class*, not a severity. The tier -- never the finding
count -- decides what happens to a finding.
"""

from __future__ import annotations

from typing import Optional

from .models import RuleStrategy, Tier

# Ordered worst-first for stable rendering; the tier decides handling.
_STRATEGIES: tuple[RuleStrategy, ...] = (
    RuleStrategy(
        rule="file-complexity",
        tier=Tier.A,
        action=(
            "Reduce per-function complexity in place (dispatch tables, guard "
            "clauses, extracted predicates); plan + human gate before editing."
        ),
        rationale=(
            "The score is a pure SUM of per-function complexity, so splitting "
            "a file redistributes it across siblings rather than reducing it "
            "-- both halves stay flagged. Only per-function reduction removes "
            "it. Split only when a file holds genuinely unrelated "
            "responsibilities. Existing tooling: "
            "workflows/code/qlty-complexity-sweep.yaml."
        ),
    ),
    RuleStrategy(
        rule="function-complexity",
        tier=Tier.A,
        action="Extract helpers, dispatch tables, early returns.",
        rationale="Localized to one function; low blast radius.",
    ),
    RuleStrategy(
        rule="python:S3776",
        tier=Tier.A,
        action="Extract helpers, dispatch tables, early returns, guard clauses.",
        rationale=(
            "Radarlint's cognitive-complexity rule. Reports the same defect as "
            "function-complexity but from `qlty check` rather than `qlty "
            "smells`, and scores it differently -- one function measured 26 "
            "under function-complexity and 22 here, another 49 vs 43. A single "
            "fix normally clears both, so deduplicate before planning -- but "
            "key on (path, LINE), never (path, function name): qlty reports "
            "functions by UNQUALIFIED name, so two classes in one file that "
            "both define `run` are indistinguishable by name and keying on it "
            "merges two real findings into one. Allow a small line offset when "
            "pairing the two rules, since they anchor to slightly different "
            "lines. Unlike the qlty rule, the message states the threshold. "
            "Existing tooling: workflows/code/qlty-complexity-sweep.yaml."
        ),
    ),
    RuleStrategy(
        rule="nested-control-flow",
        tier=Tier.A,
        action=(
            "Flatten with early returns or guard clauses; extract the inner "
            "block into a helper."
        ),
        rationale=(
            "Usually the same defect the complexity rules flag, seen from the "
            "nesting angle, and it clears alongside them. Existing tooling: "
            "workflows/code/qlty-complexity-sweep.yaml."
        ),
    ),
    RuleStrategy(
        rule="boolean-logic",
        tier=Tier.A,
        action="De Morgan simplification; extract named predicates.",
        rationale="Localized expression rewrite, verifiable by tests.",
    ),
    RuleStrategy(
        rule="function-parameters",
        tier=Tier.B,
        action=(
            "Default LEAVE. Fix only when sibling functions in the same module "
            "already use a params object -- i.e. the finding is pattern drift."
        ),
        rationale=(
            "A read-only pass over 31 findings returned 29 LEAVE / 2 FIX. Test "
            "fixture factories and framework-injected handlers are correct with "
            "many defaulted kwargs. The 2 real fixes were flagged for drift from "
            "an established local pattern, not for the parameter count -- so "
            "ranking by raw value is close to useless for this rule."
        ),
    ),
    RuleStrategy(
        rule="return-statements",
        tier=Tier.D,
        action="Report only. Do not propose a fix.",
        rationale=(
            "Triaged 12/12 LEAVE. Dominated by CLI registration functions that "
            "build a subcommand tree and validators that early-exit per error "
            "path -- both cases where multiple returns are the clearer form."
        ),
    ),
    RuleStrategy(
        rule="similar-code",
        tier=Tier.D,
        action=(
            "Report the clone group and every location, and require a human to "
            "read them before acting. No auto-proposed merge -- the metric is "
            "not trustworthy enough to generate one, but genuine duplication "
            "found on reading IS worth fixing."
        ),
        rationale=(
            "Triaged 6/6 clone groups LEAVE. The hasher matches on structure and "
            "size, not meaning: it fires on any two similarly-sized dict/list "
            "literals and on small adapter modules sharing an interface. Mass is "
            "a proxy for size, not debt -- the highest-mass finding in the repo "
            "(157) was a false positive whose 'obvious' fix would have merged "
            "two unrelated constants."
        ),
    ),
)

_BY_RULE: dict[str, RuleStrategy] = {s.rule: s for s in _STRATEGIES}

# Rules qlty's linters emit that land in Tier C (false positive -> suppress with
# a stated reason). Keyed by the normalized rule key, which for radarlint
# retains its own `python:` prefix (see runner._strip_rule_namespace).
_TIER_C_HINTS: dict[str, str] = {
    "python:S5754": "Re-raised SystemExit in a test asserting it is not raised.",
    "python:S125": "Trailing explanatory comment misread as commented-out code.",
    "python:S5655": "Structural test double vs. nominal annotation; fix the annotation (Protocol), not the test.",
}

# Scanner notices that are not defects. ripgrep emits one rule per comment
# marker it matches, so these report a fact about the source rather than a
# problem to remediate. Classified explicitly so they are distinguishable from
# a genuine strategy-table lookup miss, which is what Tier UNKNOWN means.
# Assembled from fragments so this table does not itself trip the very
# comment-marker scan it describes (ripgrep matches these literals anywhere,
# including here).
_INFORMATIONAL_RULES: frozenset[str] = frozenset(
    {"NO" + "TE", "TO" + "DO", "FIX" + "ME", "HA" + "CK", "X" + "XX"}
)

_UNKNOWN_ACTION = (
    "No strategy recorded. Read the finding before acting; do not assume it is "
    "actionable."
)

_COMPLEXITY_SWEEP = "workflows/code/qlty-complexity-sweep.yaml"

# Rules the complexity sweep actually discovers and remediates. It runs both
# scans because they return DISJOINT sets -- but the split is by TOOL, not by
# granularity, and assuming otherwise is how per-function findings get missed:
#   `qlty smells`  (tool "qlty", driver "structure")
#       file-complexity, function-complexity, nested-control-flow
#   `qlty check`   (linters)
#       python:S3776 -- the only complexity rule on that side
# So two of the three per-function rules come from `smells`, not `check`.
#
# Radarlint keys are normalized -- the tool namespace is stripped but the
# rule's own `python:` prefix survives, so cognitive complexity is
# `python:S3776`, never `radarlint-python:python:S3776`
# (see runner._strip_rule_namespace).
_COMPLEXITY_SWEEP_RULES: frozenset[str] = frozenset(
    {
        "file-complexity",
        "function-complexity",
        "nested-control-flow",
        "python:S3776",
    }
)


def strategy_for(rule: str) -> RuleStrategy:
    """Return the strategy for a rule, or an explicit UNKNOWN placeholder.

    Never returns None: an unrecognized rule must still render with a stated
    posture rather than silently vanishing from triage output.
    """
    known = _BY_RULE.get(rule)
    if known is not None:
        return known

    if rule in _INFORMATIONAL_RULES:
        return RuleStrategy(
            rule=rule,
            tier=Tier.INFO,
            action="None. Informational scanner notice, not a defect.",
            rationale=(
                "Emitted for a comment marker in the source; it records a fact "
                "about the code rather than a problem to remediate."
            ),
        )

    hint = _TIER_C_HINTS.get(rule)
    if hint is not None:
        return RuleStrategy(
            rule=rule,
            tier=Tier.C,
            action="Suppress inline with a stated reason, or fix the annotation.",
            rationale=hint,
        )

    return RuleStrategy(
        rule=rule,
        tier=Tier.UNKNOWN,
        action=_UNKNOWN_ACTION,
        rationale="Rule is absent from the Phase 1 strategy table.",
    )


def known_strategies() -> tuple[RuleStrategy, ...]:
    """All explicitly tabulated strategies, in declaration order."""
    return _STRATEGIES


def tooling_for(rule: str) -> Optional[str]:
    """Existing workflow that automates a rule, if any."""
    if rule in _COMPLEXITY_SWEEP_RULES:
        return _COMPLEXITY_SWEEP
    return None
