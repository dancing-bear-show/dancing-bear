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
./bin/mail-assistant --help
./bin/calendar-assistant --help
```

## Architecture

```
mail/                     # Gmail/Outlook providers, CLI wiring, helpers
calendars/                # Outlook calendar CLI + Gmail scans
schedule/                 # plan/apply calendar schedules
resume/                   # extract/summarize/render resumes
phone/                    # iOS layout tooling
whatsapp/                 # local-only ChatStorage search
desk/                     # desktop/workspace tooling
maker/                    # utility generators
bin/                      # entry wrappers and helper scripts
core/                     # shared helpers
tests/                    # lightweight unittest suite
.llm/                     # LLM context, flows, capsules
config/                   # YAML inputs (canonical source of truth)
out/                      # derived outputs and plans
```

## LLM Context Files

Read in order for best context:
1. `.llm/CONTEXT.md` - system overview and rules
2. `.llm/MIGRATION_STATE.md` - current status and remaining work
3. `.llm/PATTERNS.md` - copy-paste templates for common tasks
4. `.llm/DOMAIN_MAP.md` - where things live in the codebase

## Development Rules

**Do:**
- Keep CLI flags/subcommands stable; add new under `labels`, `filters`, `outlook`
- Prefer wrapper executables (`./bin/mail-assistant`) over `python -m`
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
- Check module: `~/.qlty/bin/qlty check mail/`
- Auto-fix: `~/.qlty/bin/qlty check --fix path/to/file.py`
- Linters: ruff (style), bandit (security), complexity metrics

**Testing:**
- Run tests: `make test` or `python3 -m unittest -v`
- With coverage: `coverage run -m unittest discover && coverage report`
- Add targeted tests only for new CLI surfaces/behaviors
- Never run tests that require network/secrets without explicit user approval

**CI/CD:**
- `.github/workflows/ci.yml` runs qlty checks + tests with coverage on push/PR
- Coverage uploaded to qlty for tracking
- Both jobs must pass for merge

## Key Commands

```bash
# Token-efficient agentic schemas (prefer over --help)
./bin/mail-assistant --agentic --agentic-format yaml --agentic-compact
./bin/llm agentic --stdout

# Domain map
./bin/llm domain-map --stdout

# Flows
./bin/llm flows --list
./bin/llm flows --id <flow_id> --format md
```

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

- Canonical filters: `config/filters_unified.yaml`
- Derived configs: `out/filters.gmail.from_unified.yaml`, `out/filters.outlook.from_unified.yaml`
- Always run plan first, then apply with dry-run, then apply for real

## Security

- Never commit `credentials.json` or tokens
- Restrict scopes to labels/settings/readonly/modify where required
- If sensitive data appears in logs, redact and rotate immediately

## Worktree Isolation

**Session-level**: Always launch with `claude -w` to auto-create a worktree. Each session gets its own branch and working directory under `.claude/worktrees/`, preventing sessions from clobbering each other.

**Subagent-level**: When spawning an Agent that writes code, use `isolation: "worktree"` so the subagent works in its own isolated copy of the repo. This prevents the subagent's edits from colliding with the parent session's working directory. Read-only agents (research, search, exploration) do not need isolation.

**If launched without `-w`**: Call `EnterWorktree` before your first file edit. Skip only for read-only requests (explain, search, explore).

**Git safety**:
- Never push directly to `main` — always use a PR from a worktree/feature branch
- Never force-push to `main`
- Never `git add -A` or `git add .` — stage specific files by name
- Never `git reset --hard`, `git clean -f`, `git checkout .` without explicit approval
- Before opening a PR, rename the ephemeral worktree branch to a conventional name: `feat/`, `fix/`, `chore/`, `docs/`

**Parallel sessions** (tmux): Use `claude --tmux` to open a new pane with its own worktree, or split manually (`Ctrl-b %` / `Ctrl-b "`) and run `claude` in each pane. Each session is fully isolated — separate directory, branch, and context.

**Agent Teams** (coordinated parallel work): For 5+ tasks that need status tracking or mid-flight steering, use `TeamCreate` + `TaskCreate` instead of plain `Agent()` calls. Partition tasks by file/module to avoid conflicts — subagents in a team share the same worktree.

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

**Spawn teammates** for multi-file changes, test writing, code review, research. Use `isolation: "worktree"` for agents that write code (`code-writer`, `tester`, `ci-fixer`). Read-only agents (`reviewer`, `researcher`, `Explore`, `Plan`, `fact-checker`, validators) do not need isolation.

Do inline for single-line fixes, quick reads, git operations.

**Backstop agents** (spawn after primary work completes):
- `fact-checker` — always spawn after composing reports, postmortems, cost analyses, PR descriptions, or any deliverable that aggregates data from multiple sources.

**Model selection**: Haiku for lookup + comparison. Sonnet for synthesis, judgment, multi-step reasoning. Inherit Opus only when generating code that will ship.

## PR Reviews

When reviewing PRs, follow `.github/CLAUDE_REVIEW.md` for detailed guidelines. Key points:
- Prioritize: Security > Bugs > Breaking Changes > Tests > Maintainability
- Use severity markers: 🔴 Blocking, 🟡 Suggestions, 🟢 Nice to Have
- Include file:line references and concrete fix suggestions
- Skip style nitpicks and generated files

## Ignore During Scanning

Skip these heavy/non-core paths: `.venv/`, `.cache/`, `.git/`, `maker/`, `_disasm/`, `out/`, `_out/`, `backups/`, `personal_assistants.egg-info/`
