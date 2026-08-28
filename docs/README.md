# Documentation

Guided, newcomer-friendly documentation for dancing-bear. Start at the top.

| Doc | Read it when |
|---|---|
| [Getting Started](getting-started.md) | You just cloned the repo and want a first useful result. |
| [Why CLIs, Not MCP](why-clis-not-mcp.md) | You want the design thesis — why capabilities are CLIs rather than an MCP server. |
| [Features](features.md) | You're asking "what can this actually do for me?" |
| [Architecture](architecture.md) | You're about to change code and need to know how the pieces fit. |
| [Workflow Engine](workflow-engine.md) | You want to run or author one of the 52 YAML DAG workflows. |

## Reference docs

These are the canonical, detail-heavy sources. The guided docs above link into them
rather than restating them, so when the two disagree, trust these.

| Doc | Covers |
|---|---|
| [../README.md](../README.md) | Full command reference for every app. |
| [../GETTING_STARTED.md](../GETTING_STARTED.md) | Reference setup, credential layout, troubleshooting. |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | Development workflow, PR process. |
| [../SECURITY.md](../SECURITY.md) | Credential handling and disclosure policy. |
| [../.llm/DESIGN_CRITERIA.md](../.llm/DESIGN_CRITERIA.md) | The C1–C10 standard `src/` is graded against. |
| [../.llm/PATTERNS.md](../.llm/PATTERNS.md) | Copy-paste templates for common tasks. |

## Domain notes

| Doc | Covers |
|---|---|
| [phone_configurator.md](phone_configurator.md) | Supervising an iPhone with Apple Configurator 2 and applying a Home Screen Layout profile. |

For qlty triage, the shipped CLI is the source of truth — the design proposal
that preceded it was implemented and has been removed:

```bash
./bin/qlty-assistant rules   # per-rule remediation tiers and strategies
./bin/qlty-assistant scan    # merged check + smells, defaults to --all
```

## Discovering commands

Don't trust a command you read in a doc — the schemas are auto-derived from the real
parsers and can't drift:

```bash
./bin/llm inventory --stdout                                  # how to invoke all 18 apps
./bin/<app> --agentic --agentic-format yaml --agentic-compact # one app's real schema
./bin/workflow list                                           # the authoritative workflow catalog
```
