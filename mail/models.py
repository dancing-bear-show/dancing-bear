"""Data models for mail operations (Gmail/Outlook)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from .utils.label_mapping import build_label_mapping


@dataclass
class LabelMapping:
    """Bidirectional label ID to name mapping."""

    id_to_name: Dict[str, str]
    name_to_id: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_labels(cls, labels: list) -> LabelMapping:
        """Create mapping from Gmail labels list."""
        id_to_name, name_to_id = build_label_mapping(labels)
        return cls(id_to_name=id_to_name, name_to_id=name_to_id)
