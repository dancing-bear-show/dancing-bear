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
  workflow/               # YAML DAG workflow engine (parse/compile/run/lint/list/status)
  core/                   # shared helpers
  telemetry/              # Claude Code session telemetry (cost, tokens, TUI)
  worker/                 # background job queue and daemon
  metals/                 # precious metals purchase tracking
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
4. `.llm/DOMAIN_MAP.md` - where things live in the codebase

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
- The workflow engine (`src/workflow/compiler.py`) inserts `--` before flags for most skills; `llm` and `docs` CLIs are exempt (`_NO_SEPARATOR_CLIS`). `docs` is reserved for a planned Confluence CLI — no `bin/docs` ships today
- `--` separator is now **optional** for all CLIApp-based CLIs (mail, calendar, schedule, resume, phone, whatsapp, desk, wifi, maker, apple_music, metals, workflow); `src/core/cli_framework.py` strips bare `--` tokens automatically. The workflow engine's `_NO_SEPARATOR_CLIS` exemption for `llm`/`docs` remains unchanged.
- Auto-derived agentic schema: mail, calendar, schedule, resume, phone, whatsapp, desk, wifi, maker, apple_music, and metals support `--agentic --agentic-format json` (via `CLIApp.run_with_assistant`) to emit a machine-readable parser schema that never drifts from the real CLI; add `--agentic-compact` to strip low-value fields; add `--agentic-domain <prefix>` to filter to one subcommand group.
- charts, diagrams, worker, and workflow build their parser via `CLIApp.build_parser()` but skip `run_with_assistant()`, so none of the four support `--agentic`. charts and diagrams dispatch commands directly (never call `CLIApp.run()`) solely to preserve their own legacy no-subcommand exit codes/messages — `CLIApp.run()`'s `--output`-as-format parsing is guarded behind `add_common_args`, so it no longer crashes on diagrams' file-path-valued `--output`. worker and workflow call `CLIApp.run(argv, on_no_command=...)`, using that hook to preserve their own legacy no-subcommand exit codes/messages while still normalizing and parsing argv exactly once.

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
- For repo-wide triage prefer `./bin/qlty-assistant` over raw qlty: it merges
  `check` + `smells` (disjoint sets — running one hides the other), defaults to
  `--all`, dedupes clone groups, and ranks findings by remediation tier
- `./bin/qlty-assistant scan --expect-min N` fails loudly on an implausibly
  empty scan, which is what the exclusion trap below looks like
- `.qlty/qlty.toml` `exclude_patterns` ignores `**/.claude/**`, so agents spawned with `isolation: "worktree"` (created under `.claude/worktrees/`) get a silently empty scan — 0 issues means "excluded", not "clean"
- Run qlty from the main checkout or a worktree outside `.claude/`; treat a suspiciously empty result as a broken environment, not a passing one

**Linting (ruff directly):**
- Use `make lint` (or `make lint-fix`), never a bare `ruff check`
- There is **no standalone `ruff` on PATH**. CI lints through `qlty check`, which
  runs ruff from qlty's own pinned tool cache — so `ruff check <file>` fails as
  "command not found", and a `pip install ruff` would drift from the version CI
  enforces. `bin/ruff-resolve.sh` resolves the qlty-pinned build (override with
  `RUFF_BIN=`), and `make lint` wraps it over `src/`, `tests/`, and `bin/`
- This matters because the two obvious fallbacks both **fail silently**: a bare
  `ruff` may not exist, and `qlty check` inside `.claude/worktrees/` scans zero
  files while printing "✔ No issues". Neither absence is a passing lint
- If the tool cache is cold, run any `~/.qlty/bin/qlty check` once from outside
  `.claude/` to populate it, then `make lint`
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
This repo has ~30 workflows. Reinventing one wastes the work already invested in
it and produces a second, diverging implementation of the same process.

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
