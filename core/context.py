from __future__ import annotations

"""Shared application context helpers."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass
class AppContext:
    root: Path
    config: Dict[str, str]
    args: object

    def resolve(self, rel: str) -> Path:
        return (self.root / rel).resolve()
