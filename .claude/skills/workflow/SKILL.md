---
name: workflow
description: Execute a stage of a YAML DAG workflow. Use when a dispatch instruction JSON file is present in the workspace dispatch/ directory. Reads the dispatch file, follows the embedded prompt for the given stage, writes outputs to the workspace, and marks the stage done.
tools: Read, Write, Edit, Bash, Glob, Grep
---

# Workflow Stage Executor

Execute a single stage of a YAML DAG workflow. Each stage has a dispatch JSON file written by `./bin/workflow run`. This skill reads that file and carries out the stage instructions.

## When to invoke

Invoke this skill when:
- A dispatch JSON file exists at `<workspace>/dispatch/<NNN>-<stage-name>.json`
- The user says "execute workflow stage", "run stage", or "process dispatch"
- The orchestrator hands off a stage for agent execution

## Workflow

### Phase 1 — Read dispatch file

Read the dispatch JSON at the path indicated. It contains:
- `stage_name` — name of the stage to execute
- `stage_index` — numeric index for file naming
- `agent_type` — the agent role required (researcher, doc-writer, etc.)
- `prompt` — full execution instructions for this stage
- `workspace_dir` — absolute path to the workflow workspace
- `workflow_name` — name of the parent workflow

### Phase 2 — Execute stage instructions

Follow the `prompt` exactly. Key conventions:
- Read input files from `<workspace_dir>/outputs/<filename>`
- Write output files to `<workspace_dir>/outputs/<filename>`
- Stage result files go to `<workspace_dir>/stages/<NNN>-<stage-name>.json`
- Validation reports go to `<workspace_dir>/validation/<stage-name>.json`

### Phase 3 — Write stage result

After completing the stage, write a result JSON to:
`<workspace_dir>/stages/<NNN>-<stage-name>.json`

Format:
```json
{
  "stage_name": "<stage-name>",
  "stage_index": <NNN>,
  "status": "success",
  "started_at": "<ISO8601>",
  "finished_at": "<ISO8601>",
  "duration_ms": <ms>,
  "data": {},
  "errors": [],
  "output_files": ["<filename>", ...],
  "input_stages": ["<stage-name>", ...],
  "metadata": {}
}
```

Use `status: "failed"` and populate `errors` if the stage could not complete.

## Status values

- `success` — stage completed, outputs written
- `failed` — stage could not complete; errors list populated
- `skipped` — stage skipped due to `when:` condition evaluating false
- `awaiting_human` — human gate reached; stage paused for review

## Notes

- Never edit files outside `<workspace_dir>` unless the prompt explicitly requires it
- Keep output files as JSON where possible for downstream checks
- If `validates_output` checks are specified in the prompt, verify them before marking success
