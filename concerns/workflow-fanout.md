# Workflow Fan-Out and Output Contract Guide

## When loaded

Load this guide when the diff contains workflow YAML files using fan-out patterns
or `worker_queue` — stages with `fan_out:`, `executor: worker_queue`, or multi-agent
parallel patterns. Fan-out, worker-queue, and output-contract concerns are split into
this file; fragment/include/skill-sync concerns live in `workflow-fragments.md`;
general workflow concerns live in `workflow.md`.

## Concerns

### parallel-fan-out-missing-fragment
- **severity**: minor
- **check**: Verify that any workflow stage that fans out parallel work over a
  list of items uses the `parallel-fan-out` shared fragment rather than
  duplicating the enqueue → worker-queue → collect boilerplate inline. The
  fragment is at `workflows/shared/parallel-fan-out.yaml` and provides three
  reusable stages: `pf-enqueue`, `pf-process` (sequential single-agent), and `pf-collect`.
- **triggers**: Workflow YAML files that contain a stage with `mode: worker_queue`
  without a corresponding `include` of `workflows/shared/parallel-fan-out.yaml`;
  stage descriptions that manually describe writing per-item job files to a
  `fan-out-jobs/` directory and reading results from `fan-out-results/`.
- **example**: A new workflow adds a `process-items` stage with `fan_out.mode: worker_queue`
  and an inline `pf-enqueue`-style description. The same logic already exists in
  the `parallel-fan-out` fragment — inline duplication means future fixes to the
  enqueue/collect pattern must be made in both places. Include the fragment and
  wire `fan_out_input_file`, `fan_out_task`, and `fan_out_output_file` params
  instead.

### fanout-writes-to-gather-output
- **severity**: major
- **check**: Verify that a fan-out (worker_queue) gather stage declares its own per-item intermediate files in `writes_to`, not the merged output produced later by the collect stage.
- **triggers**: Worker-queue stages whose description writes per-item files named with a variable suffix (e.g. `{team_name}`, `{number}`) but whose `writes_to` lists a bare filename (e.g. `amp-rules.json`) that matches the downstream collect stage's merged output; pairs of gather+collect stages where `writes_to` is identical on both.
- **example**: `gather-amp-rules` (worker_queue fan-out) writes `amp-rules-{team_name}.json` per item but `writes_to: ["amp-rules.json"]`. The workflow engine checks for `amp-rules.json` after the gather group; it does not exist yet (that file is produced by `collect-amp-rules`), so the gather stage is marked failed despite all jobs succeeding. Fix: `writes_to: ["amp-rules-{team_name}.json"]` for the gather stage.

### fanout-fallback-schema-mismatch
- **severity**: critical
- **check**: Verify that the fallback error object written by a worker_queue stage on failure contains all keys that downstream collect and validation stages expect — a fallback with a different schema (missing `rules[]`, wrong type for a field, object where array is expected) causes collect/validation stages to crash or produce wrong aggregates.
- **triggers**: Worker-queue stage descriptions that specify a fallback JSON object on failure (e.g. `{"team": ..., "error": ...}`) whose key set differs from the success-path output schema; downstream collect stages that iterate over per-team files and access fields not present in the fallback; worker-queue fallback descriptions that write a JSON object when the success path writes a JSON array.
- **example**: The `gather-items` worker_queue fallback writes `{"team": ..., "error": "..."}`, but `collect-items` parses each per-team file as an array of rows. A failed fetch produces `{}` where an array is expected — `collect-items` crashes with `TypeError: 'dict' object is not iterable`. Fix: mirror the success-path shape in the fallback — `[]` for an array output, or `{"team": ..., "rules": [], "error": "..."}` for an object output, so collect stages can always merge without branching on type.

### fanout-source-writes-to-order
- **severity**: major
- **check**: Verify that the first file in a stage's `writes_to` list matches the file the fan-out engine uses as the source payload — the engine resolves `fan_out.source` by reading the first `writes_to` entry of the referenced stage.
- **triggers**: Workflow YAML stages used as a `fan_out.source` whose `writes_to` list has more than one entry; fan-out stages where `fan_out.field` cannot be found in the first `writes_to` file because the relevant array lives in the second or later entry; stages whose `writes_to` lists a manifest or index file after the primary output rather than first.
- **example**: `enumerate-targets` has `writes_to: ["manifest.json", "fan-out-index.json"]`. A downstream fan-out stage uses `fan_out.source: enumerate-targets` with `field: items`. The engine reads `manifest.json` (first entry) to resolve `items` — but `items` is in `fan-out-index.json`. Fan-out finds no `items` key and produces zero jobs. Fix: list `fan-out-index.json` first so the top-level `items` array is accessible to the fan-out engine.

### fanout-key-scalar-array
- **severity**: critical
- **check**: Verify that `fan_out.field` points to an array of objects, not an array of plain scalars — the fan-out engine extracts `fan_out.key` as a field within each array element, which fails when elements are strings rather than objects.
- **triggers**: Workflow YAML fan-out stages where `fan_out.key` is set (e.g. `key: team_name`) and the source stage's `writes_to` output description says the field contains an array of strings; fan-out stages that extract a named key from items produced by a stage that serializes plain string lists.
- **example**: `fan_out: {source: list-teams, field: teams_list, key: team_name}` — but `list-teams` writes `{"teams_list": ["sre", "platform", "data"]}`. The engine attempts `item["team_name"]` on each string element, gets `TypeError: string indices must be integers`, and produces zero fan-out jobs. Fix: change the producer to write `{"teams_list": [{"team_name": "sre"}, {"team_name": "platform"}, ...]}` and update the stage description to reflect the object array shape.

### worker-queue-invokes-subprocess-workflow
- **severity**: critical
- **check**: Verify that worker-queue stage scripts never invoke `./bin/workflow run` or
  `Skill(skill="workflow", ...)` as a subprocess — nested workflow invocations run in an
  isolated process with no shared worker context and are silently ignored.
- **triggers**: Any worker-queue stage whose script or description invokes `./bin/workflow`,
  or spawns a `Skill("workflow")` call; agent prompts inside worker-queue stages that say
  "run the workflow" or "invoke the skill".
- **example**: A worker-queue script calls `./bin/workflow run workflows/sub.yaml` — the
  child workflow starts but its output is never surfaced to the parent ledger. Fix: move the
  sub-workflow logic into a direct CLI chain or spawn it as an LLM stage with explicit
  `reads_from` / `writes_to` contracts.

### worker-queue-mode-misplaced
- **severity**: major
- **check**: Verify that parallel/fan-out execution is declared using `executor: worker_queue` with a `script:` field, or `fan_out.mode: worker_queue` — not a bare `mode: worker_queue` at the stage level, which is not a recognized field.
- **triggers**: Workflow YAML stages with a top-level `mode: worker_queue` key outside a `fan_out:` block; stages that describe parallel processing but use `mode:` directly rather than `executor:` or `fan_out.mode:`; fragments advertising worker_queue behavior with neither `executor: worker_queue` nor `fan_out:` present.
- **example**: A stage declares `mode: worker_queue` at the top level — this key is unrecognized by the workflow compiler and silently ignored, so the stage runs sequentially as a single unit instead of fanning out. Fix: use `executor: worker_queue` with `script:` for script-driven parallelism, or `fan_out: {mode: worker_queue, items: [...]}` for item-driven fan-out.

### writes-to-undeclared-output
- **severity**: major
- **check**: Verify that every file a stage may write — including conditional outputs on failure or human-gate update paths — is declared in the stage's `writes_to` list.
- **triggers**: Workflow YAML stage descriptions that mention writing a file where the named file does not appear in the stage's `writes_to` list; stages that conditionally produce diagnostic files on non-success branches.
- **example**: A stage description reads "If `verify` fails, write `verify-failure.txt` with the error detail" but `writes_to` only lists `result.json`. Downstream stages cannot declare the missing file in `reads_from`, and resume/skip logic cannot track whether the artifact was produced. Fix: add `verify-failure.txt` to `writes_to`; write an empty placeholder on success so the file always exists and downstream `reads_from` the stage by name.

### writes-to-unresolved-placeholder
- **severity**: major
- **check**: Verify that `writes_to` entries contain no `{param}` placeholders — the workflow compiler only substitutes trigger params into stage descriptions, not into `writes_to` paths.
- **triggers**: Any workflow YAML stage whose `writes_to` list contains a `{...}` expression; fragment files where `writes_to` uses param names like `{primary_artifact}` or `{report_artifact}` that appear in the parent workflow's `trigger.params`.
- **example**: `writes_to: ["{report_artifact}"]` — the engine never substitutes `{report_artifact}`; the engine and all downstream `reads_from` declarations see the literal string `"{report_artifact}"`, not the resolved path. Fix: expand the path at workflow-authoring time, or use a fixed conventional name like `outputs/report.md`.

### validate-kind-description-ignored
- **severity**: major
- **check**: Verify that stages requiring a custom output contract or using `description` to define their prompt are declared `kind: execute`, not `kind: validate` — the validate prompt builder does not include `stage.description`, so any contract specified there is silently ignored.
- **triggers**: Workflow YAML stages with `kind: validate` whose `description` block contains fan-out tokens (`{index}`), a structured findings schema, or custom behavioral instructions beyond a simple validation directive; `kind: validate` stages with no `outputs` block defining the JSON schema contract.
- **example**: A `validate-concerns` stage uses `kind: validate` and puts the required findings schema plus `{index}` fan-out token in `description`. The validate path builds a generic 'return findings as a JSON array' prompt — the `description` block is dropped. Fix: switch to `kind: execute` and move the contract into a dedicated `outputs` block.

### writes-to-double-outputs-prefix
- **severity**: major
- **check**: Verify that `writes_to` entries do not begin with `outputs/` — these paths are already relative to `{workspace}/outputs/`, so an `outputs/` prefix resolves to `{workspace}/outputs/outputs/...`, causing output-validation mismatches with downstream `reads_from` declarations.
- **triggers**: `writes_to` list entries that begin with the literal string `outputs/`; corresponding stage descriptions or downstream stages that reference the same file without the `outputs/` prefix.
- **example**: `writes_to: ["outputs/manifest.json"]` resolves to `{workspace}/outputs/outputs/manifest.json`, but the next stage reads `{workspace}/outputs/manifest.json`. Post-group output verification finds the file missing and marks the stage failed. Fix: drop the prefix — `writes_to: ["manifest.json"]`.

### work-dir-agent-path-protocol
- **severity**: critical
- **check**: Verify that any `isolation: work-dir` stage instructs its agent to read/write
  via an **absolute path under the agent's OWN worktree cwd** (`{cwd}/inputs/<name>`,
  `{cwd}/outputs/<name>`) — NOT a bare relative path (`inputs/<name>`, `outputs/<name>`)
  and NOT an absolute `{workspace}/...` path. The orchestrator copies each input into
  `{cwd}/inputs/` before signaling proceed; the agent reads and writes absolute-under-own-cwd.
- **triggers**: `isolation: work-dir` stage descriptions using `{workspace}/...` paths
  (these prompt); descriptions telling the agent to read/write a **bare relative** path
  (`inputs/foo.md`, `outputs/bar.json`) (these leak into the shared repo tree); a stage
  that correctly avoids `{workspace}/...` but still uses bare-relative paths.
- **why**: The Write/Read tools resolve a **bare relative path against the orchestrator's
  original CWD (the shared repo tree), NOT the agent's worktree** — so a bare-relative
  read/write escapes the isolation boundary (write → leaks; read → reads the shared tree's
  copy or fails). An absolute `{workspace}/...` path prompts, because the subagent's fresh
  session does not inherit the parent's allow list. The fix is symmetric — the orchestrator
  copies inputs IN (to `{cwd}/inputs/`) and copies outputs OUT (from `{cwd}/outputs/`),
  and the agent uses **absolute paths under its own cwd** in both directions.
- **example**: A concern-sweep fan-out stage (`isolation: work-dir`) says "Read
  `{workspace}/concerns/correctness.md`" (prompts) or "Read `inputs/correctness.md`"
  (bare relative — reads the shared tree). Fix: the orchestrator copies the concern
  guide into `{cwd}/inputs/` and passes the agent its `cwd`; the prompt says
  "Read `<cwd>/inputs/correctness.md` (absolute, under your own worktree cwd)".
  The agent likewise writes `<cwd>/outputs/{index}.json`.

### agent-spec-missing-tools
- **severity**: major
- **check**: Verify that every `agent:` block in a workflow YAML declares an explicit
  `tools:` list — omitting `tools:` causes `AgentSpec.tools` to default to empty, which
  the engine interprets as "all tools allowed". This grants more access than intended.
- **triggers**: Workflow YAML `agent:` blocks that contain `role:`, `model:`, and `access:`
  but no `tools:` key; stages where the agent role has known tool restrictions
  (e.g. `unit-validator`, `researcher`) but no explicit list is declared; any agent block
  on a stage that only needs Read/Write but could accidentally use Bash or Edit without
  the restriction.
- **example**: A `validate-draft` stage uses `role: unit-validator` with no `tools:` key.
  The unit-validator is documented as Read+Write only, but the missing declaration means
  it may use Bash or Edit — mutating repo files instead of only producing findings JSON.
  Fix: add `tools: [Read, Write]` for read/write-only stages; `tools: [Read, Write, Edit]`
  for stages that need to modify existing files; `tools: [Read]` for read-only validators.

### readonly-validate-uses-sonnet
- **severity**: minor
- **check**: Verify that read-only unit-validator and cross-unit-validator stages use `model: haiku` — spawning `model: sonnet` for read-only validation is inconsistent with repo convention and costs approximately 2× more per validation stage.
- **triggers**: Workflow YAML stages with `agent.role: unit-validator` or `agent.role: cross-unit-validator` and `access: read-only` that specify `model: sonnet` or omit `model:` (which inherits the orchestrator default of sonnet); stages with `tools: [Read, Grep]` and no write access that do not declare `model: haiku`.
- **example**: A `validate-catalog-coverage` stage has `access: read-only`, `tools: [Read]`, and `model: sonnet`. Established convention is to use `model: haiku` for read-only unit/cross-unit validation. Fix: set `model: haiku` on all read-only validator stages.

### haiku-agent-writes-to-worktree
- **severity**: critical
- **check**: Verify that Haiku fan-out agents (researcher-haiku, unit-validator, cross-unit-validator) spawned with `isolation: worktree` do NOT write output files to the repo worktree. Haiku agents in isolated worktrees cannot write to repo paths — the Write tool may be blocked at the harness level in certain permission modes. Writing to repo paths in that context silently fails with "Permission denied", leaving downstream stages with missing input.
- **triggers**: Workflow YAML fan-out stages with `model: haiku` (or `role: researcher-haiku`, `role: unit-validator`, `role: cross-unit-validator`) whose `description` instructs agents to write output files to repo-relative paths instead of `{workspace}/...` paths; stages where the Haiku agent's only write target is inside the repo tree rather than the engine-provided workspace.
- **fix**: Write Haiku agent output directly to `{workspace}/outputs/...` paths. If the session's harness blocks workspace writes for Haiku, promote to `model: sonnet` or use an `executor: inline` copy stage after the fan-out to move files from a local staging path into the workspace.
- **example**: An `extract-evidence` fan-out stage uses `role: researcher-haiku` and instructs agents to `Write evidence-staging/{stage_name}.json` (repo-local). In a session where Haiku's Write tool is harness-blocked for repo paths, every agent reports "Permission denied" and the staging dir remains empty, causing all downstream agents to SKIP. Fix: point agents to `{workspace}/outputs/evidence/{stage_name}.json` instead.

### agent-isolation-wrong-key-or-value
- **severity**: critical
- **check**: Verify that stage isolation is declared as `isolation: worktree` under `agent:`. This is the ONLY supported form. `FanOutSpec` has no `isolation` field (see `models.py`), so `fan_out.isolation` is not parsed by anything, and `work-dir` is not a recognised value anywhere in the engine.
- **triggers**: `isolation:` appearing under a `fan_out:` block; the value `work-dir` anywhere; any misspelling of the `isolation` key.
- **note**: Since `_parse_agent` rejects unknown agent keys, a misspelled key now raises `WorkflowParseError` at parse time rather than being silently dropped. An `isolation:` under `fan_out:` is still silently ignored — `_parse_fan_out` does not read it.
- **example**:
  ```yaml
  # bad — fan_out.isolation is not a parsed field; silently ignored
  agent:
    role: researcher
  fan_out:
    mode: worker_queue
    isolation: work-dir

  # bad — "work-dir" is not a supported value; raises WorkflowParseError
  agent:
    role: code-writer
    isolation: work-dir

  # good — the only supported form, for fan-out and single-agent stages alike
  agent:
    role: code-writer
    isolation: worktree
  ```
  The parsed value is carried into the compiled manifest as `agent_isolation`
  and must be passed to `Agent(isolation=...)` by the orchestrator; see
  `.claude/skills/workflow/SKILL.md`. A stage that declares isolation but whose
  agent does not receive it runs in the shared tree, which is how parallel
  code-writers end up interleaving edits to the same file.
