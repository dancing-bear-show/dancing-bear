"""A fake ``subprocess.run`` for GhCLI that answers like gh and records every call.

GraphQL calls (``gh api graphql --input -``) and REST POSTs
(``gh api --method POST <path> --input -``) both send their request body as
JSON on stdin. The fake parses that JSON off ``kwargs["input"]`` and exposes
each field via ``call.fields``/``call.value()`` — tagged ``"-F"`` for a
non-string (int/bool) value and ``"-f"`` for a string, mirroring the old
argv-flag convention — so existing assertions about *how* a value was sent
keep working: they now mean "was in the stdin JSON", never argv. GraphQL
calls additionally expose the query text via ``call.query``. ``search_prs``
and other argv-flag calls are unaffected and still send their fields as
``-f``/``-F`` argv pairs, which are parsed as before.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from subprocess import CompletedProcess
from typing import Any, Callable


@dataclass
class GhCall:
    argv: list[str]
    query: str = ""
    #: name -> (flag, value) for every -f/-F pair other than ``query``.
    fields: dict[str, tuple[str, str]] = field(default_factory=dict)
    input: str | None = None
    env: dict[str, str] | None = None
    timeout: float | None = None

    def value(self, name: str) -> str | None:
        got = self.fields.get(name)
        return got[1] if got else None


def _stdin_json(kwargs: dict[str, Any]) -> dict[str, Any]:
    return json.loads(kwargs.get("input") or "{}")


def _as_field(val: Any, *, typed: bool) -> tuple[str, str]:
    """Render a JSON value as the (flag, text) pair older assertions expect.

    Strings read as ``-f``. Non-strings read as ``-F`` when ``typed`` (REST
    POST, where line must stay an int) and as ``-f`` otherwise (GraphQL
    variables), so call.value()/call.fields keep meaning "was sent" — now
    against the stdin JSON rather than argv.
    """
    if isinstance(val, str):
        return "-f", val
    return ("-F" if typed else "-f"), json.dumps(val)


def _parse_argv_fields(call: GhCall, argv: list[str]) -> None:
    """Legacy transport: -f/-F pairs in argv, query possibly via @tempfile."""
    pairs = zip(argv, argv[1:])
    for flag, arg in pairs:
        if flag not in ("-f", "-F"):
            continue
        key, _, val = arg.partition("=")
        if key != "query":
            call.fields[key] = (flag, val)
        elif flag == "-F" and val.startswith("@"):
            with open(val[1:], encoding="utf-8") as fh:
                call.query = fh.read()
        else:
            call.query = val


def parse_call(argv: list[str], kwargs: dict[str, Any]) -> GhCall:
    call = GhCall(argv=list(argv), input=kwargs.get("input"), env=kwargs.get("env"),
                  timeout=kwargs.get("timeout"))
    stdin_body = "--input" in argv
    if stdin_body and argv[:3] == ["gh", "api", "graphql"]:
        # {"query": ..., "variables": {...}} on stdin.
        payload = _stdin_json(kwargs)
        call.query = payload.get("query", "")
        for key, val in (payload.get("variables") or {}).items():
            call.fields[key] = _as_field(val, typed=False)
    elif stdin_body and "--method" in argv and "POST" in argv:
        # REST POST fields on stdin: {"body": ..., "line": 12, ...}.
        for key, val in _stdin_json(kwargs).items():
            call.fields[key] = _as_field(val, typed=True)
    else:
        _parse_argv_fields(call, argv)
    return call


def ok(payload: Any, returncode: int = 0, stderr: str = "") -> CompletedProcess[str]:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return CompletedProcess(args=[], returncode=returncode, stdout=text, stderr=stderr)


class FakeGh:
    """Callable standing in for ``subprocess.run``; ``handler(call)`` answers."""

    def __init__(self, handler: Callable[[GhCall], CompletedProcess[str]]) -> None:
        self.handler = handler
        self.calls: list[GhCall] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> CompletedProcess[str]:
        call = parse_call(argv, kwargs)
        self.calls.append(call)
        return self.handler(call)

    def graphql_calls(self, needle: str) -> list[GhCall]:
        return [c for c in self.calls if needle in c.query]


def paged(items: list[Any], size: int, after: str | None, prefix: str) -> tuple[list[Any], dict[str, Any]]:
    """Slice ``items`` like a GraphQL connection with cursors ``<prefix><offset>``."""
    start = int(after[len(prefix):]) if after else 0
    chunk = items[start:start + size]
    end = start + len(chunk)
    return chunk, {"hasNextPage": end < len(items), "endCursor": f"{prefix}{end}" if chunk else None}


def comment_node(i: int, login: str = "rev", typename: str = "User") -> dict[str, Any]:
    return {
        "databaseId": 1000 + i,
        "author": {"login": login, "__typename": typename},
        "body": f"comment {i}",
        "createdAt": f"2026-09-23T00:{i // 60:02d}:{i % 60:02d}Z",
        "url": f"https://example.invalid/c{i}",
    }
