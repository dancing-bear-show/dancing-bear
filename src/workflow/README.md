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
```

`run` defaults to dry-run; pass `--execute` to execute. `--params key=value` overrides trigger parameters (repeatable).

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

- `cli.py` — CLIApp-based dispatch; 9 subcommands; `_emit_one`/`_emit_rows` delegate to `core.cli_output`
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

## Tests

`tests/workflow_tests/`
