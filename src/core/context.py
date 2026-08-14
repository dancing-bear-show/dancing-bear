"""Shared application context helpers."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class AppContext:
    root: Path
    config: dict[str, str]
    args: object

    def resolve(self, rel: str) -> Path:
        return (self.root / rel).resolve()
