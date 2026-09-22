---
name: rename-session
description: Rename the current tmux session to a short summary of what you're working on right now. Use when you want to update the name immediately rather than waiting for the automatic 20-prompt cycle.
allowed-tools:
  - Bash
---

# Rename tmux Session

Generate a descriptive name for the current tmux session based on what we're
working on right now, then apply it.

## Generate and Apply Name

Look at the last few messages in context to understand the current task.
**Before choosing a name, check whether a PR exists for the current branch:**

```bash
pr_number=$(GITHUB_TOKEN= gh pr view --json number -q .number 2>/dev/null)
```

- If `$pr_number` is non-empty, prefer `pr-<NUMBER>-<topic>` (e.g. `pr-42-gmail-filters`).
- If empty, use the topic alone (current behavior).

Then apply the name:

```bash
name="topic-not-action"  # replace with the chosen name (pr-<N>-<topic> when a PR exists)
tmux rename-session "$name"
client_tty=$(tmux display-message -p '#{client_tty}' 2>/dev/null)
[ -n "$client_tty" ] && printf "\033]0;%s\007" "$name" > "$client_tty"
tmux display-message -p 'Session: #S'
```

**Naming rules:**
- 2-4 words, lowercase, hyphens not spaces (no spaces in the name)
- Capture the topic, not the action — `gmail-label-sync` not `syncing-gmail-labels`
- Max 30 characters
- No punctuation other than hyphens
- When a PR exists on the current branch, prefix the name with `pr-<NUMBER>-`

**Good:** `pr-42-gmail-filters`, `mail-label-sync`, `calendar-scan`, `resume-render`, `whatsapp-search`
**Bad:** branch names (too long), repo names (no context), `edit-filter-yaml` (too granular)

Report the new session name to the user.
