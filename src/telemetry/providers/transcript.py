"""TranscriptProvider: reads and parses Claude Code JSONL transcript files.

Session discovery and windowed-aggregation entry points.  Low-level JSONL
record parsing lives in ``transcript_parse``.  Agent token accumulation
lives in ``transcript_aggregate``.
"""

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.date_utils import now_utc

from telemetry.models import AgentSummary, AgentTokenRow, SessionEvent, SessionSummary
from telemetry.pricing import TokenMetrics, compute_cost
from telemetry.providers.transcript_aggregate import (
    TokenAccumulators,
    accumulate_agent_tokens,
    build_agent_row,
)
from telemetry.providers.transcript_parse import (
    JSONL_GLOB,
    SUBDIR_GLOB,
    MessageKey,
    iter_jsonl_files,
    message_key,
    parse_assistant_record,
    parse_session_file,
    parse_user_record,
)


logger = logging.getLogger(__name__)


@dataclass
class _SessionUnit:
    """One parsed session (a flat file, or an old-format subagent file group)."""

    session_id: str
    project_path: str
    events: list[SessionEvent]
    agents: list[AgentSummary]
    fallback_ts: datetime  # file mtime; used when the session has no events

    @property
    def start_time(self) -> datetime:
        return min((e.timestamp for e in self.events), default=self.fallback_ts)

    @property
    def api_events(self) -> list[SessionEvent]:
        return [e for e in self.events if e.event_type == "api_request"]


@dataclass
class _SnapshotSeen:
    """The largest output count and cost already counted for one billed call."""

    output_tokens: int
    cost: float


def _unbilled_part(
    e: SessionEvent, seen: dict[MessageKey, _SnapshotSeen] | None
) -> tuple[float, int, bool] | None:
    """Return ``(cost, output_tokens, first_copy)`` not yet counted for *e*, or None.

    A call repeated in another file (a resumed session) contributes only its
    output growth over what *seen* already holds; input and cache tokens are
    final on the first copy and are not added again (``first_copy`` False).
    None means the copy adds nothing. Updates *seen*.
    """
    cost = e.cost_usd or 0.0
    output = e.output_tokens or 0
    key = message_key(e.message_id, e.request_id)
    if seen is None or key is None:
        return cost, output, True
    prev = seen.get(key)
    if prev is not None and output <= prev.output_tokens:
        return None
    seen[key] = _SnapshotSeen(output, cost)
    if prev is None:
        return cost, output, True
    return cost - prev.cost, output - prev.output_tokens, False


def _global_max_output(units: list[_SessionUnit]) -> dict[MessageKey, int]:
    """Return the largest ``output_tokens`` per billed call across *units*."""
    global_max: dict[MessageKey, int] = {}
    for unit in units:
        for e in unit.api_events:
            key = message_key(e.message_id, e.request_id)
            if key is not None:
                global_max[key] = max(global_max.get(key, -1), e.output_tokens or 0)
    return global_max


def _billable_events(
    api_events: list[SessionEvent],
    billed: set[MessageKey],
    global_max: dict[MessageKey, int],
) -> list[SessionEvent]:
    """Return the events of one session that are billed to it; update *billed*.

    A resumed or compacted session copies earlier records into a new file, so
    one call can appear in several sessions, sometimes as an incomplete
    snapshot. The call is billed once: to the first session (in scan order)
    holding its completed snapshot (``global_max``). Copies in other sessions,
    and incomplete copies anywhere, are dropped. Events without a message id
    are always billed.
    """
    kept: list[SessionEvent] = []
    for e in api_events:
        key = message_key(e.message_id, e.request_id)
        if key is None:
            kept.append(e)
        elif key not in billed and (e.output_tokens or 0) == global_max.get(key):
            billed.add(key)
            kept.append(e)
    return kept


class TranscriptProvider:
    """Reads and parses Claude Code JSONL transcript files."""

    def __init__(self, projects_dir: Path | None = None):
        if projects_dir is None:
            projects_dir = Path.home() / ".claude" / "projects"
        self.projects_dir = Path(projects_dir)

    # ------------------------------------------------------------------
    # Core parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_token_cost(
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read: int,
        cache_create: int,
        cache_1h: int = 0,
    ) -> float:
        """Compute USD cost for a set of token counts at the given model's rates.

        Delegates to ``pricing.compute_cost`` so the configured
        ``cost_multiplier`` is applied to every cost computed in this provider
        (MTD, per-session, per-tool, per-agent), not just paths that go
        through ``pricing.compute_cost`` directly. ``cache_1h`` is the
        1-hour-TTL part of ``cache_create``.
        """
        return compute_cost(
            TokenMetrics(input_tokens, output_tokens, cache_read, cache_create, cache_1h), model
        )

    def _parse_assistant_record(
        self,
        record: dict,
        agent_tool_inputs: dict[str, dict],
        sequence: int,
    ) -> tuple[list[SessionEvent], int]:
        """Parse one assistant JSONL record into SessionEvent objects.

        Returns (new_events, updated_sequence).
        """
        return parse_assistant_record(
            record, agent_tool_inputs, sequence, self._compute_token_cost
        )

    def _parse_user_record(
        self,
        record: dict,
        agent_tool_inputs: dict[str, dict],
    ) -> AgentSummary | None:
        """Parse one user JSONL record into an AgentSummary, or None if not an agent result."""
        return parse_user_record(record, agent_tool_inputs, self._compute_token_cost)

    def parse_session_with_agents(
        self, path: Path
    ) -> tuple[list[SessionEvent], list[AgentSummary]]:
        """Parse a JSONL transcript and return (events, agents).

        For each assistant message with usage, one ``api_request`` SessionEvent
        is emitted. For each tool_use block inside that assistant message, one
        ``tool_use`` SessionEvent is emitted. If a user message carries a
        ``toolUseResult`` with an ``agentId``, an AgentSummary is created.

        The ``description`` for an AgentSummary comes from the Agent tool_use
        input field (line where the assistant calls the Agent tool), not from
        the toolUseResult.
        """
        return parse_session_file(path, self._compute_token_cost)

    def parse_session(self, path: Path) -> list[SessionEvent]:
        """Parse a transcript, returning only the events list."""
        events, _ = self.parse_session_with_agents(path)
        return events

    # ------------------------------------------------------------------
    # Session discovery
    # ------------------------------------------------------------------

    @staticmethod
    def _iter_jsonl_files(project_dir: Path) -> Iterator[tuple[Path, str]]:
        """Yield (jsonl_path, session_id) for all JSONL files under project_dir.

        Handles two storage layouts:
        - New (post-Apr 2026): ``<project>/<session-uuid>.jsonl``
          session_id = file stem
        - Old (pre-Apr 2026): ``<project>/<session-uuid>/subagents/<agent-id>.jsonl``
          session_id = the ``<session-uuid>`` directory name
        """
        return iter_jsonl_files(project_dir)

    def _parse_session_safe(
        self, jsonl_file: Path
    ) -> tuple[list[SessionEvent], list[AgentSummary]]:
        """Parse one file; an unreadable or corrupt file yields no events."""
        try:
            return self.parse_session_with_agents(jsonl_file)
        except Exception as exc:  # nosec B110 - one corrupt file must not abort the scan
            logger.debug("skipping unreadable transcript %s: %s", jsonl_file, exc)
            return [], []

    def _flat_units(
        self, project_dir: Path, project_path: str, since: datetime | None
    ) -> list[_SessionUnit]:
        """Parse the new flat-format ``<session>.jsonl`` files of one project."""
        units: list[_SessionUnit] = []
        for jsonl_file in project_dir.glob(JSONL_GLOB):
            file_ts = datetime.fromtimestamp(jsonl_file.stat().st_mtime, tz=timezone.utc)
            # A file is only appended to, so one last modified before ``since``
            # cannot hold an in-window event.
            if since is not None and file_ts < since:
                continue
            events, agents = self._parse_session_safe(jsonl_file)
            units.append(_SessionUnit(jsonl_file.stem, project_path, events, agents, file_ts))
        return units

    def _subdir_units(
        self, project_dir: Path, project_path: str, since: datetime | None
    ) -> list[_SessionUnit]:
        """Parse old subdirectory-format sessions, merging each session's files.

        The old format stores one JSONL per subagent; they are merged into one
        session-level unit whose events carry the real session id.
        """
        subdir_files: dict[str, list[Path]] = {}
        for jsonl_file in project_dir.glob(SUBDIR_GLOB):
            subdir_files.setdefault(jsonl_file.parent.parent.name, []).append(jsonl_file)

        units: list[_SessionUnit] = []
        for session_id, files in subdir_files.items():
            latest_ts = max(
                datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc) for f in files
            )
            if since is not None and latest_ts < since:
                continue
            events: list[SessionEvent] = []
            agents: list[AgentSummary] = []
            for jsonl_file in files:
                evts, file_agents = self._parse_session_safe(jsonl_file)
                events.extend(evts)
                agents.extend(file_agents)
            for event in events:
                event.session_id = session_id
            units.append(_SessionUnit(session_id, project_path, events, agents, latest_ts))
        return units

    @staticmethod
    def _summary_from_unit(
        unit: _SessionUnit, billable: list[SessionEvent]
    ) -> SessionSummary:
        """Build a SessionSummary; cost and tokens come from *billable* only."""
        api_events = unit.api_events
        return SessionSummary(
            session_id=unit.session_id,
            project_path=unit.project_path or None,
            start_time=unit.start_time,
            end_time=max((e.timestamp for e in unit.events), default=unit.fallback_ts),
            model=(api_events[0].model or "") if api_events else "",
            total_cost=sum(e.cost_usd or 0.0 for e in billable),
            cost_is_estimated=False,
            total_events=len(unit.events),
            efficiency_score=0.0,
            agents=unit.agents,
            input_tokens=sum(e.input_tokens or 0 for e in billable),
            output_tokens=sum(e.output_tokens or 0 for e in billable),
            cache_read_tokens=sum(e.cache_read_tokens or 0 for e in billable),
            cache_creation_tokens=sum(e.cache_creation_tokens or 0 for e in billable),
        )

    def get_sessions(self, since: datetime | None = None) -> list[SessionSummary]:
        """Scan all project dirs under projects_dir for .jsonl files.

        Returns a list of SessionSummary objects, one per session found.
        Handles both the new flat format and the old subdirectory format.

        Two phases keep cross-session dedup correct under ``since``: every
        session is parsed and filtered on its real ``start_time`` first, and
        only then is each duplicated call assigned to one kept session, so a
        call is never billed to a session that is not in the result.
        """
        if not self.projects_dir.exists():
            return []

        units: list[_SessionUnit] = []
        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            project_path = "/" + project_dir.name.lstrip("-").replace("-", "/")
            units.extend(self._flat_units(project_dir, project_path, since))
            units.extend(self._subdir_units(project_dir, project_path, since))

        kept = [u for u in units if since is None or u.start_time >= since]
        global_max = _global_max_output(kept)
        billed: set[MessageKey] = set()
        summaries = [
            self._summary_from_unit(u, _billable_events(u.api_events, billed, global_max))
            for u in kept
        ]
        summaries.sort(key=lambda s: s.end_time or s.start_time, reverse=True)
        return summaries

    def _windowed_events(
        self, jsonl_file: Path, since: datetime
    ) -> list[SessionEvent]:
        """Return api_request events from jsonl_file with timestamp >= since."""
        try:
            events, _ = self.parse_session_with_agents(jsonl_file)
        except Exception:
            return []
        return [e for e in events if e.event_type == "api_request" and e.timestamp >= since]

    def _accumulate_windowed_event(
        self,
        e: SessionEvent,
        bucket_start: datetime,
        num_slots: int,
        totals: dict,
        seen: dict[MessageKey, _SnapshotSeen] | None = None,
    ) -> None:
        """Add one api_request event's cost and tokens into the running totals dict.

        ``seen`` tracks billed calls across every file in the scan; see
        ``_unbilled_part``.
        """
        part = _unbilled_part(e, seen)
        if part is None:
            return
        cost, output, first_copy = part
        totals["cost"] += cost
        totals["output_tokens"] += output
        if first_copy:
            totals["input_tokens"] += e.input_tokens or 0
            totals["cache_read_tokens"] += e.cache_read_tokens or 0
        if e.model:
            totals["models"][e.model] = totals["models"].get(e.model, 0.0) + cost
        offset = (e.timestamp - bucket_start).total_seconds()
        if 0.0 <= offset < num_slots * 3600:
            totals["hourly_costs"][min(int(offset / 3600), num_slots - 1)] += cost

    def get_windowed_totals(self, since: datetime) -> dict[str, object]:
        """Sum costs and tokens for api_request events whose timestamp >= since.

        Unlike get_sessions (which uses file mtime to filter), this method parses
        every session file and sums only the individual API request events that fall
        within the window. This prevents a session started before the window from
        contributing its full lifetime cost to the window total.

        Returns a dict with keys:
            cost (float), input_tokens (int), output_tokens (int),
            cache_read_tokens (int), sessions (int), cost_is_estimated (bool),
            models (dict[str, float]), hourly_costs (list[float])
        """
        now = now_utc()
        num_slots = 12
        bucket_start = now - timedelta(hours=num_slots)
        hourly: list[float] = [0.0] * num_slots

        totals: dict = {
            "cost": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "sessions": 0,
            "cost_is_estimated": False,
            "models": {},
            "hourly_costs": hourly,
        }
        if not self.projects_dir.exists():
            return totals

        # Shared across all projects and files so a call copied into a resumed
        # session's file is counted once.
        seen: dict[MessageKey, _SnapshotSeen] = {}
        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            self._accumulate_windowed_project(
                project_dir, since, bucket_start, num_slots, totals, seen
            )

        return totals

    def _accumulate_windowed_project(
        self,
        project_dir: Path,
        since: datetime,
        bucket_start: datetime,
        num_slots: int,
        totals: dict,
        seen: dict[MessageKey, _SnapshotSeen],
    ) -> None:
        """Accumulate windowed totals for all JSONL files in one project directory."""
        seen_sessions: set[str] = set()
        for jsonl_file, session_id in self._iter_jsonl_files(project_dir):
            file_ts = datetime.fromtimestamp(jsonl_file.stat().st_mtime, tz=timezone.utc)
            if file_ts < since:
                continue
            windowed = self._windowed_events(jsonl_file, since)
            if not windowed:
                continue
            if session_id not in seen_sessions:
                totals["sessions"] += 1
                seen_sessions.add(session_id)
            for e in windowed:
                self._accumulate_windowed_event(e, bucket_start, num_slots, totals, seen)

    def get_current_session_id(self) -> str | None:
        """Return the session ID of the most recently modified .jsonl file.

        Scans both flat format (<session>.jsonl) and old subdirectory format
        (<session>/subagents/<agent>.jsonl).
        """
        if not self.projects_dir.exists():
            return None

        latest_session: str | None = None
        latest_mtime: float = -1.0

        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            for jsonl_file, session_id in self._iter_jsonl_files(project_dir):
                mtime = jsonl_file.stat().st_mtime
                if mtime > latest_mtime:
                    latest_mtime = mtime
                    latest_session = session_id

        return latest_session

    def find_session_file(self, session_id: str) -> Path | None:
        """Find a .jsonl file by session ID across all project directories.

        Handles both flat format (<session-id>.jsonl) and old subdirectory
        format (<session-id>/subagents/<agent-id>.jsonl).
        """
        if not self.projects_dir.exists():
            return None

        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            candidate = project_dir / f"{session_id}.jsonl"
            if candidate.exists():
                return candidate
            subagents_dir = project_dir / session_id / "subagents"
            if subagents_dir.is_dir():
                for f in subagents_dir.glob("*.jsonl"):
                    return f

        return None

    def _accumulate_agent_tokens_for_project(
        self, project_dir: Path, since: datetime, accs: TokenAccumulators
    ) -> None:
        """Accumulate agent token usage for all JSONL files in one project directory."""
        for jsonl_file, _ in self._iter_jsonl_files(project_dir):
            file_ts = datetime.fromtimestamp(jsonl_file.stat().st_mtime, tz=timezone.utc)
            if file_ts < since:
                continue
            self._accumulate_agent_tokens(jsonl_file, since, accs)

    def aggregate_agents(self, since: datetime) -> list[AgentTokenRow]:
        """Scan all JSONL files and aggregate token usage by agentName.

        Messages without an agentName are grouped under ``"(orchestrator)"``.
        Returns one AgentTokenRow per unique agent name, sorted by estimated
        cost descending.
        """
        accs = TokenAccumulators()

        if not self.projects_dir.exists():
            return []

        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            self._accumulate_agent_tokens_for_project(project_dir, since, accs)

        # Collapse per-(agent, model) into per-agent rows
        agent_names: set[str] = {name for name, _ in accs.input.keys()} | set(accs.call_count)
        rows: list[AgentTokenRow] = [
            self._build_agent_row(agent_name, accs)
            for agent_name in agent_names
        ]

        rows.sort(key=lambda r: r.est_cost, reverse=True)
        return rows

    def _build_agent_row(
        self,
        agent_name: str,
        accs: TokenAccumulators,
    ) -> AgentTokenRow:
        """Collapse per-(agent, model) accumulators into one AgentTokenRow for agent_name."""
        return build_agent_row(agent_name, accs)

    def _accumulate_agent_tokens(
        self,
        jsonl_file: Path,
        since: datetime,
        accs: TokenAccumulators,
    ) -> None:
        """Parse one JSONL file and accumulate token counts into accs."""
        accumulate_agent_tokens(jsonl_file, since, accs)
