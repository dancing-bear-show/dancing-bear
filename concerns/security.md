# Security Review Guide

## When loaded

Load this guide when the diff contains `.py` files. Security concerns apply to
any Python code that handles credentials, spawns subprocesses, or evaluates
dynamic input.

## Concerns

### credential-logging
- **severity**: critical
- **check**: Verify no token, password, or secret value appears in log
  output, exception messages, or response fields.
- **triggers**: `logging.*`, `print(`, `f"...{...}"` expressions near auth
  variables; exception formatters; response serialization.
- **example**: `log.debug(f"Authenticating with token={self.token}")` — the
  token appears in plaintext in every log shipping pipeline.

### shell-injection
- **severity**: critical
- **check**: Verify no `subprocess` or `os.system` call passes unsanitized
  user input into a shell string.
- **triggers**: `subprocess.run(..., shell=True)`; `os.system(`; string
  concatenation or f-strings in subprocess argument lists.
- **example**: `subprocess.run(f"grep {query} file.txt", shell=True)` where
  `query` comes from an API response — a value of `x; rm -rf /` executes
  destructively.

### eval-exec
- **severity**: critical
- **check**: Verify `eval()` and `exec()` are not called on external input.
- **triggers**: `eval(`, `exec(` anywhere in changed files.
- **example**: `eval(user_filter)` to parse a dynamic filter expression from
  a config file — any Python expression executes with the process's full
  privileges.

### nosec-rationale-accuracy
- **severity**: major
- **check**: Verify every `# nosec` comment encodes a truthful rationale.
  Do not claim "path is not user-controlled" for general-purpose helpers
  that are also called with caller-supplied paths from CLI arguments. The
  correct rationale is "writing to caller-supplied output path is intentional"
  (a design choice), not a false claim about provenance.
- **triggers**: `# nosec` on any `open(`, `Path(`, or file-write operation
  in a shared utility function (not a private module-internal function).
- **example**: `tmp.write_text(...) # nosec B603 - path is not user-controlled`
  on a helper called from CLI code with `args.out` — the claim is false; the
  correct comment is `# nosec B603 - writing to caller-supplied output path is
  intentional; CLI tools pass user-specified destinations`.

### filename-sanitization-traversal
- **severity**: major
- **check**: Verify that sanitization of externally-supplied filenames rejects `""`, `"."`, and `".."` in addition to stripping directory separators. `basename()` alone lets those through, and they resolve to a directory rather than a file.
- **triggers**: `os.path.basename(name)` or `Path(name).name` as the only sanitization on an attachment or API-supplied filename; destination paths built as `dest_dir / sanitized`.
- **example**: A Gmail part with `filename: ".."` survives `basename()` unchanged, so writing to `downloads_dir / ".."` targets the parent directory and raises `IsADirectoryError` — or worse, escapes the intended destination. Fix: after taking the basename, fall back to a safe default (`"attachment"`) for empty, `.`, `..`, and whitespace-only names.

### unsafe-uri-scheme-in-output
- **severity**: major
- **check**: Verify that hyperlink generation allowlists `http`/`https`/`mailto` when the URL can come from user-supplied or external data. Any other scheme embedded as a real link relationship becomes clickable in the generated document.
- **triggers**: A URL taken from config, an API response, or profile data and passed to `add_hyperlink()` or an equivalent relationship builder; URL normalizers that accept "anything with a scheme".
- **example**: `normalize_link_url("javascript:alert(1)")` passing through unchanged embeds an executable link in a generated DOCX; `file:` URIs similarly point at local paths on the recipient's machine. Fix: allowlist the three safe schemes and fall back to plain text for everything else, creating no relationship at all.

### inline-python-code-injection
- **severity**: critical
- **check**: Verify that no caller-controlled value is interpolated into the source text of a `python3 -c '...'` argument. This is injection even without `shell=True` — the Python source itself is the payload.
- **triggers**: Workflow stages or subprocess calls building a `python3 -c` argument via f-string or `{placeholder}` substitution of a filename, company name, branch, or any trigger param.
- **example**: `python3 -c "import zipfile; zipfile.ZipFile('{workspace}/resume-{company}.docx')"` — a `{company}` containing a quote breaks the command, and one crafted as `x'); __import__('os').system('...')#` executes arbitrary code. Fix: pass the value as an argv parameter and read `sys.argv[1]` inside the `-c` body.

### jwt-claim-type-not-validated
- **severity**: major
- **check**: Verify that token claims used in arithmetic or formatting (`iat`, `exp`, `nbf`) are type-validated at the decode boundary, not just checked for presence. A malformed claim should surface as a clear configuration error, not a `TypeError` from deep inside validation.
- **triggers**: `claims.get("exp")` fed straight into subtraction or `datetime.fromtimestamp()`; JWT decode paths building a claims dataclass with no `int` coercion.
- **example**: `decode_claims()` passed `iat`/`exp` through untyped, so a token carrying `"exp": "1700000000"` made `seconds_remaining()` raise `TypeError: unsupported operand type(s) for -: 'str' and 'int'` instead of reporting a malformed token. Fix: coerce with `int(...)` inside `try/except (TypeError, ValueError)` and raise `ConfigError`.

### unvalidated-param-substitution
- **severity**: critical
- **check**: Verify every workflow trigger param or stage-supplied variable substituted into a shell command or file path in a stage description or executor script has an explicit allowlist, type check, or quoting rule applied before substitution.
- **triggers**: a `{param}` placeholder in a workflow stage `description:` or an executor script body that is substituted into shell text or a filesystem path, where the param's source is a trigger param or a value another stage produced
- **example**: `workflows/demo/qwen-job-type.yaml:181` substitutes `{workspace}` into a shell command on the assumption it is engine-controlled, but `--workspace` is caller-supplied — nothing validates it before the substitution runs. Fix: apply an explicit allowlist or type check to every caller-supplied param before it reaches shell or path text, e.g. `src/workflow/compiler.py`'s `enforce_param_rules`, and extend that enforcement to params not yet named in an explicit rule rather than only the ones an author remembered to list.
- **sweep**: structural — every workflow trigger param or stage-supplied variable that is substituted into a shell command or file path in a stage description or an executor script has an explicit allowlist, type check, or quoting rule applied before substitution
- **cause**: LATE_DISCOVERY — the unvalidated substitution was found on later review of code already merged; FIX_REGRESSION — a fix validating one param left a sibling param of the same stage unvalidated; SIBLING — the same brace-placeholder construct recurs in a later stage of the same workflow; INCOMPLETE_FIX — a fix quoted or validated some substitutions in a commit block but left others in the same block unvalidated

### regex-parses-shell
- **severity**: critical
- **check**: Answer yes to each step: Does the guard tokenise the shell text (shlex or equivalent) rather than matching a regex or substring against the raw string? If it does not tokenise, does the PR text or test suite enumerate every shell metacharacter and separator (`;`, `&&`, `||`, `|`, newline, backtick, `$()`) the guard must still see through? Is there a test asserting rejection for a crafted string that hides the dangerous token behind at least one of those separators? Does a fail-closed default apply when the check itself errors (e.g. an unbound variable, a malformed pattern), rather than the command proceeding?
- **triggers**: a shell command guard, wiring check, or classifier in `.claude/**`, `src/**/*.py`, or a shell script is added or modified to match against shell command text using a regex or substring test
- **example**: `tests/infra/test_guard_hooks.py:250` documents that a wiring regex matched any `bash` token appearing after whitespace, including one that only occurs inside an `echo` argument rather than as an actual command invocation — and `workflows/code/qwen-local-handler.yaml:2155` shows a heredoc validation still closable by a newline plus a RAW marker, letting injected content past the guard. Fix: tokenise the shell text with `shlex` (or an equivalent parser) instead of matching a regex or substring against the raw string, and add a rejection test for a crafted string that hides the dangerous token behind a separator such as `;`, `&&`, `|`, or a literal newline.
- **sweep**: procedure, applied to the diff when the trigger matches:
  1. Does the guard tokenise the shell text (shlex or equivalent) rather than matching a regex or substring against the raw string?
  2. If it does not tokenise, does the PR text or test suite enumerate every shell metacharacter and separator (`;`, `&&`, `||`, `|`, newline, backtick, `$()`) the guard must still see through?
  3. Is there a test asserting rejection for a crafted string that hides the dangerous token behind at least one of those separators?
  4. Does a fail-closed default apply when the check itself errors (e.g. an unbound variable, a malformed pattern), rather than the command proceeding?
  Record: the separator/metacharacter checklist, each item paired with a rejection test
- **cause**: SIBLING — a regex/substring guard fixed for one bypass shape at one call site recurs unfixed at a sibling guard matching shell text the same way

### unquoted-shell-var
- **severity**: critical
- **check**: Verify every occurrence of a workflow-supplied variable interpolated into a shell command in a stage description quotes the variable AND the quoting stops command substitution ($() and backticks), not just word-splitting.
- **triggers**: a workflow-supplied variable or placeholder is interpolated into a shell command in a stage `description:` or an executor script
- **example**: `workflows/code/qwen-local-handler.yaml:360` double-quotes `ollama_host` but double quotes alone don't stop `$()`/backtick expansion, and `workflows/code/review-and-fix.yaml`'s `worktree_path` is typed unquoted into a shell `source` line despite a prior quoting fix elsewhere in the same file. Fix: quote the variable AND confirm the quoting stops command substitution — double-quoting alone still lets a value like `$(rm -rf /)` execute; sanitize or reject the value before interpolation rather than relying on quoting alone to neutralize it.
- **sweep**: every occurrence of a workflow-supplied variable interpolated into a shell command in a stage description quotes the variable AND the quoting stops command substitution ($() and backticks), not just word-splitting
- **cause**: SIBLING — a quoting gap fixed at one call site recurs unfixed at a sibling call site interpolating the same variable elsewhere; INCOMPLETE_FIX — a fix added double-quoting but did not verify the quoting stops command substitution, so the same value can still trigger $() or backtick expansion
