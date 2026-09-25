"""Classify a GitHub comment author as bot or human.

GitHub answers "is this a bot?" differently on each API surface:

* GraphQL exposes ``author.__typename`` (``"Bot"`` / ``"User"`` / ...).
* REST exposes ``user.type`` (``"Bot"`` / ``"User"``).
* The login spelling differs between them for the same account: GraphQL returns
  ``copilot-pull-request-reviewer`` and REST returns
  ``copilot-pull-request-reviewer[bot]``.

The typed fields are GitHub's own answer and cover accounts no allowlist
anticipates. ``github-code-quality`` posts under a bare login with no ``[bot]``
suffix and is on no list, so a login-only rule calls it human — on one real PR
that was 10 of 14 threads. The login rules are therefore a last resort, used
only when neither typed field is present.
"""

from __future__ import annotations

from typing import Literal

AuthorKind = Literal["bot", "human"]

BOT_SUFFIX = "[bot]"

#: Logins known to be bots, compared after ``[bot]`` is stripped.
KNOWN_BOT_LOGINS = frozenset({"copilot-pull-request-reviewer", "github-actions"})

#: Copilot's reviewer login, as GraphQL spells it (REST adds ``[bot]``).
COPILOT_LOGIN = "copilot-pull-request-reviewer"


def normalize_login(login: str | None) -> str:
    """Strip a trailing ``[bot]`` so both API spellings compare equal."""
    if not login:
        return ""
    return login[: -len(BOT_SUFFIX)] if login.endswith(BOT_SUFFIX) else login


def classify_author(
    login: str | None,
    *,
    typename: str | None = None,
    user_type: str | None = None,
) -> AuthorKind:
    """Return ``"bot"`` or ``"human"``, preferring the typed fields.

    Precedence: GraphQL ``__typename``, then REST ``user.type``, then the login.
    A typed field that is present decides on its own — a ``User`` is human even
    if its login happens to match the allowlist.
    """
    if typename:
        return "bot" if typename == "Bot" else "human"
    if user_type:
        return "bot" if user_type == "Bot" else "human"
    if not login:
        return "human"
    if login.endswith(BOT_SUFFIX) or normalize_login(login) in KNOWN_BOT_LOGINS:
        return "bot"
    return "human"


def is_copilot_reviewer(
    login: str | None,
    *,
    typename: str | None = None,
    user_type: str | None = None,
) -> bool:
    """True when the author is the Copilot pull-request reviewer.

    Both halves are required: the account must classify as a bot (typed fields
    first, as in ``classify_author``) and its normalised login must be
    Copilot's. A ``User`` whose login happens to match is not Copilot.
    """
    if classify_author(login, typename=typename, user_type=user_type) != "bot":
        return False
    return normalize_login(login) == COPILOT_LOGIN
