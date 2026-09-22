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

  Resolve the real path before asking, so consent names the actual location.
  This must match the hook's own fallback exactly
  (`tmux-session-namer.py:70-73`): an empty `XDG_CACHE_HOME` counts as unset
  per the XDG spec, and a set-but-relative value is rejected too, since
  joining it would land under the current working directory rather than the
  user's home:

      python3 -I -S -c "import os; _xdg = os.environ.get('XDG_CACHE_HOME') or ''; _xdg = _xdg if os.path.isabs(_xdg) else os.path.expanduser('~/.cache'); print(os.path.join(_xdg, 'claude'))"
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

    cache="$(python3 -I -S -c "import os; _xdg = os.environ.get('XDG_CACHE_HOME') or ''; _xdg = _xdg if os.path.isabs(_xdg) else os.path.expanduser('~/.cache'); print(os.path.join(_xdg, 'claude'))")"
    rm -f "$cache"/prompts-*.txt "$cache"/count-*.txt

(The hook also keeps a `count-<session>.txt` alongside each history file — a
prompt counter, no prompt text — so remove both.)

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
# Fail fast. Without this, a failed mkdir or cp lets the run continue to patch
# settings.json and report success while the hook is missing or stale — the
# wiring would then point at a script that is not there.
set -e

mkdir -p ~/.claude/hooks

# Refuse to overwrite a symlinked hook. `cp` follows a symlink and writes
# through it to the LINK'S TARGET — a dotfiles-managed file, or someone's own
# custom hook pointed at from this path. Silently unlinking and replacing it
# (or backing it up and writing through it anyway) would clobber content this
# skill does not own and cannot restore. Abort and tell the user exactly what
# it points at so they can resolve it themselves.
if [ -L ~/.claude/hooks/tmux-session-namer.py ]; then
  target=$(readlink ~/.claude/hooks/tmux-session-namer.py)
  echo "ABORT: ~/.claude/hooks/tmux-session-namer.py is a symlink to $target"
  echo "Refusing to overwrite it — cp would write through the link and modify that target in place."
  echo "Resolve this yourself: either update $target directly, or remove the symlink and re-run this skill to install a regular file."
  exit 1
fi

# Check if already installed
if [ -f ~/.claude/hooks/tmux-session-namer.py ]; then
  if diff -q ~/.claude/hooks/tmux-session-namer.py configs/llm/tmux-session-namer.py > /dev/null; then
    # Still chmod: the repo copy is mode 100644, so an installed byte-identical
    # copy may not be executable, and the verification below would then abort an
    # install that is otherwise correct.
    chmod +x ~/.claude/hooks/tmux-session-namer.py
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

# Confirm the installed copy matches the repo version before anything wires it
# up. `set -e` catches a failing cp; it does not catch one that wrote nothing
# useful, and the settings patch below must not point at a stale script.
diff -q ~/.claude/hooks/tmux-session-namer.py configs/llm/tmux-session-namer.py > /dev/null \
  || { echo "ABORT: installed hook does not match configs/llm/tmux-session-namer.py"; exit 1; }
test -x ~/.claude/hooks/tmux-session-namer.py \
  || { echo "ABORT: installed hook is not executable"; exit 1; }
echo "Verified: installed hook matches the repo version and is executable"
```

## Step 3: Patch ~/.claude/settings.json

Read `~/.claude/settings.json`, check if the `UserPromptSubmit` hook is already present,
and add it if not. **Merge carefully — do not overwrite existing hooks.**

Use the Write/Edit tool to run this patch script, or execute it directly via Bash:

```bash
python3 -I -S - << 'PY'
import contextlib, json, os, re, shlex, shutil, stat, sys, tempfile, time

settings_path = os.path.expanduser("~/.claude/settings.json")
# Follow a symlink to its target before touching anything. os.replace() acts on
# the LINK path, so replacing a symlinked settings.json turns it into a regular
# file and leaves the real file (a dotfiles repo, typically) without the hook —
# while reporting success.
settings_path = os.path.realpath(settings_path)

# Orphaned .settings-*.tmp files older than this are certainly stale: no run of
# this script holds one open for anywhere near this long. Anything younger
# might belong to a concurrent installer that is still mid-write, so the sweep
# below must never touch it.
STALE_TMP_AGE_SECONDS = 300

try:
    import fcntl
except ImportError:  # nosec B110 - some filesystems/platforms cannot lock; see _locked() below
    fcntl = None


@contextlib.contextmanager
def _locked(path):
    """Hold an exclusive lock across the whole read-modify-write, sweep
    included, so two concurrent installers cannot interleave.

    Without this, two installs can each read the same settings.json, each
    compute a different append/upgrade, and the second save_settings()
    silently clobbers the first's change (lost update) — and the orphan sweep
    can unlink a temp file a concurrent run is still writing, so its later
    os.replace() fails with FileNotFoundError.

    If fcntl is unavailable (guarded above), prefer running unlocked over
    failing the install outright, but the caller must then skip the sweep —
    it is only safe to remove a stale temp file while holding this lock.
    """
    if fcntl is None:
        yield False
        return
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    lock_path = path + ".lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _sweep_stale_temp_files(directory):
    """Remove only .settings-*.tmp files old enough to be certainly orphaned.

    Must run only while holding the lock from _locked(): removing ANY
    .settings-*.tmp unconditionally (the earlier version of this sweep) can
    delete a concurrent invocation's still-live temp file, and its later
    os.replace() then fails because the source is gone.
    """
    now = time.time()
    for stale in os.listdir(directory):
        if not (stale.startswith(".settings-") and stale.endswith(".tmp")):
            continue
        candidate = os.path.join(directory, stale)
        try:
            age = now - os.stat(candidate).st_mtime
        except OSError:  # nosec B110 - vanished between listdir and stat; nothing to sweep
            continue
        if age < STALE_TMP_AGE_SECONDS:
            continue  # too young to be certainly stale — may be a live concurrent write
        try:
            os.unlink(candidate)
        except OSError:  # nosec B110 - best-effort sweep; never block the write
            pass


def save_settings(data, *, sweep):
    """Replace settings.json atomically, preserving its mode.

    `open(path, "w")` truncates the live file before writing a byte, so an
    interruption or a full disk mid-dump leaves the user's GLOBAL Claude
    settings empty or half-written — destroying every hook, permission and env
    var they have configured. Serialise to a temp file in the same directory
    (same filesystem, so os.replace is atomic), fsync it, then rename over the
    original — a crash at any point leaves the old file intact.

    Mirrors core.fileutil.atomic_write_json, inlined because this script runs
    standalone under `python3 -I -S` and cannot import repo modules.

    `sweep` is True only when the caller holds the exclusive lock — skip the
    sweep entirely when it does not, rather than sweeping unsafely.
    """
    directory = os.path.dirname(settings_path) or "."
    os.makedirs(directory, exist_ok=True)

    if sweep:
        _sweep_stale_temp_files(directory)

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
    dest = f"{settings_path}.bak.{time.strftime('%Y%m%d%H%M%S')}"
    shutil.copy2(settings_path, dest)
    return dest


def _read_settings():
    if not os.path.exists(settings_path):
        return {}
    if os.path.getsize(settings_path) == 0:
        return {}
    try:
        with open(settings_path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: {settings_path} contains invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)


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
#
# Match the exact script PATH as a whitespace-delimited token, never a bare
# substring. A substring test also matches an unrelated user hook such as
# `python3 ~/.claude/hooks/tmux-session-namer-custom.py`, and this loop
# REWRITES what it matches — so a loose test would silently destroy someone
# else's hook while claiming to have upgraded ours.
HOOK_PATH = "~/.claude/hooks/tmux-session-namer.py"


def _raw_token_blocks_expansion(raw_tok):
    """True if `raw_tok` quotes `$`/`~` in a way the shell would NOT expand.

    `raw_tok` must still carry its original quote characters (i.e. come from
    `shlex.shlex(..., posix=False)`, never `shlex.split`, which strips quotes
    before we get a chance to see them). The rule, walked char by char while
    tracking single/double-quote state (a backslash escapes the next char
    outside single quotes):

        - inside single quotes, the shell expands NEITHER `$name`/`${name}`
          NOR `~` — both are literal, so either one occurring there blocks
          expansion
        - inside double quotes, the shell DOES expand `$name`/`${name}` but
          NOT `~` — so only `~` there blocks expansion; `$HOME` in double
          quotes is real and must still match
        - unquoted, both expand normally and never block

    This asymmetry is why the token can't just be quote-stripped and expanded
    unconditionally: whether `$HOME` and `~` are live depends on which quote
    style (if any) wrapped them, and `shlex.split`'s quote removal throws that
    context away before we can tell.
    """
    in_single = False
    in_double = False
    i = 0
    n = len(raw_tok)
    while i < n:
        ch = raw_tok[i]
        if ch == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue
        if ch == "\\" and not in_single and i + 1 < n:
            i += 2  # escaped char is literal; irrelevant to $/~ blocking
            continue
        if ch == "$" and in_single:
            return True
        if ch == "~" and (in_single or in_double):
            return True
        i += 1
    return False


def _strip_quotes(raw_tok):
    """Remove the quote characters `shlex.shlex(posix=False)` left in place,
    without touching anything else. Good enough for our narrow token shapes
    (a single quoted run, or none) — not a general shell-quote remover."""
    return raw_tok.replace("'", "").replace('"', "")


def _resolve_script_token(raw_tok, home):
    """Expand $HOME / ${HOME} / ~ in a single raw (quote-preserved) token;
    return None if the result is not an absolute path (a bare relative path
    cannot be shown to be ours: Claude Code gives the hook no guaranteed
    working directory) or if the token's own quoting means the shell would
    never have expanded it in the first place (see `_raw_token_blocks_expansion`)."""
    if _raw_token_blocks_expansion(raw_tok):
        return None
    tok = _strip_quotes(raw_tok)
    path = tok.replace("${HOME}", home).replace("$HOME", home)
    if path.startswith("~"):
        path = home + path[1:]
    if not os.path.isabs(path):
        return None
    return os.path.normpath(path)


# Interpreter options that are terminal for our purposes: once python sees
# one of these, it runs code/a module, never a script file, so no operand
# after it can be "our path" running as a script. Checked per-letter so a
# combined cluster like `-Ic` is still caught.
_TERMINAL_OPT_LETTERS = frozenset("cm")

# Short options that consume the NEXT token as their own argument (the next
# token is never the script operand). Long forms that do the same, unless
# `=`-joined with their value.
_ARG_TAKING_SHORT = frozenset("WX")
_ARG_TAKING_LONG = frozenset({"--check-hash-based-pycs"})

# Short options that take no argument and may appear combined, e.g. `-IS`.
_NOARG_SHORT = frozenset("ISEubBdOqvstxP")


# The exact trailing tokens the installer's own canonical wiring leaves after
# the script operand. Only this exact sequence is tolerated after our path —
# anything else after it is a chained user command that a rewrite would
# silently delete, so it must not match. See `_python_script_operand`.
_CANONICAL_SUFFIX = ("2>/dev/null", "||", "true")


def _python_script_operand(cmd):
    """Return (raw_operand_token, trailing_tokens) for a python invocation in
    `cmd`, or (None, None) if `cmd` does not run a script this way.

    A path token appearing ANYWHERE in a command is not evidence the command
    RUNS it — `echo <path>`, `cat <path>` and `grep <path> file` all contain
    the exact path as a token without executing it. The only safe signal is
    the path being the script argument handed to a python interpreter, so
    this walks the tokens instead of scanning for a matching one:

        - skip a leading `env` (a common shebang-less prefix)
        - the next token's basename must look like python: `python`,
          `python3`, `python3.11`, etc.
        - walk interpreter options by ARITY, not by "starts with -":
            - `-c` / `-m` (alone or in a combined cluster like `-Ic`) mean
              python is running code or a module, never a script file —
              return None immediately, regardless of what follows
            - `-W`, `-X`, `--check-hash-based-pycs` consume the NEXT token
              as their own argument (unless `=`-joined for the long form),
              so that token is never the script operand
            - `-I -S -E -u -b -B -d -O -q -v -s -t -x -P` take no argument
              and may appear combined (`-IS`)
        - the first remaining non-flag token is the script operand; every
          token after it is returned as `trailing_tokens` so the caller can
          reject a chain (see `is_managed_hook`)

    Tokenizes with `posix=False` so returned tokens keep their original quote
    characters — the caller (`_resolve_script_token`) needs that to tell a
    live `$HOME`/`~` from a quoted, shell-literal one; `shlex.split` throws
    that distinction away before we could ever see it. Falls back to
    str.split() if shlex chokes on unbalanced quotes (best-effort — a command
    that doesn't even tokenise cleanly gets no match).

    Imports shlex/re locally: this function is extracted and exec'd in
    isolation by tests/infra/test_tmux_session_namer.py, which only injects
    `os` into that namespace, so a module-level import would NameError there
    even though the full script (which does import them at the top) never
    hits this path.
    """
    import re
    import shlex

    try:
        lexer = shlex.shlex(cmd, posix=False, punctuation_chars=False)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = cmd.split()

    i = 0
    if i < len(tokens) and tokens[i] == "env":
        i += 1
    if i >= len(tokens):
        return None, None
    interp = os.path.basename(tokens[i])
    if not re.match(r"^python3?(\.\d+)?$", interp):
        return None, None
    i += 1
    while i < len(tokens) and tokens[i].startswith("-") and tokens[i] != "-":
        tok = tokens[i]
        long_name = tok.split("=", 1)[0]
        if long_name in _ARG_TAKING_LONG:
            if "=" not in tok:
                i += 1
            i += 1
            continue
        letters = tok[1:]
        if any(ch in _TERMINAL_OPT_LETTERS for ch in letters):
            return None, None
        if len(letters) == 1 and letters in _ARG_TAKING_SHORT:
            i += 2
            continue
        if letters and all(ch in _NOARG_SHORT for ch in letters):
            i += 1
            continue
        # Unrecognized option shape: don't guess at its arity — bail rather
        # than risk treating its argument as the script operand.
        return None, None
    if i >= len(tokens):
        return None, None
    return tokens[i], tokens[i + 1 :]


def is_managed_hook(cmd):
    """True only for a command that RUNS our installed script AND does
    nothing else a rewrite would silently discard.

    This loop REWRITES whatever it matches, so both error directions are
    damaging: a false positive replaces someone else's hook or destroys a
    chained command, a false negative leaves a stale entry wired and appends
    a duplicate beside it. Five earlier versions each fixed one direction and
    broke another —

        substring 'tmux-session-namer' in cmd   also matched ...-custom.py
        token in (HOOK_PATH, expanduser(...))   missed $HOME and absolute forms
        basename(token) == basename(target)     matched /tmp/tmux-session-namer.py
        any token resolving to our path         matched `echo <path>`, `cat <path>`
        expand $HOME/~ unconditionally           matched a single-quoted, shell-literal path
        accept the operand regardless of what follows   claimed `... && echo audit`,
                                                          which a rewrite would delete

    — so this only accepts the path when it is the script OPERAND of a
    recognized python invocation (see `_python_script_operand`), resolves
    that operand to an absolute path with quoting taken into account (see
    `_resolve_script_token`), and — since the upgrade below replaces the
    WHOLE command string — requires that nothing follows the operand except
    either nothing at all, or exactly the `2>/dev/null || true` suffix this
    installer itself writes (`_CANONICAL_SUFFIX`). Any other trailing
    material (`&& echo audit`, `; other-hook`, `|| logger ...`) means the
    command does more than run our hook, and a rewrite would silently drop
    that part — so it is rejected rather than claimed. When in doubt this
    returns False: a missed upgrade only appends a duplicate (caught by
    Step 5's count check), while a wrong match destroys someone's command.

    Covered by tests/infra/test_tmux_session_namer.py, which tables the
    spellings that must match against the same-named files, the quoted
    forms, and the chained commands, that must not.
    """
    home = os.path.expanduser("~")
    target = os.path.normpath(
        os.path.join(home, ".claude", "hooks", "tmux-session-namer.py")
    )
    operand, trailing = _python_script_operand(cmd)
    if operand is None:
        return False
    if trailing and tuple(trailing) != _CANONICAL_SUFFIX:
        return False
    path = _resolve_script_token(operand, home)
    return path is not None and path == target


upgraded = False
removed_count = 0

# Hold the lock across the ENTIRE read-modify-write, sweep included. Locking
# only around save_settings() would still let two installers both read the
# same settings, both compute an append, and the second write silently
# overwrite the first's change (lost update) — the read has to be inside the
# critical section too.
with _locked(settings_path) as have_lock:
    settings = _read_settings()
    hooks = settings.setdefault("hooks", {})
    existing = hooks.get("UserPromptSubmit", [])

    # Find every managed entry first, keep exactly ONE, and drop the rest.
    # An earlier installer version could append a second managed hook via an
    # exact-string comparison that missed the first; if both survive, the
    # namer runs twice per prompt and the duplicate is only noticed by Step 5
    # AFTER it has already been (re-)persisted. Collect matches before
    # mutating anything, so the keep/remove decision is made on a stable view
    # rather than on a list this same loop is editing.
    matches = [
        (entry, h)
        for entry in existing
        for h in entry.get("hooks", [])
        if is_managed_hook(h.get("command", ""))
    ]

    if matches:
        keep_entry, keep_hook = matches[0]
        if keep_hook.get("command", "") != hook_command:
            upgraded = True
        keep_hook["command"] = hook_command
        for entry, h in matches[1:]:
            entry["hooks"].remove(h)
            removed_count += 1
        # Drop any entry left with no hooks at all — only ours removed, never
        # a sibling command that happened to share the entry.
        existing[:] = [e for e in existing if e.get("hooks")]
        hooks["UserPromptSubmit"] = existing
        backup = backup_settings()
        save_settings(settings, sweep=have_lock)
        if removed_count:
            print(
                f"Removed {removed_count} duplicate managed hook "
                f"{'entry' if removed_count == 1 else 'entries'}; kept one, "
                "wired to the isolated form"
            )
        elif upgraded:
            print("Upgraded the existing UserPromptSubmit hook to the isolated form")
        else:
            print("UserPromptSubmit hook already present and isolated — skipping")
        if backup:
            print(f"Previous settings saved to {backup}")
    else:
        existing.append({
            "hooks": [{"type": "command", "async": True, "command": hook_command}]
        })
        hooks["UserPromptSubmit"] = existing
        backup = backup_settings()
        save_settings(settings, sweep=have_lock)
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
import json, os, re, shlex, sys
s = json.load(open(os.path.expanduser('~/.claude/settings.json')))
hooks = s.get('hooks', {}).get('UserPromptSubmit', [])
cmds = [h.get('command','') for e in hooks for h in e.get('hooks',[])]
# Same rule the patch script's is_managed_hook uses — must not diverge from
# it. A path token appearing anywhere in the command is not evidence the
# command RUNS it ('echo <path>', 'cat <path>' both contain the token without
# executing it), so only accept the path as the script operand of a
# recognized python invocation, with nothing after it except our own
# canonical '2>/dev/null || true' suffix — anything else trailing (a user's
# '&& echo audit', '; other-hook', ...) is a chain a rewrite would silently
# destroy, so it must not count as ours either.
_home = os.path.expanduser('~')
_target = os.path.normpath(os.path.join(_home, '.claude', 'hooks', 'tmux-session-namer.py'))
_CANONICAL_SUFFIX = ('2>/dev/null', '||', 'true')

# Same arity table as the patch script's is_managed_hook / _python_script_operand
# — must not diverge from it. -c/-m are terminal (python runs code/a module, not
# a script); -W/-X/--check-hash-based-pycs consume the NEXT token as their own
# argument; the rest are argument-free and may appear combined (-IS).
_TERMINAL_OPT_LETTERS = frozenset('cm')
_ARG_TAKING_SHORT = frozenset('WX')
_ARG_TAKING_LONG = frozenset({'--check-hash-based-pycs'})
_NOARG_SHORT = frozenset('ISEubBdOqvstxP')


def _script_operand(cmd):
    # posix=False keeps each token's original quote characters — required so
    # _is_ours below can tell a live \$HOME/~ from one quoted literal by the
    # shell, which shlex.split's quote removal would otherwise hide.
    try:
        lexer = shlex.shlex(cmd, posix=False, punctuation_chars=False)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = cmd.split()
    i = 0
    if i < len(tokens) and tokens[i] == 'env':
        i += 1
    if i >= len(tokens):
        return None, None
    if not re.match(r'^python3?(\.\d+)?\$', os.path.basename(tokens[i])):
        return None, None
    i += 1
    while i < len(tokens) and tokens[i].startswith('-') and tokens[i] != '-':
        tok = tokens[i]
        long_name = tok.split('=', 1)[0]
        if long_name in _ARG_TAKING_LONG:
            if '=' not in tok:
                i += 1
            i += 1
            continue
        letters = tok[1:]
        if any(ch in _TERMINAL_OPT_LETTERS for ch in letters):
            return None, None
        if len(letters) == 1 and letters in _ARG_TAKING_SHORT:
            i += 2
            continue
        if letters and all(ch in _NOARG_SHORT for ch in letters):
            i += 1
            continue
        return None, None
    if i >= len(tokens):
        return None, None
    return tokens[i], tokens[i + 1:]


def _blocks_expansion(raw_tok):
    # Same quoting rule as the patch script's _raw_token_blocks_expansion:
    # single quotes block both \$name and ~; double quotes block only ~
    # (\$name still expands inside double quotes).
    in_single = False
    in_double = False
    i = 0
    n = len(raw_tok)
    while i < n:
        ch = raw_tok[i]
        if ch == chr(39) and not in_double:
            in_single = not in_single
            i += 1
            continue
        if ch == chr(34) and not in_single:
            in_double = not in_double
            i += 1
            continue
        if ch == chr(92) and not in_single and i + 1 < n:
            i += 2
            continue
        if ch == chr(36) and in_single:
            return True
        if ch == chr(126) and (in_single or in_double):
            return True
        i += 1
    return False


def _is_ours(cmd):
    tok, trailing = _script_operand(cmd)
    if tok is None:
        return False
    if trailing and tuple(trailing) != _CANONICAL_SUFFIX:
        return False
    if _blocks_expansion(tok):
        return False
    p = tok.replace(chr(39), '').replace(chr(34), '')
    p = p.replace(chr(36) + '{HOME}', _home).replace(chr(36) + 'HOME', _home)
    if p.startswith('~'):
        p = _home + p[1:]
    return os.path.isabs(p) and os.path.normpath(p) == _target


namer = [c for c in cmds if _is_ours(c)]

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
count for this session reaches a multiple of 20. The cadence comes from a
monotonic counter in `count-<session>.txt`, not from the prompt-history line
count — the history is trimmed to 200 lines, and deriving the cadence from that
made the rename fire on every prompt once the file saturated.

The counter is incremented under an `flock`, because the hook is registered
`async: true` and two invocations can overlap. If the counter cannot be written,
the hook skips the rename for that prompt rather than guessing a count — a
guessed one lands on 200 at the saturated history length and fires every time.
So a session whose cache directory is read-only gets no automatic renaming, and
no surprise `claude -p` calls either.

It records the first 120 characters of each prompt to
`<resolved cache dir>/prompts-*.txt` — report the path you resolved in Step 0,
not a hard-coded `~/.cache`, since the hook honours `XDG_CACHE_HOME` — and sends
the last 20 to `claude -p` on each 20th prompt. To undo: remove the
`UserPromptSubmit` entry from `~/.claude/settings.json` and delete that
directory's `prompts-*.txt`.
```
