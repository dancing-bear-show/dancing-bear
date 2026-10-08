# Fix-Regression Review Guide

## When loaded

Load this guide after a batch of review-thread fixes is applied, before the fix
commit is pushed. Applies when the task type is `review-fix`. The sweep runs
against the fixers' combined diff and the thread text that drove each fix.

For general collateral-damage concerns (incomplete guard coverage, unsubstituted
placeholders, TOCTOU races, null-id handling), see `collateral-damage.md` —
that guide is co-selected and covers those patterns. This guide covers the
regression shapes specific to automated review-fix runs.

## Concerns

### instance-fix-not-class-fix
- **severity**: critical
- **check**: The fix handles the reviewer's cited example but leaves sibling
  forms of the same construct unguarded. Verify by enumerating every syntactic
  form the guard or check must handle and probing each one independently.
- **triggers**: A conditional, parser, or guard is added or modified by a fix
  commit; the reviewer's comment cited a specific code fragment.
- **example**: PR #454 — a `cd` guard detected `then cd <dir>` but not `then
  echo hi; cd <dir>`, loop bodies, `case` arms, `&&`/`||` chains, or nested
  `if`. Sibling forms all remained unguarded. Fix: enumerate every syntactic
  form the construct can appear in and add a test or probe asserting each is
  handled (or explicitly excluded with a reason).
- **sweep**: procedure, applied to the diff when the trigger matches:
  1. Identify the construct the fix guards or transforms (e.g. "bare `cd` in a
     shell conditional").
  2. List every syntactic sibling: `then`, loop bodies (`do`/`done`), `case`
     arms, `&&`/`||` short-circuits, nested `if`, function bodies, subshells.
  3. For each sibling not present in the diff's tests, run a probe against the
     changed code with that form as input.
  4. Record a finding for every sibling form that is either not handled or has
     no test demonstrating it is handled.
- **cause**: INCOMPLETE_FIX — the fix targeted the reviewer's specific example
  rather than the class of inputs the guard must handle

### new-scanner-edge-cases
- **severity**: critical
- **check**: A fix that adds a hand-written lexer, quote scanner, or keyword
  counter introduces its own edge cases in both directions — false-safe (input
  that should trigger but does not) and false-unsafe (input that should not
  trigger but does). Verify with adversarial inputs in both directions.
- **triggers**: A fix commit adds a function or loop that tracks quote state,
  counts shell keywords, or parses structured text character by character or
  token by token.
- **example**: PR #437 — a quote scanner treated `'` inside a double-quoted
  string as opening a single-quoted span, so `"'$CMD'"` was classified
  statically safe (false-safe). PR #454 — a keyword counter counted argument
  words, so `echo fi` closed a shell block (false-unsafe). Fix: construct at
  least one false-safe adversarial input (input that should fire but doesn't)
  and one false-unsafe adversarial input (input that shouldn't fire but does),
  and add tests for both.
- **sweep**: procedure, applied to the diff when the trigger matches:
  1. Identify the scanner's state machine (quote modes, nesting counters,
     keyword sets).
  2. Construct a false-safe input: something that should trigger the scanner
     but doesn't because of an edge in the state machine (e.g. `'` inside
     double quotes, a keyword used as an argument).
  3. Construct a false-unsafe input: something that should NOT trigger the
     scanner but does (e.g. a keyword that appears as a string literal, a
     quote that is escaped).
  4. Run each input through the changed code and record the result.
  5. Report a finding for each direction that lacks a test or probe.
- **cause**: FIX_REGRESSION — the new scanner introduced an untested edge case;
  INCOMPLETE_FIX — the scanner was tested only with the reviewer's example and
  not with adversarial inputs

### partial-fix-stated-cause
- **severity**: major
- **check**: The fix addresses a symptom named in the reviewer's comment but
  not the stated cause. Read the thread's original complaint and verify the fix
  addresses it — not only a surface manifestation.
- **triggers**: A fix commit modifies code that a review thread cited; the
  thread text names both a symptom and a cause (e.g. "interpolation" vs.
  "word-splitting").
- **example**: PR #454 — `FILE="<file>"` still interpolated a filename into
  shell source after the fix. The reviewer's complaint was interpolation, and
  the fix addressed word-splitting (a symptom) without stopping the
  interpolation (the cause). Fix: re-read the thread's stated cause and
  verify the code path that produces the cause is blocked, not only the symptom.
- **sweep**: procedure, applied to the diff when the trigger matches:
  1. Identify the thread's stated cause (the mechanism that produces the
     problem) and the symptom (the observable consequence).
  2. Verify the fix blocks the cause, not only the symptom: does the code
     path that produces the cause still exist after the fix?
  3. If the thread named only a symptom, verify the fix removes the code that
     could re-introduce it through a different path.
- **cause**: INCOMPLETE_FIX — the fixer read the example but not the stated
  mechanism; INSTANCE_FIX — only the reviewer's cited line was changed

### check-then-use-toctou
- **severity**: major
- **check**: A validation (exists, islink, is-regular-file, parent-dir check)
  is separated from the open/read it guards by any intervening state change.
  Verify with a FIFO or symlink that changes between the check and the use.
  For general TOCTOU races involving concurrent actors, see `toctou-race` in
  `collateral-damage.md`. This concern focuses on file-type checks (islink,
  isfile, stat) that are then followed by an open or read, where an attacker
  can swap the target.
- **triggers**: A fix commit adds `os.path.islink`, `os.path.exists`,
  `os.path.isfile`, `os.stat`, or a parent-directory check, followed by
  an `open()`, `read()`, or subprocess invocation on the same path.
- **example**: PR #448 — `islink` check followed by `read()`; a symlink
  created between the two passes `O_NOFOLLOW` safety. PR #456 — symlink-parent
  check followed by `read(path)` directly; a FIFO passes `os.path.islink`
  check but blocks on `read()`. Fix: open the file first with `O_NOFOLLOW` (or
  the equivalent) and then stat the open file descriptor, not the path. Or use
  a single atomic operation (e.g. `open(..., flags=os.O_NOFOLLOW)`) that
  refuses to follow a symlink at open time.
- **sweep**: procedure, applied to the diff when the trigger matches:
  1. For each path-check call in the diff, find the subsequent open/read on the
     same variable or derived path.
  2. Measure the gap: are there any lines between the check and the use that
     could change the filesystem state?
  3. Probe: create a symlink at the checked path after the check but before the
     open, and confirm the fix catches it. If no test does this, record a
     finding.
- **cause**: FIX_REGRESSION — the check-then-use gap was introduced by the fix
  commit itself; INCOMPLETE_FIX — the fix removed one TOCTOU path and left
  another

### vacuous-or-non-discriminating-tests
- **severity**: critical
- **check**: A test added by a fix cannot fail, or was never shown to fail
  without the fix in place. Verify by running the new test against the
  pre-fix code in a throwaway worktree — never by reverting the fix in the
  shared tree. If the test still passes without the fix, it is
  non-discriminating.
- **triggers**: A test is added or modified by a fix commit.
- **example**: PR #455 — a test asserted that a made-up key `..._TYPO` is
  absent from a result dict; the key is absent by construction and the test
  passes whether the fix is in place or not. A non-discriminating test provides
  false confidence and masks a missing real assertion. Fix: run the new test
  against the pre-fix code (in a throwaway worktree, as below) and confirm it
  fails. Record that result explicitly in the thread reply.
- **sweep**: procedure, applied to the diff when the trigger matches:
  1. For each new test in the diff, identify what code path would cause it to
     fail.
  2. Verify that code path existed before the fix (i.e. the test targets the
     bug, not a pre-existing property).
  3. Run the test against the pre-fix code WITHOUT touching the shared tree.
     The sweep is read-only, and a revert left behind by a failed probe would
     be committed. During a review-fix run the fixes are still uncommitted, so
     HEAD is the pre-fix code: `git worktree add --detach <tmp> HEAD`, copy
     only the new or changed test file(s) into `<tmp>`, run the test there
     with `PYTHONPATH="<tmp>/src"`, then `git worktree remove --force <tmp>`.
     If it passes against the pre-fix code, record a finding.
  4. If the test cannot run in isolation (it depends on other changed files
     that cannot be copied without also copying the fix), do not fall back to
     reverting. Judge from the diff: name the assertion and the pre-fix code
     path that would make it fail; if there is none, record a finding.
- **cause**: FIX_REGRESSION — the test was written to assert a property that
  holds regardless of the fix; VACUOUS — the assertion targets a key or
  condition that cannot possibly be set by the code under test

### unbacked-verification-claims
- **severity**: critical
- **check**: The fixer's result JSON claims `test_result: "pass"` but the
  evidence is missing or contradicted. Verify by re-running the result's
  `test_command`: the output must contain a `Ran N tests` line and end in `OK`,
  not `FAILED`. A null or empty `test_command` with `test_result: "pass"` is
  itself a finding — there is no runnable evidence for the claim.
- **triggers**: A fix result JSON has `test_result: "pass"` or the reply text
  asserts the suite is green.
- **example**: PR #448 reported "1503 tests" but the log predated the final
  commit; PRs #452 and #455 reported OK while their logs ended in FAILED. A
  pushed fix whose test claim is unbacked leaves a regression undetected.
  Fix: always re-run the suite after the final edit and verify via the
  `test_command` in the result JSON.
- **sweep**: procedure, applied to each fix result when the trigger matches:
  1. Read the result's `test_command` and `test_result` fields.
  2. If `test_result` is "pass" but `test_command` is null or empty, record a
     finding: there is no runnable evidence for the pass claim.
  3. Otherwise, re-run `test_command` (read-only; the sweep must not edit
     source files). Check the output for a `Ran N tests` line. If absent,
     record a finding: the suite may not have run.
  4. Check the outcome line (`OK` or `FAILED (errors=N, failures=N)`). If it
     ends in FAILED, record a finding: the claim contradicts the run output.
  5. Check whether the changed files are in scope: if the test command is
     scoped to a subset of the tree that excludes a changed file, record a
     finding.
- **cause**: UNBACKED_CLAIM — the fixer ran tests early and did not re-run
  after the last edit; FAILED_IGNORED — the fixer saw FAILED and reported OK

### gate-suppressions-added
- **severity**: critical
- **check**: The fix introduces a `# type: ignore`, `# noqa`, `# nosec`, or
  `# NOSONAR` annotation, or a test `skip` or `expectedFailure` decorator, to
  make a gate pass. CLAUDE.md forbids `# type: ignore`; the others require a
  reason comment and must not be added to suppress a new violation the fix
  itself introduced.
- **triggers**: A fix commit adds any of `# type: ignore`, `# noqa`, `# nosec`,
  `# NOSONAR`, `@unittest.skip`, `@pytest.mark.skip`, or
  `@unittest.expectedFailure`.
- **example**: PR #456 added `# type: ignore[arg-type]` to pass mypy; CLAUDE.md
  forbids this unconditionally. A `# nosec` added to suppress a bandit finding
  the fix itself introduced hides a real security signal. Fix: resolve the
  underlying issue rather than suppressing it. If the suppression is a genuine
  false positive, add it with a reason comment and a reference to the relevant
  CLAUDE.md rule; `# type: ignore` is never acceptable.
- **sweep**: structural — for each suppression annotation on an ADDED diff
  line (a `+` line inside a hunk; not context, not deletions, not the `+++`
  file header):
  1. Is it `# type: ignore`? Record a critical finding unconditionally.
  2. Is it `# noqa`, `# nosec`, or `# NOSONAR`? Verify it has a reason comment
     and that the finding it suppresses predates the fix (is not a violation the
     fix introduced). Record a finding if either check fails.
  3. Is it a skip or expectedFailure decorator? Verify it was applied to a
     pre-existing test, not a new one added by the fix. Record a finding if it
     was applied to a new test.
- **cause**: GATE_BYPASS — the fix suppressed a gate to make CI pass without
  addressing the underlying issue

### rename-schema-drift
- **severity**: major
- **check**: A field, key, flag, or function renamed or added in one place is
  not updated in every reader: prose instructions, JSON schemas, tests, and
  downstream stages that reference the old name. Verify by grepping for the old
  name across the whole tree after the fix.
- **triggers**: A fix commit renames a field, key, flag, or function, or adds
  a new required field to a JSON schema.
- **example**: PR #448 — the fix used `scope_reason` in the prose instruction
  but `reason` in the JSON schema; downstream stages reading `reason` found
  nothing, and stages reading `scope_reason` found nothing. Fix: after
  renaming, grep for the old name across `src/`, `workflows/`, `tests/`, and
  `.claude/` and update every occurrence. Then grep for the new name and
  confirm every reader is covered.
- **sweep**: procedure, applied to the diff when the trigger matches:
  1. Identify every field, key, or function renamed or added.
  2. For each, grep the full repo for the old name; record any hits outside the
     diff's own deletions.
  3. For the new name, grep `src/`, `workflows/`, `tests/`, and `.claude/` and
     confirm every reader that used the old name now uses the new one.
- **cause**: INCOMPLETE_FIX — the fix updated the definition but not all callers;
  RENAME_PARTIAL — a rename was applied to source code but not to prose,
  schema, or tests that reference it by string literal

### stale-descriptions
- **severity**: major
- **check**: A fix that changes a threshold, default, timeout, or behaviour
  leaves the PR description, docstrings, comments, or workflow stage descriptions
  stating the old value or the old behaviour. Verify by reading every mention of
  the changed value in the surrounding context.
- **triggers**: A fix commit changes a numeric constant, timeout, default, or
  algorithm in a way that is also described in prose (a docstring, comment,
  workflow stage description, or PR description body).
- **example**: PR #452 — the fix made a timeout derived and capped at 2,000 s,
  but the PR description still said "1,200 s / 1,800 s". A reviewer reading
  the description sees the wrong value and may raise a new thread on the next
  review. Fix: after changing a constant, grep for every prose mention of the
  old value (`git grep "1200\|1800"`) and update each one. If the new value is
  derived rather than fixed, replace the literal with a description of the
  derivation.
- **sweep**: procedure, applied to the diff when the trigger matches:
  1. Identify every numeric constant, threshold, or named default changed by
     the diff.
  2. For each, grep the PR description, in-file docstrings and comments, and
     workflow stage descriptions for the old value (as a number and as prose,
     e.g. "1,200 seconds" and "1200").
  3. Record a finding for each hit outside the diff's own changes.
- **cause**: STALE_PROSE — the implementation was updated but the surrounding
  documentation was not; INCOMPLETE_FIX — the fix is technically correct but
  leaves the PR description misleading
