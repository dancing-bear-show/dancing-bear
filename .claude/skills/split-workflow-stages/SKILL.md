---
name: split-workflow-stages
description: Split oversized workflow stages into smaller single-responsibility stages. Audits a workflow YAML for stages with multiple responsibilities (long descriptions, multiple data sources, mixed gather+transform logic), plans splits with human approval, applies edits, and validates lint. Use when workflow stages are too complex to debug or re-run in isolation.
allowed-tools: Bash, Read, Edit, Write, Glob, Grep, Agent
skills:
  - dancing-bear-rules
---

# Split Workflow Stages

Split oversized workflow stages into smaller, single-responsibility stages while preserving all `depends_on`, `reads_from`, and `writes_to` linkages.

## When to Use

- A stage description exceeds **80 lines**
- A stage both gathers raw data AND resolves/transforms it in the same block
- A stage reads from 3+ distinct external sources AND produces 2+ distinct output files
- A stage mixes "collect X" logic with "cross-reference Y against Z" logic
- Downstream fact-checkers or validators cannot verify outputs because the reasoning is opaque
- A stage is hard to re-run in isolation when debugging a workflow failure

## Responsibility Heuristics

| Heuristic | Threshold | Indicator |
|-----------|-----------|-----------|
| Description length | > 80 lines | Stage took on too much |
| Distinct data sources with distinct outputs | 3+ sources AND 2+ output files | Classic gather+transform conflation |
| Gather + resolve in same description | Any | "Read the config AND resolve its interpolations" in one stage |
| Gather + cross-reference in same description | Any | "Collect findings AND cross-reference against the concern library" in one stage |
| Gather + validate in same description | Any | "Fetch the file list AND verify each file parses" in one stage |
| Validate + write corrections in same description | Any | "Check claims AND apply fixes" in one stage |
| Inline reference data > 10 rows | Any | Hardcoded substitution maps or ownership tables in description text |

A stage with **2 or more** matching heuristics is a strong split candidate.

## Step 1 — Audit

Measure description length per stage:

```bash
python3 -c "
import sys, yaml
path = sys.argv[1]
d = yaml.safe_load(open(path))
for s in d.get('stages', []):
    lines = len((s.get('description') or '').strip().splitlines())
    reads = len(s.get('reads_from') or [])
    writes = len(s.get('writes_to') or [])
    flag = 'CANDIDATE' if lines > 80 or (reads >= 3 and writes >= 2) else 'ok'
    print(f'{flag:10} {s[\"name\"]:45} desc_lines={lines:4} reads={reads} writes={writes}')
" workflows/<domain>/<workflow>.yaml
```

Then read each flagged stage's description and count its distinct responsibilities by
hand — the line count is a proxy, the responsibility count is the real signal.

Record the audit as a findings file in the scratchpad, one entry per candidate:

```json
{
  "workflow_file": "workflows/code/code-review.yaml",
  "total_stages": 14,
  "candidate_stages": [
    {
      "name": "sweep-concerns",
      "description_lines": 112,
      "responsibilities": [
        "read the concern library",
        "filter concerns against the PR diff",
        "cross-reference filtered concerns against prior review threads"
      ],
      "responsibility_count": 3,
      "recommended_split": [
        "sweep-concerns-load: read the concern library",
        "sweep-concerns-filter: filter against the diff",
        "sweep-concerns-crossref: cross-reference prior threads"
      ],
      "reason": "Description 112 lines (threshold 80); 3 distinct responsibilities"
    }
  ],
  "stages_ok": ["fetch-diff", "post-comments"]
}
```

If `candidate_stages` is empty, the workflow is already well-decomposed — stop and say so.

## Step 2 — Plan the splits (human gate)

Before editing anything, present the plan and get explicit approval. For each candidate show:

- The original stage and its identified responsibilities
- The proposed new stage names and what each one does
- Which downstream stages will have their `depends_on` / `reads_from` updated
- An explicit request to approve all, drop specific splits, or request changes

Only proceed to Step 3 after the user approves.

## Split Naming Convention

New stage names follow `{original-name}-{suffix}`:

| Original | Split A | Split B | Split C (if needed) |
|----------|---------|---------|---------------------|
| `sweep-concerns` | `sweep-concerns-load` | `sweep-concerns-filter` | `sweep-concerns-crossref` |
| `analyze-coverage` | `analyze-coverage-measure` | `analyze-coverage-gaps` | — |

The **last** stage in the split chain replaces the original in all downstream
`depends_on` and `reads_from` fields.

## Step 3 — Apply

Apply one split at a time. For each:

1. Replace the original stage block with the new chain, in DAG order.
2. Chain the new stages: each reads from and depends on its predecessor.
3. Redistribute `writes_to` — each new stage writes only the artifacts it actually produces.
4. Repoint every downstream `depends_on` / `reads_from` reference from the original
   name to the **last** stage in the chain.
5. Preserve `human_gate`, `when`, and `validation` on whichever new stage they belong to
   (a gate usually belongs on the last stage; a `when` usually applies to all).

For multi-stage edits across several candidates, spawn a `code-writer` agent with
`isolation: "worktree"` and copy its output back — per CLAUDE.md, isolated agent
edits never merge automatically.

## Step 4 — Validate

```bash
# Structure + CLI command references
./bin/workflow lint workflows/<domain>/<workflow>.yaml --check-commands

# Confirm the DAG still compiles and ordering is what you expect
./bin/workflow compile workflows/<domain>/<workflow>.yaml --format yaml
```

Check specifically that:
- No stage forward-references a stage declared later in the file
- Every `reads_from` entry names a stage that actually `writes_to` something
- No downstream stage still references the pre-split name
- The parallel groups in the compiled plan match your intent (splits should chain
  sequentially, not fan out accidentally)

Fix any errors and re-lint until clean.

## Step 5 — Report

Summarize what changed: stages split, new names, downstream references repointed,
and the final lint result. Note any candidate the user chose to skip.

## Workspace Artifacts

Write intermediate files to the session scratchpad rather than the repo:

| File | Purpose |
|------|---------|
| `audit-findings.json` | Full audit results with the candidate list |
| `split-plan.json` | The approved split plan |
| `lint-results.json` | Lint output after edits |

## Adding Heuristics

To add a new heuristic, extend both the **Responsibility Heuristics** table above and
the detection logic in the Step 1 audit snippet, so the documented signal and the
measured signal stay in sync.
