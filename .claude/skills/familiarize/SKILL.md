---
name: familiarize
description: Preload repo context for the dancing-bear personal-assistants codebase. Use when the user runs /familiarize, says "get familiar with this repo", or starts a new session and wants Claude oriented before making changes.
allowed-tools: Bash, Read, Glob
skills:
  - dancing-bear-rules
---

# Project Familiarization

Load context about dancing-bear at session start.

## When to Use

- **Session start** — run before responding to first request
- **Context refresh** — when you need to re-orient
- **Feature discovery** — exploring what tools are available

## Run Familiarize

```bash
./bin/llm familiar --stdout
```

This returns a YAML capsule covering:
- Skip paths and heavy files to avoid
- Key CLIs and agentic schema pointers
- Familiarization contract (read-only rules)

## Deep Dive (On-Demand Only)

Load these only when the task requires deeper understanding:

| File | When to Load |
|------|-------------|
| `.llm/CONTEXT.md` | Architecture questions, system overview |
| `.llm/MIGRATION_STATE.md` | In-flight work, current status |
| `.llm/PATTERNS.md` | Implementing features, copy-paste templates |
| `.llm/FAMILIARIZE_CORE.md` | Familiarization contract details |

Generate on demand (never preload):

```bash
./bin/llm domain-map --stdout   # directory structure deep dive
```

## Tool Discovery

For CLI capabilities, use agentic schemas (never `--help`):

```bash
./bin/<assistant> --agentic --agentic-format yaml --agentic-compact
```

Primary surfaces: `mail-assistant`, `calendar-assistant`, `schedule-assistant`, `phone-assistant`.
Load only the wrapper(s) relevant to the current task.

## After Familiarize

You should know:
- What the project does (unified personal-workflow CLIs: mail, calendar, schedule, phone, WhatsApp)
- How to run CLIs (`./bin/<assistant> <subcommand> <flags>`)
- Where to find patterns (`.llm/PATTERNS.md`)
- Paths to skip (`.venv/`, `.git/`, `.cache/`, `maker/`, `_disasm/`, `out/`, `_out/`, `backups/`)
- Available skills (`/familiarize`, `/dancing-bear-rules`, etc.)
