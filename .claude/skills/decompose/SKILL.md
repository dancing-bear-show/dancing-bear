---
name: decompose
description: Split an oversized Python file into smaller focused modules with backward-compatible re-exports. Use when a file is too large to review or maintain comfortably.
allowed-tools: Bash, Read, Edit, Write, Glob, Grep, Agent
skills:
  - dancing-bear-rules
---

# Decompose

Split an oversized Python source or test file into focused submodules. All original imports remain valid via re-exports. The companion workflow `workflows/code/decompose-sweep.yaml` automates this across an entire domain.

## When to Use

- A file exceeds the size thresholds below
- User says "decompose", "split", "break up", or "too large"
- Code review flags a file as too large to review
- Maintenance pass on a domain you're touching anyway

## Size Thresholds

Calibrated against the actual file distribution in this repo:

| File type | Flag for review | Strong candidate | Split immediately |
|-----------|----------------|------------------|-------------------|
| Source module (`<domain>/*.py`) | 500+ lines | 700+ lines | 900+ lines |
| Test file (`tests/**/*.py`) | 700+ lines | 850+ lines | 1000+ lines |
| Helper/utility module | 400+ lines | 550+ lines | 700+ lines |

> Rationale: source files in this repo cluster around 400-600 lines with the top 5 ranging 915-1041; test files cluster around 700-900 with the top at 1084. Thresholds are set to catch genuine outliers, not routine files.

## Step 1: Identify Candidates

```bash
# Find large source files in a domain
find <domain>/ -name "*.py" -not -path "*/__pycache__/*" | xargs wc -l | sort -rn | head -20

# Find large test files
find tests/<domain>_tests/ -name "*.py" | xargs wc -l | sort -rn | head -10

# Repo-wide (skip venv, pycache)
find . -name "*.py" \
  -not -path "./.venv/*" \
  -not -path "*/__pycache__/*" \
  -not -path "*/.claude/*" \
  | xargs wc -l | sort -rn | head -20
```

## Step 2: Analyze Structure

Read the full file, then identify:

- **Split boundaries**: test classes, functional groupings (producers vs consumers), feature areas, command groups
- **Shared state**: fixtures, base classes, constants, helpers used by multiple groups
- **Dependency map**: which symbols are imported by other files in the package

```bash
# Find all importers of the module being split
grep -rn "from <domain>.<module> import\|import <domain>.<module>" . \
  --include="*.py" \
  -l
```

### Naming conventions

**Test files** — split by test class grouping:

| Before | After |
|--------|-------|
| `tests/mail_tests/gmail/test_gmail_api.py` (710 lines) | `test_gmail_api_labels.py`, `test_gmail_api_filters.py`, `test_gmail_api_messages.py` |

**Source modules** — split by responsibility:

| Before | After |
|--------|-------|
| `mail/filters/processors.py` (641 lines) | `processors_core.py`, `processors_gmail.py`, `processors_outlook.py` |
| `schedule/pipeline.py` (1024 lines) | `pipeline_fetch.py`, `pipeline_plan.py`, `pipeline_apply.py` |

**Helper/mock modules** — extract by concern:

| Before | After |
|--------|-------|
| `tests/fakes/api_helpers.py` | `fakes/gmail_helpers.py`, `fakes/outlook_helpers.py` |

## Step 3: Execute the Split

For each file to split, spawn a `code-writer` agent with isolation:

```python
Agent(
    subagent_type="code-writer",
    isolation="worktree",
    description="Split <domain>/<module>.py into focused submodules",
    prompt="""
Split <domain>/<module>.py into the following files:
  - <domain>/<submodule_a>.py  — <responsibility A>
  - <domain>/<submodule_b>.py  — <responsibility B>
  - <domain>/<submodule_c>.py  — <responsibility C> (shared fixtures/constants)

Target: each output file under <N> lines.

Rules:
1. Backward compatibility: update <domain>/<module>.py to re-export everything
   it previously defined, so all existing importers keep working without changes:
       from .submodule_a import *  # noqa: F401,F403
       from .submodule_b import *  # noqa: F401,F403
2. Extract shared fixtures/base classes into <submodule_c>.py first.
3. Search all importers before removing any symbol:
       grep -rn "from <domain>.<module> import\|import <domain>.<module>" . --include="*.py"
4. Each new file must be independently runnable (no circular deps).
5. Verify with: python3 -m unittest tests/<domain>_tests/ -v
6. Do not rename test classes (preserves git blame).
7. Do not touch bin/* entry points.
"""
)
```

### Critical rules

**Backward-compatible re-exports** — the original module must re-export all public symbols after the split:

```python
# <domain>/<module>.py (after split — becomes a thin re-export facade)
from .submodule_a import *  # noqa: F401,F403
from .submodule_b import *  # noqa: F401,F403
```

This is the one sanctioned pattern where a re-export wrapper is appropriate — it is a same-domain internal split, not a public API wrapper across packages. It must never touch `bin/*` entry points or rename public CLI-facing modules (see CLAUDE.md: "Avoid: Broad refactors that rename modules or move public entry points").

**Import prefix** — this repo uses bare absolute imports. Example patterns observed in the codebase:

```python
from mail.config_resolver import ConfigResolver
from core.fileutil import atomic_write_json
from core.context import AppContext
```

Use the same style in all re-export examples and generated code — no relative-only imports at the package level, no invented package prefixes.

## Step 4: Verify

```bash
# Run domain tests
python3 -m unittest tests/<domain>_tests/ -v

# Verify no broken imports
python3 -c "import <domain>.<module>"

# Check new file sizes hit targets
find <domain>/ -name "*.py" | xargs wc -l | sort -rn | head -10

# Full suite if touching shared code (core/, tests/fakes/, tests/fixtures.py)
python3 -m unittest discover tests/ -v
```

## Step 5: Report

After the split, output:

```
## Decompose Results

| Original File | Lines | Split Into | Files | Max Lines |
|---------------|-------|------------|-------|-----------|
| mail/cli/main.py | 1041 | cli/main_labels.py, cli/main_filters.py, cli/main.py (facade) | 3 | 420 |
```

## Parallel Execution

For multi-file decomposition, spawn one `code-writer` agent per file in a single message so they run concurrently. Each agent works in its own isolated worktree. After all agents complete, copy their output files back into the feature-branch worktree and verify with `git status` before committing (isolated worktrees do not auto-merge).

## Anti-Patterns to Avoid

- **Too granular**: 50-line files are worse than 500-line files — split into 2-4 submodules, not 10
- **Breaking imports**: always verify all importers still work after the split
- **Duplicating code**: shared helpers go into one submodule, not copied into each
- **Losing coverage**: run the test suite before and after; coverage must not drop
- **Renaming test classes**: keep class names identical in the new files (preserves git blame)
- **Touching bin/\***: entry point wrappers are public API — never move or rename them
- **Renaming public CLI-facing modules**: `mail/cli/main.py` → `mail/cli/main_new.py` breaks backwards compatibility
