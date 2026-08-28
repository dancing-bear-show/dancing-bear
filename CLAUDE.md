<!-- DO NOT REGENERATE: This CLAUDE.md is manually maintained. If /init is run, DO NOT overwrite — inform the user that CLAUDE.md already exists and is comprehensive. -->

# Claude Code Project Instructions

## Project Overview

Personal Assistants: unified, dependency-light CLIs for personal workflows across mail, calendars, schedules, phone layouts, resumes, and WhatsApp. Built to be safe by default (plan and dry-run first), with a single YAML source of truth for Gmail and Outlook filters.

**Constraints:** Python 3.11, dependency-light, stable public CLI

**Self-contained:** All helpers and utilities are repo-internal. External dependencies are minimal and lazily imported. This design ensures public CLI backwards compatibility and reduces fragility from external package changes. Internal APIs can be refactored freely—update all call sites atomically without backwards-compatible wrappers.

**Primary consumers:** LLM agents — CLI schemas, help text, and agentic capsules are designed for token-efficient LLM consumption. Keep output terse and accurate.

## Quick Start

```bash
# Setup
make venv

# Run tests
make test

# CLI help
./bin/assistant <mail|calendar|schedule|resume|phone|whatsapp|maker> --help
./bin/mail --help
./bin/calendar --help
```

## Architecture

```
src/                      # all Python source packages (installable via package-dir=src)
  mail/                   # Gmail/Outlook providers, CLI wiring, helpers
  calendars/              # Outlook calendar CLI + Gmail scans
  schedule/               # plan/apply calendar schedules
  resume/                 # extract/summarize/render resumes
  phone/                  # iOS layout tooling
  whatsapp/               # local-only ChatStorage search
  desk/                   # desktop/workspace tooling
  maker/                  # utility generators
  charts/                 # render time-series charts from JSON (line/bar/area/dual)
  diagrams/               # Mermaid diagram generation (flowchart/sequence/gantt/pie; telemetry cost/token pies)
  slides/                 # generate PowerPoint decks from YAML deck definitions
  sheets/                 # generate styled .xlsx spreadsheets from YAML workbook definitions
  workflow/               # YAML DAG workflow engine (parse/compile/run/lint/list/status)
  core/                   # shared helpers
  telemetry/              # Claude Code session telemetry (cost, tokens, TUI)
  worker/                 # background job queue and daemon
  apple_music/            # Apple Music CLI
  wifi/                   # Wi-Fi CLI
  qlty/                   # qlty scan/triage wrapper (tiers findings by remediation strategy)
bin/                      # entry wrappers and helper scripts
tests/                    # lightweight unittest suite
.llm/                     # LLM context, flows, capsules
configs/                  # runtime config templates (e.g. launchd plist)
out/                      # derived outputs and plans
```

## LLM Context Files

Read in order for best context:
1. `.llm/CONTEXT.md` - system overview and rules
2. `.llm/MIGRATION_STATE.md` - current status and remaining work
3. `.llm/PATTERNS.md` - copy-paste templates for common tasks
4. `./bin/llm domain-map --stdout` - where things live in the codebase. Generator-owned
   and not checked in: `.llm/DOMAIN_MAP.md` exists only after
   `./bin/llm derive-all --include-generated`, so read it via the command, not the path.

## CLI Argument Conventions

All CLIs use argparse with positional subcommand dispatch. Arguments are passed directly. Most CLIs accept a `--` separator before flags (used by the workflow engine in `src/workflow/compiler.py`); a small set (`llm`, `docs`) omit it.

**Dispatch model**: `./bin/assistant <app> <subcommand> [flags]`

| Entry point | Subcommand depth | Example |
|---|---|---|
| `./bin/assistant` | dispatches to app | `./bin/assistant mail labels sync` |
| `./bin/mail-assistant` | 2–3 levels deep | `mail-assistant labels sync --dry-run` |
| `./bin/calendar` | 2–3 levels deep | `calendar outlook add --subject "..."` |
| `./bin/llm` | 1–2 levels deep | `llm agentic --stdout` |
| `./bin/worker` | 1 level deep | `worker enqueue --type <type>` |
| `./bin/telemetry` | 1 level deep | `telemetry cost --days 7` |

**Key rules:**
- Subcommands are positional, not flag-prefixed
- Flags (`--dry-run`, `--profile`, `--format`) always follow the subcommand
- The `assistant` dispatcher strips the app name and passes remaining argv directly to the app's `main()`
- The workflow engine (`src/workflow/compiler.py`) inserts `--` before flags for most skills; `llm` and `docs` CLIs are exempt (`_NO_SEPARATOR_CLIS`). `docs` is reserved for a planned external documentation CLI — no `bin/docs` ships today
- `--` separator is now **optional** for all CLIApp-based CLIs (mail, calendar, schedule, resume, phone, whatsapp, desk, wifi, maker, apple_music, workflow); `src/core/cli_framework.py` strips bare `--` tokens automatically. The workflow engine's `_NO_SEPARATOR_CLIS` exemption for `llm`/`docs` remains unchanged.
- Auto-derived agentic schema: **all 18 apps** support `--agentic --agentic-format json` to emit a machine-readable parser schema that never drifts from the real CLI; add `--agentic-compact` to strip low-value fields; add `--agentic-domain <prefix>` to filter to one subcommand group. Run `./bin/llm inventory --stdout` for the authoritative list — it prints the exact invocation per app, because `./bin/<app>` is wrong for four of them (`apple-music` and `qlty` use `-assistant` wrappers, `resume` goes through `./bin/assistant resume`, and `desk` has no wrapper: `python3 -m desk`).
- Most apps get this via `CLIApp.run_with_assistant()`. Four wire it manually to preserve legacy no-subcommand exit codes: charts (1) and diagrams (0) call `assistant.add_agentic_flags(parser)` then `maybe_emit_agentic(...)` before their `cmd_func is None` branch; worker (1) and workflow (2) pass `on_no_command=` through `run_with_assistant()`. telemetry is Click, not argparse, so it declares eager `--agentic*` options on the group with `invoke_without_command=True`.

## Development Rules

**Do:**
- Keep CLI flags/subcommands stable; add new under `labels`, `filters`, `outlook`
- Prefer wrapper executables (`./bin/mail`) over `python -m`
- Use profiles in `~/.config/credentials.ini`; avoid `--credentials/--token`
- Apply lazy imports for optional deps (Google APIs, PyYAML)
- Keep helpers small, focused; prefer OO where cohesive (e.g., LabelSync, FilterSync)
- Update README minimally when adding user-facing commands; add tests for new CLI surfaces

**LLM Consumer Rules:**
- Keep help text terse (1-line descriptions, no prose)
- Ensure `--help` output matches actual implementation
- Verify agentic schema (`--agentic`) accurately reflects CLI structure
- Use `--agentic-compact` output for token efficiency
- Test CLI discovery: `./bin/llm agentic --stdout` must be accurate
- Flows in `.llm/FLOWS.yaml` must reference valid CLI paths

**Avoid:**
- Broad refactors that rename modules or move public entry points
- Heavy new dependencies; global imports for optional modules
- Emitting secrets/tokens in logs or passing them via flags
- Bare `except Exception: continue/pass` blocks without a `# nosec B110/B112` comment explaining the intent (e.g., `# nosec B112 - skip malformed entries silently`)
- Verbose help strings that waste tokens
- Mismatched argument names between argparse and code
- Breaking backwards compatibility of public CLI commands or parameters (bin/* entry points)
- Moving utilities to external packages (keep self-contained for stability)
- Maintaining backwards-compatible wrappers for internal APIs (update all call sites instead)

## Testing and Code Quality

**Linting (qlty):**
- Check files: `~/.qlty/bin/qlty check path/to/file.py`
- Check module: `~/.qlty/bin/qlty check src/mail/`
- Auto-fix: `~/.qlty/bin/qlty check --fix path/to/file.py`
- Linters: ruff (style), bandit (security), complexity metrics

- **`make lint` is NOT sufficient before opening a PR.** It runs ruff only.
  CI runs `qlty check`, which adds bandit and radarlint on top — so a branch
  can be green on `make lint` and still fail CI. Always run qlty over the files
  the branch actually changes before pushing:

  ```bash
  git diff --name-only main...HEAD          # note THREE dots
  ~/.qlty/bin/qlty check $(git diff --name-only main...HEAD)
  ```

  The destructive-bash guard hook rejects that second form in a worktree-isolated
  session ("too complex to verify") because of the command substitution. Split it:
  write the list to a file first, then pass the paths explicitly.

  Findings that ruff never reports and qlty does: `bandit:B105`/`B106`
  (hardcoded-password heuristics, which fire on any `token=`/`password=` kwarg
  — usually false positives in tests), and `radarlint-python:python:S1481`
  (unused local, where ruff's F841 stays silent because an attribute
  assignment like `args.profile = None` counts as a use).
- **Use `main...HEAD` (three dots), not `main..HEAD`.** Two dots diffs against
  the current tip of main, so every commit merged into main since you branched
  shows up as if it were yours. On a day-old branch that turned 9 changed files
  into 46, burying the real findings. Three dots diffs against the merge-base —
  your changes only, and the same set CI evaluates.
- Suppress a genuine false positive inline with a reason, matching the existing
  convention (`# nosec B106 - test file path, not a secret`). See
  `tests/mail_tests/test_config_resolver.py` for the house style.
- For repo-wide triage prefer `./bin/qlty-assistant` over raw qlty: it merges
  `check` + `smells` (disjoint sets — running one hides the other), defaults to
  `--all`, dedupes clone groups, and ranks findings by remediation tier
- That repo-wide form is for *triage*, not for pre-PR verification. It reports
  findings across the whole tree, most of which predate your branch, so a real
  regression of yours is easy to miss in the volume. Scope to `main...HEAD` as
  above when the question is "did I introduce anything new?"
- On a test-heavy branch `qlty smells` adds little: it skips test files, so a
  9-path scan may analyse structure on only 1 of them. `qlty check` is the gate
  that matters there.
- `./bin/qlty-assistant scan --expect-min N` fails loudly on an implausibly
  empty scan — still worth using as a sanity check on any surprisingly clean result
- **qlty now scans correctly from inside an agent worktree.** The exclusion is
  `**/.claude/worktrees/**`, narrowed from `**/.claude/**`. The old pattern also
  matched the `.claude/` directory *inside* each worktree — and since a worktree
  is a full checkout, a scan run from one reported "0 issues" against 0 scanned
  files. That false clean was indistinguishable from a real pass and hid findings
  until CI. Verified by injecting a probe defect: `ruff:F811`, `ruff:E402`, and
  `bandit:B307` are all reported from within a worktree.
- The narrowed pattern still excludes worktrees when scanning **from the main
  checkout**, which is what it is for — there are dozens of them, and each is a
  full copy of the repo.
- Exclusions resolve relative to the scan root, which is why the same pattern can
  exclude a path from one root and not another.

**Linting (ruff directly):**
- Use `make lint` (or `make lint-fix`), never a bare `ruff check`
- There is **no standalone `ruff` on PATH**. CI lints through `qlty check`, which
  runs ruff from qlty's own pinned tool cache — so `ruff check <file>` fails as
  "command not found", and a `pip install ruff` would drift from the version CI
  enforces. `bin/ruff-resolve.sh` resolves the qlty-pinned build (override with
  `RUFF_BIN=`), and `make lint` wraps it over `src/`, `tests/`, and `bin/`
- This matters because a bare `ruff` may not exist, and a missing tool is not a
  passing lint. (The companion trap — `qlty check` in a worktree silently
  scanning zero files — was fixed by narrowing the exclusion to
  `**/.claude/worktrees/**`; see the qlty section above.)
- If the tool cache is cold, run any `~/.qlty/bin/qlty check` once to populate
  it, then `make lint`
- Suppression codes are linter-specific: `# noqa:` takes ruff codes (`F401`,
  `S602`), `# NOSONAR` takes SonarQube codes (`S3776`, `S3516`). A SonarQube code
  in a `# noqa:` suppresses nothing and makes ruff warn on every run

**Testing:**
- Run tests: `make test` (pins `PYTHONPATH` to this checkout — always prefer it)
- With coverage: `make cov`
- Add targeted tests only for new CLI surfaces/behaviors
- Never run tests that require network/secrets without explicit user approval

**CRITICAL — never run bare `python3 -m unittest` in a worktree.** An inherited
`PYTHONPATH` (direnv activated in the main checkout, or the main repo's venv
still active in the shell) takes precedence over the editable install and
silently resolves `core`/`mail`/`worker` to the **main checkout's** source. Tests
then pass against unmodified code — a false green that looks identical to a real
one, and only turns red once a newly added module is imported by name.

- Use `make test`, or `PYTHONPATH="$PWD/src" python3 -m unittest discover -s tests`
- `make check-env` verifies imports resolve to the current checkout and fails loudly if not
- This applies to subagents too: an agent verifying with bare `python3` in an
  isolated worktree is not verifying anything

**CRITICAL — exit code 0 is not evidence the suite ran.** `test:` depends on
`venv:`. When several agent worktrees run `make test` concurrently they race on
shared pip/build state, and `make venv` can die in a way that still reports
`EXIT=0` with **no `Ran N tests` line anywhere in the output**. A green exit from
a run that executed zero tests is indistinguishable from a real pass.

Always confirm the summary line, never the exit code alone:

```bash
make test > /tmp/t.log 2>&1; echo "EXIT=$?"; grep -E "^Ran [0-9]+ tests" /tmp/t.log
```

- The `2>&1` is required: unittest writes `Ran N tests`, `OK`, and `FAILED` to
  **stderr**. Redirecting only stdout, or piping to `tail` without merging
  stderr, hides the verdict along with every failure
- No `Ran N tests` line means the suite did not run — re-run it, do not report a
  baseline

**CRITICAL — a CLI can print pre-change behaviour from a source tree you are not
editing.** The symptom is a command that shows the old output while your edit is
plainly in the file, which looks exactly like "the fix didn't work."

The `bin/*` wrappers are **not** at fault. Each is a symlink to `bin/_router.py`,
which resolves `_REPO_ROOT` through the symlink (`bin/_router.py:35`), inserts
that repo's `src/` on `sys.path` (`bin/_router.py:53-55`), and re-execs under
`_REPO_ROOT/.venv/bin/python3` when one exists (`bin/_router.py:36-51`). Run
`./bin/<tool>` from a worktree and the router does point at that worktree.

What actually redirects the import:

- **An inherited `PYTHONPATH`** — the same root cause as the `unittest` trap
  above, and the common one. `PYTHONPATH` entries land ahead of both the
  editable install's `.pth` and the router's own insert (which is guarded by an
  `if not in sys.path` check), so another checkout's `src/` wins on `sys.path`
  and the wrapper loads that tree's code
- **Invoking a wrapper by absolute path** from another checkout — that runs
  *that* checkout's source, correctly and by design
- **A `.venv` whose editable install points elsewhere** — each worktree's
  `.venv/…/__editable__*.pth` holds the absolute `src/` of whichever checkout
  ran `make venv` in it

**The general rule, which covers this case, the `unittest` case, and the
`make venv` race above: before concluding a change did not take effect, print
where the module actually loaded from.**

```bash
python3 -c "import resume; print(resume.__file__)"   # must be YOUR src/
```

If that path is not under the tree you are editing, the code never ran — the
change is fine and the environment is wrong.

**Coverage exemptions** (`.coveragerc`):
- `*/__main__.py` is omitted. These are `python -m <pkg>` entry shims: a
  docstring, `from .cli import main`, and a `__main__` guard. The only
  measurable statement is the import, so a test there asserts that Python can
  import a module — not that the CLI works. Cover the underlying `cli.main`
  instead; `make bin-wrappers-check` verifies the wrappers actually dispatch.
- Do **not** write tests whose only purpose is to import a module and raise its
  coverage number. A test must assert behaviour.
- Note that a re-export-only `__init__.py` already reports ~100% because any
  import of the package executes it. That number is free, not earned — don't
  read it as evidence the package is tested.
- Conversely, do **not** exempt a module just because it reports 0%. Check why
  first. `src/telemetry/tui/` once sat at 0% because `textual` was never
  declared as a dependency, so the lazy import in `telemetry/tui/__init__.py`
  never fired — a missing optional dep reports as 0%, indistinguishable from
  untested code. That was a real gap, fixed by declaring the `[tui]` extra.
- **An optional dependency must be declared as an extra and installed wherever
  coverage is measured** (`make cov`, `make dev-venv`, and CI all install
  `[tui]`). An undeclared optional dep silently zeroes out whole modules.
- Guard optional imports at the narrowest scope that needs them. Only
  `telemetry live` requires textual; `stats` and `summary` render via Rich and
  must not be gated behind a textual check.

**CI/CD:**
- `.github/workflows/ci.yml` runs qlty checks + tests with coverage on push/PR
- Coverage uploaded to qlty for tracking
- Both jobs must pass for merge

## Check for an Existing Workflow First

**Before starting any multi-step task, check whether a workflow already does it.**
This repo has 52 workflows (count as of 2026-08-28 — `./bin/workflow list` is
authoritative). Reinventing one wastes the work already invested in it and
produces a second, diverging implementation of the same process.

```bash
./bin/workflow list                      # live catalog — authoritative
./bin/workflow list | grep -i <keyword>  # narrow by intent
```

Applies when the request is a *process* with more than a couple of steps —
review a PR, mine concerns, sweep complexity, expand coverage, debug CI, tailor
a resume, open a PR, reorganize the phone layout. Skip it for single-file edits,
quick reads, and git operations.

Decision order:

1. **A workflow matches** → run it: `./bin/workflow run <file> --params k=v`.
   Say which one you're using and why.
2. **A workflow nearly matches** → run it and note the gap, or improve that
   workflow. Do **not** fork a near-duplicate.
3. **Nothing matches** → do the task directly. If it is likely to recur, offer
   to capture it with `/write-workflow`.

Use `/select-workflow` when the intent is clear but the file name isn't. Treat
any catalog in a SKILL.md as a fast-path index only — it drifts, so confirm
against `./bin/workflow list` before claiming a workflow does or doesn't exist.

Improving an existing workflow beats adding a new one. When you run one by hand
and hit a gap the YAML didn't cover, fix the YAML — that is how these get better.

## Key Commands

```bash
# Check for an existing workflow BEFORE doing multi-step work
./bin/workflow list

# Token-efficient agentic schemas (prefer over --help)
./bin/mail --agentic --agentic-format yaml --agentic-compact
./bin/llm agentic --stdout

# Domain map
./bin/llm domain-map --stdout

# Flows
./bin/llm flows --list
./bin/llm flows --id <flow_id> --format md

# Visualization + orchestration
./bin/charts render <spec.json>          # render a chart (also: grid, reshape)
./bin/diagrams from-yaml <spec.yaml>     # Mermaid from YAML (also: render, validate, embed, telemetry)
./bin/workflow run <workflow.yaml>       # run a YAML DAG (also: parse, compile, lint, list, status)
```

## Auto-Familiarization

At conversation start, BEFORE responding to the user's first request, run:

```bash
./bin/llm familiar --stdout
```

This emits a read-only familiarization capsule (skip paths, step sequence). Use `--compact` for minimal token usage.

## Generated Output Location

Generated artifacts are written **outside the checkout** by default, resolved by
`src/core/paths.py`:

1. an explicit `--out-dir` passed to the command
2. `$DANCING_BEAR_DATA_HOME`
3. `$XDG_DATA_HOME/dancing-bear`
4. `~/.local/share/dancing-bear` (default)

Each domain gets a subdirectory (`<data-home>/resume`, `<data-home>/charts`, …).
A relative `--out-dir` is still honoured as-is, so `--out-dir out` writes to
`./out` for scripts that expect the old behaviour.

Rationale: relative defaults resolve against the working directory, so running a
command from the repo wrote generated files — including resumes carrying PII —
into the checkout. Those paths are gitignored, which prevents an accidental
commit but not an accidental `git clean -fdx`.

New output-producing domains should call `core.paths.output_dir("<domain>")`
rather than defaulting to a relative path.

## Credentials (Profiles)

Use profiles in `~/.config/credentials.ini`:

```ini
[mail.gmail_personal]
credentials = /path/to/google_credentials.json
token = /path/to/token.json

[mail.outlook_personal]
outlook_client_id = <YOUR_APP_ID>
tenant = consumers
outlook_token = /path/to/outlook_token.json
```

## Config Source of Truth

- Filter configs (when used): canonical YAML lives in `config/` (not yet created); derived outputs go to `out/`
- Always run plan first, then apply with dry-run, then apply for real

## Security

- Never commit `credentials.json` or tokens
- Restrict scopes to labels/settings/readonly/modify where required
- If sensitive data appears in logs, redact and rotate immediately

## Wait Policy — Monitor vs sleep-poll

Never use a bare `sleep` loop in a Bash tool call to wait for a condition.

- **Background task**: Set `run_in_background: true` on the Bash tool call, then use the Monitor tool with the returned task ID to stream output and get notified on completion.
- **Poll until condition**: Run `until <check>; do sleep 2; done` inside Monitor — you get one notification when the loop exits.
- **One-time fixed delay** (`sleep 1` to let a server bind its port): acceptable. Sleep-as-retry-loop: never.

## Worktree Isolation

**Session-level**: Always launch with `claude -w` to auto-create a worktree. Each session gets its own branch and working directory under `.claude/worktrees/`, preventing sessions from clobbering each other.

**Make it the default**: add `alias claude='claude -w'` to `~/.zshrc` so `-w` doesn't need to be typed (or remembered) on every launch.

**Subagent-level**: When spawning an Agent that writes code, use `isolation: "worktree"` so the subagent works in its own isolated copy of the repo. This prevents the subagent's edits from colliding with the parent session's working directory. Read-only agents (research, search, exploration) do not need isolation.

**CRITICAL — isolated worktrees do not auto-merge back**: Files written by a subagent with `isolation: "worktree"` live in its own ephemeral worktree branch and are **never automatically copied back to the parent branch**. After an isolated agent completes, you must explicitly copy its output files into the correct branch worktree before staging and committing. Always verify the agent's result is in the right place with `git status` on the target branch worktree before committing.

**Which worktree to commit to**: Identify the correct worktree with `git worktree list` before making any edits or commits. The session worktree (`wf_*`) may be sparse (few files). The branch you want to commit to may live in a different named worktree. Always check — never assume the main checkout is on your feature branch.

**If launched without `-w`**: Call `EnterWorktree` before your first file edit. Skip only for read-only requests (explain, search, explore).

**Git safety**:
- Never push directly to `main` — always use a PR from a worktree/feature branch
- Never force-push to `main`
- Never `git add -A` or `git add .` — stage specific files by name
- Never `git reset --hard`, `git clean -f`, `git checkout .` without explicit approval
- Before opening a PR, rename the ephemeral worktree branch to a conventional name: `feat/`, `fix/`, `chore/`, `docs/`
- After any subagent fan-out, run `git status` in **both** the subagent worktree and the target branch worktree to confirm files landed where intended
- Never commit to the main checkout without first verifying `git branch --show-current` matches your feature branch

**Parallel sessions** (tmux): Use `claude --tmux` to open a new pane with its own worktree, or split manually (`Ctrl-b %` / `Ctrl-b "`) and run `claude` in each pane. Each session is fully isolated — separate directory, branch, and context.

**Agent Teams** (coordinated parallel work): For 5+ tasks that need status tracking or mid-flight steering, use `TeamCreate` + `TaskCreate` instead of plain `Agent()` calls. Partition tasks by file/module to avoid conflicts — subagents in a team share the same worktree.

**Team lifecycle**:
1. `TeamCreate` — create the team and get a `team_id`
2. `TaskCreate` (per agent) — spawn each teammate with its role and initial prompt
3. Work phase — send steering messages via `SendMessage` as needed; read status via the team tools
4. `TeamDelete` — tear down the team after all tasks are complete

**Keep teams open** when tasks may produce follow-up work mid-flight (e.g., a reviewer finds bugs that the code-writer must fix). **Close immediately** when all tasks are independent and complete with no expected follow-up (e.g., parallel research or validation runs).

**Cleanup**:
- `git worktree list` — see active worktrees
- `git worktree remove .claude/worktrees/<name>` — remove one
- `git worktree prune` — prune stale references

## Agent Definitions

| Agent | Model | Use For |
|-------|-------|---------|
| `code-writer` | inherit | Feature development, bug fixes, refactoring |
| `doc-writer` | Sonnet | PR descriptions, changelogs, postmortems, READMEs |
| `reviewer` | Sonnet | Code review, dead code analysis, pattern finding |
| `tester` | Sonnet | Test writing, coverage expansion, test refactoring |
| `researcher` | Haiku | Fast codebase exploration, context gathering |
| `Explore` | Haiku | File pattern search, keyword search, "how does X work" |
| `Plan` | Sonnet | Implementation planning, architecture design |
| `fact-checker` | Haiku | Validate reports/docs after doc-writer completes |
| `unit-validator` | Haiku | Per-artifact validation, structured JSON findings |
| `cross-unit-validator` | Sonnet | Multi-artifact consistency checking |
| `ci-fixer` | Sonnet | CI failure diagnosis and fix |
| `code-writer-opus` | Opus | Escalate from code-writer when Sonnet is stuck or producing incorrect code after retries |
| `tester-opus` | Opus | Escalate from tester when Sonnet fails to produce passing tests after iteration |
| `critic` | Opus | Adversarial critique of plans, workflow designs, architecture decisions |
| `haiku-reviewer` | Haiku | Concern-sweep fan-out stages; writes JSON findings, no Bash |
| `workflow-author` | Sonnet | Authoring and editing workflow YAML DAGs |
| `thread-fixer` | Sonnet | One PR review thread per agent; fixes only what that thread asked, never resolves it |

**Spawn teammates** for multi-file changes, test writing, code review, research. Use `isolation: "worktree"` for agents that write code (`code-writer`, `tester`, `ci-fixer`). Read-only agents (`reviewer`, `researcher`, `Explore`, `Plan`, `fact-checker`, validators) do not need isolation.

**After isolated agents finish**: copy their output files from their worktree into the correct feature-branch worktree, verify with `git status`, then commit. Isolated agent edits never merge back automatically.

Do inline for single-line fixes, quick reads, git operations.

**Backstop agents** (spawn after primary work completes):
- `fact-checker` — always spawn after composing reports, postmortems, cost analyses, PR descriptions, or any deliverable that aggregates data from multiple sources.
- `reviewer` — code review, dead code analysis, pattern finding. Spawn after parallel implementation agents complete.

**Model selection**: Haiku for lookup + comparison. Sonnet for synthesis, judgment, multi-step reasoning. Inherit Opus only when generating code that will ship.

**Delegation Default** — when to spawn vs inline:

| Condition | Action |
|-----------|--------|
| Write/modify code touching >1 file | Spawn `code-writer` with `isolation: "worktree"` |
| Write/modify code in 1 file, >3 tool calls expected | Spawn `code-writer` with `isolation: "worktree"` |
| Write/modify code in 1 file, ≤3 tool calls | Inline edit |
| Add or expand tests | Spawn `tester` with `isolation: "worktree"` |
| Research / explore / read-only | Inline or spawn `researcher`/`Explore` (no isolation) |
| PR description, changelog, postmortem | Spawn `doc-writer`, then backstop with `fact-checker` |
| CI failure diagnosis + fix | Spawn `ci-fixer` with `isolation: "worktree"` |
| Single-line fix, quick read, git op | Inline — no spawn needed |

**No nested Skill() invocations in sub-agents**: Sub-agents that call `Skill()` (workflow/slash-command invocations) go silent — the skill never executes and the agent produces no output. Always give sub-agents concrete CLI commands or explicit instructions instead of delegating to workflow skills.

## PR Reviews

When reviewing PRs, follow `.github/CLAUDE_REVIEW.md` for detailed guidelines. Key points:
- Prioritize: Security > Bugs > Breaking Changes > Tests > Maintainability
- Use severity markers: 🔴 Blocking, 🟡 Suggestions, 🟢 Nice to Have
- Include file:line references and concrete fix suggestions
- Skip style nitpicks and generated files

## Ignore During Scanning

Skip these heavy/non-core paths: `.venv/`, `.cache/`, `.git/`, `src/maker/`, `_disasm/`, `out/`, `_out/`, `backups/`, `personal_assistants.egg-info/`
