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

- Canonical filters: `config/filters_unified.yaml`
- Derived outputs: `out/filters.gmail.from_unified.yaml`, `out/filters.outlook.from_unified.yaml`
- Always derive from unified config, never edit derived files directly

## 6. Coding Standards

- `@dataclass` for structured data, never plain dicts
- Type hints on all function signatures; PEP 585/604 syntax (`list[str]`, `str | None`)
- Lazy imports for optional deps (Google APIs, PyYAML, MSAL)
- No bare `except Exception: pass/continue` — add `# nosec B110/B112` with intent comment

## 7. Testing

- Framework: `unittest` (not pytest); run with `make test` — never bare `python3 -m unittest` in a worktree (inherited `PYTHONPATH` resolves imports to the main checkout and yields false greens). Fallback: `PYTHONPATH="$PWD/src" python3 -m unittest discover -s tests`
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
./bin/llm agentic --stdout
```

## 11. Writing Standards

Follow `.claude/WRITING_GUIDE.md` for commit messages, PR descriptions, docs, comments, and CLI output. Key rule: professional, neutral, fact-based language — no drama, no hype. Reusable doc templates (RFC, troubleshooting, PR response) live in `templates/`.
