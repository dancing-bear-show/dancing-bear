---
name: validate-workflow
description: Validate workflow YAML files and skill docs for structural correctness and real CLI command references. Runs workflow lint with command probing, checks that skill examples use correct --params syntax, and verifies referenced stage names match the compiled DAG. Use before committing workflow changes or when instructions feel stale.
allowed-tools: Bash, Read, Glob, Grep
skills:
  - dancing-bear-rules
---

# Validate Workflow

Validates workflow YAML files and the skill SKILL.md docs that reference them.
Catches stale CLI commands, wrong `--params` syntax, and stage name drift before
they reach CI or confuse agents at runtime.

## When to Use

- Before committing new or modified workflow YAML files
- After renaming or adding stages (stage references in skills go stale)
- After adding `--params` to skill docs (easy to mis-spell trigger param names)
- User says "validate workflow", "check workflow commands", "lint workflows"
- As part of a PR review when `workflows/` or `.claude/skills/` changed

## Two Layers of Validation

### Layer 1 — Workflow YAML structural + command lint

```bash
# Lint one file (structure only, fast)
./bin/workflow lint workflows/code/code-review.yaml

# Lint with CLI command probing (validates ./bin/<cli> <sub> references in stage descriptions)
./bin/workflow lint workflows/code/code-review.yaml --check-commands

# Strict mode — warnings become errors
./bin/workflow lint workflows/code/code-review.yaml --check-commands --strict

# YAML output for programmatic use (this is the default format)
./bin/workflow lint workflows/code/code-review.yaml --check-commands --format yaml
```

Shared fragments are not runnable standalone — they carry a top-level `fragment: true`
key and must be validated with the dedicated subcommand:

```bash
./bin/workflow validate-fragment workflows/shared/expand-coverage.yaml
```

### Layer 2 — Skill doc correctness checks (manual)

Skill docs reference workflow files in two ways the linter cannot check:
1. `./bin/workflow run <path> --params key=value` — param names must match `trigger.params` in the YAML
2. Stage name tables — must match stage names in the compiled DAG (including fragment prefixes)

Run these checks manually:

```bash
# Extract trigger.params from a workflow
python3 -c "
import yaml
d = yaml.safe_load(open('workflows/code/code-review.yaml'))
print('\n'.join((d.get('trigger') or {}).get('params', {})))
"

# List all stage names after fragment expansion (compiled DAG).
# Stage names live under groups[].stages as comma-joined strings — a bare
# `grep name:` would match the workflow name and warning keys instead.
./bin/workflow compile workflows/code/code-review.yaml --format yaml 2>/dev/null | python3 -c "
import sys, yaml
d = yaml.safe_load(sys.stdin)
for g in d.get('groups', []):
    for s in str(g.get('stages', '')).split(','):
        if s.strip(): print(s.strip())
"

# Extract --params keys from a skill doc (BSD grep on macOS has no -P; use -oE)
grep -oE '\-\-params [a-z_]+' .claude/skills/code-review/SKILL.md | awk '{print $2}' | sort -u
```

## Skill Steps

### Step 1 — Lint all modified workflow YAMLs

```bash
# Find all workflows modified vs main
git diff --name-only main...HEAD -- 'workflows/**/*.yaml'

# Lint each (with command probing)
./bin/workflow lint <path> --check-commands --format yaml
```

Triage output:
- `errors`: structural — workflow is invalid and will fail at runtime. Fix before merge.
- `warnings`: non-fatal — undeclared `{var}` refs or command probe timeouts.
  - `references undeclared variable '{workspace}'` → built-in runtime var, ignore it.
  - `references undeclared variable '{source_root}'` → warn if it is not a trigger param or fragment param.
  - `command not found: ./bin/<cli> <sub>` → real problem, fix the stage description.
  - `command validation skipped (timeout)` → confirm the binary exists manually.

### Step 2 — Check `--params` keys in skill docs against workflow trigger.params

For each skill that calls `./bin/workflow run`:

1. Extract trigger.params from the target workflow YAML.
2. Extract `--params key=value` keys from the skill's SKILL.md.
3. Flag any `--params` key in the skill that is NOT in `trigger.params`.

```bash
diff \
  <(grep -oE '\-\-params [a-z_]+' .claude/skills/code-review/SKILL.md | awk '{print $2}' | sort -u) \
  <(python3 -c "
import yaml
d = yaml.safe_load(open('workflows/code/code-review.yaml'))
print('\n'.join((d.get('trigger') or {}).get('params', {})))
" | sort -u)
```

### Step 3 — Check stage name references in skill docs

For each skill that lists stage names in a table or prose:

1. Compile the target workflow to get the full stage list (includes fragment-prefixed names).
2. Compare stage names in the skill text against the compiled list.

```bash
# Get compiled stage list
./bin/workflow compile workflows/code/code-review.yaml --format yaml 2>/dev/null | python3 -c "
import sys, yaml
d = yaml.safe_load(sys.stdin)
for g in d.get('groups', []):
    for s in str(g.get('stages', '')).split(','):
        if s.strip(): print(s.strip())
"

# Search the skill for stage names that no longer exist
grep -n "<old-stage-name>" .claude/skills/*/SKILL.md
```

## Output Interpretation

| Finding | Severity | Action |
|---------|----------|--------|
| `errors: [...]` in lint output | Blocking | Fix before merge — workflow won't run |
| `command not found: ./bin/<cli> <sub>` | Blocking | Fix stage description |
| `--params` key not in trigger.params | Blocking | Correct the param name in the skill |
| Stage name in skill not in compiled DAG | Blocking | Update the skill's stage table |
| `references undeclared variable '{workspace}'` | Ignore | Built-in runtime variable |
| `command validation skipped (timeout)` | Review | Confirm binary exists: `ls bin/<cli>` |
| `references undeclared variable '{other}'` | Review | Verify it's a fragment param, not a typo |

## Sweep All Workflows

Branch on the `fragment: true` marker, not on the directory — `workflows/shared/`
holds mostly fragments but also at least one runnable entry point
(`critique.yaml`), so a directory-based split misclassifies it.

```bash
# Lint/validate every workflow, routing each file by its fragment marker
for f in $(find workflows -name '*.yaml'); do
  if grep -q '^fragment: true' "$f"; then
    ./bin/workflow validate-fragment "$f" >/dev/null 2>&1 || echo "FAIL (fragment): $f"
  else
    result=$(./bin/workflow lint "$f" --format yaml 2>/dev/null)
    valid=$(echo "$result" | grep "^valid:" | awk '{print $2}')
    if [ "$valid" != "true" ]; then
      echo "FAIL: $f"
      echo "$result" | grep -A 5 "errors:"
    fi
  fi
done

# Add --check-commands for the non-fragment files that changed on this branch
for f in $(git diff --name-only main...HEAD -- 'workflows/**/*.yaml'); do
  grep -q '^fragment: true' "$f" && continue
  ./bin/workflow lint "$f" --check-commands --format yaml
done
```

## Common Fixes

| Error | Fix |
|-------|-----|
| `command not found: ./bin/mail-assistant labels-sync` | Subcommands are positional: `./bin/mail-assistant labels sync` |
| `command not found: ./bin/telemetry costs` | Verify the real subcommand: `./bin/telemetry --help` |
| `--params pr-number` (hyphen) | Change to `--params pr_number` (underscore — matches trigger.params) |
| Stage table lists an unprefixed fragment stage | Add the include's `prefix` (e.g. `cov-identify-gaps`, not `identify-gaps`) |
| `fragment file not found: workflows/shared/foo.yaml` | Check path spelling; ensure the fragment is committed |
| Fragment fails `lint` with a missing-trigger error | Fragments are not standalone — use `./bin/workflow validate-fragment` |
