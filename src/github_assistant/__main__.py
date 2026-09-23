"""GitHub CLI entry shim: ``python -m github_assistant`` and the bin/ router."""

from __future__ import annotations

from .cli import main

__all__ = ["main"]

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
