# agent_helpers

Single-purpose checks for agent sessions. One JSON object on stdout, exit 0;
read the verdict from the body. Exit 2 is a usage error; `summarize-findings`
exits 1 on unreadable input.

```bash
./bin/agent-helpers run-tests                          # make test; fails without "Ran N tests" (N > 0)
./bin/agent-helpers run-tests --paths tests/wifi_tests # unittest discover per path
./bin/agent-helpers run-tests --tool lint              # make lint
./bin/agent-helpers run-tests --tool typecheck         # make typecheck-changed
./bin/agent-helpers validate-imports --module core.process --symbols run_binary
./bin/agent-helpers validate-ast --file src/core/process.py --all-exported
./bin/agent-helpers validate-ast --file f.py --function g --complexity
./bin/agent-helpers validate-json --file f.json --keys status,results --count results
./bin/agent-helpers summarize-findings --input f.json --group-by severity [--format table|csv]
./bin/agent-helpers analyze-patch --patch p.diff --extract imports|added-functions|all-list|dispatch-map
./bin/agent-helpers git-ops --op checkout|worktree-add|worktree-remove|worktree-list ...
```

Notes:

- `run-tests` replaces `PYTHONPATH` with this checkout's `src/` for child
  processes, applies per-tool timeouts, and tail-truncates output.
- `validate-imports` imports the module in-process; module side effects run.
- Concern-guide selection lives in `./bin/workflow select-concerns`.
