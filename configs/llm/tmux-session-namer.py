#!/usr/bin/env python3
"""
UserPromptSubmit hook: renames tmux session to a short AI summary of recent work.
Fires every 20th prompt using claude -p.

Install: copy to ~/.claude/hooks/tmux-session-namer.py
Wire up: add to ~/.claude/settings.json (see .claude/skills/install-tmux-namer/SKILL.md)
"""
import json
import sys
import os
import subprocess
import re
import shutil

try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)

session_id = str(d.get("session_id", "default"))
prompt = d.get("prompt", "").strip()

# Use truthy check — TMUX="" is not a valid tmux session
if not prompt or not os.getenv("TMUX"):
    sys.exit(0)

# Bail early if required tools are missing
if not shutil.which("claude") or not shutil.which("tmux"):
    sys.exit(0)


def _detect_pr_number() -> str:
    """Return the PR number for the current branch, or empty string. Never raises."""
    if not shutil.which("gh"):
        return ""
    try:
        result = subprocess.run(  # nosec B603 B607 - fixed args from shutil.which-validated path
            ["gh", "pr", "view", "--json", "number", "-q", ".number"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return ""
        num = result.stdout.strip()
        return num if num.isdigit() else ""
    except Exception:
        return ""


# Store history under user-private directory, using a sanitised session ID
cache_dir = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "claude")
os.makedirs(cache_dir, exist_ok=True)
os.chmod(cache_dir, 0o700)  # Fix permissions even if dir already existed
safe_id = re.sub(r"[^A-Za-z0-9._-]", "-", session_id)[:32]
history_file = os.path.join(cache_dir, f"prompts-{safe_id}.txt")

# Append prompt atomically with 0600 permissions from the start
try:
    fd = os.open(history_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(prompt[:120].replace("\n", " ") + "\n")
except Exception:
    sys.exit(0)

try:
    with open(history_file) as f:
        lines = f.readlines()
except Exception:
    sys.exit(0)

# Trim file to last 200 lines so it never grows unbounded
if len(lines) > 200:
    try:
        with open(history_file, "w") as f:
            f.writelines(lines[-200:])
        lines = lines[-200:]
    except Exception:  # nosec B110 - best-effort trim; skip silently on any IO error
        pass

count = len(lines)

if count % 20 == 0:
    recent = "".join(lines[-20:])
    pr_number = _detect_pr_number()
    pr_hint = (
        f"\n\nCurrent PR: #{pr_number} (prefer 'pr-{pr_number}-<topic>' format)"
        if pr_number else ""
    )
    try:
        result = subprocess.run(  # nosec B603 B607 - fixed args from shutil.which-validated path
            ["claude", "-p",
             "Reply with ONLY a tmux session name: 2-4 words, lowercase, hyphens instead of spaces, "
             "no punctuation, max 30 chars. Capture what the user is working on, not how. "
             f"Recent prompts:\n{recent}{pr_hint}"],
            capture_output=True, text=True, timeout=15
        )
        name = result.stdout.strip()
        name = re.sub(r"[^a-z0-9-]", "-", name.lower())
        name = re.sub(r"-+", "-", name).strip("-")[:30]
        # If a PR exists and the model didn't produce a pr-<N>-... name, prepend it.
        if name and pr_number and not name.startswith(f"pr-{pr_number}"):
            prefix = f"pr-{pr_number}-"
            # Drop a stale pr-<other>- prefix if present, then prepend correct one.
            name = re.sub(r"^pr-\d+-", "", name)
            name = (prefix + name)[:30].rstrip("-")
        if name and result.returncode == 0:
            subprocess.run(["tmux", "rename-session", name], capture_output=True)  # nosec B603 B607 - fixed args from shutil.which-validated path
            # Push iTerm2 tab title via the tmux client tty — pane ttys don't reach
            # the terminal emulator; only the client (outer) tty does.
            try:
                tty_result = subprocess.run(  # nosec B603 B607 - fixed args from shutil.which-validated path
                    ["tmux", "display-message", "-p", "#{client_tty}"],
                    capture_output=True, text=True, timeout=5,
                )
                client_tty = tty_result.stdout.strip() if tty_result.returncode == 0 else ""
                if client_tty:
                    with open(client_tty, "w") as t:
                        t.write(f"\033]0;{name}\007")
            except Exception:  # nosec B110 - best-effort iTerm2 title update; skip silently on error
                pass
    except Exception:  # nosec B110 - best-effort session rename; skip silently on error
        pass
