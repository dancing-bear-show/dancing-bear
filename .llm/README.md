# LLM Agent Knowledge Cache

Token-efficient context for agents working on this repo.

## Reading Order

1. `CONTEXT.md` — system overview, architecture, and rules
2. `MIGRATION_STATE.md` — current status and remaining work
3. `PATTERNS.md` — copy-paste templates for common tasks
4. `DOMAIN_MAP.md` — CLI tree, flows index, binaries
5. `COMMANDS.md` — curated command reference

## Agentic Schemas

Prefer compact schemas over `--help`:
```
./bin/mail-assistant --agentic --agentic-format yaml --agentic-compact
./bin/llm agentic --stdout
./bin/llm domain-map --stdout
```

## Maintenance

- Staleness: `./bin/llm stale --with-status --limit 10`
- Dependencies: `./bin/llm deps --by combined --order desc --limit 10`
- Derive all: `./bin/llm derive-all --out-dir .llm --include-generated`

## Agent Handoff

- Humans: start with `README.md`
- Agents: start with `.llm/CONTEXT.md`
