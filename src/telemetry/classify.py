"""Classification engine — classifies SessionEvent objects in-place."""

import re
from dataclasses import dataclass
from typing import Any

from telemetry.models import SessionEvent

# Default tool → classification mapping for first-pass fallback.
_TOOL_CLASS_MAP: dict[str, str] = {
    "Edit": "productive",
    "Write": "productive",
    "MultiEdit": "productive",
    "NotebookEdit": "productive",
    "Bash": "productive",
    "Agent": "productive",
}


@dataclass(frozen=True)
class WindowConfig:
    """Search-window constraints for write-after-agent detection."""

    window_seconds: float
    lookforward_events: int
    write_tools: frozenset[str]


def _matches_any(pattern_list: list[str], text: str) -> bool:
    """Return True if any regex in *pattern_list* matches *text*."""
    return any(re.search(p, text) for p in pattern_list)


@dataclass(frozen=True)
class ToolWindowScan:
    """Lookback-window constraints for a backward tool_use scan."""

    allowed_tools: frozenset[str]
    window_seconds: float
    lookback_events: int
    min_gap_seconds: float = 0.0


def _scan_tool_window(
    evt: SessionEvent,
    idx: int,
    events: list[SessionEvent],
    scan: ToolWindowScan,
) -> bool:
    """Scan backward for a matching tool_use event within the lookback window.

    Returns True when a prior event matches *scan.allowed_tools*, is within
    *scan.window_seconds*, and has at least *scan.min_gap_seconds* elapsed
    since *evt*.
    """
    file_path = (evt.tool_input or {}).get("file_path")
    if not file_path:
        return False

    start = max(0, idx - scan.lookback_events)
    for prev in reversed(events[start:idx]):
        delta = (evt.timestamp - prev.timestamp).total_seconds()
        if delta > scan.window_seconds:
            break
        if prev.event_type != "tool_use" or prev.tool_name not in scan.allowed_tools:
            continue
        if file_path != (prev.tool_input or {}).get("file_path"):
            continue
        if delta >= scan.min_gap_seconds:
            return True
    return False


class ClassifyEngine:
    """Classifies a list of SessionEvent objects using configurable rules."""

    def __init__(self, rules: dict[str, Any]) -> None:
        self.rules = rules

    def classify(self, events: list[SessionEvent]) -> None:
        """Classify events in-place using two passes."""
        self._first_pass(events)
        self._second_pass(events)

    # ------------------------------------------------------------------
    # First pass: per-event classification
    # ------------------------------------------------------------------

    def _first_pass(self, events: list[SessionEvent]) -> None:
        for i, evt in enumerate(events):
            if evt.event_type != "tool_use" or evt.classification is not None:
                continue
            result = self._classify_tool_use(evt, i, events)
            if result is not None:
                evt.classification, evt.waste_reason = result
            else:
                evt.classification = self._default_classification(evt)

    def _classify_tool_use(
        self,
        evt: SessionEvent,
        i: int,
        events: list[SessionEvent],
    ) -> tuple[str, str] | None:
        """Classify a single tool_use event. Returns (classification, reason) or None."""
        if evt.success is False:
            return ("avoidable", "failed-tool")

        if evt.tool_name == "Bash":
            result = self._classify_bash(evt)
            if result is not None:
                return result

        if evt.tool_name == "Read":
            rule = self.rules.get("avoidable", {}).get("redundant-read", {})
            if rule.get("enabled", True) and self._is_redundant_read(evt, i, events, rule):
                return ("avoidable", "redundant-read")

        if evt.tool_name in ("Edit", "MultiEdit", "NotebookEdit"):
            rule = self.rules.get("avoidable", {}).get("rapid-re-edit", {})
            if rule.get("enabled", True) and self._is_rapid_re_edit(evt, i, events, rule):
                return ("avoidable", "rapid-re-edit")

        return self._apply_custom_rules(evt)

    def _classify_bash(self, evt: SessionEvent) -> tuple[str, str] | None:
        """Check bash-as-X rules. Returns (classification, reason) or None."""
        command = (evt.tool_input or {}).get("command", "")
        first_segment = command.split("|")[0].strip()

        avoidable_rules = self.rules.get("avoidable", {})
        bash_rules = {k: v for k, v in avoidable_rules.items() if k.startswith("bash-as-")}

        for rule_name, rule_cfg in bash_rules.items():
            if not rule_cfg.get("enabled", True):
                continue
            patterns = rule_cfg.get("patterns", [])
            excludes = rule_cfg.get("exclude", [])
            if _matches_any(patterns, first_segment) and not _matches_any(excludes, first_segment):
                return ("avoidable", rule_name)

        return None

    def _is_redundant_read(
        self,
        evt: SessionEvent,
        idx: int,
        events: list[SessionEvent],
        rule: dict[str, Any],
    ) -> bool:
        return _scan_tool_window(
            evt,
            idx,
            events,
            ToolWindowScan(
                allowed_tools=frozenset({"Read"}),
                window_seconds=rule.get("window_seconds", 60),
                lookback_events=rule.get("lookback_events", 10),
            ),
        )

    def _is_rapid_re_edit(
        self,
        evt: SessionEvent,
        idx: int,
        events: list[SessionEvent],
        rule: dict[str, Any],
    ) -> bool:
        return _scan_tool_window(
            evt,
            idx,
            events,
            ToolWindowScan(
                allowed_tools=frozenset({"Edit", "MultiEdit", "NotebookEdit"}),
                window_seconds=rule.get("window_seconds", 30),
                lookback_events=rule.get("lookback_events", 5),
                min_gap_seconds=rule.get("min_gap_seconds", 0),
            ),
        )

    def _apply_custom_rules(self, evt: SessionEvent) -> tuple[str, str] | None:
        """Apply custom rules. Returns (classification, reason) or None."""
        custom_rules = self.rules.get("custom_rules", [])
        for rule in custom_rules:
            tool = rule.get("tool")
            if tool and evt.tool_name != tool:
                continue
            pattern = rule.get("pattern")
            if pattern:
                command = (evt.tool_input or {}).get("command", "")
                if not re.search(pattern, command):
                    continue
            classification = rule.get("classification", "review")
            reason = rule.get("reason", "custom")
            return (classification, reason)
        return None

    def _default_classification(self, evt: SessionEvent) -> str:
        """Return the default classification for an event."""
        tools_cfg = self.rules.get("tools", {})
        productive_tools = set(tools_cfg.get(
            "productive", ["Edit", "Write", "MultiEdit", "NotebookEdit"]
        ))
        neutral_tools = set(tools_cfg.get("neutral", []))

        if evt.tool_name in productive_tools:
            return "productive"
        if evt.tool_name in neutral_tools:
            return "neutral"
        return _TOOL_CLASS_MAP.get(evt.tool_name, "neutral")

    # ------------------------------------------------------------------
    # Second pass: context-dependent classification
    # ------------------------------------------------------------------

    def _second_pass(self, events: list[SessionEvent]) -> None:
        self._classify_abandoned_search(events)
        self._classify_fruitless_agent(events)

    def _mark_abandoned_run(
        self,
        run: list[tuple[int, SessionEvent]],
        tail_events: list[tuple[int, SessionEvent]],
        write_tools: set[str],
    ) -> None:
        """Mark a run of search events as abandoned if no write follows."""
        if any(e.tool_name in write_tools for _, e in tail_events):
            return
        for _, evt in run:
            if evt.classification in (None, "neutral"):
                evt.classification = "review"
                evt.waste_reason = "abandoned-search"

    @staticmethod
    def _scan_search_run(
        tool_events: list[tuple[int, SessionEvent]],
        start: int,
        search_tools: set[str],
    ) -> list[tuple[int, SessionEvent]]:
        """Return the consecutive run of search-tool events starting at *start*."""
        run: list[tuple[int, SessionEvent]] = []
        i = start
        while i < len(tool_events) and tool_events[i][1].tool_name in search_tools:
            run.append(tool_events[i])
            i += 1
        return run

    def _classify_abandoned_search(self, events: list[SessionEvent]) -> None:
        """Mark runs of N+ consecutive Read/Grep/Glob with no Edit/Write following as review."""
        rule = self.rules.get("review", {}).get("abandoned-search", {})
        if not rule.get("enabled", True):
            return

        consecutive_reads = rule.get("consecutive_reads", 3)
        search_tools = {"Read", "Grep", "Glob"}
        write_tools = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

        tool_events = [
            (i, e) for i, e in enumerate(events)
            if e.event_type == "tool_use" and e.tool_name is not None
        ]

        i = 0
        while i < len(tool_events):
            run = self._scan_search_run(tool_events, i, search_tools)
            if len(run) >= consecutive_reads:
                self._mark_abandoned_run(run, tool_events[i + len(run):], write_tools)
                i += len(run)
            else:
                i += 1

    def _has_write_after_agent(
        self,
        agent_evt: SessionEvent,
        events: list[SessionEvent],
        start: int,
        window: WindowConfig,
    ) -> bool:
        """Return True if a write tool appears within the look-forward window."""
        count = 0
        for j in range(start, len(events)):
            if events[j].event_type != "tool_use":
                continue
            delta = (events[j].timestamp - agent_evt.timestamp).total_seconds()
            if delta > window.window_seconds or count >= window.lookforward_events:
                break
            if events[j].tool_name in window.write_tools:
                return True
            count += 1
        return False

    def _mark_if_fruitless(
        self,
        evt: SessionEvent,
        i: int,
        events: list[SessionEvent],
        exempt_types: set[str],
        window: WindowConfig,
    ) -> None:
        """Mark a single Agent tool_use event as review if it looks fruitless."""
        if evt.event_type != "tool_use" or evt.tool_name != "Agent":
            return
        agent_type = (evt.tool_input or {}).get("subagent_type", "")
        if agent_type in exempt_types:
            return
        if self._has_write_after_agent(evt, events, i + 1, window):
            return
        if evt.classification in (None, "productive"):
            evt.classification = "review"
            evt.waste_reason = "fruitless-agent"

    def _classify_fruitless_agent(self, events: list[SessionEvent]) -> None:
        """Mark Agent calls with no Edit/Write in next N events within time window as review."""
        rule = self.rules.get("review", {}).get("fruitless-agent", {})
        if not rule.get("enabled", True):
            return

        # Agent types that are read-only by design — never fruitless
        exempt_types = set(rule.get("exempt_agent_types", [
            "reviewer", "researcher", "Explore", "fact-checker",
            "unit-validator", "cross-unit-validator", "claude-code-guide",
        ]))
        window = WindowConfig(
            window_seconds=rule.get("window_seconds", 300),
            lookforward_events=rule.get("lookforward_events", 10),
            write_tools=frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"}),
        )

        for i, evt in enumerate(events):
            self._mark_if_fruitless(evt, i, events, exempt_types, window)
