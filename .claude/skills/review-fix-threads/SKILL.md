---
name: review-fix-threads
description: Fetch every PR review thread (Copilot and human), triage each one, fix them in parallel, verify with happy/sad-path coverage, refresh the PR title and description, then reply to and resolve every thread. Use when the user says "address the review threads", "fix the review comments", "handle the Copilot feedback", or "resolve the threads on PR N".
allowed-tools: Task, TaskOutput, Bash, Read, Write, Edit, Glob, Grep, Agent, Skill
skills:
  - dancing-bear-rules
---

# Review, Fix, and Resolve PR Threads

Delegates to `workflows/code/review-fix-threads.yaml`. Runs unattended from
"here is a PR" to "every thread has a reply and is resolved".

## When to Use

- A PR has Copilot and/or human review threads waiting on the author
- The user says "address the feedback", "fix the review comments", "resolve the threads"
- Feedback has already been reviewed and now needs remediation

Use `/code-review` instead when the PR needs *reviewing* — this skill consumes
review threads that already exist, it does not produce them.

## Autonomy

There is no human gate. The workflow posts replies and resolves threads without
confirmation, including on threads it decided **not** to action — a rejected or
moot thread gets a reply explaining why, then is resolved.

What constrains it:

- `verify-fixes` reports itself failed and exits non-zero when tests, lint, or
  coverage are not green, which halts the run before anything is posted.
- `resolve-threads` re-checks `all_green` itself and **fails closed**: a
  missing, unparseable, or ambiguous verification file aborts the stage. Same
  for a missing replies file — it will not compose replacement prose at the
  moment of posting.
- A reply always posts before its thread resolves. A resolve whose reply failed
  is skipped and reported.
- Threads whose fixer crashed, or whose fix was never tested, are never
  resolved and never receive a reply claiming a fix.
- `context` and `defer` threads are never resolved — including threads deferred
  by the `max_threads` ceiling, since that is a scheduling outcome rather than
  a judgement about the comment.
- Every rejection is recorded with evidence in the final report, so the calls
  made on your behalf can be audited after the fact.

The honest caveat: stage status is self-reported. The engine skips downstream
stages only when a required stage reports `failed`, and the completion template
each agent receives pre-fills `"status": "success"`. The workflow instructs
`verify-fixes` to override that on red, but the last real defence is
`resolve-threads`' own fail-closed gate rather than the orchestrator.

Tell the user the run resolves threads autonomously before starting it, so a
run against someone else's PR is a deliberate choice.

## Derive Params from Context

```bash
GITHUB_TOKEN= gh pr view --json number -q .number
```

If that returns a number, use it. If the branch has no open PR, ask — the
workflow refuses to guess.

## Invocation

**IMPORTANT**: Use the `/workflow` skill — do NOT call `./bin/workflow run --execute`
directly. That only writes dispatch files and exits (status=pending). The
`/workflow` skill is what spawns agents and walks the DAG.

```python
Skill(skill="workflow", args="--workflow workflows/code/review-fix-threads.yaml --params pr_number=259")
```

With a narrower test command:

```python
Skill(skill="workflow", args="--workflow workflows/code/review-fix-threads.yaml --params pr_number=259 test_cmd='make test' max_threads=15")
```

## Params

| Param | Default | Description |
|-------|---------|-------------|
| `pr_number` | `""` | PR number (auto-detected from branch if blank) |
| `test_cmd` | `"make test"` | Full-suite verification command |
| `include_resolved` | `"false"` | `"true"` re-triages already-resolved threads |
| `max_threads` | `"12"` | Concurrent-agent ceiling, counted in distinct **files**; overflow is deferred and reported, never dropped |

## Stages

1. **init** — resolve and validate the PR; confirm the checkout is on its head branch
2. **fetch-threads** *(fragment)* — all three comment surfaces, full comment chains
3. **triage-threads** — classify each thread: fix / reject / moot / defer / context
4. **fix-dispatch** — group actionable threads **by file** into a fan-out index
5. **fix-threads** — one `thread-fixer` agent per file group, in parallel
6. **fix-aggregate** — merge per-thread results; flag any that are missing
7. **verify-fixes** — `make test`, `make lint`, and a happy/sad-path coverage audit
8. **check-prose** — every outgoing reply checked against `.claude/WRITING_GUIDE.md`
9. **update-pr-description** *(fragment)* — regenerate title and body from the final diff
10. **resolve-threads** — reply, then resolve; aborts if verification was not green
11. **report** — per-thread outcome table

## Triage Directives

| Directive | Meaning | Reply | Resolved |
|-----------|---------|-------|----------|
| `fix` | Real problem, concrete fix | what changed, where | yes |
| `reject` | Comment is wrong or the behaviour is intentional | reasoning + evidence | yes |
| `moot` | Code no longer exists, or already fixed | why it no longer applies | yes |
| `defer` | Real but out of scope | what should happen instead | **no** |
| `context` | Not an ask — a summary or acknowledgement | none | no |

## Shared Fragments

Both are reusable outside this workflow:

- **`workflows/shared/pr-review-threads.yaml`** — the correct thread fetch.
  GraphQL review threads *plus* REST review bodies *plus* REST issue comments,
  with full comment chains, pagination, and `[bot]`-suffix reconciliation.
- **`workflows/shared/pr-describe.yaml`** — regenerate PR title and body from
  the final diff, checked against the writing guide, pushed via `--body-file`.

## Why the Fetch Is a Fragment

Getting the threads right is most of the work, and three call sites previously
got it wrong in three different ways:

- `bin/pr-assistant` requests `comments(first: 1)` and keeps only threads whose
  *first* comment is from Copilot. A human reply inside a thread — including one
  that overrides the bot — is invisible to it.
- GitHub spells the same bot two ways: GraphQL returns
  `copilot-pull-request-reviewer`, REST returns
  `copilot-pull-request-reviewer[bot]`. Matching one spelling misclassifies
  threads on the other surface.
- `reviewThreads(first: 100)` without a `pageInfo` check truncates silently. A
  PR with more than 100 threads looks identical to a clean one.
- Outdated threads return `line: null`. Code that assumes an integer either
  crashes or invents a line number.
- Top-level review bodies and PR-level issue comments are not review threads at
  all, so `reviewThreads` never returns them — and Copilot's overall verdict
  lives there.

## Notes

- The `thread-fixer` agent fixes exactly one thread and is forbidden from
  touching anything the thread did not ask about. Out-of-scope findings are
  reported, not fixed.
- The fan-out unit is a **file**, not a thread: `fix-dispatch` groups every
  thread anchored to the same path into one agent. Two agents editing one file
  concurrently is a lost-update race — the second agent's edit is based on a
  read that predates the first's write, silently reverting it. Grouping
  prevents that structurally; an instruction to "coordinate" would not.
- Behaviour-changing fixes need a **sad-path** test, not just a happy-path one.
  A bounds check tested only in-bounds asserts nothing about the bug it fixed;
  `verify-fixes` fails the run on that gap.
