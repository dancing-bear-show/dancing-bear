"""Data models for mail operations (Gmail/Outlook)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class LabelMapping:
    """Bidirectional label ID to name mapping."""

    id_to_name: Dict[str, str]
    name_to_id: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_labels(cls, labels: list) -> LabelMapping:
        """Create mapping from Gmail labels list."""
        id_to_name = {label["id"]: label["name"] for label in labels}
        name_to_id = {label["name"]: label["id"] for label in labels}
        return cls(id_to_name=id_to_name, name_to_id=name_to_id)
