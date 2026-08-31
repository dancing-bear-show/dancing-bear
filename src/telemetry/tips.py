from __future__ import annotations

import fnmatch
from collections import defaultdict
from typing import Any

from telemetry.models import SessionEvent, Tip


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

    def generate(self, events: list[SessionEvent], max_tips: int = 3) -> list[Tip]:
        actionable = [
            e for e in events
            if e.classification in ("avoidable", "review")
            and e.blame_target is not None
            and e.waste_reason is not None
        ]

        groups: dict[tuple[str, str, str, str], list[SessionEvent]] = defaultdict(list)
        for evt in actionable:
            bt = evt.blame_target
            if bt is None:
                continue
            waste_reason = evt.waste_reason or ""
            key = (waste_reason, bt.level, bt.name, evt.classification or "")
            groups[key].append(evt)

        tips: list[Tip] = []
        for (waste_reason, level, name, _cls), evts in groups.items():
            cost_impact = sum(e.cost_usd for e in evts if e.cost_usd is not None)
            count = len(evts)
            first_bt = evts[0].blame_target
            severity = evts[0].classification or "review"
            icon = "✗" if severity == "avoidable" else "⚠"
            cost_str = f"${cost_impact:.2f}"
            label = "avoidable" if severity == "avoidable" else "review"
            if level == "session":
                message = f"{icon} {count}× {waste_reason} ({cost_str} {label})"
            else:
                message = f"{icon} {name} → {count}× {waste_reason} ({cost_str} {label})"

            if first_bt is None:
                continue

            tips.append(Tip(
                severity=severity,
                waste_reason=waste_reason,
                count=count,
                cost_impact=cost_impact,
                blame_target=first_bt,
                message=message,
                fix_hint=first_bt.fix_hint,
            ))

        tips = [t for t in tips
                if not self._is_filtered(t.blame_target.name)
                and t.cost_impact >= self._min_cost]

        tips.sort(key=lambda t: t.cost_impact, reverse=True)
        return tips[:max_tips]
