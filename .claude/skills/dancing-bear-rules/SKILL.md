---
name: dancing-bear-rules
description: Shared project rules for all dancing-bear agents. Covers CLI conventions, credential protection, output helpers, coding standards, and the plan→dry-run→apply pattern.
---

# dancing-bear Project Rules

## 1. Bin Wrappers First

Always use `./bin/<tool>` wrappers, never `python -m` directly:
```
./bin/mail <subcommand> [flags]
./bin/calendar <subcommand> [flags]
./bin/schedule <subcommand> [flags]
./bin/phone <subcommand> [flags]
./bin/assistant resume <subcommand> [flags]
./bin/whatsapp <subcommand> [flags]
./bin/workflow <subcommand> [flags]
./bin/worker <subcommand> [flags]
```

## 2. Sub-Agents Must Not Auto-Familiarize

When spawned via Agent tool, you receive all needed context in your prompt. Do not run `/familiarize` — it wastes tokens and triggers permission prompts.

## 3. Plan → Dry-Run → Apply

Never mutate state without first staging and previewing:
```bash
./bin/<tool> <action> plan --out out/<plan>.yaml
./bin/<tool> <action> apply --plan out/<plan>.yaml --dry-run
./bin/<tool> <action> apply --plan out/<plan>.yaml
```

## 4. Credential Protection

- Never overwrite `~/.config/credentials.ini`
- Never log or print tokens, API keys, or secrets
- Use profiles: `[mail.gmail_personal]`, `[mail.outlook_personal]`, etc.
- Avoid `--credentials`/`--token` flags; prefer profile-based auth

## 5. Config Source of Truth

- Canonical filters: `~/.config/dancing-bear/filters_unified.yaml` (outside checkout; `config/filters_unified.example.yaml` is the tracked template)
- Derived outputs: `out/filters.gmail.from_unified.yaml`, `out/filters.outlook.from_unified.yaml`
- Always derive from unified config, never edit derived files directly

## 6. Coding Standards

- `@dataclass` for structured data, never plain dicts
- Type hints on all function signatures; PEP 585/604 syntax (`list[str]`, `str | None`)
- Lazy imports for optional deps (Google APIs, PyYAML, MSAL)
- No bare `except Exception: pass/continue` — add `# nosec B110/B112` with intent comment

## 7. Testing

- Framework: `unittest` (not pytest); run with `make test` — never bare `python3 -m unittest` in a worktree (inherited `PYTHONPATH` resolves imports to the main checkout and yields false greens). Fallback: `PYTHONPATH="$PWD/src" python3 -m unittest discover -s tests -t .`
- Coverage: `make cov` (or `make cov-html`)
- Patch where the name is **used**, not where it's **defined**
- Use factories/fakes from `tests/fakes/`; never construct API response dicts manually

## 8. Linting

```bash
~/.qlty/bin/qlty check path/to/file.py        # check
~/.qlty/bin/qlty check --fix path/to/file.py  # auto-fix
```

## 9. Git

- Base branch: `main`
- Never commit unless explicitly asked
- Never `git add -A` or `git add .` — stage specific files
- Never push directly to `main`

## 10. LLM CLI Discovery

For CLI schemas (prefer over `--help`):
```bash
./bin/<tool> --agentic --agentic-format yaml --agentic-compact
./bin/llm agentic --stdout --compact
```

Always pass `--compact`. On `./bin/llm agentic` the uncompacted form is 38KB — it
inlines CONTEXT.md, MIGRATION_STATE.md, PATTERNS.md and AGENTS.md — versus 2KB
compact for the same CLI schema. All 18 apps support `--agentic`; run
`./bin/llm inventory --stdout` for the exact invocation of each.

Flag asymmetry to know before you type it: `--compact` exists **only** on the
top-level `./bin/llm agentic`. The per-app route
`./bin/llm --app <app> agentic --stdout --compact` exits 2 with
`unrecognized arguments: --compact`. Drop `--compact` on per-app calls.

File arguments are **not** consistent across CLIs — do not carry the convention
from one to another (measured: 220 retry episodes, ~228k tokens, mostly this):
- `./bin/workflow lint <file>` / `compile <file>` / `run <file>` — **positional**
- `./bin/diagrams validate --input <file>` / `from-yaml --input <file>` — **`--input`**

When unsure, check the schema (`--agentic --agentic-compact`) or `--help` once
before invoking, rather than guessing and retrying.

## 11. Context Discipline

Your context is re-sent on every turn. The median agent runs ~40 turns, so a token
read at turn 3 is billed ~37 more times. Measured across 511 agent runs: 32% of all
Read bytes were files re-read by the same agent, and 52% came from reads over 20k
characters.

- **Never re-Read a file you have already read this session.** It is already in your
  context — scroll up instead of re-reading.
- **Locate before you load.** `grep -n` for the symbol, then `Read` with
  `offset`/`limit` around the hit. Only 39% of reads currently scope this way.
- **Never read a generated artifact whole** — `out/**`, workflow outputs,
  `concerns/*.md`, review dumps. Grep them for the section you need. One agent pulled
  1.9M characters from a single review-output file.
- If a file is genuinely too large to work in slices, say so and summarize rather than
  pulling it in repeatedly.

## 12. Worktree Paths and Shell Shape

Isolated agents run in their own worktree, and the sandbox rejects commands it cannot
prove stay inside it. Measured: 1,129 rejected commands and 648 no-such-file errors,
nearly all avoidable.

- **Stay put.** Never `cd` to the shared checkout, never `git -C <other-path>`, never
  reference another worktree by absolute path. Work from your own cwd.
- **Keep each Bash call simple.** 388 rejections were "too complex to verify" —
  heredocs writing files, or several chained commands. Use the `Write` tool to create
  files, and issue one command per call instead of `cmd1 && cmd2 && cmd3`.
- **Relative paths break after `cd`.** `tests/fixtures.py` and `concerns/*.md` exist at
  the worktree root; they 404 only because an agent had `cd`-ed into a subdirectory.
  Anchor to the root or don't `cd` at all.
- **Imports need `PYTHONPATH="$PWD/src"`** — the single largest error class
  (542 `ModuleNotFoundError`, ~2M tokens burned).

## 13. Writing Standards

Follow `.claude/WRITING_GUIDE.md` for commit messages, PR descriptions, docs, comments, and CLI output. Key rule: professional, neutral, fact-based language — no drama, no hype. Reusable doc templates (RFC, troubleshooting, PR response) live in `templates/`.
