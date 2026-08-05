# Concern Library

Code review concern guides for dancing-bear. Each file covers a domain:

| File | Domain | Concerns |
|------|--------|----------|
| correctness.md | Python correctness, type safety, logic errors | ~39 |
| security.md | Security vulnerabilities, credential handling, input validation | ~4 |
| tests.md | Test quality, coverage, fixture patterns (unittest) | ~20 |
| patterns.md | Code patterns, CLI framework, lazy imports, plan/apply safety | ~28 |
| reuse.md | DRY, intra-domain duplication, shared extraction | ~5 |
| complexity.md | Cognitive complexity, nesting depth, logging hygiene, file size, parameter count | ~6 |
| workflow.md | FLOWS.yaml correctness, CLI references, plan/apply order | ~25 |
| workflow-fragments.md | .llm/ context files, agent definitions, generated file integrity | ~17 |
| docs.md | Documentation, docstrings, CLI help text, .llm/ context staleness | ~11 |
| resume-copy.md | Resume/profile copy: bullet voice, quantification, banned phrases, LinkedIn limits | ~11 |
| workflow-stages.md | Workflow stage runtime concerns, model tier, tool access | ~14 |
| workflow-fanout.md | Fan-out patterns, writes-to contracts, worker queue correctness | ~12 |

Used by: code review agents and the `reviewer` agent defined in CLAUDE.md.
Load guides selectively based on the file types in the diff.
