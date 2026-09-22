---
name: telemetry-analyze
description: Analyze Claude Code session cost, efficiency, and usage using dancing-bear's telemetry module. Use for cost reviews, model comparisons, session performance analysis, and identifying expensive patterns.
allowed-tools:
  - Bash
  - Read
  - Agent
skills:
  - dancing-bear-rules
---

# Telemetry Analysis

Analyze Claude Code session cost, efficiency, and usage using `./bin/telemetry`.

## When to Use

- Weekly/monthly cost reviews
- Per-session and per-agent cost comparisons (see Model Attribution for what
  "model" can and cannot mean here)
- Session performance analysis
- Budget forecasting and anomaly detection
- Identifying high-cost or high-tool-call sessions

## Data Source

`./bin/telemetry` reads `~/.claude/projects/*/*.jsonl` transcripts directly (plus the older `~/.claude/projects/*/*/subagents/*.jsonl` layout) — no setup, no collector, always works.

## Model Attribution — a limitation to report honestly

**No shipped command produces a per-model-tier cost split.** Do not write an
Opus/Sonnet/Haiku cost table; there is no source for one, so it would be
invented.

What the CLI actually gives you:

- `cost --group-by day` — daily cost totals. The JSON rows carry `day` and
  `est_cost` only, no model field.
- `cost --group-by agent` — per-agent calls and cost, again with no model field.
- `history` — one model per session, taken from the session's **first** API
  event (`src/telemetry/providers/transcript.py:128`).
- `summary` — one model per session, taken from the session's **latest** API
  event (`_latest_model` at `src/telemetry/tui/_summary.py:40-44`, which walks
  `reversed(api_events)`).

**The two commands disagree on purpose-built different rules, so do not treat
their model fields as interchangeable.** For a session that switched tiers,
`history` reports what it started on and `summary` reports what it ended on;
neither is wrong, and neither is "the" model for that session. If a report
quotes a model, name which command it came from.

So "dominant model" is not something either command gives you. A per-tier cost
breakdown is not available at all. If someone needs one, the accumulator already
exists internally (`totals["models"]` at `transcript.py:290`) and would need
exposing through a CLI flag first — that is a code change, not something this
skill can work around.

## What This Skill Does

### 1. Gather Session Data

```bash
./bin/telemetry history -d 7                        # Sessions from last 7 days
./bin/telemetry summary                              # Current session detail (tokens, cost, top tools)
./bin/telemetry cost --since 7d --group-by day       # Daily cost totals (no per-model split — see Model Attribution)
./bin/telemetry cost --since 7d --group-by agent     # Per-agent cost and call counts
```

### 2. Generate Analysis Report

Synthesize the command output into a markdown report with:
- **Cost Summary**: Total spend, session count, cost per session
- **Session models**: the per-session model, labelled with which command it came
  from — `history` reports the session's first API event, `summary` its latest
  (see Model Attribution). Not a "dominant model", and not a per-tier cost
  split, which no shipped command produces
- **Tool Usage**: Top tools by call count from `summary` output
- **Session Outliers**: Highest-cost and most-active sessions
- **Recommendations**: session consolidation, and model-downgrade candidates
  inferred from per-session models plus per-agent cost — not from a per-tier
  cost split, which is unavailable

### 3. Optional: Time Window

```bash
./bin/telemetry history -d 14                        # Last 14 days
./bin/telemetry cost --since 30d --group-by day       # Last 30 days
```

### 4. Output Options

```
/telemetry-analyze               # Markdown report to stdout
/telemetry-analyze --days 14     # Adjust lookback window
/telemetry-analyze --focus cost  # Emphasize cost breakdown
/telemetry-analyze --focus tools # Emphasize tool usage patterns
```

## Implementation Details

### Command Execution Flow

1. Gather history:
   ```bash
   ./bin/telemetry history -d 7
   ```

2. Gather cost breakdown:
   ```bash
   ./bin/telemetry cost --since 7d --group-by day
   ```

3. Gather current session detail:
   ```bash
   ./bin/telemetry summary
   ```

4. Synthesize into a report covering:
   - Summary (total cost, session count)
   - Per-day cost trend (`cost --group-by day`)
   - Per-agent cost (`cost --group-by agent`)
   - Session outliers (highest cost, most events)
   - Recommendations

### Example Output

```markdown
# Telemetry Cost Analysis Report
**Generated**: 2026-06-19

## Cost Summary
- Sessions: 8   Total Cost: $42.10

## Cost by Day (last 7 days)
| Date       |   Cost |
|------------|--------|
| 2026-06-19 |  $6.30 |
| 2026-06-18 |  $5.40 |

## Cost by Agent (last 7 days)
| Agent           | Calls |   Cost |
|-----------------|-------|--------|
| (orchestrator)  |  1240 | $28.40 |
| coverage-sweep  |   180 |  $6.10 |

## Session Outliers
- Highest cost: abc123… $12.50 (1,240 events, first model per `history`: Sonnet)
- Most active:  def456… 2,100 events $8.20

## Recommendations
- Consider Haiku for short lookup sessions
- 3 sessions had >500 events — review for redundant tool calls
```

## Integration with Other Skills

- **Use before**: Cost sections in postmortems or budget reviews
- **Use after**: Large refactors or test runs to assess cost impact
- **Pair with**: `rename-session` to track which session generated which cost

## Fact-Check

After composing a cost analysis, spawn a `fact-checker` agent:

```python
Agent(subagent_type="fact-checker", description="Validate telemetry report", prompt="""
Validate the telemetry analysis report. Check: cost totals match
their line-item breakdowns, date ranges are consistent, any percentage
claims are arithmetically correct, and — most importantly — that the
report does not present a per-model-tier cost split. No shipped
telemetry command produces one, so such a table would be fabricated.
A single per-session model is fine when the report names which command it came
from, since `history` (first API event) and `summary` (latest) can disagree for
a tier-switching session.
""")
```

## Notes

- Transcript data lives in `~/.claude/projects/` — always available, no collector needed
- The `telemetry` module source is at `src/telemetry/` (the `telemetry/` directory at the repo root is stale `__pycache__` only)
- dancing-bear does not have a `rules` subcommand or waste-classification system; focus analysis on cost and tool-call counts

## Related Skills

- `rename-session` — on-demand tmux session rename
- `install-tmux-namer` — set up automatic session naming
- `dancing-bear-rules` — repo rules and constraints
