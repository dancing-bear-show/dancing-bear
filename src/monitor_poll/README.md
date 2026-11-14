# monitor-poll

Poll a condition until it resolves or times out. One blocking call replaces
repeated status turns in an agentic loop.

## Usage

```
./bin/monitor-poll <condition> [--timeout SECS] [--interval SECS] [options] [ARGS ...]
./bin/monitor-poll status [--format json|table|csv]
./bin/monitor-poll cancel --poll-id ID
./bin/monitor-poll cancel --pid PID
```

`--timeout`, `--interval` and the other options belong to the condition
subcommand, so they go after its name. For `cmd` and `output`, put them
before the command: everything after the command belongs to it.

## Conditions

| Subcommand | Resolves when |
|---|---|
| `cmd` | A command exits with `--expect-rc` (default 0) |
| `output` | A command's stdout matches `--match` regex |
| `file` | A path exists (or, with `--absent`, disappears) |
| `http` | GET URL returns `--status` (default 200), optionally matching `--match` |
| `gh-pr` | Every check on a GitHub PR passes |
| `gh-run` | A GitHub Actions run concludes with `success` |

## Output

Each poll subcommand prints one final NDJSON record:

```json
{"condition":"http","verdict":"passed","polls":3,"elapsed_s":8.2,"detail":"HTTP 200","poll_id":"a1b2..."}
```

Verdicts: `passed` (exit 0), `failed` / `timed_out` (exit 1), `error` (exit 2).

With `--ticks`, each evaluation prints a line first; the final record is last.

## Status and cancel

```
./bin/monitor-poll status               # list active and recent polls
./bin/monitor-poll cancel --poll-id ID  # SIGTERM by poll_id
./bin/monitor-poll cancel --pid PID     # SIGTERM by OS pid
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Condition passed; or cancel sent (or refused because poll already finished) |
| 1 | Condition failed or timed out; or cancel failed (OS refused to signal the pid) |
| 2 | Condition could not be evaluated (bad input, missing tool), or bad usage |
| 6 | cancel: no matching poll found |

## Notes

- Connection failures and per-attempt timeouts are PENDING, not errors; the poll
  retries until `--timeout`.
- `cmd` and `output` take the command as an argument vector, with no shell.
  Wrap it in `sh -c` for pipes.
- `--timeout 0` checks once and exits immediately.
- `--interval` must be greater than zero.
