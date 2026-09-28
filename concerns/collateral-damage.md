# Collateral Damage Review Guide

## When loaded

Load it when a diff contains fix commits made in response to review, or edits code that prose, tests or PR text describe.

## Concerns

### incomplete-guard-coverage
- **severity**: major
- **check**: Answer yes to each step: Does the diff, its tests, or the PR text list every input form the guard receives (valid, malformed, empty, boundary, and adversarial cases)? Does it list every entry point that reaches the guard (CLI flags, stage inputs, function callers)? Does each listed input form have its own test or explicit check asserting accept or reject? Does each entry point have a test or trace that reaches the guard through that entry point?
- **triggers**: a function that rejects, filters, authorises, or validates input is added or modified in `src/**/*.py` or a guard/validation stage is added or modified in `workflows/**/*.yaml`
- **example**: `src/workflow/review_ids.py:408` defines `_KNOWN_ACTIONS = ("fixed", "rejected", "moot", "deferred")` for a fix-aggregate merge, but a value outside that tuple is accepted into an unlabeled bucket rather than rejected — the guard covers the known forms and silently passes the unknown one through. Fix: enumerate every input form the guard must handle (including the unknown/other case) and assert accept-or-reject for each, e.g. `raise ValueError(f"unknown result action {action!r}")` rather than a silent fallthrough.
- **sweep**: procedure, applied to the diff when the trigger matches:
  1. Does the diff, its tests, or the PR text list every input form the guard receives (valid, malformed, empty, boundary, and adversarial cases)?
  2. Does it list every entry point that reaches the guard (CLI flags, stage inputs, function callers)?
  3. Does each listed input form have its own test or explicit check asserting accept or reject?
  4. Does each entry point have a test or trace that reaches the guard through that entry point?
  Record: the input-form list and the entry-point list, each item paired with the test or check that covers it
- **cause**: LATE_DISCOVERY — the gap was found on later review, not introduced by a fix; SIBLING — an earlier fix repaired one instance of the guard and left other instances of the same guard shape uncaught; FIX_REGRESSION — a fix commit introduced a new guard that itself has the same absence shape; INCOMPLETE_FIX — a fix meant to close the gap only narrowed the set of uncovered forms rather than closing it

### literal-placeholder-in-agent-plan
- **severity**: major
- **check**: Verify every agent-facing plan, prompt, or stage description written or rewritten by a fix commit contains no `{...}` or `<...>` token that is not one of the workflow engine's substituted trigger params.
- **triggers**: an agent-facing plan, prompt, or stage `description:` is added or rewritten in `workflows/**/*.yaml` and contains a `{...}` or `<...>` token
- **example**: `workflows/tests/rectify-test-defects.yaml:528` introduces a `<base>` placeholder in the fix commit itself, and `workflows/code/review-and-fix.yaml:709` leaves a run-marker plan carrying an unsubstituted `{run_id}` token — both reach the agent as literal text rather than a resolved value, and in `qwen-local-handler.yaml:292` the unresolved `{job_type}` token is also prompt-injectable. Fix: resolve every placeholder against the workflow engine's declared trigger params before the text reaches an agent, and fail the lint/compile step if an unrecognized `{...}`/`<...>` token remains.
- **sweep**: structural — every agent-facing plan, prompt, or stage description written or rewritten by a fix commit contains no `{...}` or `<...>` token that is not one of the workflow engine's substituted trigger params
- **cause**: FIX_REGRESSION — a fix commit introduced a new placeholder-bearing plan or prompt that itself went unsubstituted; LATE_DISCOVERY — the unsubstituted placeholder was present since the round-0 diff and only found on later review; INCOMPLETE_FIX — a fix substituted some placeholders in the stage text but left a sibling placeholder or a different declared trigger param unresolved

### toctou-race
- **severity**: major
- **check**: Answer yes to each step: Does the diff name every actor that can run concurrently against the same state (other sessions, other queue consumers, other workflow runs)? Is the check and the following act performed as one atomic operation (a single syscall, a compare-and-swap, or a held lock spanning both), rather than two separate steps? Does a test or reply on the thread demonstrate the fix under a concurrent second actor, not just a serial re-run? If the fix narrows the race instead of closing it, does the PR text say so explicitly rather than claiming the race is fixed?
- **triggers**: a fix commit adds or modifies a lock, queue-drain, or file-existence check in `src/**/*.py`, `workflows/**/*.yaml`, or a shell script
- **example**: `.claude/scripts/name-worktree.sh:65` traded a guaranteed collision for a racy one — the pre-check and the following write are still two separate steps rather than one atomic operation — and `workflows/code/qwen-admin.yaml:823` re-reads a lock file and then unlinks it as a stale lock in a separate step, so a second actor can re-acquire the lock in between. Fix: perform the check and the act as a single atomic operation (e.g. an `os.O_EXCL` create, a compare-and-swap on the lock's contents, or a lock held across both the check and the act), and add a test that runs the check-act pair under a concurrent second actor rather than only a serial re-run.
- **sweep**: procedure, applied to the diff when the trigger matches:
  1. Does the diff name every actor that can run concurrently against the same state (other sessions, other queue consumers, other workflow runs)?
  2. Is the check and the following act performed as one atomic operation (a single syscall, a compare-and-swap, or a held lock spanning both), rather than two separate steps?
  3. Does a test or reply on the thread demonstrate the fix under a concurrent second actor, not just a serial re-run?
  4. If the fix narrows the race instead of closing it, does the PR text say so explicitly rather than claiming the race is fixed?
  Record: the concurrent-actor list and, for each, whether the check-act pair it targets is atomic or still a gap
- **cause**: FIX_REGRESSION — a fix for one race introduced a second, direct-access path that bypasses the same lock; INCOMPLETE_FIX — a fix locked one step of a multi-step sequence (e.g. a counter) and left the preceding read/append/trim steps unlocked; SIBLING — a lock/drain pattern fixed in one location recurs unfixed at another call site of the same shape; LATE_DISCOVERY — the unlocked check-act pair was part of the original design and only surfaced on later review

### null-id-unhandled
- **severity**: major
- **check**: Verify every place a GraphQL or API-derived id field (thread_id, databaseId, session_id) is used as a filename, dict key, or sort key first checks the value is not None and has an explicit fallback or rejection for the null case.
- **triggers**: a GraphQL or API response id field (`thread_id`, `databaseId`, `session_id`) is used to build a filename, a dict key, or a sort key
- **example**: `src/core/github/threads.py:183` parses GraphQL comments with an unvalidated `databaseId`, and `src/core/copilot_overview.py`'s thread-sorting path can receive a `None` `thread_id` from an entry with no explicit guard before the sort/key use. Fix: check the id field is not `None` before using it as a key, filename, or sort key, and give it an explicit fallback (e.g. skip with a logged reason) or reject it outright rather than letting `None` collide with other `None`-keyed entries or crash the sort.
- **sweep**: structural — every place a GraphQL or API-derived id field (thread_id, databaseId, session_id) is used as a filename, dict key, or sort key first checks the value is not None and has an explicit fallback or rejection for the null case
- **cause**: INCOMPLETE_FIX — a fix guarded the null id in one function but a sibling function using the same id field was left unguarded; FIX_REGRESSION — a fix commit itself introduced a new unguarded id use; LATE_DISCOVERY — the unguarded id use predates the round it was found in and surfaced only on later review

### unisolated-interpreter
- **severity**: major
- **check**: Verify every `python3` invocation started where `PYTHONPATH` may name a foreign checkout (hooks, workflow stage shell text, diagnostic/checkpoint commands) uses `-I -S`.
- **triggers**: a bare `python3 -c` or `python3 -m` invocation is added or modified in a workflow stage description, hook script, or shell script, without `-I -S` flags
- **example**: `workflows/code/qwen-local-handler.yaml:2397` runs a diagnostic that imports `worker` before isolating the interpreter, and the same file's line 1070 uses a bare `python3` checkpoint invocation from an isolated worktree. Fix: add `-I -S` to every `python3` invocation reachable from a hook, stage, or script — `-I` ignores `PYTHONPATH` and the user site directory, `-S` skips `site.py`, which is what performs `sitecustomize`/`usercustomize` imports before any Python-level guard can run.
- **sweep**: `python3 -c` in `src/`, `workflows/`, `configs/`
- **cause**: SIBLING — an isolation fix applied to one python3 invocation in a workflow file left a sibling invocation in the same file unisolated
