# Claude Code guard hooks

Three scripts: two PreToolUse guards that block access to this repo's credential
files and to destructive commands, plus a statusline renderer.

## Why hooks and not just `permissions.deny`

`permissions.deny` rules bind **tools**, not the shell.

```
Read(**/credentials.ini)     blocks the Read tool
cat ~/.config/credentials.ini    is a Bash call — the deny rule never sees it
```

The same gap exists on the write side: `Edit(**/credentials.ini)` says nothing about
`echo x > ~/.config/credentials.ini`. Deny rules are a routing decision inside the
harness; the shell is a different door. These hooks are the enforcing layer on that
door — and unlike a deny rule, which a project-level settings file can override, a
PreToolUse hook exiting 2 cannot be overridden from inside the session.

Use both. The deny rules give a cheap early exit; the hooks are what actually holds.

## The scripts

### `block-destructive-bash.sh` — PreToolUse, matcher `Bash`

Reads the payload on stdin, inspects `.tool_input.command`, and blocks:

1. **Destructive commands** — `DROP TABLE`, `DROP DATABASE`, `TRUNCATE`,
   `git push --force`/`-f`, `git reset --hard`, and `rm` with recursive+force
   pointed at a protected path.
2. **Shell reads of credential files** via
   `cat bat less more head tail nl xxd od strings grep rg ag awk sed jq cut sort uniq`,
   including inside `$(...)` and backticks.
3. **Shell writes** via `>`, `>|`, `2>` and
   `tee cp mv install dd truncate ln`. Appending (`>>`, `tee -a`, `tee --append`)
   is deliberately allowed — that is how a new profile section gets added to
   `credentials.ini` without destroying the existing ones.

### `block-protected-paths.sh` — PreToolUse, matcher `Write|Edit`

Reads `.tool_input.file_path` and blocks writes to the same credential set, plus
`.git/` and `*.pem`. Substring matching, case-sensitive.

### Protected files

Resolved from `src/core/constants.py` (`_config_roots()` → `$CREDENTIALS`'s
directory, `$XDG_CONFIG_HOME`, then `~/.config`) and `src/mail/config_resolver.py`:

| File | Holds |
|---|---|
| `credentials.ini` | every profile section — hand-maintained, nothing regenerates it |
| `credentials.json` | Gmail OAuth client secret |
| `token.json` | Gmail token |
| `outlook_token.json` | Outlook refresh token |
| `msal_flow.json` | in-flight MSAL device-code flow |

Plus universal secrets: `.ssh/`, `.gnupg/`, `.aws/credentials`, `.npmrc`, `id_rsa`,
`id_ed25519`, `.env` and `.env.*`.

Checked-in templates — `.env.example`, `.env.template`, `.env.sample` — are **not**
blocked. They carry placeholders and exist to be read and edited.

Filenames are matched bare rather than as full paths, because the directory varies
with `$XDG_CONFIG_HOME` and `$CREDENTIALS`, and a copy of `credentials.ini` sitting
in `/tmp` is exactly as sensitive as the original.

### `statusline.sh`

Renders one line:

```
[agent|wt:name] branch │ dir │ ██████░░░░ 63% │ +120/-34 │ Opus 5 │ $1.23 │ 1h15m (1m35s api)
```

Context bar is green under 50%, yellow at 50%, red at 80%. When
`.context_window.used_percentage` is absent the bar renders dim `··········` and
`--` rather than a confident green `0%` — see "Deviations" below.

The agent/worktree prefix matters here specifically: sessions run under
`.claude/worktrees/` by default, subagents get their own isolated worktrees, and the
directory name alone does not tell you which branch's worktree you are in.

## Contract

Both guards: **exit 2 blocks** the tool call and shows stderr to Claude, **exit 0
allows**. Both run under `set -u` and require `jq`.

A payload that cannot be parsed **fails closed** (exit 2). An unparseable payload
means the hook cannot see what it is approving, and a hook that approves blind is
worse than no hook — the failure of the inspecting step must not become an ALLOW.

## Running the tests

```bash
bash .claude/hooks/tests/block-destructive-bash.test.sh
bash .claude/hooks/tests/block-protected-paths.test.sh
```

Exit 0 = all pass, 1 = any failure. Each prints `ok`/`FAIL` per case and a final
`ALL PASS`. Pass a path as argument 1 to test an installed copy instead of the
repo one:

```bash
bash .claude/hooks/tests/block-destructive-bash.test.sh ~/.claude/hooks/block-destructive-bash.sh
```

**The test cases must stay in these files.** The hooks block their own test payloads
— an agent cannot type `echo "[mail.x]" > ~/.config/credentials.ini` into a Bash call
to check the hook, because the hook intercepts that call first. The cases have to be
read from disk and run as a unit. Inlining them back into ad-hoc commands makes a
working hook look broken.

## Wiring into settings.json

Not wired automatically — apply this yourself. Copy the scripts to `~/.claude/hooks/`
for global coverage, or reference them in-repo for this project only.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR/.claude/hooks/block-destructive-bash.sh\"" }
        ]
      },
      {
        "matcher": "Write|Edit",
        "hooks": [
          { "type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR/.claude/hooks/block-protected-paths.sh\"" }
        ]
      }
    ]
  },
  "statusLine": {
    "type": "command",
    "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/statusline.sh",
    "padding": 0
  }
}
```

For a global install, copy to `~/.claude/hooks/` and use `$HOME/.claude/hooks/...`
paths instead. `chmod +x` the scripts if you invoke them directly rather than
through `bash`.

The repo's existing `.claude/settings.json` already defines `SessionStart` and
`WorktreeCreate` hooks — merge the `PreToolUse` block in alongside them rather than
replacing the file.

Matching deny rules to pair with the hooks:

```json
"deny": [
  "Read(**/credentials.ini)",
  "Read(**/credentials.json)",
  "Read(**/token.json)",
  "Read(**/outlook_token.json)",
  "Read(**/msal_flow.json)",
  "Read(~/.ssh/**)",
  "Read(~/.gnupg/**)",
  "Read(~/.aws/**)",
  "Edit(**/credentials.ini)",
  "Edit(**/credentials.json)",
  "Edit(**/token.json)",
  "Edit(**/outlook_token.json)",
  "Edit(**/msal_flow.json)"
]
```

## Deviations from the reference implementation

These are the places this port intentionally departs from the original, and why.

**`rm -rf` matches the resolved target, not the flag spelling.** The original
grep'd the literal string `"rm -rf /"`, which matches *any* absolute path —
`rm -rf /Users/me/scratch` was blocked as if it were root deletion. The original's
own comment records this firing twice on legitimate cleanup. It also let every
equivalent spelling through: `rm -fr /`, `rm --recursive --force /`, `rm -rf //`.

This port normalizes the flags (bundled short flags checked characterwise, so `-rvf`
and `-Rf` count), extracts the actual operands, expands `~`/`$HOME`, collapses
repeated slashes, and compares against a protected-prefix list: `/`, `$HOME`,
`/Users`, `/etc`, `/usr`, `/var`, `/System`, `/Library`, `/opt`, `/bin`, `/sbin`,
`/Applications`. Paths under a temp dir or under the repo checkout are allowed, and
every `rm` in a compound command is checked, not just the first. A path is dangerous
because of where it points, not how the flags were typed.

**Fail closed on unparseable payloads.** The original's `CMD=$(jq -r ...)` yielded an
empty string when jq failed, every pattern then missed, and the hook exited 0 — a
spurious ALLOW produced by the failure of the very thing meant to inspect the
command. Both guards now use `jq -er` and exit 2 when the field is missing, null, or
the payload is not JSON.

**Statusline shows unknown as unknown.** The original used
`(.context_window.used_percentage // 0)`, so an absent `.context_window` rendered a
full green bar reading `0%` — indistinguishable from a genuinely empty context
window. That is the worst kind of wrong reading: confident, plausible, and pointing
the opposite direction from the truth. A session at 85% looked like a session at 0%,
which is exactly when the number matters most.

**Template carve-out extended to the Write/Edit hook.** The original applied the
`.env.example`/`.template`/`.sample` exclusion only on the Bash read path, so editing
a checked-in template was blocked by the path hook. Both hooks now share the carve-out.

**Repo-specific credential set.** The original guarded a `.env` /
Google-Workspace stack (`secrets/`, `credentials*` as a bare substring). Those were
replaced with the five files this repo actually resolves. The original's bare
`credentials` substring was dropped in favour of exact filenames — it matched
`credentials.md` and any commit message mentioning the word, which is noise rather
than safety.

**Dropped `block-risky-gws.sh`.** Google-Workspace-CLI specific; no equivalent
surface in this repo.
