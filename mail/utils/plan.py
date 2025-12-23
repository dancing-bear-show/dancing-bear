"""Plan output helpers shared across assistants."""
from __future__ import annotations

from typing import Optional


def print_plan_summary(
    *,
    create: int,
    update: Optional[int] = None,
    delete: Optional[int] = None,
    header: str = "Plan:",
) -> None:
    """Print a consistent plan summary line used by CLI tests."""

    parts: list[str] = [f"create={create}"]
    if update is not None:
        parts.append(f"update={update}")
    if delete is not None:
        parts.append(f"delete={delete}")
    print(f"{header} " + " ".join(parts))
