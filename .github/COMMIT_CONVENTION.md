# Commit Message Convention

This project follows [Conventional Commits](https://www.conventionalcommits.org/).

## Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

## Types

| Type       | Description                                      |
|------------|--------------------------------------------------|
| `feat`     | New feature                                      |
| `fix`      | Bug fix                                          |
| `docs`     | Documentation only                               |
| `refactor` | Code change (no new feature, no bug fix)         |
| `test`     | Adding or updating tests                         |
| `chore`    | Maintenance (deps, CI, configs, tooling)         |
| `perf`     | Performance improvement                          |
| `ci`       | CI/CD changes                                    |
| `style`    | Formatting, whitespace (no code change)          |
| `revert`   | Reverting a previous commit                      |

## Scopes

Use the assistant or module name:

- `mail` - mail_assistant
- `calendar` - calendar_assistant
- `schedule` - schedule_assistant
- `phone` - phone assistant
- `resume` - resume_assistant
- `whatsapp` - whatsapp assistant
- `wifi` - wifi_assistant
- `desk` - desk_assistant
- `core` - core/ shared modules
- `tests` - test infrastructure
- `ci` - GitHub Actions, workflows
- `deps` - dependency updates

## Subject Line Rules

- Use imperative mood: "add feature" not "added feature"
- No period at the end
- Max 50 characters (soft limit, 72 hard)
- Lowercase first letter

## Examples

```
feat(mail): add auto-labeling pipeline

fix(phone): handle missing IconState.plist gracefully

docs: update AGENTS.md with pipeline patterns

refactor(resume): extract parsing into pipeline module

test(mail): add FakeGmailClient fixture

chore(deps): bump pyyaml to 6.0.1

ci: add actions/read permission to codeql workflow
```

## Breaking Changes

Add `!` after type/scope and explain in footer:

```
feat(mail)!: change filter config format

BREAKING CHANGE: filters.yaml now requires 'rules' key instead of 'filters'
```

## Multi-line Body

Wrap at 72 characters. Explain *why*, not *what*:

```
fix(calendar): prevent duplicate events on re-sync

Previously, re-running sync would create duplicates because we matched
on subject only. Now we match on subject + start time + series ID to
correctly identify existing events.

Fixes #42
```

## Footer

Reference issues and co-authors:

```
Fixes #123
Closes #456
Co-Authored-By: Name <email>
```
