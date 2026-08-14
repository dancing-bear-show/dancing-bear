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

### skill-missing-readme
- **severity**: minor
- **check**: Verify that any new skill added under `.claude/skills/` that backs a multi-stage workflow includes a `README.md`. Simple single-file skills (`SKILL.md` only) do not require one.
- **triggers**: A PR adds a `.claude/skills/<name>/SKILL.md` alongside a corresponding workflow YAML, with no `README.md`; the SKILL.md describes a DAG with 4+ stages but no README explains the pipeline.
- **example**: PR adds `.claude/skills/some-audit/SKILL.md` referencing a workflow YAML (8 stages) with no README — operators have no pipeline overview. Add a README with: invocation example, per-guide concern table (if applicable), and output format.

### unsourced-quantitative-claim
- **severity**: minor
- **check**: Verify that quantitative percentage or count claims in documentation cite a stable source-of-truth artifact — a query, a dashboard, or a referenced report — so the figure can be updated when the underlying data changes.
- **triggers**: New or modified `.md` files that introduce a specific percentage (e.g. "4%", "~30%"), count ("detected in 1,200 sessions"), or rate claim without an inline citation, footnote, or link to the source query or dashboard; SKILL.md or README files that describe system behavior using concrete numbers with no audit trail.
- **example**: A SKILL.md adds "This concern is detected in approximately 4% of sessions" with no link to the query that produced that number — if session patterns shift, the figure becomes misleading with no mechanism for a reviewer to notice. Fix: add a parenthetical source (`(source: telemetry query, 2026-Q1)`) or link to a dashboard panel, or rephrase as a qualitative observation if no stable source exists.

### product-name-capitalization
- **severity**: minor
- **check**: Verify docstrings, comments, and prose use the correct capitalization for product and service names — miscased brand names appear in grep results and tool output, making them harder to search and inconsistent with official branding.
- **triggers**: `.py`, `.md`, or `.yaml` files with docstrings, inline comments, log strings, or help text containing miscased product names: "Github" (→ "GitHub"), "Pagerduty" (→ "PagerDuty"), "Openssl" (→ "OpenSSL"). Lowercase forms in CLI identifiers, import paths, and module names are correct and should not be flagged.
- **example**:
  ```python
  # bad — miscased brand names in prose/docstrings
  """Fetches calendar events from Gmail via the Google API."""  # Gmail is correct
  """Syncs labels from outlook."""  # Outlook is the product name

  # good
  """Fetches calendar events via the Google Calendar API."""
  """Syncs labels from Outlook."""
  ```
  Correct forms: GitHub, Gmail, Outlook, Google Calendar, Google Drive. Run `grep -rn 'Github\|Pagerduty' mail/ calendars/` before committing.

### changelog-format
- **severity**: minor
- **check**: Verify that `CHANGELOG.md` entries (if the project maintains one) follow a consistent convention: a top-level `Unreleased` section, entries grouped under `Added`, `Changed`, `Fixed`, `Removed`, `Tests`, or `Docs` sub-headings, and entry text uses backticks for file paths, CLIs, and module names. Flag entries that omit a group heading entirely or place new entries outside the `Unreleased` section.
- **triggers**: PRs that add features, fix bugs, or make user-facing changes (new CLIs, new config options, behavior changes) without a corresponding `CHANGELOG.md` entry in `Unreleased`. Skip for refactors, test-only, and docs-only PRs with no user-visible behavior change.
- **example**: A PR adds a new `./bin/calendar` subcommand but `CHANGELOG.md` shows no new entry under `Unreleased` — flag it. Fix: add an entry under `Added` in the `Unreleased` section.

### heading-hierarchy-skip
- **severity**: minor
- **check**: Verify that Markdown documents do not skip heading levels — every `####` (h4) must be nested under an `###` (h3), and every `###` under an `##` (h2). Skipped levels break accessibility and table-of-contents rendering. Flag any heading where the depth jumps by more than one relative to its nearest ancestor heading.
- **triggers**: `.md` files in `concerns/`, `.llm/`, or `.claude/` where an `####` or lower heading appears directly under an `##` or `#` with no intervening level; PRs that add or restructure Markdown documents with multi-level heading jumps. Skip inside fenced code blocks.
- **example**: A document has `## Overview` followed directly by `#### Details` (skipping h3) — TOC entries are misindented. Fix: change `#### Details` → `### Details`.

### template-variable-dropped
- **severity**: minor
- **check**: Verify that template or config files preserve all declared `{{VARIABLE}}` or `{placeholder}` tokens. When restructuring or regenerating a template, confirm that every placeholder present before the change still exists after it. Missing placeholders silently produce documents where required fields are rendered as blank or omitted.
- **triggers**: A PR modifies a template file and the diff removes one or more `{{...}}` or `{...}` placeholder tokens; diff shows a template variable present in the `-` lines but absent from the `+` lines.
- **example**: A config template had `profile: {{PROFILE_NAME}}` in its header; after a restructure the line was dropped — any rendering pipeline that substitutes `{{PROFILE_NAME}}` now silently omits the profile row. Fix: restore the missing placeholder.

### diagram-names-nonexistent-symbol
- **severity**: minor
- **check**: Verify every class name, function name, and component label in an architecture Mermaid diagram matches a symbol that actually exists in the source. A diagram naming a renamed or removed class misleads readers tracing the code path.
- **triggers**: A README or docs file contains a Mermaid diagram; a PR renames or removes a class/function; diagram node labels that differ from any exported name in the referenced source file.
- **example**: `src/worker/README.md` diagram references `DaemonCommand`, but the implementation class is `DaemonRunner` (`worker/cli.py:23`) — a reader following the diagram to the source never finds the class. Fix: rename the node to `DaemonRunner`.

### diagram-data-flow-mismatch
- **severity**: minor
- **check**: Verify architecture diagrams wire each command to the data source it actually uses. A blanket `commands --> data` edge lets every command appear to touch every source, which misdirects contributors even when each individual node name is correct.
- **triggers**: README or `.llm/` context files with Mermaid architecture diagrams; a PR adds or changes an implementation's data source (e.g. OTLP vs JSONL); diagram arrows that contradict the path the implementation takes.
- **example**: `src/telemetry/README.md` labelled `telemetry cost`/`sessions` as `CostScanProcessor`/OTLP-driven, but both use `TranscriptProvider` over JSONL under `~/.claude/projects`; `CostScanProcessor` is reachable only via `telemetry otel cost`. A contributor tracing the cost path is sent into the wrong subtree. Fix: replace the blanket edge with per-command edges.

### cli-example-uses-deprecated-path
- **severity**: minor
- **check**: Verify documentation examples, `.llm/` context files, and skill guides do not direct users to a deprecated CLI subcommand. LLM agents follow documented examples literally, so a deprecated path produces a user-visible warning or an error.
- **triggers**: `.llm/PATTERNS.md`, `.llm/CONTEXT.md`, or `SKILL.md` files referencing a subcommand marked `Deprecated:` in the source; a PR that adds a replacement subcommand without updating the doc examples in the same change.
- **example**: `.llm/PATTERNS.md` documents `./bin/phone export`, but the CLI marks it `Deprecated: 'phone export' uses Finder backups...` and the current path is `export-device`. Agents following the pattern invoke the deprecated command. Fix: update the example to `export-device` in the PR that deprecates the old path.

### guide-internal-inconsistency
- **severity**: minor
- **check**: Verify skill guides, concern files, and writing guides are internally self-consistent. When two sections state the same constraint with different values, implementors apply whichever rule they read first.
- **triggers**: A `SKILL.md`, guide `.md`, or task YAML where two sections describe one constraint with conflicting values (paragraph counts, word ranges); an enum listed in one step but stale in a sibling step.
- **example**: `.claude/COVER_LETTER_WRITING_GUIDE.md` said "Four paragraphs" in Structure but "3–4 paragraphs" under Length. Separately, `maid-task.yaml` Step 4 added a `resume-copy` category while the Step 3 schema enum still listed only `correctness|security|tests|patterns|workflow` — agents treat the new category as invalid. Fix: reconcile every occurrence in the same PR.

### gitignore-path-doc-mismatch
- **severity**: major
- **check**: Verify that any doc, example config, or guide claiming a path "is gitignored" names a path git actually ignores. Confirm with `git check-ignore -v <path>` rather than reading `.gitignore` by eye — nested `.gitignore` files also apply, so a root-level rule is not the only coverage.
- **triggers**: A `.md`, `.yaml`, or concern file stating a path is gitignored or "will not be committed"; docs pointing at a directory for PII-bearing captures; a PR adding such a claim without verifying the ignore rules.
- **example**: Resume docs told readers to put real LinkedIn captures in `_data/profiles/<name>/linkedin.yaml` and called it gitignored. Reviewers reading only the root `.gitignore` (which lists just `_data/profiles_private/`) concluded PII was exposed. It was in fact covered by `src/resume/.gitignore:2` (`_data/`) — but a careful reader reaching the opposite conclusion is itself a docs defect. Fix: name the rule that does the ignoring and tell readers to confirm with `git check-ignore -v`. Note the inverse trap: a path ignored *silently* (e.g. `src/resume/config/profiles/*`) looks committed but is never tracked without `git add -f`.
