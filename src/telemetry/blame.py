"""Blame attribution engine."""

from typing import Any

from telemetry.models import BlameTarget, SessionEvent


class BlameEngine:
    """Attributes blame targets to classified events."""

    def __init__(self, rules: dict[str, Any]) -> None:
        self.rules = rules

    def attribute(
        self,
        events: list[SessionEvent],
        agent_context: str | None = None,
    ) -> None:
        """Walk events in order and set blame_target on avoidable/review events."""
        active_skill: str | None = None

        for evt in events:
            if evt.tool_name == "Skill" and evt.tool_input:
                active_skill = str(evt.tool_input.get("skill") or "") or active_skill

            if evt.classification not in ("avoidable", "review"):
                evt.blame_target = None
                continue

            if agent_context is not None:
                level = "agent"
                name = agent_context
            elif active_skill:
                level = "skill"
                name = active_skill
            else:
                level = "session"
                name = "session"

            fix_hint = self._get_fix_hint(evt.waste_reason, level, name)
            evt.blame_target = BlameTarget(level=level, name=name, fix_hint=fix_hint)

    def _get_fix_hint(
        self,
        waste_reason: str | None,
        level: str,
        name: str,
    ) -> str:
        if not waste_reason:
            return f"{level.capitalize()} waste detected in {name}."

        fix_hints = self.rules.get("fix_hints", {})
        reason_hints = fix_hints.get(waste_reason, {})
        default = f"{level.capitalize()} waste: {waste_reason} in {{name}}."
        template = reason_hints.get(level, default)

        try:
            return template.format(name=name)
        except (KeyError, IndexError, ValueError):
            return template
