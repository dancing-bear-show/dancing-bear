# LLM Agent PR Template Guide
How to use the GitHub PR template effectively

## Template Usage (concise)

Structure: follow the flow — 📋 PR Summary → 🎯 Goals → 📝 Changes → 📊 Impact → 🔍 Files → 🧪 Testing → 🚀 Deployment → 📖 Additional Context

Key Sections:
- Goals Achieved: 1–3 clear objectives
- Changes Made: organized by category with ✅/🆕/🔄/⚠️ indicators
- Impact Assessment: for Users/Developers/Operations
- Files Changed: quick reference list

### Intention & Theme (Top-Level)
- One-sentence theme tying the PR together
- Why now, scope boundaries (in/out), risk posture, and success signal

Example — Intention & Theme (LLM Maintenance PR)
```
- Theme: Keep LLM context fresh and high‑impact via inventory tooling, dynamic stale‑priority, and dependency analysis.
- Why Now: Maintain agent efficiency and reduce drift as unified CLIs stabilize.
- In Scope: New `llm` CLI (inventory/stale/deps/check), `.llm/INVENTORY.md`, file‑first auth docs, targeted README/AGENTS updates, unit tests.
- Out of Scope: Domain business logic changes, network client behavior, non‑LLM documentation outside touched areas.
- Risk Posture: Additive; dev tooling and docs only; no production code paths.
- Success Signal: Weekly CI shows inventory + stale list; priority list highlights top stale areas; reviewers can pick and mark reviewed; staleness decreases over time.
```

## Effective PR Writing

Goals Section:
```
1. Fix authentication bug: resolve token expiration handling
2. Add CLI helper: enable safer plan/apply flows for filters
3. Update documentation: align README/AGENTS with current CLI tree
```

Changes Section (examples):
```
#### Bug Fixes
- ✅ auth: fix token refresh logic
- ✅ outlook rules: sanitize errors

#### New Features
- 🆕 llm: add stale/deps/check inventory helpers
- 🆕 workflows: add from-unified plan/apply
```

Impact Section: focus on user benefits, developer experience, and operational changes

## Quality Checklist

Before submitting:
- [ ] Clear goals (what/why/how)
- [ ] Categorized changes with appropriate emojis
- [ ] Impact assessment for all stakeholders
- [ ] Test validation described
- [ ] File reference for easy review navigation
- [ ] Deployment notes if applicable

LLM Maintenance (when updating docs/dependencies):
- [ ] Refresh inventory: `./bin/llm inventory --preserve` (commit `.llm/INVENTORY.md`)
- [ ] Re-check priority and dependencies: `./bin/llm stale --with-priority --with-status --limit 10`

## Auth & Secrets (File-First)
- Prefer credentials.ini over environment variables in all tooling and docs.
- Never include tokens in PRs, logs, or command examples.
- If env export is required for a third-party tool, derive it from credentials.ini for the current shell only and avoid echoing in CI logs. See `.llm/CONTEXT.md` for safe examples.
