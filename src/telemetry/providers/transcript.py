"""TranscriptProvider: parses Claude Code JSONL transcript files."""

import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telemetry.timeutil import parse_iso_utc
from telemetry.models import AgentSummary, AgentTokenRow, SessionEvent, SessionSummary
from telemetry.pricing import compute_cost


_JSONL_GLOB = "*.jsonl"
# Old subdirectory format: <project>/<session-uuid>/subagents/<agent-id>.jsonl
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
        return compute_cost(input_tokens, output_tokens, cache_read, cache_create, model)

    def _parse_assistant_record(
        self,
        record: dict,
        agent_tool_inputs: dict[str, dict],
        sequence: int,
    ) -> tuple[list[SessionEvent], int]:
        """Parse one assistant JSONL record into SessionEvent objects.

        Returns (new_events, updated_sequence).
        """
        new_events: list[SessionEvent] = []
        session_id = record.get("sessionId", "")
        ts = parse_iso_utc(record.get("timestamp", "")) or datetime.now(timezone.utc)
        msg = record.get("message", {})
        usage = msg.get("usage", {})
        model = msg.get("model", "")
        content = msg.get("content", [])

        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        cache_read = usage.get("cache_read_input_tokens", 0)
        cache_create = usage.get("cache_creation_input_tokens", 0)

        cost = 0.0
        if usage:
            cost = self._compute_token_cost(
                model, input_tokens, output_tokens, cache_read, cache_create
            )
            sequence += 1
            new_events.append(SessionEvent(
                timestamp=ts,
                event_type="api_request",
                sequence=sequence,
                session_id=session_id,
                model=model,
                cost_usd=cost,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read,
                cache_creation_tokens=cache_create,
            ))

        tool_blocks = [b for b in content if b.get("type") == "tool_use"]
        per_tool_cost = cost / len(tool_blocks) if usage and tool_blocks else 0.0

        for block in tool_blocks:
            tool_name = block.get("name", "")
            tool_id = block.get("id", "")
            tool_input = block.get("input", {})
            if tool_name == "Agent":
                agent_tool_inputs[tool_id] = tool_input
            sequence += 1
            new_events.append(SessionEvent(
                timestamp=ts,
                event_type="tool_use",
                sequence=sequence,
                session_id=session_id,
                tool_name=tool_name,
                tool_input=tool_input,
                model=model,
                cost_usd=per_tool_cost,
                cost_is_estimated=True,
            ))

        return new_events, sequence

    def _parse_user_record(
        self,
        record: dict,
        agent_tool_inputs: dict[str, dict],
    ) -> AgentSummary | None:
        """Parse one user JSONL record into an AgentSummary, or None if not an agent result."""
        tool_use_result = record.get("toolUseResult")
        if not tool_use_result or "agentId" not in tool_use_result:
            return None

        agent_id = tool_use_result["agentId"]
        agent_type = tool_use_result.get("agentType", "")
        total_tokens = tool_use_result.get("totalTokens", 0)
        total_tool_uses = tool_use_result.get("totalToolUseCount", 0)
        duration_ms = tool_use_result.get("totalDurationMs", 0)
        sub_usage = tool_use_result.get("usage", {})

        sub_input = sub_usage.get("input_tokens", 0)
        sub_output = sub_usage.get("output_tokens", 0)
        sub_cache_read = sub_usage.get("cache_read_input_tokens", 0)
        sub_cache_create = sub_usage.get("cache_creation_input_tokens", 0)

        # Resolve description from the originating Agent tool_use block
        content_blocks = record.get("message", {}).get("content", [])
        tool_use_id = next(
            (b.get("tool_use_id") for b in content_blocks if b.get("type") == "tool_result"),
            None,
        )
        agent_input = agent_tool_inputs.get(tool_use_id or "", {})
        description = agent_input.get("description", "")
        agent_model = agent_input.get("model", "")

        cost = self._compute_token_cost(
            agent_model, sub_input, sub_output, sub_cache_read, sub_cache_create
        )
        return AgentSummary(
            agent_id=agent_id,
            agent_type=agent_type,
            description=description,
            model=agent_model,
            duration_ms=duration_ms,
            total_tokens=total_tokens,
            total_tool_uses=total_tool_uses,
            cost_usd=cost,
        )

    def parse_session_with_agents(  # noqa: S3776 - JSONL file parser; loop+try/except+message-type dispatch is irreducible
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
        events: list[SessionEvent] = []
        agents: list[AgentSummary] = []
        agent_tool_inputs: dict[str, dict] = {}
        sequence = 0

        with open(path, "r", encoding="utf-8") as fh:
            for raw_line in fh:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                msg_type = record.get("type")
                if msg_type == "assistant":
                    new_evts, sequence = self._parse_assistant_record(
                        record, agent_tool_inputs, sequence
                    )
                    events.extend(new_evts)
                elif msg_type == "user":
                    agent = self._parse_user_record(record, agent_tool_inputs)
                    if agent is not None:
                        agents.append(agent)

        return events, agents

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
            model=api_events[0].model if api_events else "",
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
        for jsonl_file in project_dir.glob(_JSONL_GLOB):
            yield jsonl_file, jsonl_file.stem
        for jsonl_file in project_dir.glob(_SUBDIR_GLOB):
            # path is <project>/<session-uuid>/subagents/<agent-id>.jsonl
            # parent is <project>/<session-uuid>/subagents
            # parent.parent is <project>/<session-uuid>
            yield jsonl_file, jsonl_file.parent.parent.name

    def _session_summary_from_old_format(
        self, session_id: str, jsonl_files: list[Path], project_path: str
    ) -> SessionSummary:
        """Build a SessionSummary by aggregating multiple subagent JSONL files.

        The old subdirectory format stores one JSONL per subagent; they must be
        merged into a single session-level summary.
        """
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

        fallback_ts = file_ts or datetime.now(timezone.utc)
        # Replace per-file session_id values (agent-id stems) with the real session_id
        for event in all_events:
            event.session_id = session_id

        api_events = [e for e in all_events if e.event_type == "api_request"]
        return SessionSummary(
            session_id=session_id,
            project_path=project_path or None,
            start_time=min((e.timestamp for e in all_events), default=fallback_ts),
            end_time=max((e.timestamp for e in all_events), default=fallback_ts),
            model=api_events[0].model if api_events else "",
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
        e: "SessionEvent",
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
        now = datetime.now(timezone.utc)
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

    def aggregate_agents(self, since: datetime) -> list[AgentTokenRow]:
        """Scan all JSONL files and aggregate token usage by agentName.

        Messages without an agentName are grouped under ``"(orchestrator)"``.
        Returns one AgentTokenRow per unique agent name, sorted by estimated
        cost descending.
        """
        from collections import defaultdict

        # Per-agent, per-model accumulators
        # key: (agent_name, model)
        input_acc: dict[tuple[str, str], int] = defaultdict(int)
        output_acc: dict[tuple[str, str], int] = defaultdict(int)
        cache_read_acc: dict[tuple[str, str], int] = defaultdict(int)
        cache_write_acc: dict[tuple[str, str], int] = defaultdict(int)
        call_acc: dict[str, int] = defaultdict(int)

        if not self.projects_dir.exists():
            return []

        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            for jsonl_file, _ in self._iter_jsonl_files(project_dir):
                file_ts = datetime.fromtimestamp(jsonl_file.stat().st_mtime, tz=timezone.utc)
                if file_ts < since:
                    continue
                self._accumulate_agent_tokens(
                    jsonl_file, since,
                    input_acc, output_acc, cache_read_acc, cache_write_acc, call_acc,
                )

        # Collapse per-(agent, model) into per-agent rows
        agent_names: set[str] = {name for name, _ in input_acc.keys()} | set(call_acc)
        rows: list[AgentTokenRow] = [
            self._build_agent_row(agent_name, input_acc, output_acc, cache_read_acc, cache_write_acc, call_acc)
            for agent_name in agent_names
        ]

        rows.sort(key=lambda r: r.est_cost, reverse=True)
        return rows

    def _build_agent_row(
        self,
        agent_name: str,
        input_acc: dict[tuple[str, str], int],
        output_acc: dict[tuple[str, str], int],
        cache_read_acc: dict[tuple[str, str], int],
        cache_write_acc: dict[tuple[str, str], int],
        call_acc: dict[str, int],
    ) -> AgentTokenRow:
        """Collapse per-(agent, model) accumulators into one AgentTokenRow for agent_name.

        Single pass: collect per-model token totals, then compute cost once per model.
        """
        # Collect per-model token counts in one pass over input_acc keys.
        # Other accs share the same key set, so we only need to iterate once.
        per_model: dict[str, list[int]] = {}  # model -> [in, out, cr, cw]
        for (n, m) in input_acc:
            if n != agent_name:
                continue
            if m not in per_model:
                per_model[m] = [0, 0, 0, 0]
            per_model[m][0] += input_acc[n, m]
            per_model[m][1] += output_acc.get((n, m), 0)
            per_model[m][2] += cache_read_acc.get((n, m), 0)
            per_model[m][3] += cache_write_acc.get((n, m), 0)

        models_used = sorted(m for m in per_model if m)
        total_input = sum(v[0] for v in per_model.values())
        total_output = sum(v[1] for v in per_model.values())
        total_cr = sum(v[2] for v in per_model.values())
        total_cw = sum(v[3] for v in per_model.values())

        if per_model:
            cost = sum(
                compute_cost(
                    input_tokens=v[0],
                    output_tokens=v[1],
                    cache_read_tokens=v[2],
                    cache_creation_tokens=v[3],
                    model=m,
                )
                for m, v in per_model.items()
            )
        else:
            cost = 0.0

        return AgentTokenRow(
            agent=agent_name,
            calls=call_acc[agent_name],
            input_tokens=total_input,
            output_tokens=total_output,
            cache_read_tokens=total_cr,
            cache_write_tokens=total_cw,
            models=models_used,
            est_cost=cost,
        )

    def _accumulate_agent_tokens(  # noqa: S3776 - JSONL line-by-line accumulator; dispatch is irreducible
        self,
        jsonl_file: Path,
        since: datetime,
        input_acc: dict[tuple[str, str], int],
        output_acc: dict[tuple[str, str], int],
        cache_read_acc: dict[tuple[str, str], int],
        cache_write_acc: dict[tuple[str, str], int],
        call_acc: dict[str, int],
    ) -> None:
        """Parse one JSONL file and accumulate token counts into the given dicts."""
        try:
            with open(jsonl_file, encoding="utf-8") as fh:
                for raw_line in fh:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        record = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue

                    if record.get("type") != "assistant":
                        continue

                    msg = record.get("message", {})
                    usage = msg.get("usage")
                    if not usage:
                        continue

                    ts = parse_iso_utc(record.get("timestamp", ""))
                    if ts is not None and ts < since:
                        continue

                    agent_name = record.get("agentName") or "(orchestrator)"
                    model = msg.get("model", "") or ""
                    key = (agent_name, model)

                    input_acc[key] += usage.get("input_tokens", 0)
                    output_acc[key] += usage.get("output_tokens", 0)
                    cache_read_acc[key] += usage.get("cache_read_input_tokens", 0)
                    cache_write_acc[key] += usage.get("cache_creation_input_tokens", 0)
                    call_acc[agent_name] += 1
        except OSError:  # nosec B110 - skip unreadable JSONL files silently
            pass
