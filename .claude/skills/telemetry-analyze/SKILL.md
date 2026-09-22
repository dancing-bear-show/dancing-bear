---
name: telemetry-analyze
description: Analyze Claude Code session cost, efficiency, and usage using dancing-bear's telemetry module. Use for cost reviews, model comparisons, session performance analysis, and identifying expensive patterns.
allowed-tools:
  - Bash
  - Read
  - Task
---

# Telemetry Analysis

Analyze Claude Code session cost, efficiency, and usage using `./bin/telemetry`.

## When to Use

- Weekly/monthly cost reviews
- Model efficiency comparisons
- Session performance analysis
- Budget forecasting and anomaly detection
- Identifying high-cost or high-tool-call sessions

## Data Source

`./bin/telemetry` reads `~/.claude/projects/<project>/*.jsonl` transcripts directly (recursive — one directory per project, plus older `*/subagents/` layouts) — no setup, no collector, always works.

## What This Skill Does

### 1. Gather Session Data

```bash
./bin/telemetry history -d 7     # Sessions from last 7 days
./bin/telemetry summary          # Current session detail (tokens, cost, top tools)
./bin/telemetry cost --since 7d --group-by day   # Daily cost breakdown
```

### 2. Generate Analysis Report

Synthesize the command output into a markdown report with:
- **Cost Summary**: Total spend, session count, cost per session
- **Model Breakdown**: Opus vs Sonnet vs Haiku usage and cost
- **Tool Usage**: Top tools by call count from `summary` output
- **Session Outliers**: Highest-cost and most-active sessions
- **Recommendations**: Model downgrade opportunities, session consolidation

### 3. Optional: Time Window

```bash
./bin/telemetry history -d 14    # Last 14 days
./bin/telemetry cost --since 30d --group-by day  # Last 30 days
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
   - Summary (total cost, session count, dominant model)
   - Model analysis (cost and token usage by tier)
   - Session outliers (highest cost, most events)
   - Recommendations

### Example Output

```markdown
# Telemetry Cost Analysis Report
**Generated**: 2026-06-19

## Cost Summary
- Sessions: 8   Total Cost: $42.10
- Dominant model: Sonnet

## Cost by Model (last 7 days)
| Date       | Opus  | Sonnet | Haiku |   Cost |
|------------|-------|--------|-------|--------|
| 2026-06-19 | 0     | 1.2M   | 0     |  $6.30 |
| 2026-06-18 | 0     | 980K   | 45K   |  $5.40 |

## Session Outliers
- Highest cost: abc123… $12.50 (Sonnet, 1,240 events)
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
Task(subagent_type="fact-checker", prompt="""
Validate the telemetry analysis report. Check: cost totals match
their line-item breakdowns, date ranges are consistent, model tier
labels (opus/sonnet/haiku) match the raw data, and any percentage
claims are arithmetically correct.
""")
```

## Notes

- Transcript data lives in `~/.claude/projects/` — always available, no collector needed
- The `telemetry` module source is at `src/telemetry/` (the `telemetry/` directory at the repo root is stale `__pycache__` only)
- `telemetry rules` manages *classification* rules (`--init` scaffolds
  `~/.telemetry-transcripts/rules.yaml`, `--validate` checks them, `--explain NAME`
  shows one). There is no waste-classification system behind it, so for cost and
  efficiency questions focus on cost and tool-call counts rather than expecting
  `rules` to label waste for you.

## Related Skills

- `rename-session` — on-demand tmux session rename
- `install-tmux-namer` — set up automatic session naming
- `dancing-bear-rules` — repo rules and constraints
