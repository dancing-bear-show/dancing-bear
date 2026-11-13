"""Memory CLI entry shim: ``python -m memory`` and the bin/ router."""

from __future__ import annotations

from .cli import main

__all__ = ["main"]

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
