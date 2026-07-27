# Concern Library

Code review concern guides for dancing-bear. Each file covers a domain:

| File | Domain | Concerns |
|------|--------|----------|
| correctness.md | Python correctness, type safety, logic errors | ~30 |
| security.md | Security vulnerabilities, credential handling, input validation | ~4 |
| tests.md | Test quality, coverage, fixture patterns (unittest) | ~19 |
| patterns.md | Code patterns, CLI framework, lazy imports, plan/apply safety | ~27 |
| reuse.md | DRY, intra-domain duplication, shared extraction | ~4 |
| complexity.md | Cognitive complexity, nesting depth, logging hygiene | ~4 |
| workflow.md | FLOWS.yaml correctness, CLI references, plan/apply order | ~25 |
| workflow-fragments.md | .llm/ context files, agent definitions, generated file integrity | ~17 |
| docs.md | Documentation, docstrings, CLI help text, .llm/ context staleness | ~11 |
| workflow-stages.md | Workflow stage runtime concerns, model tier, tool access | ~14 |
| workflow-fanout.md | Fan-out patterns, writes-to contracts, worker queue correctness | ~12 |

Used by: code review agents and the `reviewer` agent defined in CLAUDE.md.
Load guides selectively based on the file types in the diff.
