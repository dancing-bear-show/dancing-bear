# Contributing to Personal Assistants

Thank you for your interest in contributing! This project provides unified CLIs for personal workflows (mail, calendars, schedules, resumes, phone layouts, WhatsApp).

## Quick Start

1. **Fork and clone** the repository
2. **Set up environment**:
   ```bash
   make venv
   source .venv/bin/activate  # or use direnv
   ```
3. **Run tests** to ensure everything works:
   ```bash
   make test
   ```

## Development Guidelines

### Code Style

- **Python 3.11+** required
- Follow existing patterns in the codebase
- Use lazy imports for optional dependencies
- Keep CLI flags/subcommands stable
- See `.github/COMMIT_CONVENTION.md` for commit message format

### Testing

- Add tests for new CLI surfaces and features
- Run tests before submitting: `make test` or `python3 -m unittest -v`
- CI runs tests automatically (see `.github/workflows/ci.yml`)
- Aim for focused, lightweight tests

### Code Quality

- Run quality checks locally:
  ```bash
  ~/.qlty/bin/qlty check .
  ```
- CI runs `qlty` (ruff + bandit) automatically
- Fix security issues (bandit S rules) and complexity warnings

### Architecture

See `.llm/CONTEXT.md` and `.llm/DOMAIN_MAP.md` for:
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
- Generated files (`.llm/AGENTIC*.md`, `out/**`)

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
