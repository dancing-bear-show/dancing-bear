from __future__ import annotations

import fnmatch
from collections import defaultdict
from typing import Any

from telemetry.models import SessionEvent, Tip

# (waste_reason, blame level, blame name, classification)
_GroupKey = tuple[str, str, str, str]


def _is_actionable(event: SessionEvent) -> bool:
    """Return True when an event carries enough blame context to become a tip."""
    if event.classification not in ("avoidable", "review"):
        return False
    if event.blame_target is None:
        return False
    return event.waste_reason is not None


def _group_events(events: list[SessionEvent]) -> dict[_GroupKey, list[SessionEvent]]:
    """Bucket actionable events by (waste_reason, level, name, classification)."""
    groups: dict[_GroupKey, list[SessionEvent]] = defaultdict(list)
    for evt in events:
        bt = evt.blame_target
        if bt is None:
            continue
        key = (evt.waste_reason or "", bt.level, bt.name, evt.classification or "")
        groups[key].append(evt)
    return groups


def _format_message(
    severity: str, level: str, name: str, waste_reason: str, count: int, cost_impact: float
) -> str:
    """Render the single-line tip message for one event group."""
    icon = "✗" if severity == "avoidable" else "⚠"
    label = "avoidable" if severity == "avoidable" else "review"
    cost_str = f"${cost_impact:.2f}"
    if level == "session":
        return f"{icon} {count}× {waste_reason} ({cost_str} {label})"
    return f"{icon} {name} → {count}× {waste_reason} ({cost_str} {label})"


def _build_tip(key: _GroupKey, evts: list[SessionEvent]) -> Tip | None:
    """Collapse one event group into a Tip, or None when blame context is missing."""
    waste_reason, level, name, _cls = key
    first_bt = evts[0].blame_target
    if first_bt is None:
        return None
    cost_impact = sum(e.cost_usd for e in evts if e.cost_usd is not None)
    count = len(evts)
    severity = evts[0].classification or "review"
    return Tip(
        severity=severity,
        waste_reason=waste_reason,
        count=count,
        cost_impact=cost_impact,
        blame_target=first_bt,
        message=_format_message(severity, level, name, waste_reason, count, cost_impact),
        fix_hint=first_bt.fix_hint,
    )


class TipsEngine:
    def __init__(self, rules: dict[str, Any] | None = None):
        filters = (rules or {}).get("tip_filters", {})
        self._exclude_patterns = filters.get("exclude_blame_patterns", [])
        self._min_cost = filters.get("min_cost_impact", 0.0)

    def _is_filtered(self, blame_name: str) -> bool:
        for pattern in self._exclude_patterns:
            if fnmatch.fnmatch(blame_name, pattern):
                return True
        return False

    def _keep(self, tip: Tip) -> bool:
        """Return True when a tip survives the blame-pattern and min-cost filters."""
        if self._is_filtered(tip.blame_target.name):
            return False
        return tip.cost_impact >= self._min_cost

    def generate(self, events: list[SessionEvent], max_tips: int = 3) -> list[Tip]:
        groups = _group_events([e for e in events if _is_actionable(e)])
        built = (_build_tip(key, evts) for key, evts in groups.items())
        tips = [t for t in built if t is not None and self._keep(t)]
        tips.sort(key=lambda t: t.cost_impact, reverse=True)
        return tips[:max_tips]
