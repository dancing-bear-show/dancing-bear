# Docs Review Guide

## When loaded

Load this guide when the diff adds or modifies any `.md` file, `README`, or
doc file. Load alongside `patterns.md` for changes that also touch source files.

## Concerns

### writing-guide-violation
- **severity**: minor
- **check**: Verify that new or modified documentation (READMEs, PR descriptions,
  code comments, CLI output strings) avoids the following anti-patterns. Flag
  every instance found, not just the first.
- **triggers**: Any of the following found in prose or commit subjects:
  - Hollow enthusiasm: "powerful", "amazing", "incredible", "seamlessly", "robust"
  - Weasel words: "It's worth noting", "Note that", "It should be mentioned"
  - Filler transitions: "Let's dive into", "Moving on to", "With that in mind"
  - Thesaurus abuse: "utilize" (use "use"), "leverage" (use "use"), "facilitate"
  - Hedging stacks: "might potentially", "could possibly", "may be able to"
  - False empathy or sycophancy: "Great question", "Absolutely!", "Certainly!"
  - Redundant preambles: "As mentioned earlier", "As we discussed"
  - Over-summarizing: a "Summary" section that restates what was just written
  - Bold/emoji overuse: bold on more than 1 in 10 phrases; emoji in prose not
    explicitly requested
  - Passive voice inflation: "was updated", "has been added" where active reads clearly
  - Exclamation marks in body prose
  - Commit subject in past tense ("added", "fixed") or missing type prefix
  - Commit subject over 72 characters or starting with a capital after the colon
- **scope exception**: Do NOT apply to files that necessarily quote anti-pattern
  phrases as examples. Exclude occurrences inside fenced code blocks and inline
  code spans.
- **example**: "This powerful feature enables teams to easily leverage advanced
  analytics!" — flags hollow enthusiasm, thesaurus abuse, and an exclamation mark.
  Rewrite: "Adds analytics subcommand returning per-domain cost breakdown."

### domain-missing-readme
- **severity**: minor
- **check**: Verify that any new domain directory that ships a CLI entry point
  also includes a `README.md` with a quick-start example and architecture notes.
- **triggers**: A PR adds a new CLI handler file with no accompanying `README.md`;
  or a PR substantially expands an existing domain (new subcommands) that has no
  `README.md`.
- **example**: PR adds `whatsapp/__main__.py` with 4 subcommands but no `README.md`
  — downstream agents have no quick-start reference and fall back to `--help`
  alone. Add a README with: overview, quick-start examples, and any auth notes.

### readme-flag-stale
- **severity**: minor
- **check**: Verify that flag names documented in README files match the flags
  actually declared in the corresponding source. Renamed or removed flags in docs
  mislead both human contributors and LLM agents.
- **triggers**: A PR renames or removes a CLI flag without updating the domain
  README; README contains `--flag-name` that no longer appears in the
  corresponding source file's argument declarations.
- **example**: README documents `./bin/mail-assistant filters sync --delete-all`
  but the flag was renamed to `--delete-missing` in source — every example in
  the README now produces an `unrecognized arguments` error. Update README
  examples in the same PR as the flag rename.

### orphan-doc-reference
- **severity**: minor
- **check**: Verify that CLI names, class names, and subcommand names referenced
  in README files and docs still exist in the source. Orphan references arise when
  features are removed or renamed without updating documentation.
- **triggers**: A PR removes or renames a public class, CLI subcommand, or `bin/`
  entry point; diff removes a source file or renames a function but no
  corresponding README or doc update appears in the same diff.
- **example**: `README.md` references `./bin/mail-assistant labels legacy-export`
  but that subcommand was removed in this PR — the README now documents a command
  that returns an error. Remove or replace the reference in the same commit.

### llm-context-stale
- **severity**: minor
- **check**: Verify that `.llm/` context files (CONTEXT.md, DOMAIN_MAP.md,
  PATTERNS.md) are updated when the PR adds new CLI subcommands, new bin/ entry
  points, or new domain modules that LLM agents need to discover.
- **triggers**: A PR adds a new `bin/` entry point with no update to `.llm/DOMAIN_MAP.md`
  or `.llm/AGENTIC.md`; new CLI flows added without updating `.llm/FLOWS.yaml`; new
  domain patterns added without updating `.llm/PATTERNS.md`.
- **example**: PR adds `./bin/desk-assistant` with 3 subcommands but `.llm/DOMAIN_MAP.md`
  still lists only mail, calendar, and schedule — agents calling `./bin/llm domain-map`
  will not discover the new entry point. Run `./bin/llm derive-all --out-dir .llm
  --include-generated` to regenerate derived context files.
