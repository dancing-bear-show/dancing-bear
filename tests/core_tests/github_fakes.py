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


def parse_call(argv: list[str], kwargs: dict[str, Any]) -> GhCall:
    call = GhCall(argv=list(argv), input=kwargs.get("input"), env=kwargs.get("env"),
                  timeout=kwargs.get("timeout"))
    if argv[:3] == ["gh", "api", "graphql"] and "--input" in argv:
        # Request body travels as JSON on stdin: {"query": ..., "variables": {...}}.
        # Represent each variable as if it arrived via "-f" so existing
        # call.value()/call.fields assertions are unaffected by the transport
        # change — they now assert "in the stdin JSON", not "in argv".
        payload = json.loads(kwargs.get("input") or "{}")
        call.query = payload.get("query", "")
        for key, val in (payload.get("variables") or {}).items():
            call.fields[key] = ("-f", val if isinstance(val, str) else json.dumps(val))
        return call
    if "--method" in argv and "POST" in argv and "--input" in argv:
        # REST POST body travels as JSON on stdin too: {"body": ..., "line": 12, ...}.
        # Tag string values "-f" and non-string (int/bool) values "-F" so
        # existing call.value()/call.fields assertions keep meaning "was
        # sent", now against the stdin JSON instead of argv -f/-F pairs.
        payload = json.loads(kwargs.get("input") or "{}")
        for key, val in payload.items():
            tag = "-f" if isinstance(val, str) else "-F"
            call.fields[key] = (tag, val if isinstance(val, str) else json.dumps(val))
        return call
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
