#!/usr/bin/env python3

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from typing import Any

from core.secrets import mask_text

__all__ = ["GhCLI"]


class GhCLI:
    """Thin wrapper around the `gh` CLI for JSON-friendly calls."""
    def __init__(self, run_func: Callable[..., Any] | None = None) -> None:
        """Create a GhCLI that uses the provided run function (for tests)."""
        self._run = run_func or subprocess.run

    def ensure_available(self) -> None:
        """Raise SystemExit if the `gh` binary is not available in PATH."""
        if shutil.which("gh") is None:
            raise SystemExit("gh CLI not found in PATH. Install from https://cli.github.com/")

    def auth_status(self) -> tuple[bool, str]:
        """Return (ok, output) from `gh auth status`."""
        res = self._run(["gh", "auth", "status"], text=True, capture_output=True)
        return (res.returncode == 0, res.stdout or res.stderr or "")

    def api(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Call `gh api` and parse JSON response for the given path.

        Note: For GET query params, use `-F key=value` as separate argv tokens
        to avoid quoting/flag parsing issues.
        """
        cmd = ["gh", "api", path]
        if params:
            for k, v in params.items():
                cmd.extend(["-F", f"{k}={v}"])
        res = self._run(cmd, text=True, capture_output=True)
        if res.returncode != 0:
            err_msg = mask_text(res.stderr or res.stdout or "gh api failed")
            raise RuntimeError(err_msg)
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
            k = str(k).replace("_", "-")
            cmd += [f"--{k}", str(v)]
        cmd += ["--json", "number,title,repository,createdAt,updatedAt,url"]
        res = self._run(cmd, text=True, capture_output=True)
        if res.returncode != 0:
            err_msg = mask_text(res.stderr or res.stdout or "gh search prs failed")
            raise RuntimeError(err_msg)
        return json.loads(res.stdout)

    def api_with_headers(self, path: str) -> tuple[int, dict[str, str], str]:
        """Call gh api --include and return (status, headers, body).

        status is the parsed HTTP status code on success (0 if no status line
        was present), or -1 when the gh process itself failed. The body is
        masked on the failure path.
        """
        cmd = ["gh", "api", "--include", path]
        res = self._run(cmd, text=True, capture_output=True)
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
            res = self._run(cmd, text=True, capture_output=True)
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
        for k, v in (variables or {}).items():
            if v is None:
                continue  # omit null variables — gh CLI passes "None" as a string otherwise
            cmd.extend(["-F", f"{k}={v}"])
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
        except OSError:
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
        res = self._run(cmd, text=True, capture_output=True)
        if res.returncode != 0:
            err_msg = mask_text(res.stderr or res.stdout or "gh pr view failed")
            raise RuntimeError(err_msg)
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
        """
        full_cmd = ["gh", *cmd]
        res = self._run(full_cmd, text=True, capture_output=True)
        if res.returncode != 0:
            err_msg = mask_text(res.stderr or res.stdout or "gh pr list failed")
            raise RuntimeError(err_msg)
        return res.stdout
