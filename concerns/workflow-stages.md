# Workflow Stage Review Guide

## When loaded

Load this guide alongside `workflow.md` when the diff contains `.yaml` or `.yml`
workflow files or agent definitions. This file covers stage-level runtime concerns:
agent prompts, tool allowlists, executor routing, sleep-poll anti-patterns, and
inline-vs-agent execution decisions.

Engine-level, parameter, and DAG concerns are in `workflow.md`.
Fan-out, worker-queue, and output-contract concerns are in `workflow-fanout.md`.
Fragment, include, sub-workflow, and skill-sync concerns are in `workflow-fragments.md`.

## Concerns

### wrong-cli-flags
- **severity**: critical
- **check**: Verify every `./bin/` CLI invocation in a stage body uses flags
  that exist on that CLI, verified against its `--agentic` schema.
- **triggers**: Any workflow YAML stage whose description contains `./bin/`
  commands with explicit flag names.
- **example**: `./bin/mail-assistant labels sync --delete-all` uses `--delete-all` but
  the CLI requires `--delete-missing`; `./bin/calendar outlook list --format yaml` but
  the CLI only registers `json` and `table`. Verify with
  `./bin/<tool> --agentic --agentic-format yaml --agentic-compact` before
  committing.

### stage-tools-bash-overuse
- **severity**: minor
- **check**: Verify that stage agent blocks do not prescribe Bash as the tool
  for file reads, content searches, or directory listing when a dedicated tool
  is more efficient. Specifically flag: `cat`, `head`, `tail` (use Read tool);
  `grep`, `rg`, `awk`, `sed` against file paths (use Grep tool);
  `find . -name`, `ls <dir>` for file discovery (use Glob tool).
- **triggers**: Workflow YAML stage `description` blocks where Bash is used
  **exclusively** for file-access operations: `cat <file>`, `head <file>`,
  `tail <file>`, `grep <pattern> <file>`, `find . -name <pat>` (discovery),
  `ls <dir>` (listing). Only flag when a structured alternative (`Read`,
  `Grep`, `Glob`) clearly covers the same need — do not flag Bash uses for
  subprocess execution, git commands, or CLI invocations.
- **example**: A `gather` stage description says "Run `cat output.json` to
  read the data" and lists `tools: [Bash, Write]` — the correct form
  is `tools: [Read, Write]` with the Read tool called on `output.json`
  directly.

### stage-sleep-poll
- **severity**: major
- **check**: Verify that no stage description instructs an agent to poll for
  completion using a shell sleep loop (`while ... sleep`, `until ... do sleep`,
  `; sleep N;`, `&& sleep N`). The correct pattern is the Monitor tool — the
  poll runs in a subprocess and fires one notification on completion, keeping
  the orchestrator thread free.
- **triggers**: Stage `description` blocks containing sleep **inside a polling
  loop**: `while true; do ... sleep`, `until <condition>; do sleep`,
  `for ... sleep` constructs; descriptions that say "poll until", "wait for
  the file", "retry every N seconds" without mentioning the Monitor tool.
  Do NOT flag `sleep` inside a Monitor `command` string (that runs in a
  subprocess, not the orchestrator thread) or a one-shot `sleep N` before a
  single check.
- **example**: A stage description reads "Run `until ls outputs/result.json; do
  sleep 5; done` to wait for the result." This blocks the agent thread and
  emits spurious idle messages. Replace with a Monitor tool call using
  `until ls outputs/result.json 2>/dev/null; do sleep 5; done && echo DONE`.
  See CLAUDE.md § "Wait Policy — Monitor vs sleep-poll" for the canonical pattern.

### stage-inline-large-data
- **severity**: major
- **check**: Verify that no stage description calls for inline Python
  (`python3 -c "..."`) or a serial shell loop (`for item in ...; do ... done`)
  to process more than ~20 items or files larger than 1 MB. These patterns
  block the agent thread for the full duration and cannot be parallelized.
- **triggers**: Stage `description` blocks containing `python3 -c` that
  processes a **data file** (not a trivial one-liner); `for` or `while` loops
  in stage descriptions where each iteration invokes a `./bin/` CLI **and the
  item count is >20 or file size >1 MB**; descriptions that say "for each item,
  call" or "iterate over all sessions" without referencing a fan-out mechanism.
  Do NOT flag small inline scripts (≤5 items, no external file reads).
- **example**: A stage description reads "For each of the 50 sessions, run
  `./bin/telemetry sessions --session-id X --format json`." This serializes 50
  CLI calls in one agent thread. Fix: enqueue items as separate work units
  using a fan-out pattern and process them in parallel.

### misleading-method-name
- **severity**: minor
- **check**: Verify that method names accurately describe what the method does. Methods with "live", "signal", or "gate" in their names should actually interact with live systems or enforce a real quality gate — not just filter a static list by a field value.
- **triggers**: Method names containing `gate`, `live`, `signal`, `check`, or `validate` in source files where the implementation only filters/transforms an existing in-memory collection without any I/O, API calls, or threshold enforcement.
- **example**: `_gate_live_signals()` sounds like it queries an external source for live signal presence, but the implementation is `return [c for c in candidates if c.noise_verdict != "rejected"]` — a pure filter on a pre-computed field. Rename to `_filter_rejected_candidates()` to match actual behavior.

### agent-spawned-for-trivial-stage
- **severity**: minor
- **check**: Verify that stages whose work is a single CLI command or a simple
  credential check (auth verification, connectivity probe, daemon presence check)
  declare `executor: inline` instead of the default `executor: agent`. Spawning
  a full background agent for a one-liner wastes resources.
- **triggers**: Any `kind: gather` stage whose description consists entirely of
  one or two `./bin/` commands writing a status JSON; stages named `check-auth`,
  `check-daemon`, `pre-flight`, `verify-auth`, or similar; stages whose
  `writes_to` list contains only a single `*-status.json` or `*-check.json` file
  and whose description contains no LLM synthesis instructions.
- **example**: A `check-auth` stage runs `./bin/mail-assistant --agentic` and
  writes `auth/auth-status.json`. It has `agent: {role: researcher, model: sonnet}`
  but no `executor:` field — the orchestrator spawns a full agent to run one CLI
  command. Fix: add `executor: inline` and comment out the `agent:` block.

### input-path-no-upfront-validation
- **severity**: minor
- **check**: Verify that user-facing CLIs that accept `--file`, `--config`, or any path argument validate the path exists before constructing expensive objects (API clients, renderers, parsers). Relying on downstream OS errors produces generic "No such file or directory" messages with no indication of which flag caused the failure.
- **triggers**: CLI `run()` methods that accept path arguments and immediately pass them to a constructor or processor without a preceding `Path(arg).exists()` check; `argparse` parsers with `type=str` for file paths (not `type=argparse.FileType`).
- **example**: A CLI calls `SyncProvider(config_path=args.config)` without first checking `Path(args.config).exists()` — if `--config` points to a non-existent file, the user sees `FileNotFoundError` with no indication that `--config` is the problem. Fix: validate all input paths upfront with a clear error message before constructing any objects.

### stage-access-tool-mismatch
- **severity**: major
- **check**: Verify that stages declaring `access: read-only` do not list `Write` or `Edit` in their tools array, and that stages listing `Write` or `Edit` declare `access: read-write`.
- **triggers**: Any workflow YAML stage with `access: read-only` in combination with `Write` or `Edit` in the `tools` list; agent definitions whose frontmatter declares read-only access but whose stage body instructs the agent to write output files.
- **example**: A stage has `access: read-only` but its `tools` list includes `Write` and it writes `outputs/sessions-index.json` — the agent will hit a permission error at runtime or silently skip the write. Fix: change `access: read-write` for any stage whose agent must produce output files.

### stage-description-bash-file-discovery
- **severity**: minor
- **check**: Verify that stage descriptions instruct agents to use the `Glob` tool for file discovery rather than `ls` or `find` via Bash.
- **triggers**: Workflow YAML stage descriptions that include `ls`, `find .`, or `find /` instructions for locating files; descriptions that say "use ls to list" or "run find to discover" when the stage's `tools` list includes `Glob`.
- **example**: Step 1 of a stage description says "run `ls mail/` to discover providers" — this shells out when the `Glob` tool (`mail/*/provider.py`) is both faster and cheaper. Fix: replace with "Use the Glob tool to enumerate `mail/*/provider.py`".

### stage-tool-not-in-allowlist
- **severity**: major
- **check**: Verify that every tool a stage description instructs the agent to use is listed in the stage's `tools` array — agents cannot use unlisted tools regardless of what the description says.
- **triggers**: Workflow YAML stage descriptions that name a specific tool (`Glob`, `Grep`, `Read`, `WebFetch`) that does not appear in the stage's `tools` list; stage descriptions that say "use the Glob tool" or "use Read" without the corresponding entry in `tools`.
- **example**: A stage description says "Use the Glob tool to find config files" but `tools: [Read, Bash]` — the agent cannot call `Glob` and will fall back to a Bash `find`, defeating the instruction. Fix: add `Glob` to the `tools` list, or rewrite the description to use only listed tools.

### inline-eligible-stage-uses-agent
- **severity**: minor
- **check**: Verify that stages whose entire workload is one or two trivial CLI or shell commands use `executor: inline` rather than spawning an agent. Stages that only run `./bin/` commands or `gh` operations require no synthesis, judgment, or multi-step reasoning — spawning an agent wastes resources and introduces unnecessary latency.
- **triggers**: Workflow YAML stages that (a) have no `executor: inline` set, (b) whose `description` contains nothing but a single `./bin/` or `gh` command (possibly preceded by a `Read` of one file), and (c) whose `tools` list is limited to `[Bash]` or `[Read, Bash]` with no `Edit`, `Write`, or `Glob` needed for reasoning.
- **example**: A `post-comments` stage whose description is entirely "read decision.txt then run `./bin/github pr-review-comment N --body-file /tmp/body.txt`" is assigned `role: doc-writer` and spawns a full agent. The stage produces no synthesized output — only a side-effect CLI call. Fix: add `executor: inline` so the orchestrator runs the command directly. Auth checks, comment posting, and other single-step CLI stages are canonical inline candidates.
