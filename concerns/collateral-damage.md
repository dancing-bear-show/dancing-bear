# Collateral Damage Review Guide

## When loaded

Load it when a diff contains fix commits made in response to review, or edits code that prose, tests or PR text describe.

## Concerns

### incomplete-guard-coverage
- **severity**: major
- **check**: Answer yes to each step: Does the diff, its tests, or the PR text list every input form the guard receives (valid, malformed, empty, boundary, and adversarial cases)? Does it list every entry point that reaches the guard (CLI flags, stage inputs, function callers)? Does each listed input form have its own test or explicit check asserting accept or reject? Does each entry point have a test or trace that reaches the guard through that entry point?
- **triggers**: a function that rejects, filters, authorises, or validates input is added or modified in `src/**/*.py` or a guard/validation stage is added or modified in `workflows/**/*.yaml`
- **example**: A fix-aggregate guard defines `_KNOWN_ACTIONS = ("fixed", "rejected", "moot", "deferred")` and branches on them, but a value outside the tuple falls through to an unlabeled bucket rather than being rejected — the guard covers known forms and silently passes unknowns. Fix: enumerate every input form the guard must handle (including the unknown case) and assert accept-or-reject for each, e.g. `raise ValueError(f"unknown result action {action!r}")` rather than a silent fallthrough.
- **sweep**: procedure, applied to the diff when the trigger matches:
  1. Does the diff, its tests, or the PR text list every input form the guard receives (valid, malformed, empty, boundary, and adversarial cases)?
  2. Does it list every entry point that reaches the guard (CLI flags, stage inputs, function callers)?
  3. Does each listed input form have its own test or explicit check asserting accept or reject?
  4. Does each entry point have a test or trace that reaches the guard through that entry point?
  Record: the input-form list and the entry-point list, each item paired with the test or check that covers it
- **cause**: LATE_DISCOVERY — the gap was found on later review, not introduced by a fix; SIBLING — an earlier fix repaired one instance of the guard and left other instances of the same guard shape uncaught; FIX_REGRESSION — a fix commit introduced a new guard that itself has the same absence shape; INCOMPLETE_FIX — a fix meant to close the gap only narrowed the set of uncovered forms rather than closing it

### literal-placeholder-in-agent-plan
- **severity**: major
- **check**: Verify every `{name}` token in an agent-facing plan, prompt, or stage description written or rewritten by a fix commit is one the engine fills: (1) a param declared under `trigger.params`; (2) an engine-supplied variable — `{workspace}`, filled at dispatch, or `{work_dir}`, a built-in param the CLI injects; or (3) a placeholder the stage's fan-out config names for forwarding — `{fan_out_index}` and `{<fan_out.key>}` on a `mode: agent` fan-out, which the orchestrator fills per item. A `worker_queue` fan-out fills its key only in `fan_out.script`, so the key is not forwarded in that stage's description. The engine fills no `<...>` token: each one reaches the agent literally, so flag it unless the text tells the agent how to resolve it.
- **triggers**: an agent-facing plan, prompt, or stage `description:` is added or rewritten in `workflows/**/*.yaml` and contains a `<...>` token, or a `{name}` token that is not a declared trigger param, `{workspace}`, `{work_dir}`, `{fan_out_index}`, or the stage's own agent-mode `fan_out.key`
- **example**: A fix commit rewrites a stage description and introduces a `<base>` placeholder; a sibling stage carries an unsubstituted `{run_id}` token in its run-marker plan — both tokens reach the spawned agent as literal text rather than resolved values (seen on #397 and #400). Fix: check every placeholder against the set the engine fills — declared trigger params, `{workspace}`, `{work_dir}`, and the stage's forwarded fan-out placeholders — before the text reaches an agent, and fail the lint/compile step if any other `{...}`/`<...>` token remains.
- **sweep**: structural — every `{name}` token in an agent-facing plan, prompt, or stage description written or rewritten by a fix commit is a declared trigger param, an engine-supplied variable (`{workspace}`, `{work_dir}`), or a placeholder the stage's agent-mode fan-out forwards (`{fan_out_index}`, `{<fan_out.key>}`); every `<...>` token tells the agent how to resolve it, since the engine fills none
- **cause**: FIX_REGRESSION — a fix commit introduced a new placeholder-bearing plan or prompt that itself went unsubstituted; LATE_DISCOVERY — the unsubstituted placeholder was present since the round-0 diff and only found on later review; INCOMPLETE_FIX — a fix substituted some placeholders in the stage text but left a sibling placeholder or a different declared trigger param unresolved

### toctou-race
- **severity**: major
- **check**: Answer yes to each step: Does the diff name every actor that can run concurrently against the same state (other sessions, other queue consumers, other workflow runs)? Is the check and the following act performed as one atomic operation (a single syscall, a compare-and-swap, or a held lock spanning both), rather than two separate steps? Does a test or reply on the thread demonstrate the fix under a concurrent second actor, not just a serial re-run? If the fix narrows the race instead of closing it, does the PR text say so explicitly rather than claiming the race is fixed?
- **triggers**: a fix commit adds or modifies a lock, queue-drain, or file-existence check in `src/**/*.py`, `workflows/**/*.yaml`, or a shell script
- **example**: A worktree-naming script checks whether a branch name exists and then creates it as two separate steps — a second session can claim the same name between them, trading a guaranteed collision for a racy one. A lock-file manager reads the file, decides it is stale, and then unlinks it in a separate step — another actor can re-acquire between the read and the unlink. Fix: perform the check and the act as a single atomic operation (e.g. `os.O_EXCL` create, a compare-and-swap on the lock contents, or a held lock spanning both), and add a test that runs the check-act pair under a concurrent second actor, not only a serial re-run.
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
- **example**: A GraphQL response parser builds a per-thread dict keyed by `thread.get("databaseId")` without checking for `None`; a sibling sort path uses `key=lambda t: t["thread_id"]` on entries where `thread_id` may be absent, crashing with `KeyError` or sorting `None` against strings. Fix: check the id field is not `None` before using it as a key, filename, or sort key, and give it an explicit fallback (e.g. skip with a logged reason) or reject it outright rather than letting `None` collide with other `None`-keyed entries or crash the sort.
- **sweep**: structural — every place a GraphQL or API-derived id field (thread_id, databaseId, session_id) is used as a filename, dict key, or sort key first checks the value is not None and has an explicit fallback or rejection for the null case
- **cause**: INCOMPLETE_FIX — a fix guarded the null id in one function but a sibling function using the same id field was left unguarded; FIX_REGRESSION — a fix commit itself introduced a new unguarded id use; LATE_DISCOVERY — the unguarded id use predates the round it was found in and surfaced only on later review

### unisolated-interpreter
- **severity**: major
- **check**: Verify every `python3` invocation started where `PYTHONPATH` may name a foreign checkout (hooks, workflow stage shell text, diagnostic/checkpoint commands) either passes `-I` (add `-S` for a stdlib-only body) or is prefixed with `PYTHONPATH="$PWD/src"` to pin it to this checkout. A hook that runs Python must use `-I -S` specifically, since a hook has no repo import to pin.
- **triggers**: a bare `python3 -c` or `python3 -m` invocation is added or modified in a workflow stage description, hook script, or shell script, without `-I` or a `PYTHONPATH="$PWD/src"` prefix
- **example**: A workflow stage runs `python3 -c "import worker; ..."` as a diagnostic with neither `-I` nor a `PYTHONPATH="$PWD/src"` prefix; a sibling stage runs a bare `python3 -m unittest` checkpoint from an isolated worktree. When `PYTHONPATH` names a foreign checkout, both invocations silently import that checkout's `worker` before any Python-level guard runs. Fix: add `-I -S` for a stdlib-only probe or hook (`-I` ignores `PYTHONPATH` and the user site directory, `-S` skips `site.py`, which is what performs `sitecustomize`/`usercustomize` imports), `-I` alone when the body needs site-packages, or prefix the invocation with `PYTHONPATH="$PWD/src"` when it must import this repo's own packages — the house form for import probes and test runs, and the accepted alternative to `-I` in the workflow-isolation test suite.
- **sweep**: grep for `python3 -c` or `python3 -m` in `workflows/**/*.yaml`, `.claude/agents/**/*.md`, `.claude/skills/**/*.md`, and hook/shell scripts; for each hit, confirm it carries `-I`/`-IS`/`-I -S` or a leading `PYTHONPATH="$PWD/src"` (or `"$(pwd)/src"`) prefix — a hit with neither is unisolated
- **cause**: SIBLING — an isolation fix applied to one python3 invocation in a workflow file left a sibling invocation in the same file unisolated
