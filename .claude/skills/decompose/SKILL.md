---
name: decompose
description: Split an oversized Python file into smaller focused modules, updating all call sites directly (no re-export facades). Use when a file is too large to review or maintain comfortably.
allowed-tools: Bash, Read, Edit, Write, Glob, Grep, Agent
skills:
  - dancing-bear-rules
---

# Decompose

Split an oversized Python source or test file into focused submodules. The original module is deleted and every import site is updated to name its new module directly — no re-export facades. The companion workflow `workflows/code/decompose-sweep.yaml` automates this across an entire domain.

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
1. NO re-export facade: delete <domain>/<module>.py entirely and update every
   import site to point at the new modules directly. Do not leave behind a
   `from .submodule import *` shim.
2. Extract shared fixtures/base classes into <submodule_c>.py first.
3. Search all importers before removing any symbol — including non-Python
   references (YAML, markdown, mock.patch target strings):
       grep -rn "from <domain>.<module> import\|import <domain>.<module>" . --include="*.py"
       grep -rn "<domain>[./]<module>" src/ tests/ bin/ .llm/ workflows/ concerns/ docs/ README.md
4. Each new file must be independently runnable (no circular deps).
5. Verify with `make test` (pins PYTHONPATH to this checkout). NEVER run bare
   `python3 -m unittest` — an inherited PYTHONPATH silently resolves imports to
   the MAIN checkout and produces a false green. Fallback:
       PYTHONPATH="$PWD/src" python3 -m unittest discover -s tests -t .
6. Do not rename test classes (preserves git blame).
7. Do not touch bin/* entry points.
"""
)
```

### Critical rules

**No re-export facades** — this is a hard project rule. After the split, the
original module is **deleted**, not converted into a shim:

```python
# WRONG — <domain>/<module>.py left behind as a facade
from .submodule_a import *  # noqa: F401,F403
from .submodule_b import *  # noqa: F401,F403
```

```python
# RIGHT — update each import site to name the new module directly
from slides.parsers_dict import load_deck_from_dict
from slides.parsers_csv import load_deck_from_csv
```

Facades hide the new structure, keep the old module name alive as a second
import path, and accumulate. Update all call sites atomically instead — this
repo explicitly permits that for internal APIs (see CLAUDE.md: "Avoid:
Maintaining backwards-compatible wrappers for internal APIs (update all call
sites instead)"). `workflows/code/scripts/detect_facades.py` flags any that
slip through; run it after the split to confirm zero findings for the domain.

**Do not miss non-import references.** `mock.patch("<domain>.<module>.func")`
target strings in tests, module paths cited in `concerns/*.md` "when loaded"
triggers, and architecture notes in READMEs all break silently — the tests
still pass and the concerns guide simply stops firing. Grep beyond `*.py`.

The split must never touch `bin/*` entry points or rename public CLI-facing modules (see CLAUDE.md: "Avoid: Broad refactors that rename modules or move public entry points"). Public API surfaces like a package's `__init__.py` `__all__` should keep exporting the same symbol names — only the internal source of each symbol changes.

**Import prefix** — this repo uses bare absolute imports. Example patterns observed in the codebase:

```python
from mail.config_resolver import ConfigResolver
from core.fileutil import atomic_write_json
from core.context import AppContext
```

Use the same style in all rewritten import sites and generated code — no relative-only imports at the package level, no invented package prefixes.

## Step 4: Verify

```bash
# Confirm imports resolve to THIS checkout, not the main one
make check-env

# Full suite — never bare `python3 -m unittest` (false greens in a worktree)
make test

# Lint with the ruff build CI enforces (there is no bare `ruff` on PATH)
make lint

# The old module must be GONE, and the new ones importable
PYTHONPATH="$PWD/src" python3 -c "
import importlib
for m in ['<domain>.<submodule_a>', '<domain>.<submodule_b>']:
    importlib.import_module(m)
try:
    importlib.import_module('<domain>.<module>')
    raise SystemExit('ERROR: old module still importable — facade left behind')
except ModuleNotFoundError:
    print('old module removed: OK')
"

# No facade slipped through
PYTHONPATH="$PWD/src" python3 workflows/code/scripts/detect_facades.py <domain>/

# Check new file sizes hit targets
find src/<domain>/ -name "*.py" | xargs wc -l | sort -rn | head -10
```

Do NOT run `qlty check` from a worktree under `.claude/` — it is excluded there
and prints a false "✔ No issues" while scanning zero files.

## Step 5: Report

After the split, output:

```
## Decompose Results

| Original File | Lines | Split Into | Files | Max Lines | Call Sites Updated |
|---------------|-------|------------|-------|-----------|--------------------|
| slides/parsers.py | 773 | parsers_markdown.py, parsers_dict.py, parsers_csv.py, _parse_bullets.py, _parse_text.py | 5 | 288 | 6 |
```

Report the original module as **deleted**, not as a facade, and state the
verification actually run (`make test` count, `make lint`, facade detector).

## Parallel Execution

For multi-file decomposition, spawn one `code-writer` agent per file in a single message so they run concurrently. Each agent works in its own isolated worktree. After all agents complete, copy their output files back into the feature-branch worktree and verify with `git status` before committing (isolated worktrees do not auto-merge).

## Anti-Patterns to Avoid

- **Leaving a re-export facade**: delete the original module and update call sites; a `from .x import *` shim is a project-rule violation, not a convenience
- **Too granular**: 50-line files are worse than 500-line files — split into 2-4 submodules, not 10
- **Breaking imports**: always verify all importers still work after the split
- **Missing non-Python references**: `mock.patch()` target strings, `concerns/*.md` "when loaded" triggers, and README module lists break silently — tests stay green while the concerns guide stops firing
- **Duplicating code**: shared helpers go into one submodule, not copied into each
- **Duplicating test bodies**: when splitting a test file, each test must live in exactly one file — copying full method bodies into several files makes them run twice
- **False-green verification**: bare `python3 -m unittest` in a worktree resolves to the main checkout; `qlty check` under `.claude/` scans zero files. Neither absence is a pass
- **Losing coverage**: run the test suite before and after; coverage must not drop
- **Renaming test classes**: keep class names identical in the new files (preserves git blame)
- **Touching bin/\***: entry point wrappers are public API — never move or rename them
- **Renaming public CLI-facing modules**: `mail/cli/main.py` → `mail/cli/main_new.py` breaks backwards compatibility
