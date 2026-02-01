# PR Workflow Assistant

Automated PR management: create PRs, review GitHub Copilot feedback, check qlty linting issues, check CI/CD status, resolve conversations, and update PR metadata.

## Quick Start

```bash
# Full workflow: create/update PR, review Copilot feedback, check qlty issues, resolve conversations, add summary
./bin/pr-assistant

# Dry run (see what would happen)
./bin/pr-assistant --dry-run

# Create PR only
./bin/pr-assistant --no-resolve-copilot --no-update-summary --no-check-qlty

# Review Copilot feedback and qlty issues on existing PR
./bin/pr-assistant --no-create
```

## Features

- **Auto-create PRs**: Creates a PR if one doesn't exist for the current branch
- **Review Copilot feedback**: Fetches all GitHub Copilot review comments
- **Check qlty issues**: Runs qlty linter on all PR files and reports issues by severity
- **Check CI/CD status**: Fetches GitHub Actions and other CI/CD check results
- **Resolve conversations**: Automatically marks Copilot review conversations as resolved
- **Add summaries**: Posts a combined summary of Copilot feedback, qlty issues, and CI/CD status to the PR
- **Update metadata**: Update PR title and description

## Usage

### Basic Workflow

```bash
# On your feature branch with changes ready
./bin/pr-assistant
```

This will:
1. Check for existing PR (create if missing)
2. Fetch Copilot review comments
3. Check qlty linting issues on all PR files
4. Check CI/CD status (GitHub Actions, etc.)
5. Display combined summary
6. Resolve all Copilot conversations
7. Add combined summary comment to PR

### Common Scenarios

#### Create PR without Copilot processing
```bash
./bin/pr-assistant --no-resolve-copilot --no-update-summary
```

#### Only process Copilot feedback (no PR creation)
```bash
./bin/pr-assistant --no-create
```

#### Review Copilot feedback without resolving
```bash
./bin/pr-assistant --no-resolve-copilot
```

#### Update PR title and description
```bash
./bin/pr-assistant --title "New title" --body "New description"
```

#### Create PR against different base branch
```bash
./bin/pr-assistant --base develop
```

### Flags

- `--create` / `--no-create`: Control PR creation (default: create)
- `--resolve-copilot` / `--no-resolve-copilot`: Auto-resolve Copilot conversations (default: resolve)
- `--check-qlty` / `--no-check-qlty`: Check qlty linting issues on PR files (default: check)
- `--check-ci` / `--no-check-ci`: Check CI/CD status (default: check)
- `--update-summary` / `--no-update-summary`: Add summary comment (default: add)
- `--base BRANCH`: Base branch for new PRs (default: main)
- `--title TEXT`: Override PR title
- `--body TEXT`: Override PR description
- `--dry-run`: Preview actions without making changes

## Flows

Use via `./bin/llm flows`:

```bash
# List all PR flows
./bin/llm flows --list | grep pr_

# Run a specific flow
./bin/llm flows --id pr_auto --format md
```

Available flows:
- `pr_auto`: Full workflow (default behavior)
- `pr_dry_run`: Preview mode
- `pr_create`: Just create PR
- `pr_review_copilot`: Review and resolve Copilot feedback
- `pr_summary`: Add summary without resolving
- `pr_update_title`: Update PR title

## Requirements

- GitHub CLI (`gh`) must be installed and authenticated
- Must be run from within a git repository
- Must be on a branch (not detached HEAD)
- qlty CLI (`~/.qlty/bin/qlty`) for linting checks (optional - skipped if not found)

## Example Output

```
Found PR #54: fix: resolve 168 qlty linting issues (99.4% reduction)
URL: https://github.com/dancing-bear-show/dancing-bear/pull/54

Fetching Copilot review comments...
Found 3 Copilot comment(s)

## Copilot Review Summary

Found 3 Copilot review comment(s):

### 1. core/pr_workflow.py:45
Consider adding type hints for better code clarity...

### 2. core/pr_workflow.py:67
This could be simplified using a dict comprehension...

### 3. bin/pr-assistant:23
Missing docstring for main function...

Checking qlty issues on PR files...
Checking 5 file(s)...

## Qlty Linting Issues

Found 7 issue(s):

### HIGH (2)

- `core/pr_workflow.py:120` - subprocess call - check for execution of untrusted input. (bandit:B603)
- `mail/filters.py:45` - SQL injection vulnerability detected (bandit:B608)

### MEDIUM (3)

- `core/pr_workflow.py:85` - Local variable `url` is assigned to but never used (ruff:F841)
- `bin/pr-assistant:15` - Undefined name `Optional` (ruff:F821)
- `mail/utils.py:67` - Missing return type annotation (ruff:ANN201)

### LOW (2)

- `tests/test_pr.py:23` - Line too long (120 > 88 characters) (ruff:E501)
- `core/helpers.py:156` - Replace the unused local variable "code" with "_" (radarlint:S1481)

Resolving Copilot conversations...
✓ Comment 12345 in core/pr_workflow.py
✓ Comment 12346 in core/pr_workflow.py
✓ Comment 12347 in bin/pr-assistant

Updating PR with summary...
✓ Added summary comment

✓ Workflow complete. PR: https://github.com/dancing-bear-show/dancing-bear/pull/54
```

## Implementation Details

- **Core logic**: `core/pr_workflow.py`
- **CLI wrapper**: `bin/pr-assistant`
- **Flows**: `.llm/FLOWS.yaml` (pr_workflow section)
- Uses GitHub CLI (`gh`) for all GitHub API interactions
- Resolves conversations using GraphQL API

## Troubleshooting

### "gh CLI not found"
Install GitHub CLI: https://cli.github.com/

### "No PR found for current branch"
Either:
- Use `--create` to auto-create (default behavior)
- Create PR manually first with `gh pr create`

### "Failed to resolve conversation"
- Check GitHub permissions
- Ensure PR is not locked
- Verify you have write access to the repository
