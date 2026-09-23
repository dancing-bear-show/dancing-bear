# GitHub CLI

Thin porcelain over `core.github`. Every subcommand parses arguments, reads any
body from a file, calls into `core.github`, and prints JSON.

```
./bin/github repo
./bin/github threads fetch --pr 123 --out threads.json
./bin/github threads reply --thread ID --body-file reply.md --run-id RUN --resolve
./bin/github threads resolve --thread ID
./bin/github threads state --pr 123
./bin/github pr view --pr 123 --fields number,title,state
./bin/github pr view --pr 123 --value headRefOid
./bin/github pr diff --pr 123 --name-only
./bin/github pr create --base main --title "..." --body-file pr.md --draft
./bin/github pr edit --pr 123 --body-file pr.md
./bin/github pr ready --pr 123
./bin/github pr checks --pr 123
./bin/github pr checks --pr 123 --watch
./bin/github pr list --state open --fields number,title,url
./bin/github pr comment --pr 123 --body-file note.md
./bin/github pr comments --pr 123 --kind review
./bin/github run log --run 456789
```

## Rules encoded in the CLI

- Text bodies always travel via a file path (`--body-file PATH`, `-` for stdin);
  never argv. Review-derived text does not pass through a shell.
- `GITHUB_TOKEN` is scrubbed by `core.github.client()`.
- `threads reply` verifies the GraphQL payload (gh exits 0 on `errors`); a
  failed reply never triggers a resolve.
- `threads reply --run-id RUN` re-fetches the whole chain and skips if any
  comment already carries `<!-- dancing-bear-run: RUN -->`.
- `pr edit` reads the PR back and exits 1 if GitHub does not hold what was sent.

Package name is `github_assistant`, not `github`, so it never shadows PyPI's
`github` package.
