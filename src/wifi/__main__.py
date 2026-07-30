"""Wi-Fi diagnostics CLI."""

from __future__ import annotations

from .cli import main

__all__ = ["main"]

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
