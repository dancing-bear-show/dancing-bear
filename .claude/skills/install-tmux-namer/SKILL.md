---
name: install-tmux-namer
description: Install the tmux auto-session-namer hook for Claude Code. Copies the hook script, patches ~/.claude/settings.json, and optionally patches ~/.zshrc for iTerm tab sync. Use when setting up a new machine or after cloning dancing-bear.
allowed-tools: Bash, Read, Write, Edit, Glob
skills:
  - dancing-bear-rules
---

# Install tmux Session Auto-Namer

Installs the Claude Code hook that automatically renames your tmux session
to a short AI-generated summary of what you're working on, updated every 20 prompts.

## Step 1: Check Prerequisites

```bash
# Must be running inside tmux
echo ${TMUX:-"NOT IN TMUX — start a tmux session first"}

# claude CLI must be on PATH (used for summarization)
which claude || echo "claude not found — install Claude Code first"

# python3 must be available
which python3
```

If not in tmux, stop here — the hook is a no-op outside tmux.

## Step 2: Copy Hook Script

```bash
mkdir -p ~/.claude/hooks

# Check if already installed
if [ -f ~/.claude/hooks/tmux-session-namer.py ]; then
  if diff -q ~/.claude/hooks/tmux-session-namer.py configs/llm/tmux-session-namer.py > /dev/null; then
    echo "Up to date — nothing to do"
  else
    backup=~/.claude/hooks/tmux-session-namer.py.bak.$(date +%Y%m%d%H%M%S)
    cp ~/.claude/hooks/tmux-session-namer.py "$backup"
    echo "Existing hook differs from repo version — backed up to $backup"
    cp configs/llm/tmux-session-namer.py ~/.claude/hooks/tmux-session-namer.py
    chmod +x ~/.claude/hooks/tmux-session-namer.py
    echo "Hook script updated at ~/.claude/hooks/tmux-session-namer.py"
  fi
else
  echo "Installing..."
  cp configs/llm/tmux-session-namer.py ~/.claude/hooks/tmux-session-namer.py
  chmod +x ~/.claude/hooks/tmux-session-namer.py
  echo "Hook script installed at ~/.claude/hooks/tmux-session-namer.py"
fi
```

## Step 3: Patch ~/.claude/settings.json

Read `~/.claude/settings.json`, check if the `UserPromptSubmit` hook is already present,
and add it if not. **Merge carefully — do not overwrite existing hooks.**

Use the Write/Edit tool to run this patch script, or execute it directly via Bash:

```bash
python3 -I -S - << 'PY'
import json, os, sys

settings_path = os.path.expanduser("~/.claude/settings.json")

if not os.path.exists(settings_path):
    settings = {}
elif os.path.getsize(settings_path) == 0:
    settings = {}
else:
    try:
        with open(settings_path) as f:
            settings = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: {settings_path} contains invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

hooks = settings.setdefault("hooks", {})
existing = hooks.get("UserPromptSubmit", [])

hook_command = "python3 ~/.claude/hooks/tmux-session-namer.py 2>/dev/null || true"

already_wired = any(
    h.get("command") == hook_command
    for entry in existing
    for h in entry.get("hooks", [])
)

if already_wired:
    print("UserPromptSubmit hook already present — skipping")
else:
    existing.append({
        "hooks": [{"type": "command", "async": True, "command": hook_command}]
    })
    hooks["UserPromptSubmit"] = existing
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)
    print("Added UserPromptSubmit hook to ~/.claude/settings.json")
PY
```

After patching, open `/hooks` in Claude Code or restart to reload settings.

## Step 4: Patch ~/.zshrc for iTerm Tab Sync (Optional)

This makes your iTerm tab title mirror the tmux session name on every prompt.

**This step is optional and must not run without explicit user consent.** Ask the
user whether they want iTerm tab sync before touching `~/.zshrc` — e.g. "Add iTerm
tab title sync to ~/.zshrc? (y/n)". Only run the block below if they say yes; if they
decline or don't respond, skip this step and note it as skipped in the final report.

```bash
ZSHRC=~/.zshrc
MARKER="# Mirror tmux session name to iTerm tab title"

if grep -q "$MARKER" "$ZSHRC"; then
  echo "iTerm sync already in ~/.zshrc — skipping"
else
  cat >> "$ZSHRC" << 'ZSHEOF'

# Mirror tmux session name to iTerm tab title
function set_iterm_title_from_tmux() {
    if [[ -n "$TMUX" ]]; then
        local session=$(tmux display-message -p '#S')
        echo -ne "\033]0;${session}\007"
    fi
}
precmd_functions+=(set_iterm_title_from_tmux)
ZSHEOF
  echo "Added iTerm sync to ~/.zshrc"
  echo "Run: source ~/.zshrc"
fi
```

## Step 5: Verify

```bash
# Confirm hook script is present and executable
ls -la ~/.claude/hooks/tmux-session-namer.py

# Confirm hook is in settings
python3 -I -S -c "
import json, os
s = json.load(open(os.path.expanduser('~/.claude/settings.json')))
hooks = s.get('hooks', {}).get('UserPromptSubmit', [])
cmds = [h.get('command','') for e in hooks for h in e.get('hooks',[])]
print('Hook wired:', any('tmux-session-namer' in c for c in cmds))
"

# Confirm tmux is reachable
tmux display-message -p 'tmux OK: session=#S'
```

## Report

After completing the steps, report:

```
## tmux Session Namer Install Status

| Component | Status |
|-----------|--------|
| Hook script | ~/.claude/hooks/tmux-session-namer.py |
| settings.json | UserPromptSubmit hook wired |
| ~/.zshrc | iTerm sync added (or skipped) |
| Reload needed | Open /hooks or restart Claude |

The hook runs on the next prompt, but only renames the session once the prompt
count for this session reaches a multiple of 20 (configs/llm/tmux-session-namer.py:82).
```
