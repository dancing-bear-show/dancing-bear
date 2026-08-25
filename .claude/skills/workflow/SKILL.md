---
name: workflow
description: Execute a workflow definition. Parses YAML, compiles DAG, walks parallel groups, spawns agents per stage, handles human gates and validation.
allowed-tools: Agent, Bash, Read, Write, Edit, Glob, Grep, Task, TeamCreate, TeamDelete, SendMessage, TaskCreate, TaskUpdate, TaskList, TaskGet, Skill
skills:
  - dancing-bear-rules
---

# Workflow — DAG Execution Engine

Parse a workflow YAML definition, compile it into a parallel execution plan, walk each group by spawning the appropriate agent type, handle human gates, run validation passes, and report results.

## When to Use

- User says "run workflow X", "execute workflow X", or references a file in `workflows/`
- User wants to preview a workflow execution plan (`--dry-run`)
- User wants to resume a halted workflow from a human gate

## Usage

```
/workflow workflows/test/coverage-report.yaml
/workflow workflows/test/coverage-report.yaml --execute
/workflow workflows/test/coverage-report.yaml --workspace out/my-run
/workflow workflows/test/coverage-report.yaml --params min_coverage=80
```

## Input Parsing

Extract these arguments from the user's request or skill args:

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--workflow` / positional | Yes | -- | Path to YAML file in `workflows/` |
| `--execute` | No | false | Actually run the workflow (default is dry-run/preview) |
| `--workspace` | No | `out/{name}-{run_id}` | Override workspace directory |
| `--params` | No | -- | Trigger parameter overrides as `key=value` pairs |

---

## Execution Flow

### Step 0: Parse and Compile

Parse `--params` arguments into a dict. Then compile the workflow:

```bash
.venv/bin/python bin/workflow compile <WORKFLOW_PATH> --format json
```

This prints the compiled manifest as JSON. The top-level keys are:

| Key | Contents |
|---|---|
| `groups` | `[{group, stages, parallelism}]` — `stages` is a comma-joined string, in execution order |
| `resolutions` | one entry per stage: `{stage, template_resolved, guide_resolved, cli_commands, agent_role, agent_model, agent_isolation}` |
| `contract_warnings_detail` | `[{stage, upstream, message}]` |

Read `groups` for execution order and `resolutions` for each stage's agent
spec — including `agent_isolation`, which must reach `Agent()` (see step 2a).
If compile fails, report the error and stop.

**If `--execute` is NOT set (dry-run):** print the execution plan and stop:

```bash
.venv/bin/python bin/workflow compile <WORKFLOW_PATH>
```

### Step 1: Initialize Workspace

```bash
.venv/bin/python bin/workflow init-workspace <WORKFLOW_PATH> \
  [--workspace <WORKSPACE>] [--params key=value ...]
```

This prints the workspace path. Store it. If `--workspace` was provided, pass
it. The workspace will contain `manifest.json`, `stages/`, `outputs/`,
`validation/`, and `dispatch/` subdirectories.

Generate a `RUN_ID` in the format `{workflow_name}-{YYYYMMDD}-{8_hex_chars}`.

### Step 2: Walk Parallel Groups

**Critical rules for agent sessions:**

1. **One stage per agent.** Never bundle multiple stages into one agent session.
   Each stage gets its own agent.

2. **Strict DAG ordering.** Never spawn a stage until ALL stages in previous
   groups have completed and written their result files.

3. **CLI-only for external queries.** Agents must use `./bin/<tool>` CLI
   commands. Use `--agentic` or `--help` to probe CLIs; never run commands
   that create external resources in gather/execute/validate stages.

4. **Always spawn agents in the background.** Use `run_in_background=True` on
   every `Agent()` call. This allows parallel stages to run concurrently and
   keeps the main conversation responsive.

5. **Never use data from prior runs or prompt context.** Each stage must read
   ONLY from the current workspace.

6. **Never publish or create external resources unless the stage is explicitly
   a `kind: publish` stage.** Only publish stages may run `gh pr create`,
   post comments, or write outside the workspace.

7. **`isolation: worktree` for code-writer agents requires an explicit merge
   step before validate.** After all parallel code-writers in a group complete,
   merge their worktree branches before spawning any validate stage:

   ```bash
   git merge --no-ff worktree-agent-{id} -m "merge stage {stage_name}"
   ```

   Read-only agents (researcher, reviewer, Explore, unit-validator) do not
   need merging.

8. **Validate stages must wait for all implementation output to exist.** Before
   spawning a validate agent, verify every file in `reads_from` stage's
   `writes_to` list exists at `{workspace}/{file}`. If any is missing, wait.

9. **`kind: sub-workflow` stages run inline via the `/workflow` skill:**
   ```python
   Skill(skill="workflow", args="--workflow <stage.sub_workflow> --execute ...")
   ```
   Do NOT spawn an agent — agents cannot invoke skills.

Iterate through `groups` (from the compiled manifest) in order. For each group:

#### 2a. Spawn Agents

**Inline stages run directly — no agent spawned.** Check `stage.spec.executor`:

```python
if stage.spec.executor == "inline":
    # Run Bash commands from the stage description directly.
    # Write output files with the Write tool.
    # Write stage result JSON to {workspace}/stages/{index:03d}-{stage_name}.json.
    continue  # skip agent-spawn path
```

**Create a team for the workflow run (once per invocation):**

```python
team_name = None
try:
    TeamCreate(
        team_name=f"wf-{workflow_name}-{run_id[:8]}",
        description=f"Workflow {workflow_name} run {run_id}",
    )
    team_name = f"wf-{workflow_name}-{run_id[:8]}"
except Exception as _team_err:
    # Already inside a team or transient error — run without sub-team panes.
    team_name = None
```

**Before spawning any agent**, check for an existing successful result:

```python
result_file = f"{workspace}/stages/{index:03d}-{stage_name}.json"
# If result_file exists and status == "success": skip this stage
```

**Parallel group:** Spawn one background agent per incomplete stage in the same
message so they run concurrently.

**Sequential group:** Spawn one agent.

**`description` is required on every Agent call.**

```python
agent_kwargs = dict(
    description=f"Stage {stage_name} — {stage_kind}",
    subagent_type=ROLE_MAP[stage.agent.role],
    run_in_background=True,
    prompt="...",
)
if team_name:
    agent_kwargs["name"] = stage_name
    agent_kwargs["team_name"] = team_name
# REQUIRED: a stage declaring `agent.isolation: worktree` must receive it here.
# Normalize first — the two stage representations spell this differently, and
# `compile --format json` yields plain dicts with no `.agent` attribute:
#   - compiled manifest: resolutions entry, key "agent_isolation"
#   - parsed definition: stage.agent.isolation
isolation = (
    stage.get("agent_isolation")
    if isinstance(stage, dict)
    else getattr(stage.agent, "isolation", None)
)
# Omitting this is what made `isolation: worktree` a no-op: the YAML read as
# isolated while parallel code-writers shared one tree and interleaved edits.
if isolation:
    agent_kwargs["isolation"] = isolation
Agent(**agent_kwargs)
```

**Never drop `isolation`.** If a stage declares it, the spawned agent must get
it. A workflow whose stages say `isolation: worktree` but whose agents share a
tree will silently produce interleaved edits, and any later `git merge
worktree-agent-*` step will fail because no such branch was ever created.

Map `stage.agent.role` to `subagent_type`:

| Agent Role | subagent_type |
|------------|---------------|
| `researcher` | `researcher` |
| `code-writer` | `code-writer` |
| `doc-writer` | `doc-writer` |
| `reviewer` | `reviewer` |
| `tester` | `tester` |
| `critic` | `critic` |
| `unit-validator` | `unit-validator` |
| `cross-unit-validator` | `cross-unit-validator` |
| `fact-checker` | `fact-checker` |

If `stage.agent.model` is set explicitly in the YAML, pass `model=` on the
Agent call. Otherwise omit it and inherit the session model.

#### 2b. Build Agent Prompts

For each stage, construct the prompt:

1. **File access rules** (prepend to every prompt):

   > File access rules: use the Read tool (not cat/head/tail), Grep tool (not grep/rg in Bash), Glob tool (not find/ls). Reserve the Bash tool for CLI commands and subprocess execution only. Cache file contents after the first Read — never call Read on the same path twice. After editing a file with Edit, do NOT re-read it to verify. The only exception: reading a file for the first time after a different agent wrote it.

2. **Workspace lock** (immediately after file access rules):

   > Workspace: {workspace} — write ALL output files under this exact path. Do NOT create subdirectories outside this path.

3. **Input data**: for each entry in `reads_from`, read the actual output files
   now (with the Read tool) and inline relevant content into the prompt. Do NOT
   assume what upstream stages produced — read the files.

4. **Output instructions**: for each entry in `writes_to`, tell the agent to
   write to `{workspace}/{file}`. Path resolution:
   - Bare filenames → `{workspace}/outputs/{name}`
   - Paths starting with `outputs/`, `validation/`, `stages/`, `dispatch/` →
     `{workspace}/{path}` (workspace-root)
   - Other explicit paths → `{workspace}/{path}`

5. **Stage description verbatim**: copy CLI commands exactly as written —
   never paraphrase or substitute command names.

6. **Data provenance rule**:

   > Data provenance rule: use ONLY data from workspace files and CLI command outputs. Do not cite numbers or facts from prompt context. Every claim must trace to a file you read or a command you ran.

7. **Completion**: end every prompt with:

   > Finally, use the Write tool to create {workspace}/stages/{index:03d}-{stage_name}.json with:
   > {"stage_name": "...", "stage_index": N, "status": "success", "started_at": "<ISO8601>", "finished_at": "<ISO8601>", "duration_ms": <ms>, "output_files": [...], "data": {<summary>}, "errors": []}

#### 2c. Collect Results — WAIT FOR ALL AGENTS IN GROUP

**Use Monitor (not bare sleep loops) to wait for stage completion:**

```python
Monitor(
    description=f"Waiting for {stage_name} result + outputs",
    persistent=False,
    timeout_ms=300000,
    command=f"""
until ls {workspace}/stages/{index:03d}-{stage_name}.json 2>/dev/null \
   && ls {workspace}/{writes_to_file} 2>/dev/null; do sleep 5; done
python3 -c "
import json
s = json.load(open('{workspace}/stages/{index:03d}-{stage_name}.json'))
print(f'{stage_name}: {{s[\"status\"]}}')
"
"""
)
```

When waiting for multiple parallel stages, launch one Monitor per stage.

**Reap early finishers within the group.** As each Monitor fires:

```python
result = json.load(open(f"{workspace}/stages/{idx:03d}-{stage_name}.json"))
if result["status"] in ("success", "failed"):
    SendMessage(to=stage_name, message={"type": "shutdown_request"})
    # wait for shutdown_approved, then continue waiting for remaining siblings
```

**Verification before advancing:**

```bash
# Stage result must exist and show success:
python3 -c "import json; s=json.load(open('{workspace}/stages/{N:03d}-{stage}.json')); assert s['status']=='success', s"
# Every writes_to output must exist:
for file in {group_writes_to}; do
    ls {workspace}/${file} || echo "MISSING: ${file}"
done
```

After confirming all results:

1. Read each stage result and check status:
   - Required stage failed → halt and report
   - Optional stage failed → log warning and continue

2. **Output contract checks** (if `validates_output` is set on the stage):
   Read the compiled manifest's `validates_output` list for this stage. For
   each check, verify the file exists and (if `checks: [schema]`) validate
   it against the declared schema. If any check fails, send a correction
   message to the still-open agent, wait up to 1 correction round, re-check.
   Mark the stage failed if checks still fail after 1 correction.

3. **Reap completed agents** before spawning the next group:
   ```python
   for agent_name in completed_group_agents:
       SendMessage(to=agent_name, message={"type": "shutdown_request"})
   # wait for shutdown_approved from each
   ```
   Every group boundary is a reap point. Don't accumulate open agents.

   **`idle_notification` ≠ done.** Agents using Monitor emit
   `idle_notification` while waiting. Never send `shutdown_request` to an
   agent that sent only an `idle_notification`. Wait for a substantive result
   message before reaping.

4. Check for human gates (see Step 3).

5. Only then proceed to the next group.

### Step 3: Human Gate Handling

When a stage has `human_gate: true` and completed successfully:

1. Read and display the stage's output files to the user.
2. Present a summary of what was produced.
3. Wait for user input:
   - `approve` — continue to the next group
   - `reject` — halt the workflow
   - `drop N` — remove finding/item N, rewrite the file, continue
   - `edit N field=value` — modify item N, rewrite the file, continue
   - `add: "description"` — append a new item, rewrite the file, continue
4. After amendments, write an updated stage result reflecting the edits.

### Step 4: Validation Stages

For validation stages, build the prompt from the stage's `ValidationSpec`
(criteria + max_revisions) and the target data from `reads_from` stages.

#### Strategy: `unit`

Spawn parallel `unit-validator` agents, one per unit in the output list.

#### Strategy: `cross_unit`

Spawn a single `cross-unit-validator` agent across all outputs.

#### Strategy: `adversarial`

Two waves:
1. **Challengers**: reviewer agents challenge claims → write to `{workspace}/validation/challenges/`
2. **Evidence**: researcher agents gather evidence → write to `{workspace}/validation/evidence/`

Then apply corrections to source outputs.

#### Strategy: `deliverable`

Spawn a single `unit-validator` with goal-driven criteria from the stage spec.

#### Strategy: `fact_check`

Spawn a single `fact-checker` agent.

#### Findings Format

All validators write findings as a JSON array:

```json
[
  {
    "id": "F-001",
    "status": "PASS | FAIL | WARN",
    "claim": "...",
    "expected": "...",
    "actual": "...",
    "severity": "critical | minor | info",
    "category": "accuracy | consistency | completeness | cross_reference",
    "source": "<file or CLI command used to verify>",
    "fix": "..."
  }
]
```

Write findings to `{workspace}/validation/{stage_name}-findings.json`.

### Step 5: Completion

After all groups have executed:

1. Read all stage results from `{workspace}/stages/`.
2. Compute summary: total stages, succeeded, failed, skipped, total duration.
3. Report final status: `success`, `failed`, or `halted`.
4. List output files with their paths.
5. **Shut down the workflow team:**
   ```python
   for agent_name in last_group_agents:
       SendMessage(to=agent_name, message={"type": "shutdown_request"})
   # wait for shutdown_approved
   TeamDelete()
   ```

---

## Agent Prompt Templates

### Prompt Construction Rules

1. **Lead with the action.** First sentence: an imperative naming a tool and
   what to do. Background goes after.

2. **No fenced code blocks for commands.** Write CLI commands as plain indented
   text under "Execute with the Bash tool:".

3. **Name the tools explicitly.** "Use the Bash tool to run:" not "run".

4. **Completion is the last instruction.** End with "Finally, use the Write
   tool to create {result_path} with {result_json}."

5. **Two-action minimum for CLI stages: Bash then Write.**

6. **Prepend file access rules and workspace lock to every prompt.**

### Gather Stage (researcher)

```
File access rules: use the Read tool (not cat/head/tail), Grep tool (not grep/rg in Bash), Glob tool (not find/ls). Reserve the Bash tool for CLI commands only. Cache file contents after the first Read.

Workspace: {workspace} — write ALL output files under this exact path.

Data provenance rule: use ONLY data from workspace files and CLI command outputs. Every claim must trace to a file you read or a command you ran.

Stage: {stage_name} in workflow {workflow_name}

{stage_description}

Output files to produce:
  {workspace}/{writes_to file 1}
  {workspace}/{writes_to file 2}

Finally, use the Write tool to create {workspace}/stages/{index:03d}-{stage_name}.json with:
{"stage_name": "{stage_name}", "stage_index": {index}, "status": "success",
 "started_at": "<ISO8601>", "finished_at": "<ISO8601>", "duration_ms": <ms>,
 "output_files": [<paths written>], "data": {<brief summary>}, "errors": []}
```

### Execute Stage (code-writer / doc-writer / tester)

```
File access rules: use the Read tool (not cat/head/tail), Grep tool (not grep/rg in Bash), Glob tool (not find/ls). Reserve the Bash tool for CLI commands only. Cache file contents after the first Read.

Workspace: {workspace} — write ALL output files under this exact path.

Data provenance rule: use ONLY data from workspace files and CLI command outputs.

Use the Read tool to load these input files:
  {workspace}/{reads_from stage 1's writes_to file}
  {workspace}/{reads_from stage 2's writes_to file}

Stage: {stage_name} in workflow {workflow_name}

{stage_description}

Output: use the Write (or Edit) tool to create {workspace}/{writes_to path}.

Finally, use the Write tool to create {workspace}/stages/{index:03d}-{stage_name}.json with:
{"stage_name": "{stage_name}", "stage_index": {index}, "status": "success",
 "started_at": "<ISO8601>", "finished_at": "<ISO8601>", "duration_ms": <ms>,
 "output_files": [<paths written>], "data": {<brief summary>}, "errors": []}
```

### Inline Stage (executor: inline — runs in main orchestrator session)

No agent is spawned. The orchestrator executes the stage directly:

1. Use the Bash tool for each command in the stage description.
2. Use the Write tool to create each file in `writes_to` at
   `{workspace}/{file}` (workspace-relative path as written in the YAML).
3. Write the stage result at `{workspace}/stages/{index:03d}-{stage_name}.json`.

On any command failure, set `"status": "failed"` and populate `"errors"`. If
`required: true`, halt the workflow after writing the result file.

### Validation Stage (unit-validator / reviewer / fact-checker)

```
File access rules: use the Read tool (not cat/head/tail), Grep tool (not grep/rg in Bash), Glob tool (not find/ls). Reserve the Bash tool for CLI commands only. Cache file contents after the first Read.

Workspace: {workspace} — write ALL output files under this exact path.

Data provenance rule: use ONLY data from workspace files and CLI command outputs. Every claim must trace to a file you read or a command you ran.

Use the Read tool to load:
  {workspace}/{reads_from stage's writes_to files}

Stage: {stage_name} — validating outputs from {source_stage} in workflow {workflow_name}
Strategy: {validation_strategy}

Criteria:
{criteria, one per line}

Return findings as a JSON array. Each finding:
{"id": "F-NNN", "status": "PASS|FAIL|WARN", "claim": "...", "expected": "...",
 "actual": "...", "severity": "critical|minor|info", "category": "...",
 "source": "<file or command>", "fix": "..."}

Use the Write tool to create {workspace}/validation/{stage_name}-findings.json.
Use the Write tool to create {workspace}/validation/{stage_name}-summary.md.

Finally, use the Write tool to create {workspace}/stages/{index:03d}-{stage_name}.json with:
{"stage_name": "{stage_name}", "stage_index": {index}, "status": "success",
 "started_at": "<ISO8601>", "finished_at": "<ISO8601>", "duration_ms": <ms>,
 "output_files": ["...findings.json", "...summary.md"], "data": {<counts>}, "errors": []}
```

---

## Error Handling

### Parse/Compile Failure

Report the error from `./bin/workflow compile` and stop.

### Stage Execution Failure

Required stage failed:
1. Write the failure result to `{workspace}/stages/`.
2. Report which stage failed and the error.
3. Halt — do not run downstream stages.

Optional stage failed:
1. Write the failure result.
2. Log the failure.
3. Continue (downstream stages that `reads_from` this stage receive empty input).

### Validation Failures — Correction Cycle

If validation finds **critical** findings:

1. Count critical findings. If zero, continue.
2. Check `max_revisions`. If 0, halt and report unresolved issues.
3. Spawn a **correction agent** (same role as the execute stage that produced the output):
   ```python
   Agent(
       description=f"Fix {N} critical findings in {output_file}",
       subagent_type="doc-writer",  # or whatever produced the original output
       prompt=f"""
   Fix ONLY the critical findings listed below. Do not rewrite sections that passed.
   Every correction must be traceable to source data in the workspace.

   Critical findings:
   {list each with: claim, expected, actual, fix}

   Source data:
   {reads_from paths}

   Overwrite: {workspace}/{output_file}
   Write correction log: {workspace}/validation/corrections-applied.json
   """,
       ...
   )
   ```
4. After correction completes, re-run the validation stage (decrement `max_revisions`).
5. If critical findings remain after `max_revisions` cycles, halt and report.

---

## Resume Support

**Always check for existing results before spawning agents** — same logic for
fresh runs and resumes.

Before spawning an agent for any stage:

```bash
ls {workspace}/stages/*-{stage_name}.json 2>/dev/null
```

- `"success"` → skip, use existing result
- `"failed"` or `"pending"` → re-run
- File missing → run (never attempted)

### Resuming a specific workspace

If the user provides a workspace path (e.g., "resume out/coverage-report-..."):

1. Read `{workspace}/manifest.json` to get the YAML path and trigger params.
2. Re-parse and re-compile the workflow.
3. Scan `{workspace}/stages/` for existing results.
4. For each parallel group:
   - All stages `success` → skip the group
   - Any missing or failed → run only those stages
5. Continue with remaining groups.

### Forcing a re-run

If the user says "re-run stage X":
- Delete `{workspace}/stages/*-{stage_name}.json`
- Delete `{workspace}/{stage_writes_to_files}`
- Re-run the stage.

---

## Fan-Out Stages

If a stage has `fan_out` defined, check `fan_out.mode`:

### mode: agent (default)

1. Read the output file from the `fan_out.source` stage.
2. Parse JSON and extract the array at `fan_out.field`.
3. For each item, spawn a separate background agent:
   ```python
   fan_kwargs = dict(
       description=f"Stage {stage_name} — {item[fan_out.key]}",
       subagent_type=ROLE_MAP[stage.agent.role],
       run_in_background=True,
       prompt="...",  # substitute {fan_out.key} value into description + writes_to
   )
   if team_name:
       fan_kwargs["team_name"] = team_name
       fan_kwargs["name"] = f"{stage_name}-{item[fan_out.key]}"
   # Same rule as single-agent stages: isolation must reach Agent(), and the
   # value must be normalized first because a compiled-manifest stage is a
   # plain dict with no `.agent` attribute. Fan-out writers sharing one tree is
   # the worst case: N agents, same files.
   isolation = (
       stage.get("agent_isolation")
       if isinstance(stage, dict)
       else getattr(stage.agent, "isolation", None)
   )
   if isolation:
       fan_kwargs["isolation"] = isolation
   Agent(**fan_kwargs)
   ```
4. All fan-out agents run in parallel (same group).
5. Collect all results (one Monitor per agent) before advancing.
6. Each fan-out agent writes its result to
   `{workspace}/stages/{index:03d}-{stage_name}-{item_key}.json`.

### mode: worker_queue

Headless, CLI-only fan-out — no agents spawned. The Python dispatcher
(`workflow/dispatchers.py`'s `WorkerQueueDispatcher`) enqueues one
`Job(type="workflow_stage")` per fan-out item via `worker.queue.enqueue`,
substituting `{key}` into `fan_out.script`. Each job returns `pending`
immediately; a worker (`./bin/worker run-once` or the daemon) processes it
asynchronously via `worker/handlers.py`'s `handle_workflow_stage`. Same
applies to a single stage with `executor: worker_queue` (no `fan_out`
needed). See `workflows/demo/worker-queue-stage.yaml` and
`workflows/demo/worker-queue-fanout.yaml` for runnable examples.
