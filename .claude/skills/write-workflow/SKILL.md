---
name: write-workflow
description: Author a new workflow YAML from a plain-language description. Interviews the user for requirements, drafts the YAML using project conventions, validates it with the workflow engine, and writes the final file. Use when you want to create a new workflow.
allowed-tools: Bash, Read, Write, Glob, Grep
skills:
  - dancing-bear-rules
---

# write-workflow

Author a new workflow YAML from a plain-language description. Interviews the user for requirements, drafts a well-formed YAML that follows project conventions, validates it with the workflow engine, and writes the final file.

## When to Use

- User says "write a workflow for X", "create a workflow that does Y", "I want a workflow to Z"
- User wants to automate a multi-step task as a reusable YAML pipeline
- User needs a new entry in `workflows/` that integrates with the `/workflow` skill

## Relationship to the `workflow-author` agent

This repo also defines a `workflow-author` agent (`.claude/agents/workflow-author.md`). Use this skill for interactive authoring in the current session; delegate to the agent when workflow authoring is one step inside a larger task and you want it done out-of-context.

---

## Step 1 — Interview

Ask the user (or infer from their request) the following. If the initial request already carries enough detail, infer the answers and skip asking.

1. **Name**: short kebab-case identifier (e.g. `mail-label-audit`, `resume-render-sweep`)
2. **Description**: what does this workflow do in one sentence?
3. **Trigger params**: what inputs must the user supply at run time? (e.g. `source_root`, `pr_number`, `min_coverage`). List each param and what it represents.
4. **Stages**: what are the logical steps? For each stage, infer:
   - What kind of work is it? (gather / propose / execute / validate / publish / sub-workflow — see guide below)
   - Which agent role fits best? (see role guide below)
   - Does it depend on the output of an earlier stage?
   - Should a human review and approve the output before the workflow continues? (→ `human_gate: true`)
5. **Fan-out**: does any stage need to run once per item in a dynamic list (e.g. once per file, once per directory group)?
6. **Existing fragments**: should any shared fragment from `workflows/shared/` be included?

   Available fragments (pick any that fit the workflow shape). Each fragment's header comment documents its expected `prefix`, the stage names it injects, and the `trigger.params` the caller must set — read the file before including it.

   **Code quality**
   - **`multi-parallel-scans.yaml`** — Parallel code-quality scans (reuse/duplication, complexity, coverage, security) collated into a unified findings file. Use when you need raw multi-dimension scan output.
   - **`simplify.yaml`** — Reviews all changed files for over-engineering, duplication, and unnecessary abstraction, then applies the cleanups. Use as a quality pass after implementation.
   - **`complexity-reduce.yaml`** — Reduces per-function cognitive complexity for one directory group's flagged files and verifies the result. Pairs with a fan-out over directory groups.
   - **`expand-coverage.yaml`** — Identifies files below a coverage threshold, spawns testers to write missing tests, verifies targets pass. Caller sets `source_root`, `test_path`, `min_coverage`.
   - **`batch-fix-verify.yaml`** — Runs the test suite once after all code changes are applied, with a single targeted retry. Use as a tail after batched edits.

   **Review and validation**
   - **`code-review-swarm.yaml`** — Adversarial code-review swarm: fetch PR diff, sweep concern guides, fan out per-file validators in parallel.
   - **`validate-code.yaml`** — Single-pass code review for focused changes (typically 3–8 changed files). Lighter than the swarm.
   - **`adversarial-validate.yaml`** — Discover units, validate each in parallel, check cross-unit consistency, apply corrections. Use for multi-artifact deliverables.
   - **`validate-and-correct.yaml`** — Lightweight tail: validate findings, apply corrections, re-validate. Use when cross-unit consistency is not required.
   - **`validate-then-render.yaml`** — Fact-check the primary artifact against gathered workspace data, apply corrections, then render.
   - **`plan-critic.yaml`** — Adversarial critique of a plan, design doc, architecture decision, or review summary.
   - **`critique.yaml`** — Standalone entry point wrapping `plan-critic.yaml`.

   **Reporting and orchestration**
   - **`report-generate.yaml`** — Template-driven report generation with a correction + recheck pass. Use when the deliverable is a structured document.
   - **`pr-open-and-wait-ci.yaml`** — Opens a draft PR, marks it ready, polls GitHub Actions to completion, runs qlty. Place as the final include when the workflow ends by opening a PR.
   - **`worker-queue-babysitter.yaml`** — Watches a background worker queue drain after a `worker_queue` stage or fan-out.
   - **`otel-workflow-telemetry.yaml`** — Collects per-run workflow cost/stage telemetry from stage JSON files under each run's workspace.

   **PR and docs**
   - **`pr-describe.yaml`** — Generates or refreshes a PR title and description from the branch diff.
   - **`pr-review-threads.yaml`** — Fetches every PR review thread, triages each, fans out fixes, then replies and resolves.
   - **`sync-docs-on-land.yaml`** — Updates docs that reference changed surfaces once a branch lands.
   - **`prompt-mine-transcripts.yaml`** — Mines session transcripts for recurring prompts and workflow candidates.

Before drafting, summarize your understanding back to the user in a short numbered list and confirm the shape is correct.

---

## Step 2 — Draft the YAML

### Top-level structure (required fields)

```yaml
name: <kebab-case>
version: "1.0"
description: >
  <one to three sentences explaining what the workflow does
  and when to use it>

trigger:
  source: manual
  params:
    <param_name>: ""   # <what the param controls>

stages:
  - ...
```

### Including a fragment

```yaml
include:
  - path: workflows/shared/expand-coverage.yaml
    prefix: cov
    depends_on: [prior-stage]
    reads_from: [prior-stage]
```

The `prefix` is prepended to every injected stage name (`cov-identify-gaps`, …). Downstream `depends_on` must reference the prefixed names.

### Stage field reference

Every stage requires: `name`, `kind`, `description`, `agent` (with `role`). The `required` field is optional — the parser defaults it to `true`. Add it explicitly only when setting `required: false`.

| Field | When to add |
|-------|-------------|
| `depends_on` | Stage must wait for another stage to complete |
| `reads_from` | Stage names whose outputs this stage reads (e.g. `[gather-context]`) |
| `writes_to` | Outputs-relative paths this stage produces under `{workspace}/outputs/` (e.g. `[result.md]`, `[context/data.json]`). Do not include an `outputs/` prefix — the engine adds it |
| `human_gate: true` | A human must approve before the workflow proceeds |
| `validation` | Stage output should be checked before continuing |
| `fan_out` | Stage runs once per item in a dynamic list |
| `when` | Skip condition — stage is skipped unless the expression holds |
| `executor` | `agent` (default), `inline`, `local`, or `skill` |
| `validates_output` | Inline output-contract checks on the files this stage writes |

### Kind selection guide

| Kind | Use when |
|------|----------|
| `gather` | Reading external data, scanning files, querying CLIs |
| `propose` | Drafting a plan or document for human review before acting |
| `execute` | Writing code, docs, configs, or calling create/update APIs |
| `validate` | Reviewing, fact-checking, running tests, quality gates |
| `publish` | External side effects: open a PR, send a notification |
| `sub-workflow` | Delegating to another workflow YAML via `sub_workflow: <path>` |

### Agent role guide

Roles resolve against `.claude/agents/`. Common choices:

| Role | Use when |
|------|----------|
| `researcher` | Read-only discovery — reads files, queries CLIs, produces structured findings |
| `doc-writer` | Writing prose, templates, or structured documents |
| `code-writer` | Writing or editing code, configs, or running build tools |
| `reviewer` | Reviewing output, checking quality, writing findings |
| `fact-checker` | Verifying accuracy of claims against source data |
| `tester` | Writing or expanding tests |
| `unit-validator` / `cross-unit-validator` | Per-artifact and multi-artifact validation with structured JSON findings |
| `critic` | Adversarial critique of plans and designs |
| `ci-fixer` | CI failure diagnosis and fix |

Escalate to `code-writer-opus`, `tester-opus`, or `ci-fixer-opus` only when the Sonnet-tier agent has already failed.

### Parallelism

Stages with no shared `depends_on` chain run in parallel automatically. Group all independent discovery/gather stages together so they execute concurrently. Only add `depends_on` where a real data dependency exists.

### Validation blocks

Add a `validation:` block to any stage whose output quality must be checked before the workflow proceeds. `strategy` must be one of `unit`, `cross_unit`, `adversarial`, `fact_check`, or `deliverable`:

```yaml
validation:
  strategy: unit
  criteria:
    - All required fields are present
    - No placeholder values remain
  max_revisions: 2
```

### Human gates

Add `human_gate: true` to any `propose` or `validate` stage where a human must approve before execution continues. The workflow pauses and surfaces the stage output for review.

### writes_to paths

Paths are relative to `{workspace}/outputs/` — the engine prefixes them automatically. Subdirectories are allowed (`context/data.json`). Do not include an `outputs/` prefix. Workspace-root paths written by the engine itself (`validation/`, `stages/`, `dispatch/`) are off-limits.

### Fan-out

For stages that must run once per item in a dynamically produced list:

```yaml
fan_out:
  source: <name-of-stage-that-produced-the-list>
  field: items        # the list field in that stage's output file
  key: group          # the per-item key used as the loop variable
  mode: agent         # "agent" spawns a parallel sub-agent per item
```

`mode: worker_queue` dispatches items to the background worker queue instead, using a `script:` template with `{key}` substituted. Pair it with the `worker-queue-babysitter.yaml` fragment.

### Comments

Add a block comment (`#`) above each logical phase group (discovery, drafting, review) explaining what that group accomplishes and why it is ordered that way.

### Ordering rule

Declare stages in DAG order — a stage's `depends_on` must always reference a stage that appears earlier in the file. Never forward-reference.

---

## Step 3 — Validate

Lint the YAML with the workflow engine:

```bash
./bin/workflow lint <output_path> --check-commands
```

Fix any failures before proceeding:

- **Parse errors** — fix the YAML structure (missing required key, wrong kind value, indentation)
- **Unknown commands** — update stage descriptions to reference `./bin/<cli> <subcommand>` form; the linter probes each binary
- **Unknown variables** — ensure every `{var}` reference matches a key in `trigger.params`

Once lint passes, show the compiled execution plan so the user can confirm stage ordering and parallelism:

```bash
./bin/workflow compile <output_path> --format yaml
```

Present the parallel groups and stage list. Ask the user to confirm before writing the final file.

---

## Step 4 — Write the file

Write the validated YAML to `workflows/<domain>/<name>.yaml`, matching the existing layout (`workflows/code/`, `workflows/mail/`, `workflows/tests/`, …). If the user specified a different path, use that.

Confirm: "Workflow written to `workflows/<domain>/<name>.yaml`. Run it with: `/workflow --workflow workflows/<domain>/<name>.yaml`"

---

## Step 5 — Offer deeper validation

Offer to run `/validate-workflow` on the new file for a deeper check covering trigger param drift, stale stage names referenced in skill docs, and cross-file consistency.

---

## Common Patterns (Reference)

The snippets below show only the `stages:` block. Combine with the boilerplate from Step 2.

### 1. Linear pipeline (gather → execute → validate)

```yaml
stages:
  # Phase 1 — discovery: read the inputs needed before making changes
  - name: gather-context
    kind: gather
    description: >
      Use the researcher role to read the relevant files and query any CLIs
      needed to understand the current state. Write a structured summary to
      {workspace}/outputs/context.json.
    agent:
      role: researcher
    writes_to: [context.json]

  # Phase 2 — execution: produce the output artifact
  - name: produce-output
    kind: execute
    description: >
      Use the code-writer role to produce the artifact described by the
      workflow. Read context from {workspace}/outputs/context.json.
    agent:
      role: code-writer
    depends_on:
      - gather-context
    reads_from: [gather-context]
    writes_to: [result.md]

  # Phase 3 — validation: confirm the output meets quality criteria
  - name: validate-output
    kind: validate
    description: >
      Use the reviewer role to check {workspace}/outputs/result.md against the
      criteria below. Fail if any criterion is unmet.
    agent:
      role: reviewer
    depends_on:
      - produce-output
    reads_from: [produce-output]
    validation:
      strategy: unit
      criteria:
        - All required sections are present
        - No placeholder values remain
        - Output is internally consistent
      max_revisions: 2
```

### 2. Human-gate pipeline (gather → propose [human_gate] → execute → validate)

```yaml
stages:
  # Phase 1 — discovery
  - name: gather-context
    kind: gather
    description: >
      Use the researcher role to collect the data needed to draft a plan.
      Write findings to {workspace}/outputs/context.json.
    agent:
      role: researcher
    writes_to: [context.json]

  # Phase 2 — proposal: draft for human approval before taking action
  - name: propose-plan
    kind: propose
    description: >
      Use the doc-writer role to draft a plan based on {workspace}/outputs/context.json.
      A human reviews the plan before execution proceeds.
    agent:
      role: doc-writer
    depends_on:
      - gather-context
    reads_from: [gather-context]
    writes_to: [plan.md]
    human_gate: true

  # Phase 3 — execution: carry out the approved plan
  - name: execute-plan
    kind: execute
    description: >
      Use the code-writer role to implement the approved plan from
      {workspace}/outputs/plan.md. Write the result to {workspace}/outputs/result.md.
    agent:
      role: code-writer
    depends_on:
      - propose-plan
    reads_from: [propose-plan]
    writes_to: [result.md]

  # Phase 4 — validation
  - name: validate-result
    kind: validate
    description: >
      Use the reviewer role to verify that {workspace}/outputs/result.md matches
      the approved plan and meets quality standards.
    agent:
      role: reviewer
    depends_on:
      - execute-plan
    reads_from: [execute-plan]
    validation:
      strategy: unit
      criteria:
        - Output matches the approved plan
        - No steps from the plan were skipped
        - No placeholder values remain
      max_revisions: 2
```

### 3. Parallel gather + merge (two independent gather stages → single execute)

```yaml
stages:
  # Phase 1 — parallel discovery: both gather stages run concurrently
  # because neither depends on the other
  - name: gather-signals
    kind: gather
    description: >
      Use the researcher role to query the relevant signals and write
      structured findings to {workspace}/outputs/signals.json.
    agent:
      role: researcher
    writes_to: [signals.json]

  - name: gather-config
    kind: gather
    description: >
      Use the researcher role to read configuration files and write
      structured findings to {workspace}/outputs/config.json.
    agent:
      role: researcher
    writes_to: [config.json]

  # Phase 2 — merge: consume both gather outputs to produce the report
  - name: produce-report
    kind: execute
    description: >
      Use the doc-writer role to merge findings from {workspace}/outputs/signals.json
      and {workspace}/outputs/config.json into a unified report at
      {workspace}/outputs/report.md.
    agent:
      role: doc-writer
    depends_on:
      - gather-signals
      - gather-config
    reads_from:
      - gather-signals
      - gather-config
    writes_to: [report.md]
```

### 4. Fan-out (gather list → fan-out execute per item → aggregate validate)

```yaml
stages:
  # Phase 1 — enumerate: produce the list of items to process
  - name: enumerate-groups
    kind: gather
    description: >
      Use the researcher role to list all directory groups that need processing.
      Write a JSON file with an "items" array to {workspace}/outputs/groups.json.
      Each item must have a "group" key.
    agent:
      role: researcher
    writes_to: [groups.json]

  # Phase 2 — fan-out: one agent per group runs concurrently
  - name: process-group
    kind: execute
    description: >
      Use the code-writer role to process the group identified by the
      {group} variable. Write per-group results to
      {workspace}/outputs/{group}-result.json.
    agent:
      role: code-writer
    depends_on:
      - enumerate-groups
    reads_from: [enumerate-groups]
    writes_to: ["{group}-result.json"]
    fan_out:
      source: enumerate-groups
      field: items
      key: group
      mode: agent

  # Phase 3 — aggregate: review all per-group results together
  - name: aggregate-results
    kind: validate
    description: >
      Use the reviewer role to read all per-group result files from
      {workspace}/outputs/ and write a consolidated summary to
      {workspace}/outputs/summary.md.
    agent:
      role: reviewer
    depends_on:
      - process-group
    reads_from: [process-group]
    writes_to: [summary.md]
    validation:
      strategy: cross_unit
      criteria:
        - A result entry exists for every group from enumerate-groups
        - No group result is empty or contains only placeholder values
      max_revisions: 1
```
