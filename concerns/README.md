# Concern Library

Code review concern guides for dancing-bear. Each file covers a domain:

| File | Domain | Concerns |
|------|--------|----------|
| correctness.md | Python correctness, type safety, logic errors | ~22 |
| security.md | Security vulnerabilities, credential handling, input validation | ~4 |
| tests.md | Test quality, coverage, fixture patterns (unittest) | ~11 |
| patterns.md | Code patterns, CLI framework, lazy imports, plan/apply safety | ~17 |
| reuse.md | DRY, intra-domain duplication, shared extraction | ~4 |
| complexity.md | Cognitive complexity, nesting depth, logging hygiene | ~4 |
| workflow.md | FLOWS.yaml correctness, CLI references, plan/apply order | ~8 |
| workflow-fragments.md | .llm/ context files, agent definitions, generated file integrity | ~6 |
| docs.md | Documentation, docstrings, CLI help text, .llm/ context staleness | ~5 |

Used by: code review agents and the `reviewer` agent defined in CLAUDE.md.
Load guides selectively based on the file types in the diff.
