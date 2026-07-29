---
name: improve-decompose-sweep
description: Calibrate the decompose-sweep workflow after a completed run. Reads telemetry, identifies patterns (defer reasons, overshoot rate, test failures), proposes threshold and heuristic changes backed by data, patches the workflow YAML, and reports a summary.
allowed-tools: Bash, Read, Edit, Write, Glob, Grep
skills:
  - dancing-bear-rules
---

# Improve Decompose Sweep

Post-run calibration for `workflows/code/decompose-sweep.yaml`. Reads run telemetry, identifies patterns, proposes and applies data-backed changes, then validates and logs the calibration.

## When to Use

- After a `decompose-sweep` workflow run completes
- User says "improve decompose", "calibrate decompose", or "decompose retrospective"
- Recurring calibration pass (monthly, or after 3+ runs)

## Step 1: Collect Telemetry

Run telemetry files land in the workflow's `workspace_dir`. The workflow engine resolves `{work_dir}` to `<cwd>/out/` (see `workflow/cli.py`), so sweep runs write to:

```
out/decompose-sweep/run-metrics.json
out/decompose-sweep/run-<timestamp>/run-metrics.json
```

```bash
# Find all sweep run telemetry files
find out/decompose-sweep -name "run-metrics.json" | sort

# Read the most recent
find out/decompose-sweep -name "run-metrics.json" | sort | tail -1 | xargs cat
```

Fallback — if no telemetry files exist (e.g., run was aborted, workspace cleaned), parse agent summary messages from conversation context and note the source in the calibration log entry.

## Step 2: Analyze Patterns

From the collected metrics, compute:

**Defer rate by reason**
How often each defer heuristic triggered. High rates indicate a threshold is too aggressive.

| Reason | Count | % of candidates |
|--------|-------|-----------------|
| file_not_large_enough | N | N% |
| has_open_pr | N | N% |
| recently_modified | N | N% |
| imports_too_tangled | N | N% |

**Overshoot rate**
Files that were split but output modules still exceed the target line count. Indicates the `plan-splits` stage is over-estimating how cleanly a file divides.

**Test failure domains**
Which domains produced failing tests post-split. Cluster by root cause:
- Import errors (re-export facade incomplete)
- Missing shared fixtures (not extracted to shared submodule)
- Circular dependencies introduced

**Strategy accuracy**

| Strategy | Used | Met target | Avg lines saved | Avg output max |
|----------|------|------------|-----------------|----------------|
| extract-submodules | N | N% | N | N |
| extract-package | N | N% | N | N |
| split-tests-by-class | N | N% | N | N |
| extract-helpers | N | N% | N | N |

## Step 3: Calibrate

Propose changes with data citations. Each proposal must name the metric that motivates it.

**Threshold adjustments** — only lower if the defer rate for `file_not_large_enough` exceeds 40% across 3+ runs. Only raise if > 20% of splits produce files that still exceed target.

**Defer heuristic changes** — add a new heuristic only if the same pattern appears in 2+ runs. Remove one only if it has a 0% trigger rate across 3+ runs.

**Strategy selection improvements** — adjust strategy criteria if a strategy's "met target" rate is below 60% on 3+ uses.

**New verification steps** — propose only if the same root-cause test failure category appears in 2+ runs.

## Step 4: Patch the Workflow

Apply approved calibration changes directly to `workflows/code/decompose-sweep.yaml`:

- **Threshold changes**: edit `trigger.params` (line-count thresholds passed to the sweep)
- **Defer heuristic changes**: edit the `plan-splits` stage description where defer criteria are listed
- **Strategy criteria changes**: edit the `plan-splits` stage description where strategy selection logic is described
- **New verification steps**: edit the `verify-tests` stage description

After each edit, lint and compile:

```bash
./bin/workflow lint workflows/code/decompose-sweep.yaml
./bin/workflow compile workflows/code/decompose-sweep.yaml
```

If lint fails, fix before proceeding — do not log a calibration entry for a broken workflow.

## Step 5: Update Calibration Log

Append a one-line-per-change entry to the top comment block of `workflows/code/decompose-sweep.yaml`:

```yaml
# Calibration log:
# 2026-07-28 raise source_threshold 700→800: overshoot rate 28% over 4 runs
# 2026-07-28 add defer heuristic has_active_milestone: appeared in 3 consecutive runs
```

Bump `version` in the workflow metadata field (e.g., `"1.0"` → `"1.1"`).

## Step 6: Report

```
## Decompose Sweep Calibration — <date>

### Run Stats (last <N> runs)
- Files scanned: N
- Deferred: N (N%)
- Split: N
- Overshoot: N (N%)
- Test failures: N

### Changes Applied
- <change 1> — motivated by <metric>
- <change 2> — motivated by <metric>

### Proposed but Deferred (need more data)
- <change> — only N run(s), need 3

### Prediction for Next Run
Expected defer rate: ~N% | Expected overshoot rate: ~N%
```

## Anti-Patterns to Avoid

- **Lower thresholds without data**: need 3+ runs before reducing any threshold
- **Change strategy criteria on one failure**: wait for 2+ occurrences of the same root cause
- **Touch passing parts of the workflow**: only edit what the data implicates
- **Skip lint after patching**: always validate — a broken workflow is worse than the status quo
- **Log entries without metric citations**: every calibration line must name the data that motivated it
