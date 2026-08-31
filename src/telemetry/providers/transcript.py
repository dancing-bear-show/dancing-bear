"""TranscriptProvider: reads and parses Claude Code JSONL transcript files.

Session discovery and windowed-aggregation entry points.  Low-level JSONL
record parsing lives in ``transcript_parse``.  Agent token accumulation
lives in ``transcript_aggregate``.
"""

import logging
from collections.abc import Iterator
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
    iter_jsonl_files,
    parse_assistant_record,
    parse_session_file,
    parse_user_record,
)


logger = logging.getLogger(__name__)

_JSONL_GLOB = "*.jsonl"
_SUBDIR_GLOB = "*/subagents/*.jsonl"


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
    ) -> float:
        """Compute USD cost for a set of token counts at the given model's rates.

        Delegates to ``pricing.compute_cost`` so the configured
        ``cost_multiplier`` is applied to every cost computed in this provider
        (MTD, per-session, per-tool, per-agent), not just paths that go
        through ``pricing.compute_cost`` directly.
        """
        return compute_cost(TokenMetrics(input_tokens, output_tokens, cache_read, cache_create), model)

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

    def _session_summary_from_file(
        self, jsonl_file: Path, project_path: str
    ) -> SessionSummary:
        """Build a SessionSummary from a single .jsonl transcript file."""
        file_ts = datetime.fromtimestamp(jsonl_file.stat().st_mtime, tz=timezone.utc)
        try:
            events, agents = self.parse_session_with_agents(jsonl_file)
        except Exception:
            events, agents = [], []

        api_events = [e for e in events if e.event_type == "api_request"]
        return SessionSummary(
            session_id=jsonl_file.stem,
            project_path=project_path or None,
            start_time=events[0].timestamp if events else file_ts,
            end_time=events[-1].timestamp if events else file_ts,
            model=(api_events[0].model or "") if api_events else "",
            total_cost=sum(e.cost_usd or 0.0 for e in api_events),
            cost_is_estimated=False,
            total_events=len(events),
            efficiency_score=0.0,
            agents=agents,
            input_tokens=sum(e.input_tokens or 0 for e in api_events),
            output_tokens=sum(e.output_tokens or 0 for e in api_events),
            cache_read_tokens=sum(e.cache_read_tokens or 0 for e in api_events),
            cache_creation_tokens=sum(e.cache_creation_tokens or 0 for e in api_events),
        )

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

    def _merge_subagent_files(
        self, jsonl_files: list[Path]
    ) -> tuple[list[SessionEvent], list[AgentSummary], datetime | None]:
        """Parse and merge all subagent JSONL files, returning (events, agents, latest_mtime)."""
        all_events: list[SessionEvent] = []
        all_agents: list[AgentSummary] = []
        file_ts: datetime | None = None

        for jsonl_file in jsonl_files:
            ts = datetime.fromtimestamp(jsonl_file.stat().st_mtime, tz=timezone.utc)
            if file_ts is None or ts > file_ts:
                file_ts = ts
            try:
                evts, agents = self.parse_session_with_agents(jsonl_file)
            except Exception:
                evts, agents = [], []
            all_events.extend(evts)
            all_agents.extend(agents)

        return all_events, all_agents, file_ts

    def _session_summary_from_old_format(
        self, session_id: str, jsonl_files: list[Path], project_path: str
    ) -> SessionSummary:
        """Build a SessionSummary by aggregating multiple subagent JSONL files.

        The old subdirectory format stores one JSONL per subagent; they must be
        merged into a single session-level summary.
        """
        all_events, all_agents, file_ts = self._merge_subagent_files(jsonl_files)
        fallback_ts = file_ts or now_utc()
        # Replace per-file session_id values (agent-id stems) with the real session_id
        for event in all_events:
            event.session_id = session_id

        api_events = [e for e in all_events if e.event_type == "api_request"]
        return SessionSummary(
            session_id=session_id,
            project_path=project_path or None,
            start_time=min((e.timestamp for e in all_events), default=fallback_ts),
            end_time=max((e.timestamp for e in all_events), default=fallback_ts),
            model=(api_events[0].model or "") if api_events else "",
            total_cost=sum(e.cost_usd or 0.0 for e in api_events),
            cost_is_estimated=False,
            total_events=len(all_events),
            efficiency_score=0.0,
            agents=all_agents,
            input_tokens=sum(e.input_tokens or 0 for e in api_events),
            output_tokens=sum(e.output_tokens or 0 for e in api_events),
            cache_read_tokens=sum(e.cache_read_tokens or 0 for e in api_events),
            cache_creation_tokens=sum(e.cache_creation_tokens or 0 for e in api_events),
        )

    def _collect_flat_sessions(
        self,
        project_dir: Path,
        project_path: str,
        since: datetime | None,
        summaries: list[SessionSummary],
    ) -> None:
        """Append SessionSummary objects from new flat-format .jsonl files."""
        for jsonl_file in project_dir.glob(_JSONL_GLOB):
            file_ts = datetime.fromtimestamp(jsonl_file.stat().st_mtime, tz=timezone.utc)
            if since is not None and file_ts < since:
                continue
            summary = self._session_summary_from_file(jsonl_file, project_path)
            if since is not None and summary.start_time < since:
                continue
            summaries.append(summary)

    def _collect_subdir_sessions(
        self,
        project_dir: Path,
        project_path: str,
        since: datetime | None,
        summaries: list[SessionSummary],
    ) -> None:
        """Append SessionSummary objects from old subdirectory-format .jsonl files."""
        subdir_files: dict[str, list[Path]] = {}
        for jsonl_file in project_dir.glob(_SUBDIR_GLOB):
            session_id = jsonl_file.parent.parent.name
            subdir_files.setdefault(session_id, []).append(jsonl_file)

        for session_id, files in subdir_files.items():
            latest_ts = max(
                datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc) for f in files
            )
            if since is not None and latest_ts < since:
                continue
            summary = self._session_summary_from_old_format(session_id, files, project_path)
            if since is not None and summary.start_time < since:
                continue
            summaries.append(summary)

    def get_sessions(self, since: datetime | None = None) -> list[SessionSummary]:
        """Scan all project dirs under projects_dir for .jsonl files.

        Returns a list of SessionSummary objects, one per session found.
        Handles both the new flat format and the old subdirectory format.
        """
        summaries: list[SessionSummary] = []
        if not self.projects_dir.exists():
            return summaries

        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            project_path = "/" + project_dir.name.lstrip("-").replace("-", "/")
            self._collect_flat_sessions(project_dir, project_path, since, summaries)
            self._collect_subdir_sessions(project_dir, project_path, since, summaries)

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
    ) -> None:
        """Add one api_request event's cost and tokens into the running totals dict."""
        cost = e.cost_usd or 0.0
        totals["cost"] += cost
        totals["input_tokens"] += e.input_tokens or 0
        totals["output_tokens"] += e.output_tokens or 0
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

        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            self._accumulate_windowed_project(project_dir, since, bucket_start, num_slots, totals)

        return totals

    def _accumulate_windowed_project(
        self,
        project_dir: Path,
        since: datetime,
        bucket_start: datetime,
        num_slots: int,
        totals: dict,
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
                self._accumulate_windowed_event(e, bucket_start, num_slots, totals)

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
