"""Shared application context helpers."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict


@dataclass
class AppContext:
    root: Path
    config: Dict[str, str]
    args: object

    def resolve(self, rel: str) -> Path:
        return (self.root / rel).resolve()
