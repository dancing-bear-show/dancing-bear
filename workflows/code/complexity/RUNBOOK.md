# Complexity Reduction Runbook

Generated 2026-08-06 from 71 flagged files.
12 groups emitted, 70 files targeted, 1 deferred.

Run groups one at a time, reviewing and committing between each.
Each child ends in a human gate before anything is committed.

| # | Group | Files | Total Cx | Command |
|---|-------|-------|----------|---------|
| 1 | telemetry | 12 | 829 | ./bin/workflow run workflows/code/complexity/telemetry.yaml |
| 3 | mail | 9 | 591 | ./bin/workflow run workflows/code/complexity/mail.yaml |
| 4 | resume | 7 | 587 | ./bin/workflow run workflows/code/complexity/resume.yaml |
| 5 | phone | 7 | 471 | ./bin/workflow run workflows/code/complexity/phone.yaml |
| 6 | core | 7 | 463 | ./bin/workflow run workflows/code/complexity/core.yaml |
| 7 | calendars | 6 | 372 | ./bin/workflow run workflows/code/complexity/calendars.yaml |
| 8 | workflow | 4 | 258 | ./bin/workflow run workflows/code/complexity/workflow.yaml |
| 9 | schedule | 3 | 191 | ./bin/workflow run workflows/code/complexity/schedule.yaml |
| 10 | wifi | 2 | 163 | ./bin/workflow run workflows/code/complexity/wifi.yaml |
| 11 | worker | 2 | 156 | ./bin/workflow run workflows/code/complexity/worker.yaml |
| 12 | charts | 2 | 117 | ./bin/workflow run workflows/code/complexity/charts.yaml |

## Deferred files (not targeted by any group)

| File | Cx | Reason |
|------|-----|--------|
| bin/pr-assistant | 94 | GATE 1: path starts with bin/ — public CLI entry points are never restructured. |

## Notes

- Children are independent; a failed group does not block others.
- Each child runs the FULL test suite, so cross-group regressions surface.
- Re-run the generator after landing groups to rescore the tree.
