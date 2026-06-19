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
