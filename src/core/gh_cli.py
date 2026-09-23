from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404 - subprocess imported deliberately; individual call sites carry their own B602/B603 review
import sys
from collections.abc import Callable
from typing import Any

from core.cli_errors import CLIError, ExitCode
from core.secrets import mask_text

__all__ = ["GhCLI", "GhError", "field_args"]


class GhError(CLIError):
    """A ``gh`` call failed, including a GraphQL call that exited 0 with errors."""

    def __init__(self, message: str) -> None:
        super().__init__(mask_text(message), ExitCode.ERROR)


def field_args(variables: dict[str, Any] | None) -> list[str]:
    """Render variables as ``gh api`` field flags, choosing the flag by type.

    ``-F`` is a *typed* field: it converts ``true``/``false``/``null``/digits,
    and it reads a value beginning with ``@`` as a file path. A string routed
    through it can therefore change type, or post a local file's contents. So
    only ``bool`` and ``int`` values use ``-F``; every other value uses ``-f``,
    which sends the literal text. ``None`` is omitted, because gh would
    otherwise send the string ``"None"``.
    """
    out: list[str] = []
    for key, value in (variables or {}).items():
        if value is None:
            continue
        if isinstance(value, bool):
            out.extend(["-F", f"{key}={'true' if value else 'false'}"])
        elif isinstance(value, int):
            out.extend(["-F", f"{key}={value}"])
        else:
            out.extend(["-f", f"{key}={value}"])
    return out


#: Sentinel: "use the instance's configured timeout".
_DEFAULT_TIMEOUT: Any = object()


class GhCLI:
    """Thin wrapper around the `gh` CLI for JSON-friendly calls."""
    def __init__(
        self,
        run_func: Callable[..., Any] | None = None,
        *,
        scrub_github_token: bool = False,
        timeout: float | None = None,
    ) -> None:
        """Create a GhCLI that uses the provided run function (for tests).

        ``scrub_github_token`` drops ``GITHUB_TOKEN`` from the child environment
        so gh uses its own keyring credentials: a stale exported token otherwise
        silently overrides them and every call fails auth. ``GH_TOKEN`` is left
        alone — it is gh's own variable and is set deliberately.

        ``timeout`` (seconds) bounds every call, so a network or auth stall
        fails instead of blocking an unattended caller forever. A call that is
        long-running by design (``pr checks --watch``) opts out per call.
        """
        self._run = run_func or subprocess.run
        self._scrub = scrub_github_token
        self._timeout = timeout

    def _exec(
        self,
        cmd: list[str],
        *,
        input_text: str | None = None,
        timeout: float | None = _DEFAULT_TIMEOUT,
    ) -> Any:
        """Run ``cmd`` with captured text output and the configured environment."""
        kwargs: dict[str, Any] = {"text": True, "capture_output": True}
        if self._scrub:
            kwargs["env"] = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
        if input_text is not None:
            kwargs["input"] = input_text
        limit = self._timeout if timeout is _DEFAULT_TIMEOUT else timeout
        if limit is not None:
            kwargs["timeout"] = limit
        try:
            return self._run(cmd, **kwargs)
        except subprocess.TimeoutExpired as exc:
            raise GhError(f"gh {' '.join(cmd[1:3])} timed out after {limit}s") from exc

    def run(
        self,
        args: list[str],
        *,
        input_text: str | None = None,
        timeout: float | None = _DEFAULT_TIMEOUT,
    ) -> Any:
        """Run ``gh <args>`` and return the completed process unchanged.

        For porcelain commands (``pr create``, ``pr checks --watch``) whose exit
        status and text output are the result: the caller decides what counts
        as failure. Pass ``timeout=None`` for a call that is meant to block.
        """
        return self._exec(["gh", *args], input_text=input_text, timeout=timeout)

    def api_paginated(self, path: str) -> list[Any]:
        """GET every page of a REST list endpoint and return one flat list.

        REST returns 30 items per page by default, and the page that goes
        missing without ``--paginate`` is the *last* — for reviews and comments,
        the newest. ``--slurp`` wraps the pages in one JSON array so a page
        boundary cannot corrupt the parse.
        """
        res = self._exec(["gh", "api", "--paginate", "--slurp", path])
        if res.returncode != 0:
            raise GhError(res.stderr or res.stdout or f"gh api {path} failed")
        try:
            pages = json.loads(res.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise GhError(f"gh api {path} returned non-JSON output: {exc}") from exc
        if not isinstance(pages, list):
            raise GhError(f"gh api {path} returned {type(pages).__name__}, expected a list of pages")
        items: list[Any] = []
        for page in pages:
            if not isinstance(page, list):
                raise GhError(f"gh api {path} is not a list endpoint (page is {type(page).__name__})")
            items.extend(page)
        return items

    def api_post(self, path: str, fields: dict[str, Any]) -> dict[str, Any]:
        """POST to a REST endpoint and return the created object.

        Fields are sent as a JSON object on stdin (``gh api --method POST
        <path> --input -``), matching ``graphql_checked``'s transport: JSON
        keeps an int like ``line`` an integer and a string like ``body`` a
        literal string, so no field — including review-derived text —
        touches the ``gh`` process argv or is misread as an ``@path`` file
        reference. ``None``-valued fields are omitted. Raises on a non-zero
        exit or a response that is not an object.
        """
        clean_fields = {k: v for k, v in (fields or {}).items() if v is not None}
        res = self._exec(
            ["gh", "api", "--method", "POST", path, "--input", "-"],
            input_text=json.dumps(clean_fields),
        )
        if res.returncode != 0:
            raise GhError(res.stderr or res.stdout or f"gh api POST {path} failed")
        try:
            data = json.loads(res.stdout or "null")
        except json.JSONDecodeError as exc:
            raise GhError(f"gh api POST {path} returned non-JSON output: {exc}") from exc
        if not isinstance(data, dict):
            raise GhError(f"gh api POST {path} returned {type(data).__name__}, expected an object")
        return data

    def graphql_checked(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a GraphQL call and return its ``data``, raising on any failure.

        ``gh`` exits 0 on an HTTP 200 whose body carries a GraphQL ``errors``
        array, so exit status alone says nothing about whether a mutation
        landed. This raises on a non-zero exit, a non-JSON body, an ``errors``
        array, or a missing ``data`` object.

        The request body — query and variables together — is sent as JSON on
        stdin (``gh api graphql --input -``), not through ``-f``/``-F`` field
        flags or a ``query=@tempfile`` reference. Every variable, including
        review-derived text such as a reply body, therefore never touches the
        ``gh`` process argv: nothing here can appear in process listings, hit
        the OS argv-size limit, or be misread as an ``@path`` file reference.
        ``None``-valued variables are omitted, matching ``field_args``.
        """
        body: dict[str, Any] = {"query": query}
        clean_vars = {k: v for k, v in (variables or {}).items() if v is not None}
        if clean_vars:
            body["variables"] = clean_vars
        res = self._exec(["gh", "api", "graphql", "--input", "-"], input_text=json.dumps(body))
        try:
            payload = json.loads(res.stdout or "null")
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and payload.get("errors"):
            messages = "; ".join(
                str(e.get("message", e)) if isinstance(e, dict) else str(e)
                for e in payload["errors"]
            )
            raise GhError(f"GraphQL errors: {messages}")
        if res.returncode != 0:
            raise GhError(res.stderr or res.stdout or "gh api graphql failed")
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise GhError("gh api graphql returned no data object")
        return payload["data"]

    def ensure_available(self) -> None:
        """Raise SystemExit if the `gh` binary is not available in PATH."""
        if shutil.which("gh") is None:
            raise SystemExit("gh CLI not found in PATH. Install from https://cli.github.com/")

    def auth_status(self) -> tuple[bool, str]:
        """Return (ok, output) from `gh auth status`."""
        res = self._exec(["gh", "auth", "status"])
        return (res.returncode == 0, res.stdout or res.stderr or "")

    def api(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Call `gh api` and parse JSON response for the given path.

        Params go through ``field_args``, so a string value is sent literally
        and never read as an ``@file`` reference.
        """
        cmd = ["gh", "api", path, *field_args(params)]
        res = self._exec(cmd)
        if res.returncode != 0:
            err_msg = mask_text(res.stderr or res.stdout or "gh api failed")
            raise CLIError(err_msg, ExitCode.ERROR)
        try:
            return json.loads(res.stdout)
        except Exception:  # nosec B110 - non-JSON gh api output returned as raw string
            return res.stdout

    def search_prs(self, **kwargs: Any) -> Any:
        """Call `gh search prs` with kwargs mapped to flags and return JSON."""
        # kwargs are raw flags passed through, caller composes
        cmd = [
            "gh",
            "search",
            "prs",
        ]
        # Example: author=@me, state=all, limit=5
        for k, v in kwargs.items():
            if v is None:
                continue  # omit None-valued flags — avoids passing the literal "None"
            k = str(k).replace("_", "-")
            cmd += [f"--{k}", str(v)]
        cmd += ["--json", "number,title,repository,createdAt,updatedAt,url"]
        res = self._exec(cmd)
        if res.returncode != 0:
            err_msg = mask_text(res.stderr or res.stdout or "gh search prs failed")
            raise CLIError(err_msg, ExitCode.ERROR)
        try:
            return json.loads(res.stdout)
        except Exception:  # nosec B110 - non-JSON gh search output returned as raw string
            return res.stdout

    def api_with_headers(self, path: str) -> tuple[int, dict[str, str], str]:
        """Call gh api --include and return (status, headers, body).

        status is the parsed HTTP status code on success (0 if no status line
        was present), or -1 when the gh process itself failed. The body is
        masked on the failure path.
        """
        cmd = ["gh", "api", "--include", path]
        res = self._exec(cmd)
        if res.returncode != 0:
            # -1 signals process failure, distinct from the success-path status=0
            # default used when no HTTP/ status line is parsed.
            return (-1, {}, mask_text(res.stdout or res.stderr or ""))
        raw = res.stdout
        header_text, _, body = raw.partition("\r\n\r\n")
        if not body:
            header_text, _, body = raw.partition("\n\n")
        headers: dict[str, str] = {}
        status = 0
        for line in header_text.splitlines():
            if line.upper().startswith("HTTP/"):
                try:
                    status = int(line.split()[1])
                except Exception:  # nosec B110 - malformed HTTP status line falls back to status=0
                    status = 0
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip()] = v.strip()
        return (status, headers, body)

    def graphql(self, query: str, variables: dict[str, Any] | None = None, *, debug: bool = False) -> Any:
        """Execute a GraphQL query/mutation using `gh api graphql` and return parsed JSON.

        Uses a temp file for the query payload to avoid shell quoting/newline issues.
        """
        qfile_path = None
        try:
            qfile_path = self._write_query_tempfile(query)
            cmd = self._build_graphql_cmd(query, qfile_path, variables)
            res = self._exec(cmd)
            return self._parse_graphql_result(res, debug)
        finally:
            self._cleanup_tempfile(qfile_path)

    @staticmethod
    def _write_query_tempfile(query: str) -> str | None:
        """Write the GraphQL query to a temp file for safe shell transport."""
        import tempfile as _tempfile
        try:
            with _tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as tf:
                tf.write(query)
                return tf.name
        except Exception:  # nosec B110 - tempfile create/write failure falls back to inline query
            return None

    @staticmethod
    def _build_graphql_cmd(
        query: str,
        qfile_path: str | None,
        variables: dict[str, Any] | None,
    ) -> list[str]:
        """Assemble the ``gh api graphql`` command list."""
        cmd: list[str] = ["gh", "api", "graphql"]
        if qfile_path:
            cmd.extend(["-F", f"query=@{qfile_path}"])
        else:
            cmd.extend(["-f", f"query={query}"])
        cmd.extend(field_args(variables))
        return cmd

    @staticmethod
    def _parse_graphql_result(res: subprocess.CompletedProcess[str], debug: bool) -> Any:
        """Parse the subprocess result from a GraphQL call."""
        if res.returncode != 0:
            if debug:
                err_msg = mask_text(res.stdout or res.stderr or "gh api graphql failed")
                print(err_msg, file=sys.stderr)
            return None
        try:
            return json.loads(res.stdout or "{}")
        except Exception:  # nosec B110 - return None on malformed GraphQL JSON
            if debug:
                print("Failed to parse gh api graphql output", file=sys.stderr)
            return None

    @staticmethod
    def _cleanup_tempfile(path: str | None) -> None:
        """Remove a temp file if it exists."""
        if not path:
            return
        import os as _os
        try:
            _os.unlink(path)
        except OSError:  # nosec B110 - best-effort cleanup; the temp file may already be gone
            pass

    # ---------------- Convenience wrappers ----------------
    def pr_view(self, pr: str, *, repo: str | None = None, fields: list[str] | None = None) -> Any:
        """Return PR metadata via `gh pr view --json`.

        Args:
            pr: PR number or URL
            repo: owner/name when PR is a number
            fields: list of json field names for gh to include

        Returns parsed JSON when fields are provided; raw text otherwise.
        """
        cmd: list[str] = ["gh", "pr", "view", str(pr)]
        if repo:
            cmd += ["--repo", str(repo)]
        if fields:
            # `gh pr view` supports a JSON output with selected fields
            cmd += ["--json", ",".join(fields)]
        res = self._exec(cmd)
        if res.returncode != 0:
            err_msg = mask_text(res.stderr or res.stdout or "gh pr view failed")
            raise CLIError(err_msg, ExitCode.ERROR)
        if fields:
            try:
                return json.loads(res.stdout)
            except Exception:  # nosec B110 - non-JSON pr view output returned as raw string
                return res.stdout
        return res.stdout

    def pr_list(self, cmd: list[str]) -> str:
        """Execute gh pr list command and return raw output.

        Args:
            cmd: Command tokens starting with the gh subcommand (NOT "gh"), e.g.
                 ["pr", "list", "--state", "open"]. The leading "gh" is prepended
                 automatically; do not include it in cmd.

        Returns raw stdout (typically JSON when --json flag is used).

        Raises ValueError if cmd does not start with the ["pr", "list"] tokens,
        so misuse fails clearly rather than as a confusing "gh pr list failed".
        """
        if cmd[:2] != ["pr", "list"]:
            raise ValueError('pr_list expects cmd to start with ["pr", "list", ...]')
        full_cmd = ["gh", *cmd]
        res = self._exec(full_cmd)
        if res.returncode != 0:
            err_msg = mask_text(res.stderr or res.stdout or "gh pr list failed")
            raise CLIError(err_msg, ExitCode.ERROR)
        return res.stdout
