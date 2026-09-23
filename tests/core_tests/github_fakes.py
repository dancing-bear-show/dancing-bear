"""A fake ``subprocess.run`` for GhCLI that answers like gh and records every call.

GraphQL calls are dispatched on the query text, which GhCLI writes to a temp
file passed as ``-F query=@<path>``; the fake reads that file during the call,
while it still exists. Variables arrive as ``-f``/``-F`` pairs and are recorded
with the flag that carried them, so a test can assert *how* a value was sent,
not just that it was.
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


def parse_call(argv: list[str], kwargs: dict[str, Any]) -> GhCall:
    call = GhCall(argv=list(argv), input=kwargs.get("input"), env=kwargs.get("env"),
                  timeout=kwargs.get("timeout"))
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in ("-f", "-F") and i + 1 < len(argv):
            key, _, val = argv[i + 1].partition("=")
            if key == "query":
                if tok == "-F" and val.startswith("@"):
                    with open(val[1:], encoding="utf-8") as fh:
                        call.query = fh.read()
                else:
                    call.query = val
            else:
                call.fields[key] = (tok, val)
            i += 2
            continue
        i += 1
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
