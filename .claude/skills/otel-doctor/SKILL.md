---
name: otel-doctor
description: Diagnose why this repo's local OTel telemetry pipeline isn't working (Colima down, port collision, container not running, env vars not set, or no data flowing) and fix the first failing layer. Use when `telemetry otel <cmd>` reports "OpenTelemetry infrastructure not found", or the user asks why Colima/the otel collector isn't working.
allowed-tools: Bash, Read, Skill
skills:
  - dancing-bear-rules
---

# OTel Doctor

Delegates to `workflows/code/otel-doctor.yaml`.

## When to Use

- `telemetry otel <cmd>` fails with "OpenTelemetry infrastructure not found"
- User asks why Colima or the otel collector isn't working
- After setting up `docker-compose.otel.yaml` for the first time, to confirm it's wired correctly

## How to Run

**IMPORTANT**: Use the `/workflow` skill — do NOT call `./bin/workflow run --execute` directly. It only writes dispatch files and exits (status=pending). The `/workflow` skill is what actually spawns agents, waits for results, and handles human gates.

```python
Skill(skill="workflow", args="--workflow workflows/code/otel-doctor.yaml")
```

No params required.

## Workflow Stages

1. **diagnose** — run 5 checks in order, stop at the first failure: Colima running → Docker daemon reachable → this repo's otel-collector container up (including port-collision detection) → OTEL_*/CLAUDE_CODE_ENABLE_TELEMETRY env vars set in the current shell → data actually flowing to `~/.config/otel/*.jsonl`.
2. **propose-fix** [human gate] — proposes exactly one fix for the first failing check. Never proposes stopping or reconfiguring another project's container to resolve a port collision — always rebinds this repo's `docker-compose.otel.yaml` instead.
3. **apply-fix** — runs the approved command or edit (e.g. `colima start`, `docker compose -f docker-compose.otel.yaml up -d`, rebinding ports, adding the env var block to `~/.zshrc`).
4. **verify** — re-runs the same 5 checks to confirm progress.
5. **report** — summary: diagnosis, fix applied, current state, next steps.

## Known Non-Fixable-In-Process Case

If the first failing check is "env vars set", the workflow cannot fix it from within the current process — a new shell/Claude Code session must start after the vars are exported for telemetry to actually flow. The report stage states this plainly rather than claiming success.
