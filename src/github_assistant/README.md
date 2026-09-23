# GitHub CLI

Thin porcelain over `core.github`. Every subcommand parses arguments, reads any
body from a file, and calls into `core.github`. Output is command-specific:
most subcommands print JSON, but `repo` defaults to plain `owner/name` text
(`--format json` for JSON), `pr diff` and `run log` print raw text, and
`pr comment` prints a bare URL.

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
./bin/github pr review-comment --pr 123 --path src/a.py --line 10 --body-file c.md  # commit defaults to PR head
./bin/github run log --run 456789
```

## Rules encoded in the CLI

- Text bodies always travel via a file path (`--body-file PATH`, `-` for stdin);
  never argv. Review-derived text does not pass through a shell.
- `GITHUB_TOKEN` is scrubbed by `core.github.client()`.
- `threads reply` verifies the GraphQL payload (gh exits 0 on `errors`); a
  failed reply never triggers a resolve.
- `threads reply --run-id RUN` re-fetches the whole chain and skips only if a
  comment by the authenticated actor carries `<!-- dancing-bear-run: RUN -->`.
  The marker is public plaintext, so a copy by anyone else is reported as
  `forged_marker` and ignored. Markers already inside the body are stripped
  before posting, so a quoted one is never posted under our account.
- `pr edit` reads the PR back and exits 1 if GitHub does not hold what was sent.

Package name is `github_assistant`, not `github`, so it never shadows PyPI's
`github` package.
