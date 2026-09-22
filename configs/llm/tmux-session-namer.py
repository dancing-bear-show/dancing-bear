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
import stat
import subprocess
import re
import shutil

try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)

# Valid JSON of the wrong shape still has to be survivable: `[]` and `"x"` parse
# fine and then have no .get, which raised AttributeError on line 21 — a
# traceback in front of the user on a prompt, since this runs on every one.
if not isinstance(d, dict):
    sys.exit(0)

session_id = str(d.get("session_id", "default"))
prompt = str(d.get("prompt") or "").strip()

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
        # Clear any inherited GITHUB_TOKEN: a stale one makes gh fail auth, and
        # because stderr is captured the failure is silent — PR detection just
        # returns "" and the pr-<N>- prefix disappears with no indication why.
        # Matches the `GITHUB_TOKEN= gh ...` contract used across this repo.
        # Both variables: gh honours GH_TOKEN as well as GITHUB_TOKEN, so
        # clearing only one leaves a stale token able to break PR detection.
        env = {**os.environ, "GITHUB_TOKEN": "", "GH_TOKEN": ""}
        result = subprocess.run(  # nosec B603 B607 - fixed args from shutil.which-validated path
            ["gh", "pr", "view", "--json", "number", "-q", ".number"],
            capture_output=True, text=True, timeout=5, env=env,
        )
        if result.returncode != 0:
            return ""
        num = result.stdout.strip()
        return num if num.isdigit() else ""
    except Exception:
        return ""


# Store history under user-private directory, using a sanitised session ID
# XDG: an EMPTY value means unset, per the spec. `os.environ.get(k, default)`
# returns the empty string when the var is set-but-empty, and
# os.path.join("", "claude") is the RELATIVE path "claude" — so prompt text
# would land in whatever the working directory happens to be, typically a
# project checkout. Require an absolute value or fall back.
_xdg = os.environ.get("XDG_CACHE_HOME") or ""
if not os.path.isabs(_xdg):
    _xdg = os.path.expanduser("~/.cache")
cache_dir = os.path.join(_xdg, "claude")
os.makedirs(cache_dir, exist_ok=True)
# Tighten a too-permissive directory, but never LOOSEN one. The previous
# unconditional chmod(0o700) re-opened a directory a user had deliberately
# locked down (e.g. 0o500 to pause capture) and carried on recording — and the
# skill claimed the opposite. Only add the owner bits we need, and only when
# they are missing.
try:
    _mode = stat.S_IMODE(os.stat(cache_dir).st_mode)
    if _mode & 0o077:  # group/other access: strip it
        os.chmod(cache_dir, _mode & 0o700)
        _mode &= 0o700
    if _mode & 0o300 != 0o300:  # not writable+executable by us: leave it alone
        sys.exit(0)  # a locked cache dir means no capture, as documented
except OSError:
    sys.exit(0)
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

# Cadence must come from a MONOTONIC count, not from len(lines).
#
# The trim above pins len(lines) at exactly 200 once the file saturates, and
# 200 % 20 == 0 — so deriving the cadence from the line count made the rename
# fire on EVERY prompt from prompt 200 onwards instead of every 20th. That is
# 20x the `claude -p` spend, and it sends the last 20 prompt fragments off the
# machine on every single prompt rather than one in twenty.
#
# A separate counter file keeps counting past the trim. It is stored alongside
# the history with the same 0600 permissions.
#
# The increment must be LOCKED and its success must GATE the rename:
#
#  - The installer registers this hook with `async: true`, so two
#    UserPromptSubmit processes can overlap. An unlocked read/increment/write
#    lets both read the same value, both write it back, and both fire — a
#    duplicate model call plus a lost count.
#  - If the write fails, a later run re-seeds from the trimmed history. With the
#    history pinned at 200 that seeds 199, `+1` gives 200, and `200 % 20 == 0`
#    fires on EVERY prompt — reintroducing the exact bug this counter exists to
#    prevent. So a count that was not durably stored must not open the gate.
counter_file = os.path.join(cache_dir, f"count-{safe_id}.txt")
count = None
try:
    # O_CREAT without O_TRUNC: open (or create) then lock before reading, so a
    # concurrent process waits rather than racing us between read and write.
    fd = os.open(counter_file, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        # If we cannot obtain the lock, we cannot honestly claim the cadence is
        # serialized: the installer registers this hook with `async: true`, so
        # two overlapping prompts could both read/increment/write the same
        # value and both fire `claude -p`. Treat lock failure exactly like
        # counter-write failure — skip the rename for this prompt — rather
        # than proceeding unlocked. The counter itself still gets written
        # below (unlocked in that case) so the cadence is not lost permanently.
        locked = False
        try:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
            locked = True
        except (ImportError, OSError):  # nosec B112 - no flock (e.g. some network FS): skip rename, not the write
            locked = False

        raw = os.read(fd, 64).decode("utf-8", "replace").strip()
        # A value this hook could not have written is corruption, not data:
        # - negative: this hook only ever writes stored + 1 starting from a
        #   non-negative seed, so a leading "-" cannot be ours.
        # - truncated: os.read(fd, 64) caps the read at 64 bytes, so a longer
        #   digit string was cut mid-number rather than fully read; treating
        #   it as valid would count up from a wrong, truncated base.
        # Either case reseeds from the history length exactly like a
        # non-numeric value does.
        try:
            stored = int(raw)
            if stored < 0 or len(raw) >= 64:
                raise ValueError("counter value could not have been written by this hook")
        except ValueError:
            # Empty (just created) or corrupt: seed from the history length. `lines`
            # already includes the prompt appended above, so subtract it, or this
            # prompt is counted twice.
            stored = max(len(lines) - 1, 0)

        nxt = stored + 1
        os.lseek(fd, 0, os.SEEK_SET)
        os.truncate(fd, 0)
        os.write(fd, str(nxt).encode("utf-8"))
        os.fsync(fd)
        # Only claim a usable count when the write was both durable AND
        # serialized by the lock. An unlocked write still updates the counter
        # (so the cadence is not lost) but must not open the rename gate.
        count = nxt if locked else None
    finally:
        os.close(fd)
except OSError:
    # Counter unavailable. Skip the rename rather than guessing a count: a
    # guessed one fires every prompt at the saturated history length.
    count = None

if count is not None and count % 20 == 0:
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
