"""Resolve the current repository's owner and name.

Never hardcode or guess the owner: forks and renamed remotes make any guess
wrong in a way that still returns data — just for a different repository.
"""

from __future__ import annotations

from core.gh_cli import GhCLI, GhError


def resolve_owner_repo(gh: GhCLI, repo: str | None = None) -> tuple[str, str]:
    """Return ``(owner, name)`` for ``repo`` (``owner/name``) or the current checkout.

    An explicit ``repo`` is validated and split without a network call.
    """
    if repo:
        nwo = repo
    else:
        res = gh.run(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
        if res.returncode != 0:
            raise GhError(res.stderr or res.stdout or "gh repo view failed")
        nwo = (res.stdout or "").strip()
    owner, sep, name = nwo.partition("/")
    if not sep or not owner or not name or "/" in name:
        raise GhError(f"cannot parse owner/name from {nwo!r}")
    return owner, name
