---
name: familiarize
description: Preload repo context for the dancing-bear personal-assistants codebase. Use when the user runs /familiarize, says "get familiar with this repo", or starts a new session and wants Claude oriented before making changes. Reads the .llm/ context files and runs agentic-compact CLI help for the primary bin/*-assistant entry points so Claude has accurate, token-efficient knowledge of the public CLI surface without opening heavy READMEs.
tools: Read, Bash, Glob
---

# Familiarize

Preload orientation for this repo using its own token-efficient agentic capsules. This is **read-only** — do not edit files or run anything with side effects.

## Why this exists

The repo is designed for LLM consumers: `.llm/*.md` files and `--agentic --agentic-compact` output from each CLI wrapper are the canonical, terse descriptions of public behavior. They are much cheaper than READMEs and always in sync with the implementation. Use them.

## Workflow

Run everything in a single batched tool turn where possible — most calls are independent.

### Phase 1 — LLM context files

Read these in order (small, high signal):

1. `.llm/CONTEXT.md` — system overview and rules
2. `.llm/MIGRATION_STATE.md` — current status and in-flight work
3. `.llm/PATTERNS.md` — copy-paste templates for common tasks
4. `.llm/FAMILIARIZE_CORE.md` — the repo's own familiarization contract

Skip `.llm/DOMAIN_MAP.md` unless it exists (generate on demand with `./bin/llm domain-map --stdout` only if the user asks for a deeper map).

### Phase 2 — Aggregated agentic capsule

Run the unified agentic capsule. This one command gives you schemas for every app in a compact form:

```bash
./bin/llm agentic --stdout
```

Also pull the familiarization capsule itself (tiny, defines the read-only contract):

```bash
./bin/llm familiar --stdout --compact
```

### Phase 3 — Per-app agentic help (compact)

For each primary `bin/*-assistant` wrapper, fetch the compact agentic schema. These are the public CLI surfaces Claude will most often be asked to touch. Run them in parallel:

```bash
./bin/mail-assistant     --agentic --agentic-format yaml --agentic-compact
./bin/calendar-assistant --agentic --agentic-format yaml --agentic-compact
./bin/schedule-assistant --agentic --agentic-format yaml --agentic-compact
./bin/phone-assistant    --agentic --agentic-format yaml --agentic-compact
```

If the user's stated task clearly targets a single domain (e.g. "fix the WhatsApp importer"), also pull the matching wrapper:

- `./bin/whatsapp --agentic --agentic-format yaml --agentic-compact`
- `./bin/wifi-assistant --agentic --agentic-format yaml --agentic-compact`
- `./bin/apple-music-assistant --agentic --agentic-format yaml --agentic-compact`

Skip wrappers that fall outside the task — don't burn tokens loading every app.

### Phase 4 — Report

After preloading, give the user a terse summary (≤10 lines):

- Which context files were loaded
- Which CLI surfaces were loaded
- Any obvious migration / in-flight work surfaced by `MIGRATION_STATE.md`
- One sentence confirming readiness and inviting the next instruction

Do **not** dump the agentic output back at the user — the point is to have it in your own context, not theirs.

## Rules

- **Read-only.** Never pass `--write`, never run commands that modify files, never touch credentials or tokens.
- **Prefer compact agentic output over `--help`.** The repo explicitly optimizes `--agentic-compact` for LLM consumption (see `CLAUDE.md` → "LLM Consumer Rules").
- **Do not open heavy files** (`README.md`, `AGENTS.md`, provider READMEs, `config/*.yaml`, anything under `out/`) unless the user's task requires it. `.llm/FAMILIARIZE_CORE.md` calls these out as "extended, explicit only."
- **Skip noisy paths** entirely: `.venv/`, `.cache/`, `.git/`, `maker/`, `_disasm/`, `out/`, `_out/`, `backups/`, `personal_assistants.egg-info/`.
- If `./bin/llm agentic --stdout` fails (e.g. dependency missing), fall back to reading `.llm/AGENTIC_SCHEMAS.json` directly and note the failure in your report.
