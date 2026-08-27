# Contributing to Personal Assistants

This project provides unified CLIs for personal workflows (mail, calendars, schedules, resumes, phone layouts, WhatsApp).

## Quick Start

1. Fork and clone the repository.
2. Set up environment:
   ```bash
   make venv
   source .venv/bin/activate  # or use direnv
   ```
3. Run tests to verify setup:
   ```bash
   make test
   ```

## Development Guidelines

### Code Style

- Python 3.11+ required.
- Follow existing patterns in the codebase.
- Use lazy imports for optional dependencies.
- Keep CLI flags/subcommands stable.
- See `.github/COMMIT_CONVENTION.md` for commit message format.

### Testing

- Add tests for new CLI surfaces and features
- Run tests before submitting: `make test`
- Never run bare `python3 -m unittest` in a worktree — an inherited `PYTHONPATH` silently resolves imports to the main checkout and produces false greens. Use `make test` or `PYTHONPATH="$PWD/src" python3 -m unittest discover -s tests`.
- CI runs tests automatically (see `.github/workflows/ci.yml`)
- Aim for focused, lightweight tests

### Code Quality

- Run quality checks locally:
  ```bash
  make lint                      # ruff over src/, tests/, bin/
  ./bin/qlty-assistant scan      # merged qlty check + smells, ranked by remediation tier
  ```
- There is no standalone `ruff` on PATH — CI lints through qlty's pinned build, which
  `make lint` resolves via `bin/ruff-resolve.sh`. A bare `ruff check` fails as
  "command not found".
- Do not run `qlty check` from inside `.claude/worktrees/` — that path is excluded, so it
  scans zero files while printing "✔ No issues". An empty result there means broken
  environment, not clean code.
- CI runs `qlty` (ruff + bandit) automatically
- Fix security issues (bandit S rules) and complexity warnings

### Architecture

See `.llm/CONTEXT.md` and `./bin/llm domain-map --stdout` for:
- Reading order for familiarization
- Module organization
- Development rules (do/avoid)

Key principles:
- **Dependency-light**: Minimize external dependencies
- **Safe by default**: Plan → dry-run → apply flows
- **Profile-based auth**: Use `~/.config/credentials.ini`
- **OO where cohesive**: Prefer small, focused helpers

## Pull Request Process

1. **Create a feature branch**: `git checkout -b feature/your-feature`
2. **Make focused changes**: Keep PRs small and single-purpose
3. **Add/update tests**: Cover new functionality
4. **Update docs**: If adding user-facing commands, update README minimally
5. **Run tests**: Ensure all tests pass
6. **Commit with convention**: Follow `.github/COMMIT_CONVENTION.md`
7. **Open PR**: Use the PR template, reference related issues
8. **CI checks**: Wait for tests and qlty to pass
9. **Address feedback**: Respond to review comments

### PR Requirements

- ✅ Tests pass (CI)
- ✅ Code quality checks pass (qlty)
- ✅ Follows commit conventions
- ✅ No credentials/secrets in code
- ✅ Descriptive PR title and description

## What to Contribute

### Good First Issues

- Add tests for uncovered modules
- Improve error messages
- Documentation improvements
- Bug fixes

### Areas for Contribution

- Additional mail providers
- Calendar integrations beyond Outlook
- Resume renderers (PDF, HTML)
- Test coverage expansion
- Performance improvements

### Avoid

- Breaking changes to stable CLI interfaces
- Heavy new dependencies without discussion
- Broad refactors that rename/move public entry points
- Generated files (`.llm/INVENTORY.md`, `.llm/FLOWS.generated.yaml`) — fix the generator instead

## Credentials and Testing

- **Never commit secrets**: Use `.gitignore` patterns
- **Test with care**: Don't run tests requiring network/secrets without user approval
- **Use profiles**: Store creds in `~/.config/credentials.ini`
- **Example configs**: Use `*.example.yaml` files for reference

## Code of Conduct

- Be respectful and constructive
- Focus on technical accuracy
- Welcome diverse perspectives
- Assume good intent

## Questions?

- Open an issue with the "question" template
- Check existing docs: `README.md`, `.llm/CONTEXT.md`
- Review patterns: `.llm/PATTERNS.md`

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
