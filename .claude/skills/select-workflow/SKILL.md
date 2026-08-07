---
name: select-workflow
description: Interactively select the right workflow for a task. Describe what you want to do in plain language and get back the matching workflow, required params, and a ready-to-run /workflow invocation. Use when you know what you want to accomplish but aren't sure which workflow file handles it.
allowed-tools: Bash, Read
skills:
  - dancing-bear-rules
---

# Workflow Selector

Match a plain-language intent to the right workflow YAML and generate a ready-to-run invocation.

## When to Use

- User says "which workflow should I use for X"
- User describes a task and asks how to run it as a workflow
- User wants to kick off a workflow but doesn't know the file name or params
- User says "/select-workflow" or "help me pick a workflow"

## Workflow Catalog

The catalog below is a fast-path index. It can drift as workflows are added —
always confirm against the live list before presenting an invocation:

```bash
./bin/workflow list
```

### Code review and PR lifecycle

| Workflow | File | What it does | Key params |
|----------|------|--------------|------------|
| **code-review** | `workflows/code/code-review.yaml` | Adversarial swarm review of a GitHub PR: fetch diff, sweep concerns, fan out per-file validators, post inline comments | `pr_number`, `pr_size` |
| **review-and-fix** | `workflows/code/review-and-fix.yaml` | Full swarm review, then automated parallel fix of every confirmed finding | `pr_number`, `test_cmd`, `source_root`, `test_path`, `min_coverage`, `auth_domains`, `skip_review` |
| **open-pr** | `workflows/code/open-pr.yaml` | Pre-PR validation and PR creation: auth pre-flight, lint, tests, coverage, description, open | `pr_title`, `test_cmd`, `source_root`, `test_path`, `min_coverage`, `auth_domains` |
| **ci-debug** | `workflows/code/ci-debug.yaml` | Diagnose and fix GitHub Actions CI failures from a run URL or PR number | `run_url`, `pr_number`, `test_cmd`, `source_root`, `min_coverage` |
| **load-concerns** | `workflows/code/load-concerns.yaml` | Load the subset of the review concern library relevant to a task | `task_type`, `file_paths`, `max_concerns` |
| **update-review-concerns** | `workflows/code/update-review-concerns.yaml` | Mine past runs and PR threads for recurring issues the concern library misses | `window_days`, `min_occurrences`, `pr_number`, `max_prs` |

### Code quality and refactoring

| Workflow | File | What it does | Key params |
|----------|------|--------------|------------|
| **optimize-code** | `workflows/code/optimize-code.yaml` | Post-implementation optimization: 5 parallel quality scans, collate, correct, recheck | `source_root`, `test_path`, `pr_number`, `skip_checks`, `auth_domains` |
| **decompose-sweep** | `workflows/code/decompose-sweep.yaml` | Find oversized Python files, group by domain, fan out agents to split them | `source_threshold`, `test_threshold`, `domains`, `pr_title` |
| **qlty-complexity-sweep** | `workflows/code/qlty-complexity-sweep.yaml` | Sweep qlty file-complexity smells, group by source dir, reduce complexity | `complexity_floor`, `max_files`, `pr_title` |
| **complexity-fanout-generate** | `workflows/code/complexity-fanout-generate.yaml` | Triage complexity-flagged files into reduction strategies and generate the fan-out plan | `complexity_floor`, `min_symbols_to_split`, `output_dir`, `prior_split_ref` |
| **design-criteria-audit** | `workflows/code/design-criteria-audit.yaml` | Read-only audit of `src/` domains against `.llm/DESIGN_CRITERIA.md` (C1–C10) | `domains` |
| **design-criteria-normalize** | `workflows/code/design-criteria-normalize.yaml` | Apply pass for the audit's approved findings | `audit_workspace`, `domains`, `criteria` |

### Testing and coverage

| Workflow | File | What it does | Key params |
|----------|------|--------------|------------|
| **coverage-uplift** | `workflows/code/coverage-uplift.yaml` | Coverage-driven uplift with adversarial review, ending in a PR | `min_coverage`, `min_lines`, `domains`, `source_root`, `test_path`, `pr_title`, `pr_body_sources`, `test_cmd` |
| **coverage-report** | `workflows/test/coverage-report.yaml` | Phase 1: read-only analysis of happy/sad-path gaps across every domain | *(none)* |
| **coverage-improve** | `workflows/test/coverage-improve.yaml` | Phase 2: implement the improvements identified by coverage-report | `report_path`, `min_coverage`, `domains` |
| **test-coverage-assess** | `workflows/tests/test-coverage-assess.yaml` | Assess coverage by domain, then author tests for the weakest | *(none)* |
| **categorize-test-cases** | `workflows/tests/categorize-test-cases.yaml` | Classify every `test_*` method as happy-path, sad-path, or unassigned | `batch_size` |
| **fill-sad-path-gaps** | `workflows/tests/fill-sad-path-gaps.yaml` | Companion to categorize-test-cases: fill the sad-path gap matrix | `max_files` |

### Workflow development and telemetry

| Workflow | File | What it does | Key params |
|----------|------|--------------|------------|
| **optimize-workflow-from-telemetry** | `workflows/code/optimize-workflow-from-telemetry.yaml` | Calibrate an existing workflow using its own per-stage run history | `target_workflow`, `telemetry_since`, `min_runs` |
| **synthesize-workflow-from-telemetry** | `workflows/code/synthesize-workflow-from-telemetry.yaml` | Mine telemetry for repeated ad-hoc sequences not yet codified as a workflow | `telemetry_since`, `min_occurrences`, `target_workflow` |
| **otel-doctor** | `workflows/code/otel-doctor.yaml` | Diagnose the local OTel pipeline and fix the first failing layer | *(none)* |

### Domain workflows

| Workflow | File | What it does | Key params |
|----------|------|--------------|------------|
| **mail-filter-apply** | `workflows/mail/mail-filter-apply.yaml` | Review unified filter config, plan per provider, human sign-off, apply to Gmail + Outlook | `profile`, `dry_run` |
| **calendar-sync** | `workflows/calendar/calendar-sync.yaml` | Gather Outlook events, generate a schedule plan, human review, apply | `days`, `profile` |
| **ios-reorg** | `workflows/ios-reorg.yaml` | iPhone Home Screen reorganization: export layout, merge folders, apply | `device_label`, `keep` |
| **pdffill-domain-build** | `workflows/code/pdffill-domain-build.yaml` | Design and implement the `src/pdffill/` PDF form-filling domain | `real_pdf`, `run_qlty` |

### Demos

| Workflow | File | What it does | Key params |
|----------|------|--------------|------------|
| **worker-queue-stage** | `workflows/demo/worker-queue-stage.yaml` | Minimal demo of `executor="worker_queue"` | `greeting` |
| **worker-queue-fanout** | `workflows/demo/worker-queue-fanout.yaml` | Minimal demo of `fan_out.mode="worker_queue"` | `purge_older_than` |

## Step 1: Understand the Intent

Extract from the user's request:
- **What they want to accomplish** (review a PR? raise coverage? cut complexity?)
- **What they already know** (PR number? domain? source root?)
- **Scope** (one PR? one domain? the whole codebase?)

## Step 2: Match to a Workflow

```
Review a PR                       → code-review (review only)
  └─ ...and fix the findings      → review-and-fix
Open a PR for finished work       → open-pr
CI is red                         → ci-debug
Harden code just written          → optimize-code
Files too big                     → decompose-sweep
Functions too complex             → qlty-complexity-sweep
  └─ plan the fan-out only        → complexity-fanout-generate
Check domains against DESIGN_CRITERIA → design-criteria-audit → design-criteria-normalize
Raise coverage (ends in a PR)     → coverage-uplift
Analyse coverage gaps only        → coverage-report → coverage-improve
Classify existing tests           → categorize-test-cases → fill-sad-path-gaps
Tune an existing workflow         → optimize-workflow-from-telemetry
Discover a workflow worth writing → synthesize-workflow-from-telemetry
Write a brand-new workflow        → /write-workflow skill (not a workflow YAML)
Telemetry pipeline broken         → otel-doctor
Apply mail filters                → mail-filter-apply
Sync calendar to a schedule       → calendar-sync
Reorganize the iPhone layout      → ios-reorg
```

If intent is ambiguous between 2–3 workflows, briefly explain the difference and ask which fits.

## Step 3: Read the Workflow File

```bash
head -60 workflows/<matched-workflow>.yaml
```

Read the `trigger.params` block to know which params are required vs optional
(empty string default = required; non-empty default = optional with a default).

## Step 4: Collect Missing Params

For each required param (default `""`), check whether the user already supplied the
value. If not, ask for all missing required params in one concise question.

Mention optional params but don't block on them.

## Step 5: Present the Invocation

```
Workflow: <name>
File: workflows/<file>.yaml

Ready to run:
/workflow --workflow workflows/<file>.yaml --execute \
  --params <key1>=<value1> \
  --params <key2>=<value2>

Optional params (using defaults):
  <key>: <default> — <what it controls>

Dry-run preview (no execution):
/workflow --workflow workflows/<file>.yaml \
  --params <key1>=<value1>
```

Then ask: **"Run it now, dry-run first, or adjust any params?"**

- **Run now**: invoke `/workflow` with `--execute` and all params
- **Dry-run**: invoke `/workflow` without `--execute` to show the execution plan
- **Adjust**: update the param and re-present

Note that `./bin/workflow run` defaults to dry-run; `--execute` is what actually runs it.

## Step 6: Hand Off to /workflow

Once the user confirms:

```python
Skill(skill="workflow", args="--workflow workflows/<file>.yaml --execute --params key1=val1 --params key2=val2")
```

For dry-run, omit `--execute`.

## Examples

**"Review PR 172 and fix what it finds"**
→ `review-and-fix` — `pr_number=172` known; confirm `test_cmd`, `source_root`, `test_path`

**"Just review PR 172, don't change anything"**
→ `code-review` — `pr_number=172` known; `pr_size` optional

**"Coverage on src/resume is weak"**
→ `coverage-uplift` — `domains=resume`, `source_root=src/resume/`, `test_path=tests/resume/`; confirm `min_coverage` and `pr_title`

**"These files are getting too long to review"**
→ `decompose-sweep` — confirm `source_threshold`, `domains`, `pr_title`

**"CI is failing on my branch"**
→ `ci-debug` — ask for `run_url` or `pr_number`

**"Apply my mail filters"**
→ `mail-filter-apply` — ask for `profile`; keep `dry_run=true` for the first pass

**"I want a workflow that does X"**
→ Not a catalog entry — invoke the `/write-workflow` skill instead
