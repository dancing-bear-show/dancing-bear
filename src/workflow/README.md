# Workflow Engine

YAML DAG engine for composing and running multi-step assistant tasks. Entry point: `./bin/workflow`.

Supports `--agentic`: `./bin/workflow --agentic --agentic-format yaml --agentic-compact`.

## Key Commands

```bash
./bin/workflow run workflow.yaml           # dry-run (preview only)
./bin/workflow run workflow.yaml --execute # execute for real
./bin/workflow lint workflow.yaml          # validate YAML structure
./bin/workflow parse workflow.yaml         # parse and display structure
./bin/workflow compile workflow.yaml       # show execution plan (parallel groups)
./bin/workflow list                        # list available workflow definitions
./bin/workflow status <workspace-dir>      # show status of a completed run
./bin/workflow init-workspace workflow.yaml  # create workspace + manifest
./bin/workflow resume <workspace-dir>      # show which stages need re-running
./bin/workflow validate-fragment frag.yaml # validate a workflow fragment
./bin/workflow check-params "<ws>/manifest.json" --check 'name=regex'  # guard a param
./bin/workflow check-finding-keys "<ws>/outputs/fix-index.json"         # finding_key gate
./bin/workflow thread-fingerprints "<ws>/outputs/threads.json"          # per-thread discriminators
./bin/workflow check-thread-ids "<ws>/outputs/threads.json" "<ws>/outputs/triage.json" [--repair]
./bin/workflow aggregate-fix-results "<ws>/outputs/fix-index.json" "<ws>/outputs/fixes" "<ws>/outputs/fix-results.json"
```

Stage guards. Each one reads untrusted values as JSON data from a workspace
file (never from argv). Exit 0 means pass, 1 means fail. Errors go to stderr
and name an entry, never its rejected value.

- `check-params` validates params against `--check name=regex` (full match,
  repeatable). It reads the manifest's `trigger_params`, or the document root
  with `--top-level`, for stage outputs such as `handler.json`. `--print name`
  writes that one value to stdout only if every check passed, and only for a
  name some `--check` covers. It lets a stage write `X=$(...)` instead of
  interpolating a raw param.
- `check-finding-keys` checks that every `finding_key` in a fix-index is
  present, unique, and matches `[A-Za-z0-9][A-Za-z0-9_-]{0,99}`.
- `thread-fingerprints` prints JSON `[{index, thread_id, database_id,
  body_fingerprint}]` for a threads.json. It is the one tested body hash.
- `check-thread-ids` is the review-fix-threads id-coherence gate. It skips null
  ids. Each other id must exist in the fetch and match the discriminator triage
  recorded (`database_id`, or `fingerprint` as a fallback), so swapped ids
  halt. A coordinate-only difference halts unless `--repair` is given, which
  rewrites triage.json and records `_id_repairs`. See `review_ids.py`.
- `aggregate-fix-results` merges fixer results into fix-results.json on
  `finding_key`, never `thread_id`. A file counts only if its name, in-file
  `finding_key` and `thread_id` all match the index; otherwise it is a
  `key_mismatch` and its finding is reported missing.

`run` defaults to dry-run; pass `--execute` to execute. `--params key=value` overrides trigger parameters (repeatable).

Constrain overridable params with `trigger.param_rules` (name → full-match regex)
and `trigger.required` (names that must be non-blank). The engine enforces both in
`compile_workflow`, before any `{param}` is substituted, so `compile`, `run`, and
`init-workspace` all exit 1 on a violation. A blank optional param is exempt from
its rule. Errors name the param, never the value. Fragments may declare rules too,
and every rule that applies to a param must pass. See `param_rules.py`.

## Architecture

```mermaid
---
title: Workflow Engine — DAG execution pipeline
---
flowchart TB
    YAML[workflow.yaml] --> parse[parser.py\nparse_workflow]
    parse --> validate[parser_validate.py\n_validate_dag]
    validate --> compile[compiler.py\nBFS topological sort]
    compile --> manifest[WorkflowManifest\nparallel groups]
    manifest --> orchestrator[orchestrator.py\nWorkflowOrchestrator]
    orchestrator --> group[parallel group N]
    group --> dispatcher[dispatchers.py\nLocalDispatcher]
    dispatcher --> stage[ResolvedStage\nCLI command]
    stage --> persist[persistence.py\nwrite_stage_result]
    persist --> orchestrator
    orchestrator --> done[WorkflowRun complete]
```

`compiler.py` performs BFS topological sort to produce parallel groups. Stages with `human_gate: true` are isolated into their own group; the orchestrator pauses after that group and waits for acknowledgement before continuing.

## Stage Kinds

| Kind | Description |
|---|---|
| `gather` | collect / search inputs |
| `propose` | draft or plan |
| `execute` | run a command or script |
| `validate` | check or review output |
| `publish` | write or emit results |
| `sub-workflow` | inline sub-workflow (orchestrator invokes `/workflow` skill directly) |

Set `human_gate: true` on any stage to pause execution for human review after that stage completes.

## Key Modules

- `cli.py` — CLIApp-based dispatch; `_emit_one`/`_emit_rows` delegate to `core.cli_output`
- `cli_dispatch.py` — argument resolution; errors raise `CLIError` (not `SystemExit`)
- `cli_compile.py` — `_cmd_compile` implementation
- `compiler.py` — BFS topological sort; `WorkflowCompileError` subclasses `CLIError`; splits human-gated stages into isolated groups
- `parser.py` / `parser_fields.py` / `parser_errors.py` — YAML parsing and field validation
- `parser_validate.py` — DAG cycle detection and structural validation
- `orchestrator.py` — `WorkflowOrchestrator`: walks parallel groups, pauses on human gates, handles `when` conditions
- `dispatchers.py` — `LocalDispatcher` runs stages; SafeProcessor wrapping deferred (engine is the pipeline)
- `persistence.py` — `write_stage_result`; workspace file layout
- `include.py` — workflow fragment inclusion and merging
- `models.py` — `StageKind`, `ResolvedStage`, `WorkflowManifest`, `WorkflowRun` dataclasses
- `linter.py` — structural lint checks
- `output_checks.py` — post-stage output validation
- `param_guard.py` — `check-params`: validate params read as JSON data
- `review_ids.py` — `check-finding-keys`, `thread-fingerprints`, `check-thread-ids`, `aggregate-fix-results`

## Tests

`tests/workflow_tests/`
