---
name: critique
description: Run an adversarial Opus critique against a design doc, a workflow YAML, a set of files, or the current diff, using the plan-critic fragment (internal-consistency check -> adversarial critique -> fact-check -> consolidated summary -> human gate -> optional revision). Use when the user says "critique this", "adversarial review", "opus critique", or wants a design/plan scrutinized before acting on it.
allowed-tools: Agent, Bash, Read, Write, Edit, Glob, Grep, Task, Skill
skills:
  - dancing-bear-rules
---

# Critique — Adversarial Review Entry Point

Runs `workflows/shared/critique.yaml`, which wraps the existing
`workflows/shared/plan-critic.yaml` fragment (validate → critic (Opus) →
validate-critique → consolidate → human-gate → revise) behind a
`prepare-target` stage so it can be pointed at a single doc, several files,
or the current diff — not only used as an `include:` inside another workflow.

## When to Use

- User says "critique this", "adversarial review", "opus critique", "run a critic pass"
- Before running a normalize/apply workflow that writes code across many files
- Reviewing a design doc or workflow YAML before committing to it
- Reviewing a batch of just-written code/docs before opening a PR

## Usage

```
/critique .llm/DESIGN_CRITERIA.md
/critique workflows/code/design-criteria-normalize.yaml
/critique --targets .llm/DESIGN_CRITERIA.md,workflows/code/design-criteria-audit.yaml,workflows/code/design-criteria-normalize.yaml
/critique --diff                        # uncommitted changes (git diff HEAD)
/critique --diff-ref main...HEAD        # diff against a ref
/critique --focus "worktree isolation safety"
```

## Input Parsing

| Argument | Required | Default | Description |
|----------|----------|---------|--------------|
| positional / `--target` | No* | -- | Single file path to critique |
| `--targets` | No* | -- | Comma-separated file paths, concatenated into one critique target |
| `--diff` | No* | -- | Critique uncommitted changes (`git diff HEAD`) |
| `--diff-ref` | No* | -- | Critique a diff against a ref, e.g. `main...HEAD` |
| `--focus` | No | full-spectrum | One-line directive narrowing the critique (e.g. "idempotency on re-run") |

\* Exactly one of `--target`/positional, `--targets`, `--diff`, `--diff-ref` should be given. If none are given, defaults to `--diff` (uncommitted changes) — this matches "critique what I just did."

## Running

Invoke via the `/workflow` skill — do not hand-roll a critic Agent() call when this skill applies, since the included fragment already chains fact-checking and a human gate around the raw critique (a lone critic-agent spawn skips both). Do NOT invoke `./bin/workflow run workflows/shared/critique.yaml` directly: agent-required stages route through `SkillDispatcher`, which only writes dispatch JSON and returns `pending` — it does not spawn or wait for agents, so the critique will not actually execute end-to-end. The `/workflow` skill is the orchestrator that spawns agents, waits for results, and drives human gates.

```python
Skill(skill="workflow", args="--workflow workflows/shared/critique.yaml --execute --params target=<path> --params critic_focus=<focus or empty>")
```

For `--diff`/`--diff-ref`, leave `target`/`targets` blank and set `diff_ref`:
```python
Skill(skill="workflow", args="--workflow workflows/shared/critique.yaml --execute --params diff_ref=<ref or empty for uncommitted> --params critic_focus=<focus or empty>")
```

For `--targets`, pass the comma-separated list as `targets`:
```python
Skill(skill="workflow", args="--workflow workflows/shared/critique.yaml --execute --params targets=path/one.md,path/two.yaml --params critic_focus=<focus or empty>")
```

## Output

The workflow presents a human gate with
`{workspace}/outputs/plan-critic-summary.md` — internal-consistency findings,
fact-checked blockers/suggestions, strengths, and a numbered revision list.

If the user approves revisions, `pc-revise` (from the included fragment)
edits the workspace snapshot (`context/target.md`), never the caller's real
file directly — the fragment expects one flat editable document, and
multi-target/diff modes have no single file to write back to anyway. A
final `writeback-target` stage then closes that gap for single-target mode
only: it copies the approved, revised content from the snapshot back to the
real `--target` file. Diff mode and multi-target mode have no writeback
destination — `writeback-target` no-ops for them and revisions surface as
findings only (visible in `plan-critic-summary.md`, not applied anywhere).

## Notes

- This is the same critique pipeline `design-criteria-normalize.yaml`'s
  `opus-review` stage uses conceptually, but standalone and re-runnable
  against anything, not gated behind that specific workflow.
- `workflows/shared/plan-critic.yaml` is `fragment: true` and cannot be run
  directly with `./bin/workflow run` — always go through `critique.yaml` (or
  another workflow's `include:`), never invoke the fragment file itself.
