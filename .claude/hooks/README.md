# Claude Code guard hooks

Three scripts: two PreToolUse guards that block access to this repo's credential
files and to destructive commands, plus a statusline renderer.

## What these hooks are, and what they are not

**These hooks prevent accidents.** A mistyped `rm -rf /`, an agent reflexively running
`cat ~/.config/credentials.ini` because reading a config file is the obvious next step,
a `git reset --hard` that discards an afternoon of uncommitted work. That is the whole
promise, and within it they work well.

**They are not a security boundary.** They do not resist a determined bypass, and they
should not be described, deployed, or relied on as though they do.

The reason is structural, not a backlog item. The Bash guard inspects a command by
pattern-matching the command *string*. Bash's grammar is richer than any matcher: the
shell expands, quotes, escapes, splits and substitutes before a single byte reaches the
program, and much of what it will eventually run does not exist as text at the moment
the hook reads it. Concretely, all of these reach the shell:

```bash
rm${IFS}-rf /              # $IFS supplies the whitespace; there is no literal "rm -rf /"
r\m -rf /                  # backslash inside the word: bash reads "rm", the regex does not
/bin/sh -c "$SCRIPT"       # path-qualified, so the nested-shell check's command-boundary
                           # match misses it -- and the payload does not exist as text
                           # until $SCRIPT expands anyway
cat /tmp/credentials'.'ini # quote-concatenation splits the filename mid-token
rm $FLAGS /                # the flags arrive from a variable, so recursive+force is invisible
cat /tmp/notes             # ...where /tmp/notes was symlinked to credentials.ini in an
                           # EARLIER call. The operand names no protected path, and the
                           # hook sees one command at a time.
```

Four rounds of adversarial review found sixty-eight distinct holes of this shape, and
each round's fixes exposed the next round's. A fifth round would find more. The pattern
matcher is an approximation of a shell parser, and the gap between the two is where all
of these live. Extending the patterns narrows the gap; it does not close it.

**So: anything that genuinely must not happen needs enforcement somewhere the shell
cannot reach.** Filesystem permissions (`chmod 600`, an unreadable-by-this-user file), a
sandbox or container that does not have the credential mounted, or — best — credentials
that are not on disk in the first place, held in a keychain or fetched per-use from a
secrets manager. A hook that inspects a string is the wrong layer for a guarantee.

See [Known gaps (won't fix)](#known-gaps-wont-fix) for the specific classes left open
and why each one stays that way.

## Why hooks and not just `permissions.deny`

`permissions.deny` rules bind **tools**, not the shell.

```
Read(**/credentials.ini)     blocks the Read tool
cat ~/.config/credentials.ini    is a Bash call — the deny rule never sees it
```

The same gap exists on the write side: `Edit(**/credentials.ini)` says nothing about
`echo x > ~/.config/credentials.ini`. Deny rules are a routing decision inside the
harness; the shell is a different door — and these hooks watch that door.

A note on what "cannot be overridden" means here, because it is easy to overread. The
*mechanism* is robust: a PreToolUse hook exiting 2 blocks the call, and unlike a deny
rule, a project-level settings file cannot switch it off. The *coverage* is not: the hook
only blocks what it recognizes, and the section above is about everything it does not
recognize. An unbypassable mechanism wrapped around an approximate matcher is still an
approximate guard.

Use both. The deny rules give a cheap early exit and cover the `Read` tool, which neither
hook matches; the hooks cover the shell.

## Known gaps (won't fix)

These are open, and closing them is not planned. They are listed so the shape of what is
uncovered is legible — a reader should be able to see the boundary, not discover it.

They are not a TODO list. Each is a consequence of the design's limit: a pattern matcher
reading a command string cannot evaluate what the shell will do to that string. Fixing
them individually means writing a bash parser, and four rounds of that produced sixty-eight
findings and no convergence. The line is drawn here deliberately.

| Gap | Example | Why it stays open |
|---|---|---|
| Shell-synthesized whitespace | `rm${IFS}-rf /` | The token separator comes from a variable, so no literal `rm -rf` exists in the string to match. |
| Escaped or quoted command names | `r\m -rf /`, `r"m" -rf /` | Bash strips the escape or quote during word expansion and runs `rm`. Un-escaping the whole command first would corrupt legitimately quoted operands. |
| Quote-concatenated paths | `cat /tmp/credentials'.'ini` | The filename is assembled from adjacent quoted spans. The tokenizer treats quotes as boundaries, so no single token spells `credentials.ini`. |
| Variable-supplied commands and flags | `R=rm; $R -rf /`, `rm $FLAGS /` | The command word or the recursive+force flags do not exist until expansion. The hook cannot see a value it does not evaluate. |
| Qualified nested-shell evaluators | `/bin/sh -c "$SCRIPT"` | A *bare* `sh -c` / `eval` fails closed, but the nested-shell check anchors the shell name at a command boundary, so a `/bin/`-qualified spelling does not match it. Widening that pattern to accept any path prefix is a one-line change that also matches far more than intended; the inner payload is unreadable either way when it comes from a variable. |
| Non-shell evaluators | `python3 -c "…"`, `perl -e`, `node -e` | Every interpreter on the box can spawn a subprocess. Blocking them all would block ordinary work; enumerating them is exactly the command-word list this hook was rewritten to abolish. |
| Symlinked operands for reads and writes | `cat /tmp/notes` after `ln -s …/credentials.ini /tmp/notes` | The operand names no protected path, and the link was created in a *previous* tool call the hook never sees. `rm` targets do resolve symlinks; ordinary read/write operands do not. |
| `..` resolved before symlinks, not with them | `a/../b` where `a` is a link | Path normalization is textual and runs first, so it can disagree with what the kernel resolves. Resolving against the live filesystem instead reintroduces the empty-result hole textual resolution was written to avoid. |
| `TMPDIR` pointing somewhere unusual | `TMPDIR=/some/dir` in the environment | The scratch carve-out honours `$TMPDIR`, which the hook inherits rather than validates. A caller who controls the hook's environment influences which paths count as scratch. |
| Unquoted-token glob expansion | `cat *.ini`, `rm -rf *` | What a glob matches is decided by the filesystem at run time. Globs pointed *into* a known credential directory are blocked; a bare glob in the working directory is too common in legitimate use to refuse. |

Two structural limits sit underneath the table and are worth stating plainly:

- **The hook sees one command at a time.** It has no memory of previous tool calls, so
  any two-step setup — create a link, write a script, export a variable, then use it — is
  invisible by construction.
- **The hook cannot run the shell.** Every expansion it does perform (`~`, `$HOME`, `.`,
  `..`) is a textual imitation, and imitations diverge at the edges.

## The scripts

### `block-destructive-bash.sh` — PreToolUse, matcher `Bash`

Reads the payload on stdin, inspects `.tool_input.command`, and blocks:

1. **Destructive commands** — `DROP TABLE`, `DROP DATABASE`, `TRUNCATE`,
   `git push --force`/`-f`, `git reset --hard`, and `rm` with recursive+force
   pointed at a protected path.
2. **Any command that names a protected path as an operand** — reads, writes,
   deletes, and copies alike, regardless of which command word precedes the path.
3. **Globs and unresolvable expansions** pointed into a credential-bearing directory.

Appending to `credentials.ini` (`>>`, `tee -a`, `tee --append`) is the one carve-out.

#### Operands, not command words

The check keys off the **path**, not the command. An earlier version paired a fixed
reader list against a filename in one regex —
`(cat|less|grep|…)[^|;&]*credentials\.ini` — which has two holes that cannot be
closed by extending the list:

- **The list can never be complete.** `base64 ~/.config/credentials.ini` discloses the
  file as thoroughly as `cat` does, and so does
  `python3 -c 'print(open("…credentials.ini").read())'`. Every binary on the box is
  another entry someone has to remember to add.
- **The spelling has to match.** `/bin/cat credentials.ini` and `\cat credentials.ini`
  both run cat; neither matches a bare `cat` anchored at a command boundary.

So any bare mention of a protected path as an operand blocks. The cost is that
`git commit -m "docs: describe credentials.ini setup"` is blocked too — see
[Over-blocking is deliberate](#over-blocking-is-deliberate).

### `block-protected-paths.sh` — PreToolUse, matcher `Write|Edit`

Reads `.tool_input.file_path` and blocks writes to the same credential set, plus
`.git/` and key material. Substring matching, case-sensitive.

Protected **directory** segments (`.ssh/`, `.gnupg/`, `.aws/`, `.git/`) are checked
**before** the template carve-out. A filename that looks like a template must never
vouch for the directory it sits in — `.ssh/.env.example` is a write into `.ssh/`.

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

Plus universal secrets: `.ssh`, `.gnupg`, `.aws/credentials`, `.npmrc`, `id_rsa`,
`id_ed25519`, the `.env` family, and key material `.pem`, `.p8`, `.p12`.

Directory names match at a **directory boundary** — a following `/` *or end of
string*. Spelling them `\.ssh/` with a required trailing slash meant the directory
itself never matched its own pattern, because path normalization strips exactly that
slash before comparing: `rm -rf /home/alice/.ssh` fell through to the "under some
home, more than one level deep" allow branch and deleted another account's key store.

The `.env` family is `.env`, `.env.<suffix>`, `.envrc`, and the dash/underscore
spellings `.env-production` / `.env_local`. `.envrc` is direnv's file and routinely
holds exported API keys. Both hooks accept the same set: when the Bash side matched
only `.env` and dot-suffixes, a file the Write tool refused to create could still be
read with `cat`.

Naming a protected **directory** blocks too, not just a file inside one. A directory
operand carries no filename to match, so `cp -r ~/.config /tmp` and
`tar czf /tmp/x.tgz ~/.ssh` — which copy every credential and key at once — matched
nothing at all. Bare `~`, `$HOME`, and `$XDG_CONFIG_HOME` count as protected
directories for the same reason. The cost is that `ls -la ~/.config` is now blocked;
narrowing the rule to permit it would require a list of safe command words, which is
the construct [Operands, not command words](#operands-not-command-words) exists to
remove.

`.p8` and `.p12` are not generic additions — this repo uses both. `apple_music` loads
a MusicKit private key as `.p8`, and `phone` resolves a device supervision identity as
`.p12`. A leaked `.p8` signs Apple Music API tokens; a leaked `.p12` can re-supervise a
device.

Checked-in templates — `.env.example`, `.env.template`, `.env.sample` — are **not**
blocked. The exemption matches the **exact basename**: those three names and nothing
else. A path merely *containing* or *ending in* one of them is a real config file, not a
template, and stays blocked. So `.env.example` and `backend/.env.template` are readable,
while `/tmp/client.env.example.bak`, `.env.example.bak`, `foo.env.example` and
`prod.env.sample` are not.

Two earlier versions were looser, in the same direction:

- A substring scrub deleted `.env.example` from the whole command before matching, so
  `cat /tmp/client.env.example.bak` became `cat /tmp/client.bak` — a real secret file,
  invisible to every pattern.
- A `*.env.example` wildcard then exempted any basename *ending* in a template name,
  while this section and the code comments both already said "exact". A secret only had
  to be named `prod.env.sample` to opt into the carve-out, which is an exemption the file
  being guarded gets to choose for itself.

Both hooks now carry the same three-name list. They are kept in sync deliberately: the
two halves disagreeing about what a template is, is how a file one door refuses becomes
reachable through the other.

Filenames are matched bare rather than as full paths, because the directory varies
with `$XDG_CONFIG_HOME` and `$CREDENTIALS`, and a copy of `credentials.ini` sitting
in `/tmp` is exactly as sensitive as the original.

### Configured credential paths

**The guards match filenames, not the live configuration.** This is a deliberate
constraint, and it has a real edge that you should know about.

`src/core/constants.py` accepts `$CREDENTIALS` as a **full file path**, so the active
credential store can be named anything:

```bash
CREDENTIALS=/tmp/my-secrets.ini ./bin/mail labels sync
```

A filename-matching hook cannot see that `/tmp/my-secrets.ini` is a credential file.
Likewise, a profile in `credentials.ini` can point `credentials`, `token`, or
`outlook_token` at an arbitrarily named file.

**The choice made here: constrain and document, rather than resolve at runtime.**
Deriving the active paths would mean the hook parsing `credentials.ini` on every Bash
call — reading the very file it exists to protect, on the hot path of every tool call,
and failing open whenever that parse fails. That trades a narrow gap for a broader one.

Instead the hook does two things:

1. **Blocks the variable names outright.** `$CREDENTIALS`, `$OUTLOOK_TOKEN`,
   `$GOOGLE_APPLICATION_CREDENTIALS`, `$GMAIL_TOKEN`, and `$MSAL_FLOW` are blocked
   wherever they appear, with no path-shape requirement — the variable *is* the path,
   so `cat $CREDENTIALS` has no `/` to key off.
2. **Blocks unresolvable expansions** into `$XDG_CONFIG_HOME`, `.config`, `.ssh`,
   `.gnupg`, `.aws`, `.claude`, and `/etc`.

**What this means for you:** keep credential files under a config directory and use
the standard filenames. A credential file with a custom name in an unprotected
directory — `/opt/data/my-secrets.ini` — is **not** covered by these hooks. If you
must use one, add its basename to `DB_SECRET_FILES` in `block-destructive-bash.sh` and
to `PATTERNS` in `block-protected-paths.sh`.

### The append carve-out

`>>` and `tee -a` onto `credentials.ini` are allowed. That is how a new profile
section gets added without destroying the existing ones, and blocking it would
contradict CLAUDE.md's "Never overwrite `~/.config/credentials.ini`" — a rule about
truncation, whose sanctioned alternative is appending.

The carve-out is **scoped to `credentials.ini` and nothing else.** It is checked on the
basename, and it exempts only that one token; every other path in the same command is
still checked. Appending to a token file corrupts the JSON and invalidates the session;
appending to `id_rsa` corrupts a private key; `echo x >> .env` extends a secret file
outright. None of those have the justification that earned `credentials.ini` its
exemption.

### The guards protect themselves

`.claude/hooks/` and `.claude/settings*.json` are blocked by **both** hooks, for
writes and for shell redirects alike.

This is the bootstrap case. Nothing else in either file matters if the file itself is
writable: rewriting `block-destructive-bash.sh` to `exit 0`, or deleting the
`PreToolUse` entry from `settings.json`, disarms the guard — and the very next tool
call is judged by the disarmed version. Every protection here is downstream of these
two paths.

The scope is the **enforcing machinery only**. Agents legitimately author skills, agent
definitions and workflow YAML under `.claude/`, and blocking those would make the guard
unusable rather than safe. A `settings.json` outside `.claude/` is an ordinary project
file and stays writable.

### Nested shells fail closed

`sh -c`, `bash -c`, `zsh -c`, `eval`, and `xargs` into a shell are **blocked
outright**, without inspecting what they would run.

The inner script is parsed by another shell under rules these hooks do not implement.
Quoting was enough to hide the most destructive command in the vocabulary: with quotes
missing from the command-boundary class, `sh -c 'rm -rf /'` produced no `rm` call at
all. Adding quotes to that class fixes *that* spelling and does not generalize —
`sh -c "$SCRIPT"` and a base64-decoded pipeline have no text to inspect until the outer
shell runs, and inspecting a string that does not exist yet is not something a static
check can do. `xargs rm` stays allowed: its operands are visible, and the `rm` check
reads them.

### Over-blocking is deliberate

When a construct cannot be analyzed safely — a glob, an unresolvable variable
expansion in a protected-looking context, a `~otheruser` that cannot be expanded, an
unexpanded `$VAR` as an `rm` target — the hook **blocks** and tells you to run the
command yourself with a leading `!`.

The `rm`-target case is worth naming: only `$HOME` was ever expanded, so
`TARGET=/; rm -rf "$TARGET"` left a literal `$TARGET` with no leading slash, which
resolved against `$PWD` into a path comfortably inside the workspace. The most
dangerous possible value for that variable was the one the check failed to consider.

The hook cannot expand a glob without executing shell code from an untrusted payload,
and `cat ~/.config/*` is strictly *worse* than naming `credentials.ini`, because it
discloses every token file at once. Refusing is the only safe answer.

A false positive costs one clarifying question. A false negative costs a disclosed
OAuth refresh token, which cannot be un-printed. The messages say this explicitly so
the block reads as a design decision rather than a bug.

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
directory name alone does not tell you which branch's worktree you are in. The agent
name wins when both are present — inside a subagent, *which* subagent is the more
specific fact.

## Contract

Both guards: **exit 2 blocks** the tool call and shows stderr to Claude, **exit 0
allows**. Both run under `set -u` and require `jq`.

**Everything fails closed.** A payload that cannot be parsed, a field that is present
but not a string (`{}`, `[]`, `0`, `true`), and an empty or whitespace-only field all
exit 2.

The non-string case is worth calling out because it is not caught by a parse check:
`jq -er` treats `{}` and `[]` as truthy JSON and exits 0, printing `"{}"`. That value
then matches no pattern, and the hook exited 0 — approving a call it had never
inspected. The failure of the inspecting step must never become an ALLOW.

## Running the tests

The suites run automatically as part of `make test` and CI, via
`tests/infra/test_guard_hooks.py`, which shells out to them and is picked up by
unittest discovery. Nothing extra needs wiring when a case is added.

To run them directly:

```bash
make hooks-test
```

or one at a time:

```bash
bash .claude/hooks/tests/block-destructive-bash.test.sh
bash .claude/hooks/tests/block-protected-paths.test.sh
bash .claude/hooks/tests/statusline.test.sh
```

Exit 0 = all pass, 1 = any failure. Each prints `ok`/`FAIL` per case and a final
count plus `ALL PASS`. Pass a path as argument 1 to test an installed copy instead of
the repo one:

```bash
bash .claude/hooks/tests/block-destructive-bash.test.sh ~/.claude/hooks/block-destructive-bash.sh
```

### Three exit states, not two

`tests/_harness.sh` classifies `0` as ALLOW, `2` as BLOCK, and **anything else as a
test failure**, reported with its actual exit code.

Both suites used to fold every non-2 code into ALLOW. A hook that dies on `set -u`
exits 1; one whose `jq` is missing exits 127. Under the old classifier all of those
were reported as `ok ALLOW` on any case expecting ALLOW — so a hook that had stopped
running at all still printed `ALL PASS` across the entire allow half of the suite.
That is the same fail-open shape the hooks themselves were fixed for, reproduced in
the thing meant to detect it.

### A zero-case run is a failure

`_summary` prints `NO CASES RAN` and returns 1 when both counters are zero.

`ALL PASS` was previously printed whenever nothing had *failed*, which a suite with every
case deleted also satisfies — both counters at zero, exit 0, green through the shell
suite, `make test`, and CI alike. The Python wrapper additionally parses the summary line
and asserts a positive total, so an empty suite cannot read as a passing one at either
layer. Same fail-open shape as the classifier note above, one level further out.

### Adding a new suite

Drop a `*.test.sh` in `.claude/hooks/tests/` and add its name to `SUITES` in
`tests/infra/test_guard_hooks.py`.

`SUITES` is the single source of truth: one test both compares it against the directory
listing and iterates it with `subTest` to run each suite. Previously the tuple was only
compared while execution came from three hand-written `test_*` methods, so a name added
to the tuple with no matching method passed the comparison and was never run — listed and
silently skipped. Driving both from the same tuple removes that state.

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
  "Read(**/.env)",
  "Read(**/.env.*)",
  "Read(**/.envrc)",
  "Read(**/.npmrc)",
  "Read(**/*.pem)",
  "Read(**/*.p8)",
  "Read(**/*.p12)",
  "Read(**/id_rsa)",
  "Read(**/id_ed25519)",
  "Read(~/.ssh/**)",
  "Read(~/.gnupg/**)",
  "Read(~/.aws/**)",
  "Edit(**/credentials.ini)",
  "Edit(**/credentials.json)",
  "Edit(**/token.json)",
  "Edit(**/outlook_token.json)",
  "Edit(**/msal_flow.json)"
],
"allow": [
  "Read(**/.env.example)",
  "Read(**/.env.template)",
  "Read(**/.env.sample)"
]
```

**Why the `Read` list is longer than the `Edit` list.** The two hooks cover different
tools, and `Read` is covered by neither: `block-protected-paths.sh` matches `Write|Edit`,
and `block-destructive-bash.sh` matches `Bash`. A direct `Read` tool call on `.env`,
`.npmrc`, a `.pem`/`.p8`/`.p12` key, or `id_rsa` goes through no hook at all — only these
deny rules stand in front of it. Files the Bash hook refuses to `cat` were still readable
through the `Read` tool until these entries existed.

The `allow` block restores the three checked-in templates, which `Read(**/.env.*)` would
otherwise catch. It lists the three exact names rather than a `*.env.example` glob, for
the same reason both hooks do: a wildcard exemption is one an arbitrary file can opt into
just by being named `prod.env.sample`. Allow rules take precedence over deny rules, so
`.env.example` stays readable while `prod.env.sample` does not.

## Deviations from the reference implementation

These are the places this port intentionally departs from the original, and why.

**`rm -rf` matches the resolved target, not the flag spelling.** The original
grep'd the literal string `"rm -rf /"`, which matches *any* absolute path —
`rm -rf /Users/me/scratch` was blocked as if it were root deletion. The original's
own comment records this firing twice on legitimate cleanup. It also let every
equivalent spelling through: `rm -fr /`, `rm --recursive --force /`, `rm -rf //`.

This port normalizes the flags (bundled short flags checked characterwise, so `-rvf`
and `-Rf` count), extracts the actual operands, expands `~`/`$HOME`, collapses
repeated slashes, **resolves `.` and `..` textually**, and compares against a
protected-prefix list: `/`, `$HOME`, `/Users`, `/home`, `/root`, `/etc`, `/usr`,
`/var`, `/System`, `/Library`, `/opt`, `/bin`, `/sbin`, `/Applications`, `/private`.
Descendants are protected alongside the roots — `/opt` without `/opt/*` guarded the
empty parent while `rm -rf /opt/homebrew` removed an entire package manager.

`..` resolution matters on its own: `rm -rf /tmp/../etc` is `rm -rf /etc`, and the
literal `/tmp/` head made it look like allowed scratch space. `realpath` is not used —
it resolves symlinks against the live filesystem and returns *empty* for a nonexistent
path, and an empty result compared against the protected list passes silently.

`/home`, `/root` and `/private` are additions. `/home` is where Linux keeps user homes
(CI runs there). `/root` is the root account's home — not under `/home`, so none of the
`/home/<user>` reasoning reached it, and on a runner where `$HOME` is `/home/runner`
the `$HOME` entry does not cover it either. `/private` is the macOS root that `/tmp`,
`/etc`, and `/var` are all symlinks into, so `rm -rf /private/etc` reached the same
inode as `rm -rf /etc` while dodging the check for it.

**Symlinked components are resolved, because `rm` follows them.** Every comparison
above is textual, but `ln -s / /tmp/root` makes `rm -rf /tmp/root/etc` read as an
ordinary `/tmp` descendant — carved out as scratch — while actually deleting `/etc`.
The guard walks *down* the path resolving only components that **already exist**,
stopping at the first that does not: an existing prefix is resolvable, and a
nonexistent tail cannot contain a symlink because a symlink is a thing that exists.
This is why plain `realpath` is wrong here for a second reason beyond the one above —
deleting a not-yet-created path is ordinary. Checks then judge the *resolved* target,
so `/tmp/root/etc` is blocked as `/etc` on its own merits while
`/tmp/scratch/build` resolves to `/private/tmp/scratch/build` and stays allowed.
Both spellings of each temp root are listed for exactly that reason.

**`rm` is matched however it is spelled.** A bare `rm` at a command boundary missed
`/bin/rm -rf /` and `"rm" -rf /`, which run the same binary — the same
path-qualification hole the [operands, not command words](#operands-not-command-words)
rewrite closed for readers, never carried across to the `rm` detector until now.

**Line continuations are spliced before any scan.** The scans are line-oriented, so
`rm \`⏎`  -rf /` arrived as `rm \` (a call with no flags) plus `  -rf /` (no `rm` at
all). Neither half looked dangerous; the shell ran the whole thing. The splice is done
in bash rather than `sed`, because BSD and GNU `sed` disagree about labels and `N` in a
one-liner, and a splice that silently no-ops on one platform is worse than none.

**The repository itself is protected**, both `.git` and the checkout root. `.git`
holds every unpushed commit and reflog entry; the file-level rules covered
`.git/config` while the whole directory was free to delete. The root falls through the
`"$ROOT"/?*` workspace carve-out by construction (one character past the slash), and a
checkout under `$HOME` then matched the "under some home, more than one level deep"
allow — the same shape as the temp-roots bug, in a different place.

**Temp roots are protected; only their descendants are scratch.** The carve-out allows
`/tmp/?*` — at least one character past the slash. The roots themselves fell through
it and were not in the protected list either, so `rm -rf /tmp` was allowed outright,
taking out every other session's scratch directory.

**Protected home subtrees are carved back out of the `$HOME/*` allow.** `$HOME/*` was
an unconditional allow on the reasoning that `~/.cache/foo` is disposable. So is
`~/.ssh` under that rule — every private key on the machine. `~/.ssh`, `~/.gnupg`,
`~/.aws`, `~/.config`, and `~/.claude` are blocked.

**`.claude/worktrees` is protected, and so is a relative path that escapes the
checkout.** `rm -rf ..` from a session worktree resolves to `.claude/worktrees/`,
holding every other session's uncommitted work — and lands under `$HOME`, which the
"under home but not home itself" branch allowed. A relative target containing `..` is
blocked when it resolves outside the repo root; `rm -rf build/../out` still works.

**Escaped and path-qualified command names count.** `\rm -rf /` runs rm with alias
expansion suppressed. The command-boundary character class did not include the
backslash, so the regex saw no rm at all.

**`git push -f` needs no trailing space.** The pattern was `push.*-f ` — so
`git push -f`, the shortest and most likely spelling of the thing being blocked, fell
straight through while `git push -f origin main` was caught. A flag at the end of the
command has no trailing space.

**Fail closed on unparseable *and* non-string payloads.** The original's
`CMD=$(jq -r ...)` yielded an empty string when jq failed, every pattern then missed,
and the hook exited 0. Both guards now use `jq -er`, check the field's JSON `type`,
and reject empty strings.

**Statusline shows unknown as unknown.** The original used
`(.context_window.used_percentage // 0)`, so an absent `.context_window` rendered a
full green bar reading `0%` — indistinguishable from a genuinely empty context
window. That is the worst kind of wrong reading: confident, plausible, and pointing
the opposite direction from the truth. A session at 85% looked like a session at 0%,
which is exactly when the number matters most.

**Template carve-out extended to the Write/Edit hook, and tightened everywhere.** The
original applied the exclusion only on the Bash read path. Both hooks now share it —
matched on the exact basename, after the protected-directory check, never as a
substring scrub.

**Repo-specific credential set.** The original guarded a `.env` /
Google-Workspace stack (`secrets/`, `credentials*` as a bare substring). Those were
replaced with the five files this repo actually resolves. The original's bare
`credentials` substring was dropped in favour of exact filenames — it matched
`credentials.md` and any commit message mentioning the word, which is noise rather
than safety.

**Dropped `block-risky-gws.sh`.** Google-Workspace-CLI specific; no equivalent
surface in this repo.
