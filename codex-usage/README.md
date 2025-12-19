Codex Usage Utilities

Small, local CLI to parse Codex/Codex‑CLI usage from `~/.codex` and export daily summaries.

What it reports
- Daily token usage (sum of per‑call `last_token_usage`): input, cached input, output, reasoning, total
- Prompt counts from `~/.codex/history.jsonl`
- ToolCall counts from `~/.codex/log/codex-tui.log`
- Top individual calls by total tokens

Quick start
- Summarize last 24h (UTC window):
  - `python3 code/personal/codex-usage/codex_usage.py summarize --since 24h`
- Export daily CSV for a date range:
  - `python3 code/personal/codex-usage/codex_usage.py export-daily --start 2025-10-01 --end 2025-11-04 --out code/personal/codex-usage/out/daily.csv`
- List top calls (by total tokens) in the last 24h:
  - `python3 code/personal/codex-usage/codex_usage.py top-calls --since 24h --limit 10`

Cost estimation (configurable)
- Estimate cost for a window with example default rates (USD per 1K tokens):
  - `python3 code/personal/codex-usage/codex_usage.py estimate-cost --since 30d`
  - Defaults (edit via rates file or flags): input=0.0050, cached=0.0010, output=0.0150, reasoning=0.0300
- Provide a rates JSON file:
  - `python3 code/personal/codex-usage/codex_usage.py estimate-cost --since 30d --rates code/personal/codex-usage/rates.example.json`
- Override rates inline:
  - `python3 code/personal/codex-usage/codex_usage.py estimate-cost --since 7d --r-in 0.004 --r-cached 0.001 --r-out 0.012 --r-reason 0.025`
- Export daily cost CSV:
  - `python3 code/personal/codex-usage/codex_usage.py export-daily-cost --start 2025-10-01 --end 2025-11-04 --rates code/personal/codex-usage/rates.example.json --out code/personal/codex-usage/out/daily_cost.csv`

Per‑model breakdown (assumes model names appear in sessions)
- Estimate by model over a window:
  - `python3 code/personal/codex-usage/codex_usage.py estimate-cost-by-model --since 30d --rates-models code/personal/codex-usage/rates.models.example.json`
- Export daily cost by model:
  - `python3 code/personal/codex-usage/codex_usage.py export-daily-cost-by-model --start 2025-10-01 --end 2025-11-04 --rates-models code/personal/codex-usage/rates.models.example.json --out code/personal/codex-usage/out/daily_cost_by_model.csv`

Notes on rates
- Public rate card fetch is behind a web challenge; this repo ships example US‑region assumptions. Replace `rates.*.json` with your official rates.
- Fallback behavior: if a model is not listed, the tool applies `default` rates or the closest prefix match (e.g., `gpt-4o-2024-08-06` → `gpt-4o`).

Rates file format
- JSON, e.g. `rates.example.json`:
```
{
  "currency": "USD",
  "per_1k": {
    "input": 0.0050,
    "cached_input": 0.0010,
    "output": 0.0150,
    "reasoning": 0.0300
  }
}
```

Notes
- Timestamps are treated as UTC. Session JSONL timestamps with fractional seconds (e.g. `...123Z`) are supported.
- Only `event_msg` lines with `payload.type == "token_count"` are aggregated; `last_token_usage` is summed to avoid double‑counting cumulative totals.
- This tool is read‑only; it does not modify `~/.codex`.
