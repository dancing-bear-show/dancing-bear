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
