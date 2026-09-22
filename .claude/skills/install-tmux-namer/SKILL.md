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

## Step 0: Disclose what the hook captures, and get consent

**This hook records prompt text. Do not install it without telling the user
first and getting an explicit yes.**

What it does on every prompt
(`configs/llm/tmux-session-namer.py:50-95`):

- Appends the **first 120 characters of the prompt** to
  `$XDG_CACHE_HOME/claude/prompts-<session-id>.txt`, falling back to
  `~/.cache/claude/...` when `XDG_CACHE_HOME` is unset
  (`tmux-session-namer.py:51`). Trimmed to the last 200 lines. The directory is
  created `0700` and the file opened `0600`, so it is user-private — but it is
  still prompt text at rest on disk.

  Resolve the real path before asking, so consent names the actual location:

      python3 -I -S -c "import os; print(os.path.join(os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache')), 'claude'))"
- Every 20th prompt, sends **the last 20 recorded lines** to `claude -p` to
  generate the session name. That is an outbound model call containing those
  prompt fragments.

Prompts from unrelated work can contain credentials, tokens, customer data or
other PII, and this capture does not distinguish them. Say this plainly, in
these terms, and install only on an explicit yes:

> This hook saves the first 120 characters of every prompt to
> <the resolved cache path>/prompts-*.txt and sends the last 20 of them to `claude -p`
> every 20th prompt, to generate the session name. Prompt text can include
> secrets or personal data. Install it? (y/n)

If the user declines, stop — do not install any part of this, including the
hook script copy. If they want the renaming without the capture, say that the
current hook has no redaction or disable switch and that adding one is a change
to `configs/llm/tmux-session-namer.py`, not something this skill can configure.

To remove it later: delete the `UserPromptSubmit` entry from
`~/.claude/settings.json`, then delete the captured prompts from the resolved
cache directory:

    rm -f "$(python3 -I -S -c "import os; print(os.path.join(os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache')), 'claude'))")"/prompts-*.txt

## Step 1: Check Prerequisites

```bash
# tmux is not required to INSTALL — the hook checks $TMUX itself on every
# prompt (tmux-session-namer.py:25) and exits quietly when unset, so it can be
# installed ahead of a later tmux session.
echo ${TMUX:-"not in tmux — installing anyway; the hook stays idle until tmux is running"}

# claude CLI must be on PATH (used for summarization)
which claude || echo "claude not found — install Claude Code first"

# python3 must be available
which python3
```

Do not stop when `$TMUX` is unset. Warn that the hook will remain idle until
tmux is available and continue — the documented "new machine or after cloning"
setup runs outside tmux, and refusing there makes it fail for no reason.

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
import json, os, shutil, stat, sys, tempfile

settings_path = os.path.expanduser("~/.claude/settings.json")


def save_settings(data):
    """Replace settings.json atomically, preserving its mode.

    `open(path, "w")` truncates the live file before writing a byte, so an
    interruption or a full disk mid-dump leaves the user's GLOBAL Claude
    settings empty or half-written. Serialise to a temp file in the same
    directory (same filesystem, so os.replace is atomic), fsync it, then
    rename over the original — a crash at any point leaves the old file intact.
    """
    directory = os.path.dirname(settings_path) or "."
    os.makedirs(directory, exist_ok=True)

    # Sweep any .settings-*.tmp orphaned by a previous hard kill. The except
    # path below cleans up on a normal exception, but a SIGKILL or os._exit
    # skips it, and those stragglers otherwise accumulate silently.
    for stale in os.listdir(directory):
        if stale.startswith(".settings-") and stale.endswith(".tmp"):
            try:
                os.unlink(os.path.join(directory, stale))
            except OSError:  # nosec B110 - best-effort sweep; never block the write
                pass

    try:
        original_mode = stat.S_IMODE(os.stat(settings_path).st_mode)
    except FileNotFoundError:
        original_mode = 0o600

    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".settings-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, original_mode)
        os.replace(tmp, settings_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:  # nosec B110 - temp cleanup is best-effort; original error re-raised
            pass
        raise


def backup_settings():
    """Keep a timestamped copy before the first modification."""
    if not os.path.exists(settings_path):
        return None
    import time
    dest = f"{settings_path}.bak.{time.strftime('%Y%m%d%H%M%S')}"
    shutil.copy2(settings_path, dest)
    return dest

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

# -I -S for the same reason the heredocs above use it, but the exposure here is
# longer-lived: this command runs on EVERY prompt for as long as the hook stays
# installed, so an inherited PYTHONPATH or a stray sitecustomize.py in the
# session would execute before the hook's own code each time. The hook imports
# only stdlib (json, sys, os, subprocess, re, shutil), so isolation costs it
# nothing.
hook_command = "python3 -I -S ~/.claude/hooks/tmux-session-namer.py 2>/dev/null || true"

# Match on the script name, not the full command string. An earlier version of
# this skill wired the hook without -I -S; an exact-string comparison would miss
# that entry and append a SECOND hook, so the namer would then run twice on
# every prompt. Detect any wiring of this script and upgrade it in place.
upgraded = False
already_wired = False
for entry in existing:
    for h in entry.get("hooks", []):
        cmd = h.get("command", "")
        if "tmux-session-namer" not in cmd:
            continue
        if cmd == hook_command:
            already_wired = True
        else:
            h["command"] = hook_command
            upgraded = True

if upgraded:
    hooks["UserPromptSubmit"] = existing
    backup = backup_settings()
    save_settings(settings)
    print("Upgraded the existing UserPromptSubmit hook to the isolated form")
    if backup:
        print(f"Previous settings saved to {backup}")
elif already_wired:
    print("UserPromptSubmit hook already present and isolated — skipping")
else:
    existing.append({
        "hooks": [{"type": "command", "async": True, "command": hook_command}]
    })
    hooks["UserPromptSubmit"] = existing
    backup = backup_settings()
    save_settings(settings)
    print("Added UserPromptSubmit hook to ~/.claude/settings.json")
    if backup:
        print(f"Previous settings saved to {backup}")
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
# Assert the ISOLATED form specifically. Matching only the script name would
# report success for a stale bare-`python3` entry — i.e. it would pass in exactly
# the case this installer exists to correct. Also assert there is exactly one
# wiring, since a duplicate means the namer runs twice per prompt.
python3 -I -S -c "
import json, os, sys
s = json.load(open(os.path.expanduser('~/.claude/settings.json')))
hooks = s.get('hooks', {}).get('UserPromptSubmit', [])
cmds = [h.get('command','') for e in hooks for h in e.get('hooks',[])]
namer = [c for c in cmds if 'tmux-session-namer' in c]

if len(namer) == 0:
    print('FAIL: hook not wired'); sys.exit(1)
if len(namer) > 1:
    print(f'FAIL: {len(namer)} namer hooks wired — it would run {len(namer)}x per prompt')
    for c in namer:
        print('  ', c)
    sys.exit(1)

cmd = namer[0]
missing = [f for f in ('-I', '-S') if f not in cmd.split()]
if missing:
    print('FAIL: wired but NOT isolated - missing', ' '.join(missing))
    print('      ', cmd)
    sys.exit(1)

print('Hook wired and isolated:', cmd)
"

# Confirm tmux is reachable, if we are inside it. Outside tmux this is expected
# to fail and is not an install failure — the hook idles until tmux is running.
if [ -n "${TMUX:-}" ]; then
  tmux display-message -p 'tmux OK: session=#S'
else
  echo "not in tmux — install complete; the hook stays idle until a tmux session exists"
fi
```

## Report

After completing the steps, report:

```
## tmux Session Namer Install Status

| Component | Status |
|-----------|--------|
| Prompt-capture consent | granted (required — see Step 0) |
| Hook script | ~/.claude/hooks/tmux-session-namer.py |
| settings.json | UserPromptSubmit hook wired (isolated form) |
| ~/.zshrc | iTerm sync added (or skipped — consent required) |
| tmux | running / not running (hook idles until it is) |
| Reload needed | Open /hooks or restart Claude |

The hook runs on the next prompt, but only renames the session once the prompt
count for this session reaches a multiple of 20 (configs/llm/tmux-session-namer.py:82).

It records the first 120 characters of each prompt to
`<resolved cache dir>/prompts-*.txt` — report the path you resolved in Step 0,
not a hard-coded `~/.cache`, since the hook honours `XDG_CACHE_HOME` — and sends
the last 20 to `claude -p` on each 20th prompt. To undo: remove the
`UserPromptSubmit` entry from `~/.claude/settings.json` and delete that
directory's `prompts-*.txt`.
```
