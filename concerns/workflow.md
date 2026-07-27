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

### yaml-embedded-code-fragility
- **severity**: critical
- **check**: Verify that inline executable code (Python snippets, shell here-docs) embedded in workflow YAML strings does not contain `{...}` expressions that the workflow engine will substitute before the code runs, and that YAML block scalar indentation preserves the code's indentation requirements.
- **triggers**: Workflow YAML stage bodies with `python3 -c "..."` or `python3 << 'EOF'` blocks that contain curly-brace expressions; inline Python where the indentation inside the YAML block scalar does not match Python's requirements; `{workspace}`, `{team}`, or other substitution tokens inside a Python string literal or dict literal.
- **example**: A stage body contains `python3 -c "import json; d = {workspace: ...}"` — the engine substitutes `{workspace}` before Python sees the snippet, producing a syntax error or injecting an unexpected value. Fix: for workflow param references inside Python strings use `{workspace}` (single braces — the engine replaces them); for Python dict literals unrelated to params, use normal `{"key": "value"}` (no escaping needed); use a dedicated script file for any code requiring non-trivial indentation.

### inline-brace-over-escape
- **severity**: major
- **check**: In workflow YAML stage descriptions and inline executor code snippets, verify that engine-substituted params are written as single braces (`{workspace}`), NOT doubled (`{{workspace}}`). The workflow engine's param substitution is a plain `str.replace("{key}", value)`, so `{{workspace}}` is partially substituted — the inner `{workspace}` IS found and replaced, producing `{<value>}` (a literal `{` followed by the substituted path followed by `}`), not a valid path.
- **triggers**: Any inline executor stage whose description contains `{{workspace}}`, `{{run_id}}`, `{{team}}`, or any other known trigger param name with doubled braces; workflow template files with the same pattern.
- **example**: `workspace = "{{workspace}}"` in an inline stage description is partially substituted by the engine — the inner `{workspace}` matches and is replaced, producing `{/path/to/ws}` with a stray leading `{`. Fix: `workspace = "{workspace}"`. Python dict literals (`{"key": "value"}`) are fine as-is — they do not reference workflow params and need no escaping.

### trigger-param-yaml-type
- **severity**: minor
- **check**: Verify that every value in `trigger.params` that is meant to be a boolean, integer, or float is quoted — the workflow engine stores all trigger params as strings, so an unquoted `true`/`false` or `3` or `1.5` in YAML becomes the string `"True"`/`"False"`/`"3"`/`"1.5"` after coercion. Downstream `when:` guards must use the `contains` / `does not contain` forms and the compared value must match the string the engine actually stores.
- **triggers**: `trigger.params` blocks containing unquoted YAML booleans (`true`, `false`, `yes`, `no`, `on`, `off`) or unquoted integers/floats as default values; params with names like `dry_run`, `enabled`, `skip_*`, `max_*`, `limit` whose defaults are unquoted.
- **example**: `trigger.params: { dry_run: false }` — YAML parses `false` as Python `False`, then the workflow parser coerces it to the string `"False"`. A `when:` guard written as `'"{dry_run}" contains "false"'` will never match because the stored value is `"False"` (capital F). Fix: quote every boolean/integer default — `dry_run: "false"` — and match the casing in guards.

### workflow-params-flag-format
- **severity**: major
- **check**: Verify that `./bin/workflow run` invocations pass `--params` as a sequence of repeatable `key=value` flags, one per param — not as a JSON object or a single comma-separated string.
- **triggers**: Workflow YAML stage descriptions or flow invocation examples that call `./bin/workflow run --params '{"key": "val", ...}'` or `--params "k1=v1,k2=v2"`; any invocation where `--params` appears once with multiple key-value pairs.
- **example**: `./bin/workflow run workflows/foo.yaml --params '{"team": "sre", "window": "7d"}'` — the param parser returns a non-zero exit when given a JSON object instead of `key=value`. Fix: `./bin/workflow run workflows/foo.yaml --params team=sre --params window=7d`.

### writes-to-output-path-mismatch
- **severity**: major
- **check**: Verify that every path in a stage's `writes_to` list is consistent with where the stage will actually write output. The resolved write path differs by entry format — bare entries (no recognized prefix) are resolved under `{workspace}/outputs/`, while entries starting with recognized prefixes (`outputs/`, `validation/`, `stages/`, `dispatch/`) are resolved directly under `{workspace}/`. A mismatch between the description's write target and the `writes_to` resolution causes downstream stages to find no input.
- **triggers**: Workflow YAML stage descriptions that instruct the agent to write to a path that doesn't match the `writes_to` entry resolution; stage descriptions that say "write `{workspace}/analysis/file.json`" while `writes_to` lists `file.json` (which resolves to `{workspace}/outputs/file.json`); any mismatch between the path in the description and the resolved path.
- **example**: A stage description says "write `{workspace}/analysis/status.txt`" and `writes_to: ["status.txt"]`. `status.txt` resolves to `{workspace}/outputs/status.txt`. The agent writes to `{workspace}/analysis/status.txt`; downstream stages find nothing. Fix: align the description's write path with the `writes_to` entry's resolved location.

### writes-to-early-exit
- **severity**: major
- **check**: Verify that every file declared in `writes_to` is written on all code paths, including early-exit and skip branches — not only on the success path.
- **triggers**: Workflow YAML stages with a `writes_to` list whose description includes a conditional skip or threshold check ("if X, skip", "when no files match", "early exit when") without an explicit fallback write for the skipped branch; stages that write their outputs inside an `if` block with no corresponding `else` write.
- **example**: A stage declares `writes_to: [coverage/coverage-verified.json]` and its description says "exit early if pre-check indicates expansion was skipped". The early-exit path never writes `coverage-verified.json`, so the workflow orchestrator's post-group verification sees a missing file and fails all downstream stages that read it. Fix: write a sentinel JSON (`{"skipped": true}`) on the early-exit path so the `writes_to` contract is satisfied on every branch.

### dag-header-comment-stale
- **severity**: minor
- **check**: Verify that the workflow file's header DAG comment (the ASCII dependency graph near the top) accurately reflects the actual stage dependencies and parallel groups as declared in each stage's `depends_on` field.
- **triggers**: Workflow YAML files with a header comment containing a stage dependency graph (e.g. `A --> B`, `A --- B [parallel]`); any diff that adds, removes, or reorders stages, or changes a `depends_on` list without updating the header comment.
- **example**: The header comment shows two stages as parallel, but one was later changed to depend on the other, making them sequential. Operators reading the header to understand run order get a misleading picture. Fix: update the header graph from the `depends_on` topology after any structural change.

### stage-hardcoded-ignores-param
- **severity**: major
- **check**: Verify that numeric or string literals in stage bodies do not duplicate a value already covered by an existing `trigger.params` placeholder — hardcoding the literal means callers who override the param get inconsistent behavior.
- **triggers**: Workflow YAML stage descriptions or inline scripts that embed a numeric threshold, rate, or string constant as a literal where the same workflow or fragment already defines a `{param_name}` placeholder for that value; stage descriptions referencing a specific number (e.g. "80%", "--threshold 80") when a `{min_coverage}` or equivalent param exists in `trigger.params`.
- **example**: A pre-check stage hard-codes `--threshold 80` in its CLI invocation, but the workflow already declares `{min_coverage}` in `trigger.params` and other stages use `{min_coverage}` correctly. A caller who passes `--params min_coverage=90` sees the pre-check use 80 while all downstream stages use 90. Fix: replace the literal with `{min_coverage}` in every stage that references that threshold.

### agent-spec-unsupported-field
- **severity**: major
- **check**: Verify that `agent:` blocks in workflow stages do not contain fields beyond `role`, `model`, `tools`, `access`, and `isolation` — the workflow parser silently ignores any unknown key, so extra fields (e.g. `prompt`) are dropped and the intended behavior will never execute.
- **triggers**: Workflow YAML stages with an `agent:` block that contains fields other than the recognized set; stages where `agent.prompt` appears to describe a merge or post-processing step that would otherwise have no executor; stages whose `writes_to` contract depends on a step described only inside an unsupported `agent.prompt` field.
- **example**: A stage declares `agent: {role: researcher, model: sonnet, prompt: "Merge per-team findings into output.json"}`. The `prompt` field is an unknown key and is silently dropped, so the merge never runs. Fix: move the merge logic into the stage `description:` field, or implement it as a dedicated inline step in `script:`.

### embedded-script-nondeterministic-glob
- **severity**: major
- **check**: Verify that inline Python scripts embedded in workflow stages wrap `glob.glob()` calls with `sorted()` — filesystem glob order is not guaranteed and unordered iteration produces non-deterministic output ordering and key-merging behavior across runs.
- **triggers**: Workflow YAML `script:` blocks or `python3 -c "..."` snippets containing `glob.glob(` without an enclosing `sorted(...)`; merge or shard-loading loops that iterate directly over `glob.glob(...)` results; stages whose descriptions say "merge per-team files" or "load shards" using a glob pattern.
- **example**: A merge stage contains `for path in glob.glob(f"{workspace}/outputs/*/findings.json"): ...`. Filesystem readdir order varies by OS, kernel version, and directory entry count — two runs on the same inputs may merge keys in a different order, producing different output. Fix: `for path in sorted(glob.glob(f"{workspace}/outputs/*/findings.json")): ...`.

### trigger-params-shadow-work-dir
- **severity**: critical
- **check**: Verify that `trigger.params` does not declare a `work_dir` key (especially `work_dir: ""`) — the engine's param merge order lets trigger-declared params silently override the built-in `work_dir` default, breaking every downstream `{work_dir}` substitution in the same workflow.
- **triggers**: `trigger.params` blocks containing a `work_dir:` key with any value, particularly an empty string; `workspace_dir:` fields using `{work_dir}` in a workflow whose `trigger.params` also defines `work_dir`.
- **example**:
  ```yaml
  # bad — shadows the engine's built-in work_dir default
  trigger:
    params:
      work_dir: ""
      team: "sre"

  stages:
    - name: init
      workspace_dir: "{work_dir}/my-workflow-{team}"
      # resolves to "/my-workflow-sre" — rooted at filesystem root

  # good — omit work_dir from trigger.params entirely
  trigger:
    params:
      team: "sre"
  ```

### execute-stage-side-effect-conflict
- **severity**: major
- **check**: Verify that stages performing external side effects (`git push`, publishing, posting comments) are declared `kind: publish`, not `kind: execute` — the workflow dispatcher's own agent prompt tells the agent that only `kind: publish` stages are authorized for external side effects, so a `kind: execute` stage taking one gives the agent directly conflicting instructions.
- **triggers**: Workflow YAML stages with `kind: execute` whose description contains `git push origin`, API calls that create or modify external resources, or other irreversible side effects.
- **example**:
  ```yaml
  # bad — kind: execute contradicts the dispatcher's side-effect rule
  - name: commit-changes
    kind: execute
    description: |
      git add -A && git commit -m "..." && git push origin {branch}

  # good — side-effecting stages are kind: publish
  - name: commit-changes
    kind: publish
    description: |
      git add -A && git commit -m "..." && git push origin {branch}
  ```

### workflow-yaml-invalid
- **severity**: critical
- **check**: For every workflow YAML file touched by the diff, run
  `./bin/workflow compile <file>` from the project root and verify it exits 0.
  A non-zero exit means the file has a schema error, unknown stage reference,
  missing dependency, or dependency cycle — the workflow cannot be run as written.
- **triggers**: Any diff that adds or modifies a file matching `workflows/**/*.yaml`
  or `workflows/**/*.yml`.
- **example**: A new stage declares `depends_on: [missing-stage]` — compile exits
  non-zero with `WorkflowCompileError: unknown stage 'missing-stage'`. The PR must
  not be merged until `./bin/workflow compile` exits 0 cleanly.

### workflow-pseudocode-wrong-path
- **severity**: major
- **check**: Verify that module paths, method signatures, and data shapes cited in workflow stage pseudocode exist in the actual codebase — agents following pseudocode that points at non-existent files or wrong method signatures will immediately fail or produce wrong output.
- **triggers**: Workflow YAML stage descriptions containing `import` statements, file paths, or method calls with concrete module paths or method signatures; pseudocode that names argument names or return-value keys that differ from the actual implementation.
- **example**: A stage description imports `from mail.providers import GmailProvider` — but the actual class lives under `mail/gmail_provider.py`. The agent follows the pseudocode, gets `ModuleNotFoundError`, and fails. Fix: verify all pseudocode paths with `find . -name '*.py' | xargs grep -l 'class GmailProvider'` before committing the workflow. Also check method signatures match the actual module.
