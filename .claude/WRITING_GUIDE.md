# Writing Guide

Standards for all LLM-generated text in this project: commit messages, PR descriptions, documentation, code comments, and CLI output.

For resume and professional-profile copy (`src/resume/config/profiles/**`, rendered
DOCX, LinkedIn surfaces), see `.claude/RESUME_WRITING_GUIDE.md` — a different genre
with partly contradictory rules.

## Core Principles

1. **Professional neutral tone** — no drama, no hype, no judgment
2. **Lead with facts** — data over opinion, specifics over vague claims
3. **Be concise** — say it once, say it clearly, move on
4. **Match the audience** — LLM agents and engineers who value precision (see CLAUDE.md's "Primary consumers" note)
5. **Earn the reader's time** — writing that costs nothing to produce and everything to read erodes trust

## Don't Sound Like an LLM

LLM-generated prose is recognizable and it undermines credibility. When readers spot automated writing, they question the ideas behind it — not just the prose quality. ([Oxide RFD 0576](https://rfd.shared.oxide.computer/rfd/0576#_llms_as_writers))

**Avoid these LLM tells**:

| Pattern | Example | Fix |
|---------|---------|-----|
| Hollow enthusiasm | "This powerful new feature" | State what it does |
| Weasel words | "It's worth noting that" | Delete, just state the thing |
| Filler transitions | "Let's dive into", "Moving on to" | Cut them |
| Thesaurus abuse | "utilize" instead of "use" | Use plain words |
| Hedging stacks | "It might potentially be possible" | "X can Y" |
| False empathy | "Great question!" | Don't |
| Redundant preambles | "As mentioned earlier" | Just say it |
| Lists as a crutch | Bullet points for everything | Use a paragraph when prose reads better |
| Over-summarizing | "In summary, we've covered X, Y, Z" | The reader was there — don't recap |
| Bold/emoji overuse | "**key** insight is **very** important" | Bold only for: terms being defined, warnings, CLI command names — never for general emphasis |
| Passive voice inflation | "The configuration was updated" | "Updated the configuration" |
| Sycophantic openings | "Absolutely!", "Great approach!" | Never in written artifacts |

**The test**: would a senior engineer write this sentence in a design doc? If not, rewrite it.

## Tone

| Avoid | Prefer |
|-------|--------|
| "crisis", "drowning in", "flying blind" | "issue", "high volume", "limited visibility" |
| "massive refactor", "huge improvement" | "refactored X to Y", "reduced Z by N%" |
| "obviously", "simply", "just" | State the fact directly |
| Judgmental language about teams | Neutral observations with data |
| Exclamation marks in prose | Periods |

## Commit Messages

Format: `<type>(<scope>): <subject>`

**Types**: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `ci`

**Scope**: primary changed domain (`mail`, `calendar`, `schedule`, `resume`, `phone`, `whatsapp`, `wifi`, `workflow`, `core`, etc.). For cross-cutting changes use the most-affected domain or `core`. Never use a file name, ticket number, or adjective as scope.

**Rules**:
- Subject line under 72 characters
- Imperative mood: "add", "fix", "remove" (not "added", "fixes", "removing")
- Lowercase subject (no capital after colon)
- No period at end of subject
- Body (optional): explain **why**, not what — the diff shows what changed

**Good**:
```
feat(mail): add label sync dry-run mode
fix(schedule): eliminate off-by-one in weekly apply window
refactor(workflow): deduplicate stage-loading across compile and lint
```

**Bad**:
```
Updated stuff
fix: Fixed the bug in the thing
feat: Add amazing new incredible mail sync capability!
```

## PR Descriptions

- Open with 1-2 sentences: what changed and why
- Goals section: 3 bullets max
- Changes section: factual, specific, with file paths
- Avoid restating the diff — add context the diff doesn't show
- Use the template at `.github/PULL_REQUEST_TEMPLATE.md`; see `.llm/PR_TEMPLATE_GUIDE.md` for usage notes

## Documentation

- Start with what it is, then how to use it
- Code examples over prose explanations
- Keep examples runnable — test them before committing
- Reference actual file paths, CLI commands, and function names
- Don't document the obvious (e.g., "this function returns a value")
- Update docs when you change the code they describe

## Code Comments

- Comment **why**, not **what**
- No comments that restate the code: `# increment counter` above `counter += 1`
- Use comments for: non-obvious business logic, workarounds with context, suppression justifications (e.g., `# nosec B110/B112 - <intent>`)
- Prefer self-documenting code (good names, small functions) over comments

## Docstrings

- One line max, or omit entirely — the function name and type hints should carry the meaning
- No parameter lists (`Args:`, `Returns:`, `Raises:`) unless the signature is genuinely non-obvious after reading it
- Never restate the function name: `def fetch_labels` does not need `"""Fetches labels."""`
- Multi-paragraph docstrings are a sign the function does too much — split it instead

## CLI Output & Error Messages

- Errors: state what went wrong and what the user can do about it
- No stack traces in user-facing output unless `--debug` is set
- Progress messages: factual ("syncing 12 labels" not "working hard on your request")
- Keep `--help` text terse (1-line descriptions, no prose) — CLIs are primarily consumed by LLM agents

## Numbers and Data

- Include units: "reduced by 40%" not "reduced significantly"
- Use specific counts: "fixed 5 issues" not "fixed several issues"
- Round appropriately: "~1,500 tokens" not "1,487.3 tokens"
- Compare before/after when showing improvement

## Formatting

- Markdown for documentation and PR descriptions
- Tables for structured comparisons
- Code blocks with language tags for examples
- Bullet lists for 3+ related items; inline for fewer
- One blank line between sections; no triple-blank-lines
