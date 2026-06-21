# Workflow Review Guide

## When loaded

Load this guide when the diff contains `.llm/FLOWS.yaml`, `.llm/FLOWS.generated.yaml`,
or any agent definition YAML under `.claude/agents/`. The `skill-dag-sync` concern in
`patterns.md` also applies when SKILL.md files are changed.

Dancing-bear workflows are defined in `.llm/FLOWS.yaml` as curated step sequences —
they are not compiled DAGs. The concerns below cover correctness of CLI references,
param wiring, and agent definition quality.

## Concerns

### wrong-cli-flags
- **severity**: critical
- **check**: Verify every `./bin/` CLI invocation in a flow step uses flags that
  exist on that CLI, verified against its `--agentic` schema.
- **triggers**: Any flow `cmd` or `steps` entry with explicit flag names; new or
  modified entries in `.llm/FLOWS.yaml`.
- **example**: A flow step calls `./bin/mail-assistant filters sync --delete-all`
  but the CLI uses `--delete-missing`; or a step uses `--format json` but the CLI
  only registers `text`, `yaml`, and `table` as output choices. Verify with
  `./bin/<tool> --agentic --agentic-format yaml --agentic-compact` before
  committing.

### unused-flow-param
- **severity**: minor
- **check**: Verify every param declared or substituted in a flow step is actually
  used — dead params make the flow interface misleading to operators and agents.
- **triggers**: Flow entries in `.llm/FLOWS.yaml` with `{param}` placeholders where
  the param is never substituted; params documented in flow descriptions that do not
  appear in any `cmd` or `steps` value.
- **example**: A flow declares `cmd: ./bin/mail-assistant --profile {profile} filters plan`
  but `{profile}` is never passed at call sites — the placeholder is literal and
  produces a broken command. Fix: either substitute the param or use a concrete value.

### hardcoded-absolute-path
- **severity**: major
- **check**: Verify no absolute paths appear in flow commands, agent prompts, or
  YAML config files — paths like `/Users/...` are non-portable.
- **triggers**: Any `.yaml` or `.md` file containing `/Users/`, `/opt/homebrew/`,
  `/home/`, or other filesystem-rooted paths not rooted at the workspace.
- **example**: A flow step hardcodes `/Users/bcs/code/dancing-bear/bin/mail-assistant`
  instead of `./bin/mail-assistant` — breaks on any other machine.

### shell-chain-no-failure-record
- **severity**: major
- **check**: Verify that `&&`-chained shell commands in flow steps handle early
  failures — a chain that short-circuits on the first error silently skips all
  remaining steps with no structured error output.
- **triggers**: Flow `steps` entries with `&&`-chained commands where a failure
  in the first step should be surfaced rather than silently skipped.
- **example**: `./bin/mail-assistant filters plan && ./bin/mail-assistant filters sync`
  — if `plan` fails, `sync` is skipped silently. For critical flows, use separate
  steps or add explicit failure handling.

### stdout-stderr-merged-json
- **severity**: major
- **check**: Verify that no flow step redirects both stdout and stderr into a file
  that is later parsed as JSON or YAML.
- **triggers**: Flow command strings containing `> file.json 2>&1` or equivalent
  stderr-merge redirects where the output file is subsequently read as structured data.
- **example**: `./bin/mail-assistant labels export --out out/labels.json 2>&1` — any
  warning on stderr causes a parse error in the downstream consumer. Always separate:
  `> out.json 2> err.log`.

### plan-apply-order-violated
- **severity**: major
- **check**: Verify that flows which modify external state follow the canonical
  plan → dry-run → apply order. Skipping plan or dry-run in a flow removes the
  safety check that prevents unintended mutations.
- **triggers**: Flows in `.llm/FLOWS.yaml` with a `sync` or `apply` step that is
  not preceded by a `plan` step in the same flow or a referenced prerequisite flow;
  `steps` sequences that call `--apply` without a prior dry-run step.
- **example**: A flow jumps directly to `./bin/mail-assistant filters sync --delete-missing`
  without a prior `filters plan` step — operators lose the diff preview. Fix: prepend
  a `filters plan` step or document the prerequisite flow that must be run first.

### agent-definition-role-mismatch
- **severity**: minor
- **check**: Verify that agent definitions in `.claude/agents/` accurately describe
  the agent's model, capabilities, and use-cases — stale agent definitions cause the
  orchestrator to spawn agents with wrong model selection or tool access.
- **triggers**: Changes to agent definition YAML files that do not update the `model`,
  `tools`, or `description` fields to match the new intended behavior; new agent roles
  introduced without a corresponding entry in the agent definitions table in CLAUDE.md.
- **example**: An agent definition still references `claude-3-haiku` for a synthesis
  task that was upgraded to require Sonnet — the orchestrator spawns an under-powered
  model. Fix: update the `model` field in the agent definition and verify against the
  CLAUDE.md agent table.

### flow-references-nonexistent-bin
- **severity**: critical
- **check**: Verify that every `./bin/<entrypoint>` referenced in `.llm/FLOWS.yaml`
  or `.llm/FLOWS.generated.yaml` corresponds to an actual executable file in `bin/`.
- **triggers**: New flow entries added without verifying the bin/ entry point exists;
  renamed or removed `bin/` scripts without updating FLOWS.yaml references.
- **example**: A flow references `./bin/wifi-assistant diagnose` but `bin/wifi-assistant`
  was renamed to `bin/network-assistant` — the flow fails at runtime. Fix: check
  `ls bin/` before adding a new flow entry, and update FLOWS.yaml in the same PR as
  any bin/ rename.
